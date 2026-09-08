---
name: media-contracts-deployment
description: Deploying and tearing down the Media Contract Analyzer — the deploy.sh eight-step resumable menu, the 17 CDK stacks in deployment/ and their dependency order, MC-{Name}-{id}-{suffix} stack naming versus {id}-{suffix} resource naming, the .deploy-state/ tracking files, SSM parameter paths, and destroy.sh teardown. Use when deploying, resuming a failed deploy, adding or editing a CDK stack, working out a stack or resource or bucket name, collecting logs, or debugging a deploy or teardown failure.
license: MIT-0
metadata:
  project: media-contracts-analyzer
  verified-against: repository state, September 2026
---

# Deployment and Teardown

Everything is driven by two shell entrypoints (`deploy.sh`, `destroy.sh`) over a shared library
(`deployment/scripts/common.sh`, ~1150 lines) and a 17-stack CDK app (`deployment/app.py`).

Read `deployment/scripts/common.sh` before changing anything in the deploy path. It owns state,
naming, region/account resolution, the CDK wrappers, and all preflights.

## Naming — get this right first

Two independent shapes, both built from `DEPLOYMENT_ID` + `STACK_SUFFIX`:

| Shape | Form | Defined by |
| --- | --- | --- |
| Stack name | `MC-{Name}-{DEPLOYMENT_ID}-{STACK_SUFFIX}` | `_sn()` in `common.sh:545`; mirrored by `_sid()` in `app.py:62` |
| Resource id | `{DEPLOYMENT_ID}-{STACK_SUFFIX}` | `resource_id()` in `common.sh:568` |
| SSM prefix | `/mc-{STACK_SUFFIX}/` — **suffix only, no deployment id** | the stacks themselves |

`_sn()` and `_sid()` must stay in step. If you change one, change both.

- `STACK_PREFIX` defaults to `MC`.
- `STACK_SUFFIX` is 3 hex chars: `secrets.token_hex(2)[:3]`. Generated once per `DEPLOYMENT_ID` and
  persisted as `stack_suffix` in the state file. `ensure_suffix` creates it; `load_suffix` refuses to
  invent one (used by destroy and helper scripts, where a fresh suffix would target nothing).
- `DEPLOYMENT_ID` must match `^[a-z][a-z0-9-]{0,15}$`. An uppercase character crashes `cdk synth` on
  S3 bucket-name validation.
- Several deployments can coexist in one account and region.

`STACK_BASE_NAMES` (`common.sh:549`) is the authoritative list, used to parse identity back out of a
stack name so an id containing hyphens still parses:

```
ECS Dashboard AnalysisKBSync AutoTrigger Runtimes XRay Gateway Specialists
TermsKB AnalysisKB IAM ECR DynamoDB S3 InferenceProfiles Cognito Vpc
```

### Resource names you will need

```
media-contracts-{config|source|results|terms|access-logs}-{id}-{sfx}   # S3
media-contracts-{orchestrator|ui}-{id}-{sfx}                           # ECR repos
media-contracts-{id}-{sfx}                                             # ECS Express service
media-contracts-specialist-{name-with-hyphens}-{id}-{sfx}              # specialist Lambdas
media-contracts-terms-kb-{id}-{sfx}                                    # Terms KB
media-contracts-terms-vectors-{id}-{sfx}                               # S3 Vectors bucket, index "terms"
alias/media-contracts-{id}-{sfx}                                       # KMS alias
/ecs/media-contracts-ui-{id}-{sfx}                                     # ECS log group
```

## `deploy.sh`

```bash
./deploy.sh              # pick a deployment, then the interactive menu
./deploy.sh resume       # pick a deployment, run only its remaining steps
./deploy.sh 4            # pick a deployment, run option 4 directly
```

`DEPLOYMENT_ID` is deliberately **`unset` at line 41** — deploy.sh always prompts via
`choose_deployment`, so a stale exported value cannot target the wrong deployment. `destroy.sh` still
accepts it explicitly.

Startup: `choose_deployment` → `require_deployment_id` → `ensure_region` → `ensure_account` →
`ensure_suffix` → `ensure_cdk_deps`.

### The eight steps

