# Deployment

[← Home](../../README.md) | [Architecture](ARCHITECTURE.md) | [Agents & Prompting](AGENTS.md) | [Authentication](AUTHENTICATION.md) | [UI](UI.md) | [Local Dev](LOCAL_DEV.md)

---

## Prerequisites

- AWS CLI configured with credentials for the target account
- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Node.js 20+, npm
- Docker (running)
- AWS CDK v2: `npm install -g aws-cdk`
- CDK bootstrapped: `cdk bootstrap aws://{account}/{region}`

---

## Stack Overview

18 CDK stacks deployed via `deploy.sh`. All stacks are defined in `deployment/stacks/` and wired together in `deployment/app.py`.

| #   | Stack                        | Key resources                                                                |
| --- | ---------------------------- | ---------------------------------------------------------------------------- |
| 1   | `MC-Vpc-{sfx}`               | VPC, private/public subnets, NAT gateway, VPC endpoints                      |
| 2   | `MC-Cognito-{sfx}`           | User pool, UI client (PKCE), Gateway M2M client, Secrets Manager             |
| 3   | `MC-InferenceProfiles-{sfx}` | Application Inference Profiles (Sonnet 4.6, Opus 4.6, Sonnet 4.5, Haiku 4.5) |
| 4   | `MC-S3-{sfx}`                | config, source, results, terms buckets + KMS key + logging bucket            |
| 5   | `MC-DynamoDB-{sfx}`          | jobs table with status GSI                                                   |
| 6   | `MC-ECR-{sfx}`               | ECR repos for orchestrator + UI containers                                   |
| 7   | `MC-IAM-{sfx}`               | Orchestrator execution role                                                  |
| 8a  | `MC-AnalysisKB-{sfx}`        | Bedrock Knowledge Base — contract analysis (S3 Vectors)                      |
| 8b  | `MC-TermsKB-{sfx}`           | Bedrock Knowledge Base — glossary terms (S3 Vectors)                         |
| 9   | `MC-Specialists-{sfx}`       | 6 specialist Lambda functions + shared DLQ + explicit log groups             |
| 10  | `MC-Gateway-{sfx}`           | AgentCore Gateway (MCP, specialist tools, observability delivery)            |
| 11  | `MC-XRay-{sfx}`              | X-Ray Transaction Search (account-level)                                     |
| 12  | `MC-Runtimes-{sfx}`          | Orchestrator AgentCore Runtime (VPC, arm64 container)                        |
| 13  | `MC-AutoTrigger-{sfx}`       | S3 `pipeline/` prefix event → Lambda → auto-start pipeline                   |
| 14  | `MC-AnalysisKBSync-{sfx}`    | S3 events → Lambda → KB ingestion (results + terms buckets)                  |
| 15  | `MC-Dashboard-{sfx}`         | CloudWatch operational dashboard                                             |
| 16  | `MC-ECS-{sfx}`               | ECS Express Mode service (UI container, SSM-backed config)                   |

`{sfx}` is a 3-character random suffix auto-generated on first deploy and persisted in `.deploy-state/{DEPLOYMENT_ID}.json`. This allows parallel environments without name collisions.

---

## Environment Variables

Set these before deploying:

| Variable          | Required | Description                                                                   |
| ----------------- | -------- | ----------------------------------------------------------------------------- |
| `DEPLOYMENT_ID`   | Yes      | Short identifier appended to all resource names (e.g. `dev`, `prod`)          |
| `MODEL_ID`        | No       | Bedrock model ID (default: `us.anthropic.claude-sonnet-4-6`)                  |
| `IMAGE_TAG`       | No       | ECR image tag to deploy (default: `latest`)                                   |
| `AWS_REGION`      | No       | Target region (default: `us-west-2`)                                          |
| `UI_CALLBACK_URL` | No       | Cognito callback URL (default: `http://localhost:7870/callback`)              |
| `UI_LOGOUT_URL`   | No       | Cognito logout URL (default: `http://localhost:7870/`)                        |
| `ECS_SERVICE_URL` | No       | ECS service base URL for UI env generation (default: `http://localhost:7870`) |

`GATEWAY_URL` is auto-detected from stack outputs after step 4 and persisted in state. You never need to set it manually.

---

## deploy.sh — Interactive Menu

`deploy.sh` is the primary deployment tool. It provides an interactive menu with 8 resumable steps, tracks state in `.deploy-state/`, and is fully idempotent.

