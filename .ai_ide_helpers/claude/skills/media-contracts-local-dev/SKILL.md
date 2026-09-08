---
name: media-contracts-local-dev
description: Running, building, and checking the Media Contract Analyzer locally — uv and npm setup, the Express and Vite dev servers and their ports, ui/config/.env versus ui/.env, prompt iteration without deploying, MCS validation, mypy and pylint, the gitleaks pre-commit hook, Docker build constraints, and the code conventions to match. Use when setting up a dev environment, running the project locally, or looking for the build, lint, type-check, or test command.
license: MIT-0
metadata:
  project: media-contracts-analyzer
  verified-against: repository state, September 2026
---

# Local Development

## Read this first: there is no test suite

Verified by inspection, not inferred:

- **No test files.** No `test_*.py`, `*_test.py`, or `conftest.py` anywhere outside `.venv/` and
  `node_modules/`.
- **No test runner config.** No `[tool.pytest.ini_options]`, no `tox.ini`, no `Makefile`.
- **No formatter or linter config.** No ruff, no black.
- `mypy` and `pylint` **are** configured in `pyproject.toml` but nothing invokes them.
- The only enforced automation is a single pre-commit hook: **gitleaks** (`v8.30.0`).

So: do not claim a change is "tested". If asked to add tests, that means standing up pytest from
scratch — surface that as a decision rather than doing it silently. The available verification is
`validate_mcs.py`, `mypy`, `pylint`, `cdk synth`, and running the app.

## Toolchain

| Tool | Version |
| --- | --- |
| Python | `requires-python = ">=3.12.0"` |
| `uv` | required — `ensure_cdk_deps` in `common.sh` hard-errors without it |
| Node.js | 20+ (the UI image builds on `node:22-slim`) |
| Docker | required for image builds |
| AWS CDK v2 | `npm install -g aws-cdk` |
| poppler | required by `pdf2image` for local PDF rendering |

## Python setup

```bash
uv venv
source .venv/bin/activate
uv sync
```

`pyproject.toml` notes:

- `name = "Media-Contract-Analyzer"`, `version = "1.0.0"`.
- ~55 runtime dependencies including `aws-cdk-lib>=2.227.0`,
  `aws-cdk-aws-bedrock-agentcore-alpha`, `aws-cdk-aws-bedrock-alpha`, `cdk-nag`,
  `aws-cdk-mixins-preview==2.234.1a0`, `strands-agents`, `strands-agents[otel]`,
  `strands-agents-tools`, `bedrock-agentcore>=1.1.2`, `pydantic<2.12.0`, `gradio`, plus PDF/vision libs.
- **Two separate dev groups**, which is easy to miss:
  `[project.optional-dependencies] dev = ["pytest", "mypy", "pylint"]` and
  `[dependency-groups] dev = ["types-requests>=2.32.4.20260107"]`.
- `[tool.uv.workspace] members = [".kiro/skills/markdown_converter"]` — that directory is not in the
  repo, and `uv sync` tolerates its absence.
- `uv.lock`: `version = 1`, `revision = 3`, 232 packages.

## Running the UI

Two different `.env` files, for two different purposes. Mixing them up is the usual first stumble.

| File | Read by | When |
| --- | --- | --- |
| `ui/config/.env` | Express, line-by-line at boot (`ui/server/index.js:10-16`) | runtime |
| `ui/.env` | Vite, `VITE_*` only | **baked into the JS bundle at build time** |

`ui/config/.env.example` covers the server side; `ui/.env.example` covers both the `VITE_*` vars and a
second copy of the server vars. `deployment/scripts/generate_ui_env.sh` writes `ui/.env` from Cognito
stack outputs during deploy step 7.

```bash
cp ui/.env.example ui/config/.env
# edit with your deployed stack outputs
cd ui && npm install && npm run dev
```

### Ports

| Port | Process |
| --- | --- |
| **5180** | Vite dev server — `ui/vite.config.js`. **Open this one.** |
| **7870** | Express — `process.env.PORT \|\| 7870` (`ui/server/index.js:138`) |
| 8080 | Express inside the container — the `Dockerfile` sets `PORT=8080` |

`.github/documentation/LOCAL_DEV.md` says to open `http://localhost:5173`. That is Vite's default, but
this project pins `5180`. Use **5180**.