| # | Function | What it does |
| --- | --- | --- |
| 1 | `step_infra` | Preflights (`preflight_bootstrap`, `preflight_service_quotas`, `ensure_xray_decision`), then deploys `Vpc Cognito InferenceProfiles S3 DynamoDB ECR IAM AnalysisKB TermsKB`, plus `XRay` unless `MC_SKIP_XRAY=1`. |
| 2 | `step_upload` | Submenu 1–6 (default 6 = all): agent prompts, foundation prompts, UI prompts, schemas, glossaries→Terms KB. Reads `ConfigBucketName` from the S3 stack; exits if absent. |
| 3 | `step_specialists` | Deploys `Specialists`. |
| 4 | `step_gateway` | Deploys `Gateway`, reads output `GatewayUrl`, persists `gateway_url` state. Hard-exits if the output is missing. |
| 5 | `step_orchestrator` | Requires `gateway_url`. ECR login → `preflight_docker_cross_platform arm64` → `docker buildx build --platform linux/arm64 --file agentcore/orchestrator/Dockerfile --push .` → verify with `describe-images` → deploy `Runtimes`. |
| 6 | `step_supporting` | Deploys `AutoTrigger`, `AnalysisKBSync`, `Dashboard`. |
| 7 | `step_ui_build` | ECR login → `generate_ui_env.sh` → `(cd ui && npm install && npm run build)` → `preflight_docker_cross_platform amd64` → `docker build --platform linux/amd64 --file Dockerfile` → push. |
| 8 | `step_ui_deploy` | See below. |
| 9 | `step_full` | Confirm, resolve UI exposure up front, then `run_remaining`. |
| r | `step_resume` | Prompt for UI exposure only if `ecs_deployed` is unset, then `run_remaining`. |
| 10 | `show_status` | The ✓/○ step table with `_at` timestamps and the gateway URL. |
| 11 | `reset_state` | Deletes the state file and re-inits. **Deletes no AWS resources.** Suffix is preserved. |
| m | — | Placeholder, not implemented. |

The **two-phase deploy** exists because `GATEWAY_URL` is only known after the Gateway stack (step 4)
completes, and the Runtimes stack (step 5) needs it at synth time.

### Step 8 detail — why it is more than `cdk deploy`

The ECS stack pins the image by a **static tag**, so pushing a new image to the same tag leaves the
template unchanged and CDK reports "no changes" while the service keeps serving the old image. Step 8
therefore always follows the CDK deploy with an explicit container update:

```bash
aws ecs update-express-gateway-service \
  --service-arn "arn:aws:ecs:${AWS_REGION}:${ACCOUNT_ID}:service/default/media-contracts-$(resource_id)" \
  --primary-container "{\"image\":\"${UI_REPO}:${IMAGE_TAG}\",\"containerPort\":${UI_CONTAINER_PORT}}"
```

`UI_CONTAINER_PORT` (default `8080`) **must match** `CONTAINER_PORT` in
`deployment/stacks/ecs_stack.py:316`, or the rollout repoints the target port at something the app is
not listening on.

Then it polls `describe-services … deployments[0].rolloutState` 120 × 5 s (10 min), warning at attempt
60. On any failure, `_ui_deploy_failed` calls `invalidate_state "ui_image_pushed"` so a resume re-runs
step 7 before retrying step 8 — an ECS rollout failure is almost always something inside the image, and
redeploying the same broken image fails identically.

On success it exports `CORS_ORIGIN="https://${endpoint}"`, saves `cors_origin`, and **re-deploys the S3
stack** to apply CORS to the source bucket. Skip that and browser uploads fail.

**UI network exposure is fixed for the life of the VPC.** `_prompt_ui_public_access` honours
`UI_PUBLIC_ACCESS` from the environment; with `MC_ASSUME_YES=1` it defaults to `true` (public,
internet-facing) with a warning. In public mode `app.py` passes **public** subnet ids into the ECS
stack's `private_subnet_ids` parameter — the parameter name is misleading, the behaviour is intended.

### Resumable state

- Path: `${REPO_ROOT}/.deploy-state/${DEPLOYMENT_ID}.json` — a **directory** with one JSON per
  deployment. (`.deploy-state-{id}.json` appears in some stale comments and in
  `generate_ui_env.sh`; that layout is obsolete.) `.deploy-state/` is gitignored.
- Keys: `deployment_id`, `started_at`, `stack_suffix`, `gateway_url`, `cors_origin`, and the nine step
  booleans: `infra_complete`, `prompts_uploaded`, `specialists_complete`, `gateway_complete`,
  `orchestrator_image_pushed`, `orchestrator_runtime_deployed`, `supporting_complete`,
  `ui_image_pushed`, `ecs_deployed`.