```bash
# Interactive mode
DEPLOYMENT_ID=dev ./deploy.sh

# Non-interactive — run a specific step
DEPLOYMENT_ID=dev ./deploy.sh 1    # Foundational infra
DEPLOYMENT_ID=dev ./deploy.sh 9    # Full deploy (all steps)
```

### Menu

```
 1) Foundational Infra (VPC, S3, Cognito, DynamoDB, ECR, IAM, KBs)
 2) Upload Prompts, Schemas & Glossaries
 3) Specialist Lambdas
 4) Gateway
 5) Orchestrator — Build & Deploy
 6) Supporting Stacks (AutoTrigger, KBSync, Dashboard)
 7) UI — Build & Push Image
 8) UI — Deploy ECS

 9) Full Deployment (Run All Steps)

10) Show Deployment Status
11) Reset Deployment State (start fresh)
 0) Exit
```

### What Each Step Deploys

| Step | What it deploys                                                    |
| ---- | ------------------------------------------------------------------ |
| 1    | VPC, Cognito, InferenceProfiles, S3, DynamoDB, ECR, IAM, KBs, XRay |
| 2    | Syncs `media_contracts_agents/`, `schemas/`, glossaries to S3      |
| 3    | 6 specialist Lambda functions                                      |
| 4    | AgentCore Gateway + observability delivery (auto-captures URL)     |
| 5    | Builds arm64 container, pushes to ECR, deploys Runtime stack       |
| 6    | AutoTrigger, KBSync, Dashboard                                     |
| 7    | Generates `.env`, builds React, builds container, pushes to ECR    |
| 8    | Deploys ECS stack, forces rollout, updates S3 CORS                 |
| 9    | Runs steps 1–8 in sequence                                         |
| 10   | Display completion state of all steps                              |
| 11   | Clear `.deploy-state/` to start fresh                              |

### State Tracking

State is persisted in `.deploy-state/{DEPLOYMENT_ID}.json`. Each step is marked complete after success. Re-running a completed step prompts for confirmation before proceeding. This makes the deploy fully resumable after failures.

### Two-Phase Rationale

The Gateway URL is only known after stack 10 deploys (it's a runtime value, not a CDK token). The orchestrator Runtime needs it as an environment variable. Steps 1–4 are "phase 1" and step 5+ is "phase 2". `deploy.sh` handles this automatically.

---

## Manual CDK Commands

If you need to deploy individual stacks directly:

```bash
cd deployment
uv sync

# Set required env vars
export DEPLOYMENT_ID=dev
export STACK_SUFFIX=a1b  # from .deploy-state/dev.json
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-west-2

# Deploy a specific stack
uv run cdk deploy --app "python app.py" --require-approval never MC-Specialists-a1b

# Diff against deployed
uv run cdk diff --app "python app.py" MC-Specialists-a1b

# Synth (check for errors without deploying)
uv run cdk synth --app "python app.py"
```

---

## Build and Push Orchestrator Container (manual)

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REPO="${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com/media-contracts-orchestrator-dev-a1b"

aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.us-west-2.amazonaws.com"

# Must be linux/arm64 — AgentCore Runtime requirement
docker buildx build --platform linux/arm64 \
  --file agentcore/orchestrator/Dockerfile \
  --tag "${ECR_REPO}:latest" --push .
```

---

## Upload Prompts to S3 (manual)

```bash
CONFIG_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name MC-S3-a1b \
  --query "Stacks[0].Outputs[?OutputKey=='ConfigBucketName'].OutputValue" \
  --output text)

aws s3 sync media_contracts_agents/ s3://$CONFIG_BUCKET/prompts/agents/
aws s3 sync schemas/ s3://$CONFIG_BUCKET/schemas/
```

---

## Teardown

```bash
cd deployment
DEPLOYMENT_ID=dev STACK_SUFFIX=a1b uv run cdk destroy --app "python app.py" --all
```

**Notes:**
- KMS key has `RemovalPolicy.RETAIN` — delete manually if needed
- S3 buckets have `auto_delete_objects=True` — they will be emptied and deleted
- Delete the `.deploy-state/` file after teardown

---

## CDK Nag

All stacks run `AwsSolutionsChecks`. Suppressions are applied inline with documented justifications. To run the checks locally:

```bash
cd deployment
DEPLOYMENT_ID=dev STACK_SUFFIX=a1b uv run cdk synth --app "python app.py" 2>&1 | grep -i nag
```