Vite proxies `/api` → `http://localhost:7870` with a `proxyRes` hook that re-asserts the SSE headers
(`text/event-stream`, `no-cache`, `keep-alive`, `X-Accel-Buffering: no`) and sets
`timeout`/`proxyTimeout` to `3600000` ms (1 h) so long pipeline runs are not cut off. Preserve all of
that if you touch the proxy config.

### npm scripts (`ui/package.json`)

| Script | Command |
| --- | --- |
| `dev` | `concurrently -n server,vite -c blue,green "node server/index.js" "vite"` |
| `build` | `vite build` → `ui/dist` (Vite default; `build.outDir` is not configured) |
| `preview` | `vite preview` |
| `server` | `node server/index.js` |

`"type": "module"`, React 19, `react-oidc-context`, `oidc-client-ts`, `jose`, Express 5, and AWS SDK v3
clients. Dev deps: `vite ^6.4.2`, `@vitejs/plugin-react ^4.5.2`.

### Local auth is off by default

`requireAuth` (`ui/server/index.js:102`) returns `next()` immediately when `COGNITO_USER_POOL_ID` is
unset. That is the local-dev escape hatch and it leaves every `/api/*` route open. Convenient locally,
never acceptable in a deployment.

With it set, it verifies the Cognito JWT with `jose` `createRemoteJWKSet` against
`https://cognito-idp.{AWS_REGION}.amazonaws.com/{POOL_ID}/.well-known/jwks.json`, checks
`payload.client_id || payload.aud === COGNITO_UI_CLIENT_ID`, and sets `req.user`.

`loadSSMConfig()` backfills any unset env var from SSM. Note its `SSM_PARAM_MAP` uses
`/media-contracts/…` paths, but the stacks write `/mc-{suffix}/…`, so **this backfill does not
currently resolve**. Set the vars explicitly in `ui/config/.env`.

## Running the pipeline without the UI

`.github/documentation/LOCAL_DEV.md` documents `run_pipeline.py` with `--specialists` and
`--agent-mode` flags, writing to `outputs/`. **`run_pipeline.py` does not exist in this repo**, and
neither does `outputs/`. The legacy in-process orchestrator it wrapped is still there
(`utils/orchestrator.py`, `ContractReviewOrchestrator.review(...)`), so a local driver can be
reconstructed — but it is not a supported entrypoint today. Do not follow that section of the docs as
written.

To exercise the deployed pipeline instead, upload through the UI or drop a PDF at `pipeline/*.pdf` in
the source bucket to hit the auto-trigger Lambda.

Sample contracts live in `samples/` (8 PDFs plus `ANNOTATED_01_Distribution_License_Agreement.pdf`).

## Iterating on prompts locally

`PromptLoader` picks its mode from `CONFIG_BUCKET`:

```bash
unset CONFIG_BUCKET   # forces local filesystem mode, reads media_contracts_agents/ directly
```

Prompts are cached in memory per process, so restart to pick up an edit. For deployed Lambdas the cache
resets on cold start; for the orchestrator, restart the runtime session.

Sync to S3 without a redeploy:

```bash
aws s3 sync media_contracts_agents/ s3://$CONFIG_BUCKET/prompts/agents/
```

See the `media-contracts-prompts-and-schema` skill for the full sync manifest.

## Checks you can actually run

```bash
# MCS schema validation — the closest thing to a test suite
python3 schemas/base/validate_mcs.py media_contracts_agents/

# Types (config: python_version 3.12, warn_return_any, warn_unused_configs, disallow_untyped_defs)
uv run mypy agentcore/ utils/ --ignore-missing-imports

# Lint (config disables C0103 invalid-name and R0903 too-few-public-methods)
uv run pylint agentcore/ utils/

# Secret scanning
uv run pre-commit install
uv run pre-commit run --all-files
```

CDK:

```bash
cd deployment
DEPLOYMENT_ID=dev STACK_SUFFIX=a1b uv run cdk synth --app "python app.py"
DEPLOYMENT_ID=dev STACK_SUFFIX=a1b uv run cdk diff  --app "python app.py" MC-Specialists-dev-a1b
CDK_NAG=1 DEPLOYMENT_ID=dev STACK_SUFFIX=a1b uv run cdk synth --app "python app.py"
```