- `mark_complete` sets the flag to `True` **and** writes `{key}_at` as a UTC timestamp.
  `check_completed` tests `= "True"`. `invalidate_state` sets `False` and blanks the timestamp.
- `run_remaining` exports `DEPLOY_RESUME_MODE=1` and walks `ALL_STEPS` in order, returning on the first
  failure. `DEPLOY_RESUME_MODE=1` also auto-answers the submenus (step 2 → `6`, step 8 → `1`).
- Failure never marks a step complete. Note the comment at the bottom of `deploy.sh`: `dispatch "$1"`
  is deliberately **not** written as `dispatch "$1" || …`, because a command on the left of `||` runs
  with errexit suppressed for its whole call tree, which previously let a failed `cdk_deploy` fall
  through to `mark_complete`.

### Non-interactive runs

`_confirm` auto-answers yes on `MC_ASSUME_YES=1`. But `choose_deployment` has **no** bypass — it always
`read -rp`. A fully unattended run must feed stdin:

```bash
printf '1\n' | MC_ASSUME_YES=1 UI_PUBLIC_ACCESS=true ./deploy.sh 9
```

A bare `./deploy.sh 2` still prompts, because only `run_remaining` sets `DEPLOY_RESUME_MODE`.

### Environment variables

`deploy.sh`: `IMAGE_TAG` (default `latest`), `MODEL_ID` (default `us.anthropic.claude-sonnet-4-6`),
`UI_CONTAINER_PORT` (default `8080`), `UI_PUBLIC_ACCESS`, `MC_ASSUME_YES`, `MC_SKIP_XRAY`,
`AWS_REGION`/`AWS_DEFAULT_REGION`, `AWS_PROFILE`, `STACK_PREFIX`, `STACK_SUFFIX`, `CDK_QUALIFIER`.

`export_cdk_env` exports `DEPLOYMENT_ID STACK_SUFFIX STACK_PREFIX CDK_DEFAULT_ACCOUNT
CDK_DEFAULT_REGION TYPEGUARD_DISABLE=1 PYTHONWARNINGS`.

`app.py` at synth time also reads `GATEWAY_URL`, `CORS_ORIGIN`, `UI_CALLBACK_URL`
(default `http://localhost:7870/callback`), `UI_LOGOUT_URL`, `UI_PUBLIC_ACCESS`, and `CDK_NAG`
(`1|true|yes` adds `AwsSolutionsChecks(verbose=True)`).

### CDK wrappers

```bash
cdk_deploy()  { (unset VIRTUAL_ENV; cd "${DEPLOYMENT_DIR}" && uv run cdk deploy  --app "python app.py" --require-approval never "$@"); }
cdk_destroy() { (unset VIRTUAL_ENV; cd "${DEPLOYMENT_DIR}" && uv run cdk destroy --app "python app.py" --force "$@"); }
```

`ensure_cdk_deps` hard-requires `uv`, runs `uv sync --quiet` at the repo root, then points
`VIRTUAL_ENV`/`PATH` at `${REPO_ROOT}/.venv`.

### Preflights worth knowing

- `preflight_bootstrap` — checks `CDKToolkit` and reads
  `/cdk-bootstrap/${CDK_QUALIFIER:-hnb659fds}/${ACCOUNT_ID}/${AWS_REGION}` for the version.
- `preflight_docker_cross_platform {arm64|amd64}` — verifies QEMU cross-build works. The orchestrator
  must be arm64 (an AgentCore requirement); the UI must be amd64.
- `preflight_xray` / `ensure_xray_decision` — X-Ray Transaction Search is an **account-and-region
  singleton**, and enabling it needs a CloudWatch Logs resource policy. That policy competes for a
  hard, **non-adjustable** quota of 10 per region (`L-89892494`), shared with every other project in
  the account. Unchecked, CloudFormation fails mid-deploy with a bare "Resource limit exceeded" after
  other stacks already exist. Set `MC_SKIP_XRAY=1` when Transaction Search is already on.
- `common.sh` wraps `aws` and `python3` to strip `\r`, because native Windows builds emit `\r\n` and a
  stray `\r` silently breaks string comparisons, JMESPath filters, and derived resource names. Do not
  bypass those wrappers.

## The 17 CDK stacks

Instantiated in `deployment/app.py`, in this order:

| # | Class | Stack id | Purpose |
| --- | --- | --- | --- |
| 1 | `VpcStack` | `MC-Vpc-…` | Private subnets for the runtime, NAT for Bedrock egress, interface endpoints (Bedrock/S3/DynamoDB/SSM), flow logs. Exposes `vpc`, `runtime_sg`, `ui_task_sg`. |
| 2 | `CognitoStack` | `MC-Cognito-…` | One user pool, two clients: UI (OIDC auth-code + PKCE, public) and Gateway (M2M client-credentials, secret in Secrets Manager, scope `agentcore-gateway/invoke`). |
| 3 | `InferenceProfilesStack` | `MC-InferenceProfiles-…` | Bedrock Application Inference Profiles for cost attribution. Exposes `sonnet_46_arn`, `opus_46_arn`, `sonnet_45_arn`, `haiku_45_arn`, `grant_invoke_to_role()`. |
| 4 | `S3Stack` | `MC-S3-…` | Five buckets (access-logs, config, source, results, terms) plus the KMS key. Server access logging to the log bucket under `config/ source/ results/ terms/`. |
| 5 | `DynamoDBStack` | `MC-DynamoDB-…` | `contract_review_jobs`, PK `job_id` / SK `specialist`, plus a `status` GSI. |
| 6 | `ECRStack` | `MC-ECR-…` | Two repos: `orchestrator` and `ui`. (Its docstring says "one repository" — stale.) |
| 7 | `IAMStack` | `MC-IAM-…` | The orchestrator AgentCore Runtime execution role. |
| 8 | `KnowledgeBaseStack` | `MC-AnalysisKB-…` | Bedrock KB over the results bucket, S3 Vectors backend. |
| 8b | `TermsKBStack` | `MC-TermsKB-…` | Glossary KB. `chunking_strategy="NONE"`, Titan Embed v2, 1024-dim cosine index named `terms`. |
| 9 | `SpecialistLambdasStack` | `MC-Specialists-…` | One Lambda per specialist from the `SPECIALISTS` list. Python 3.13, 14-min timeout, 1024 MB, `reserved_concurrent_executions=10`, shared SQS DLQ, Powertools layer, `Tracing.ACTIVE`. |
| 10 | `GatewayStack` | `MC-Gateway-…` | AgentCore Gateway with each specialist as a Lambda-backed MCP target. Target names use hyphens to satisfy `^([0-9a-zA-Z][-]?){1,100}$`. |
| 11 | `XRayStack` | `MC-XRay-…` | Enables CloudWatch Transaction Search. Redeploying when already on fails with `AlreadyExists`. |
| 12 | `AgentCoreRuntimesStack` | `MC-Runtimes-…` | The single orchestrator runtime. Specialists are Lambdas, not runtimes. |
| 11b | `AutoTriggerStack` | `MC-AutoTrigger-…` | Lambda on `s3:ObjectCreated:*`, `prefix=pipeline/`, `suffix=.pdf`. |
| 11c | `KBSyncStack` | `MC-AnalysisKBSync-…` | Two Lambdas calling `StartIngestionJob`: results bucket `jobs-kb-versions/` → Contract KB; terms bucket → Terms KB. |
| 13 | `DashboardStack` | `MC-Dashboard-…` | CloudWatch dashboard: job health, per-specialist p50/p95/p99 and errors, throughput. |
| 14 | `ECSStack` | `MC-ECS-…` | ECS Express Gateway Service. All env from SSM `valueFrom` — no plaintext secrets. |

`DEPLOYMENT_TAGS = {"project": "media-contracts", "deployment_id": …, "managed_by": "cdk"}` is applied
to every stack.

### Dependency graph

```
IAM       → S3, DynamoDB, InferenceProfiles
AnalysisKB→ S3
TermsKB   → S3
Specialists → S3, DynamoDB, InferenceProfiles, TermsKB
Gateway   → Specialists, Cognito
Runtimes  → IAM, ECR, Vpc, Gateway, Cognito, InferenceProfiles, XRay
AutoTrigger → Runtimes, S3, DynamoDB
AnalysisKBSync → AnalysisKB, TermsKB, S3
Dashboard → Specialists, Runtimes, Gateway
ECS       → S3, DynamoDB, Runtimes, Cognito, Vpc
```

`inference_profiles_stack.grant_invoke_to_role(iam_stack.orchestrator_role)` is a cross-stack call at
`app.py:175`.

The Cognito token endpoint is hardcoded as
`https://media-contracts-{DEPLOYMENT_ID}-{STACK_SUFFIX}.auth.{AWS_REGION}.amazoncognito.com/oauth2/token`.

## SSM parameters

**Every parameter is written at `/mc-{stack_suffix}/…`.** Any `/media-contracts/…` you see in a
docstring or comment is stale.

| Parameter | Written by |
| --- | --- |
| `config-bucket-name`, `results-bucket-name`, `source-bucket-name`, `terms-bucket-name` | `s3_stack.py:227-251` |
| `jobs-table-name` | `dynamodb_stack.py:94` |
| `cognito-user-pool-id`, `cognito-ui-client-id`, `cognito-authority`, `cognito-domain`, `cognito-gateway-secret-arn`, `cognito-gateway-client-id`, `cognito-gateway-token-endpoint` | `cognito_stack.py:193-235` |
| `orchestrator-runtime-arn` | `agentcore_runtimes_stack.py:154` |
| `contract-kb-id` | `knowledge_base_stack.py:212` |
| `terms-kb-id` | `terms_kb_stack.py:195` |
| `chat-model`, `agent-mode`, `node-env` | `ecs_stack.py:84-98` |

IAM grants are prefix-scoped to `arn:aws:ssm:{region}:{account}:parameter/mc-{stack_suffix}/*`.

**Two known bugs here.** `specialist_lambdas_stack.py:270-271` grants read on
`/mc-{sfx}/gateway-url`, but **no stack writes it** — the gateway URL lives only in the CFN output and
the deploy state file. And `agentcore/auto_trigger/handler.py:30` plus `ui/server/index.js:22-33` look
up `/media-contracts/…` paths that are never written. The ECS container is unaffected because it gets
env vars by `valueFrom` on the correct paths.

## Key CloudFormation outputs

| Stack | Outputs |
| --- | --- |
| S3 | `ConfigBucketName`, `ConfigBucketArn`, `SourceBucketName`, `ResultsBucketName`, `ResultsBucketArn`, `TermsBucketName`, `TermsBucketArn`, `KmsKeyArn`. **No `AccessLogsBucketName`** — `destroy.sh` looks for it and falls back to the conventional name. |
| Cognito | `UserPoolId`, `UIClientId`, `GatewayClientId`, `Authority`, `CognitoDomain`, `GatewaySecretArn` |
| Gateway | `GatewayUrl`, `GatewayId`, `GatewayArn`, `GatewayRoleArn` |
| Runtimes | `OrchestratorRuntimeArn`, `OrchestratorRuntimeId` |
| AnalysisKB | `KnowledgeBaseId`, `KnowledgeBaseArn`, `DataSourceId` |
| TermsKB | `TermsKBId`, `TermsKBArn`, `TermsDataSourceId` |
| ECS | `ServiceArn`, `ServiceEndpoint`, `TaskRoleArn`, `ExecRoleArn` |
| ECR | `OrchestratorRepoUri`, `UIRepoUri` |
| Dashboard | `DashboardName`, `DashboardUrl` |

Read one with `stack_output "$(_sn S3)" ConfigBucketName`.

## `destroy.sh`

```bash
./destroy.sh                                     # choose the target interactively
DEPLOYMENT_ID=mc ./destroy.sh                    # explicit, cross-checked against AWS
DEPLOYMENT_ID=mc ./destroy.sh --vpc-cleanup-only  # standalone ENI/VPC remedy
```

Optional: `AWS_REGION`, `KMS_WAIT_DAYS` (default `7`, valid 7–30), `STACK_SUFFIX`.

With no `DEPLOYMENT_ID`, the target is discovered from **live CloudFormation stack names** rather than
local state — a state file can be deleted while the stacks are still up. Confirmation requires typing
the `DEPLOYMENT_ID` verbatim.

Order:

1. Empty the S3 buckets — all `Versions` then all `DeleteMarkers` via `list-object-versions` + `jq` +
   `delete-objects`, then `aws s3 rm --recursive`. Done here rather than left to `auto_delete_objects`
   because it is much faster on versioned buckets and avoids the custom resource timing out.
2. Capture `KmsKeyArn` (or resolve via the alias) and the VPC id before the stacks go.
3. Delete the **ECS Express service** with `delete-express-gateway-service` (plain `DeleteService`
   rejects it outright), falling back to `delete-service --force`. This also removes the load balancer
   it created.