`STACK_SUFFIX` matters: omit it and `app.py` generates a random one, so stack names will not match
anything deployed. `LOCAL_DEV.md`'s `cdk diff … MediaContractsSpecialists` uses the pre-suffix naming
scheme and no longer resolves.

## Docker builds

Both images build from the **repo root** as context.

**Orchestrator** (`agentcore/orchestrator/Dockerfile`): `FROM --platform=linux/arm64 python:3.12-slim`.
ARM64 is an AgentCore requirement, not a preference. apt-installs `poppler-utils libgl1
libglib2.0-0`; copies `utils/`, `media_contracts_agents/`, `agentcore/shared/`,
`agentcore/orchestrator/main.py`. `ENV PORT=8080 PYTHONPATH=/app`, non-root uid 1001, healthcheck on
`/health`. AgentCore requires listening on `0.0.0.0:8080`.

**UI** (`Dockerfile`): two stages, both `node:22-slim`. Stage 1 runs `npm ci && npm run build`; stage 2
`npm ci --omit=dev`, copies `ui/server/`, `ui/config/`, then `rm -f ui/config/.env` (production config
comes from SSM) and `--from=frontend /app/ui/dist`. `ENV NODE_ENV=production PORT=8080
AWS_REGION=us-west-2`, non-root uid 1001, healthcheck GETs `/api/env`, `CMD ["node",
"ui/server/index.js"]`. No Python in the runtime image, by design.

`agentcore/agentcore.json` describes the runtime for AgentCore tooling:
`name: "MediaContractsOrchestrator"`, `framework: "Strands"`, `codeLocation: "agentcore/orchestrator"`,
`entrypoint: "main.py"`, `build: "Container"`, `protocol: "HTTP"`, `networkMode: "VPC"`,
`memory: "none"`.

## Code conventions to match

- **Structured log strings.** `agentcore/shared/logging_config.py` scrapes `key=value` tokens out of the
  message text and promotes ~25 allowlisted keys to top-level JSON fields for Logs Insights. So write
  `logger.info("job=%s step=extraction elapsed=%.1fs", job_id, elapsed)` — not an f-string, not a dict.
  Breaking that pattern silently loses the queryable fields.
- **`from __future__ import annotations`** at the top of every Python module here.
- **Type hints everywhere** — `disallow_untyped_defs = true`.
- **Module docstrings** documenting env vars and payload schemas. `main.py`, `handler.py`,
  `job_state.py`, and `kb_writer.py` are the models to follow.
- **Tracing and metrics never break a job.** `tracing.py` and `metrics.py` swallow their own
  exceptions. Keep that.
- **Section banners** — `# ── Config ─────…` comment rules separate sections in the Python modules and
  `# ══…` in the shell scripts.
- **`status` is a DynamoDB reserved word.** Every update needs
  `ExpressionAttributeNames={"#s": "status"}`.
- **Inclusive language** — no `master`/`slave`, `whitelist`/`blacklist`. Use primary/replica,
  allowlist/denylist.

## Gitignored paths

`.kiro/`, `.claude/`, `.vscode/`, `.idea/`, `.deploy-state/`, `.venv/`, `node_modules/`, `ui/dist/`,
`outputs/`, `logs/`, `*.log`, `.env`, `cdk.out/`, `cdk.context.json`, `__pycache__/`, `.mypy_cache/`,
`.pytest_cache/`, `plan.md`, `notes.md`, `scratch/`.

`.kiro/` and `.claude/` being ignored matters if you install agent skills into them — they will not be
committed unless force-added. The canonical copies live in `.ai_ide_helpers/`.

## Documentation index

`.github/documentation/`: `ARCHITECTURE.md`, `AGENTS.md`, `DEPLOYMENT.md`, `AUTHENTICATION.md`, `UI.md`,
`UPLOAD_AND_PIPELINE_FLOW.md`, `LOCAL_DEV.md`, `VISION_LLM_THEORY_README.md`. Plus `schemas/base/`
(`README.md`, `QUICKSTART.md`, `IMPLEMENTATION_MATRIX.md`, `CHANGELOG.md`,
`DOCUMENTATION_SUMMARY.md`) and per-analyzer `README.md` files under `media_contracts_agents/`.

Useful, but check the code before repeating a specific claim. Confirmed-stale items are listed in the
`media-contracts-architecture` and `media-contracts-deployment` skills.