4. Delete the AgentCore runtime: non-`DEFAULT` endpoints first, then `delete-agent-runtime`, polling
   36 × 10 s.
5. `cleanup_vpc_enis` — interface VPC endpoints first (they own ENIs), wait, then 12 rounds of
   delete-available / force-detach-then-delete.
6. `cdk_destroy` in **reverse dependency order**: `ECS, Dashboard, AnalysisKBSync, AutoTrigger,
   Runtimes, XRay, Gateway, Specialists, TermsKB, AnalysisKB, IAM, ECR, DynamoDB, S3,
   InferenceProfiles, Cognito, Vpc`.
7. If the VPC stack is `DELETE_FAILED`, auto-fix by re-issuing `delete-stack --retain-resources <failed
   logical ids>` then re-running the ENI cleanup.
8. Schedule KMS deletion **only if zero stacks remain** — scheduling after a partial failure would mark
   a live deployment's in-use key, which is unrecoverable after the window. Then `delete-alias` to free
   the name immediately for redeployment.
9. Remove `.deploy-state/{id}.json` and `.deploy-state/{id}-outputs.json`.

Steps 3–5 exist because **ENIs are the usual reason a VPC stack will not delete.** ECS and AgentCore
release theirs asynchronously, well after the service or runtime reports gone.

Manual-cleanup warnings it can emit: retained VPC resources needing manual deletion; ENIs it could not
clean up; a KMS alias it could not delete (redeployment then waits out `KMS_WAIT_DAYS`); and the KMS key
deliberately not scheduled because stacks are still live.

## Helper scripts

| Script | Use |
| --- | --- |
| `deployment/scripts/collect_logs.sh` | `DEPLOYMENT_ID=mc ./deployment/scripts/collect_logs.sh [--minutes 30] [--job-id abc-123]`. Prefix-discovers the orchestrator runtime, six specialist Lambdas, `auto-trigger`, `kb-sync-contract`, `kb-sync-terms`, `gw-observability` groups and writes `logs/collected-{timestamp}.txt`. **Does not include the ECS UI log group.** |
| `deployment/scripts/sync_prompts.py` | `python deployment/scripts/sync_prompts.py --bucket <config-bucket> [--dry-run]`. Alternative to step 2. Does not sync `schemas/`. |
| `deployment/scripts/generate_ui_env.sh` | Writes `ui/.env` with `VITE_COGNITO_*` from Cognito outputs. Called by step 7. **Currently buggy** — see below. |
| `deployment/scripts/build_and_push.sh` | Standalone orchestrator build. **Currently buggy** — see below. |

## Known bugs and stale references

Verified by reading the code. Do not trust these paths; deploy.sh's own steps are the working path.

1. **`generate_ui_env.sh`** builds `STACK_NAME="MC-Cognito-${STACK_SUFFIX}"` (lines 18/25), omitting
   `-${DEPLOYMENT_ID}-`, so it cannot resolve the real `MC-Cognito-{id}-{sfx}`. Its fallback state path
   `.deploy-state-${DEPLOYMENT_ID}.json` (line 21) also predates the `.deploy-state/` directory.
2. **`build_and_push.sh`** uses `REPO="media-contracts-orchestrator-${DEPLOYMENT_ID}"` (line 16),
   omitting the suffix, so it targets a repo `ECRStack` never creates. Use `./deploy.sh 5`.
3. `destroy.sh` iterates the `AccessLogsBucketName` S3 output, which `s3_stack.py` does not define.
   Only the conventional-name fallback empties that bucket.
4. `deploy.sh` failure hints point at `/ecs/media-contracts-$(resource_id)`, but `ecs_stack.py:286`
   creates `/ecs/media-contracts-ui-{id}-{sfx}`.
5. `app.py`'s module docstring numbers stacks 1–14 with old `MediaContracts*` names and references
   `.deploy-state-{DEPLOYMENT_ID}.json`. Both predate the current 17-stack `MC-…` scheme.
6. `ecr_stack.py`'s docstring says one repository; the stack creates two.
7. `/media-contracts/…` in `ecs_stack.py:8-19` and `cognito_stack.py:15,22-26` are stale comments; see
   the SSM section.

## Prerequisites

AWS CLI configured, Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js 20+, Docker running,
AWS CDK v2 (`npm install -g aws-cdk`), `jq` (used by `destroy.sh`). CDK must be bootstrapped:
`cdk bootstrap aws://{ACCOUNT_ID}/{AWS_REGION}`.
