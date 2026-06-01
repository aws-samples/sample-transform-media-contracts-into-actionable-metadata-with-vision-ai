# Local Development

[← Home](../../README.md) | [Architecture](ARCHITECTURE.md) | [Agents & Prompting](AGENTS.md) | [Deployment](DEPLOYMENT.md) | [UI](UI.md)

---

## Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Node.js 20+, npm
- AWS credentials configured (read access to S3, Bedrock, DynamoDB)
- A deployed stack (or at minimum: S3 config bucket with prompts, Bedrock model access)

---

## Python Environment

```bash
uv venv
source .venv/bin/activate
uv sync
```

---

## UI (Express + React)

```bash
cp ui/.env.example ui/config/.env
# Edit ui/config/.env with your deployed stack outputs
```

Minimum required values in `ui/config/.env`:

```env
ORCHESTRATOR_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:...
JOBS_TABLE_NAME=media-contracts-jobs-dev
CONFIG_BUCKET=media-contracts-config-dev
RESULTS_BUCKET=media-contracts-results-dev
SOURCE_BUCKET=media-contracts-source-dev
COGNITO_USER_POOL_ID=us-west-2_...
AWS_REGION=us-west-2
ALLOWED_ORIGIN=http://localhost:7870

# Vite build-time (baked into JS bundle)
VITE_COGNITO_AUTHORITY=https://cognito-idp.us-west-2.amazonaws.com/us-west-2_...
VITE_COGNITO_CLIENT_ID=...
VITE_COGNITO_DOMAIN=https://media-contracts-dev.auth.us-west-2.amazoncognito.com
```

```bash
cd ui
npm install
npm run dev    # starts both Express (port 7870) and Vite dev server concurrently
```

The Vite dev server proxies API requests to Express. Open `http://localhost:5173`.

---

## Run Pipeline Locally (no UI)

`run_pipeline.py` runs the full contract review pipeline locally using `utils/orchestrator.py`. This uses Strands agents in-process — no AgentCore Runtime or Lambda required.

```bash
# Single contract, auto-detect specialists
RESULTS_BUCKET=media-contracts-results-dev \
uv run python run_pipeline.py samples/sample_contract.pdf

# Specify specialists
RESULTS_BUCKET=media-contracts-results-dev \
uv run python run_pipeline.py samples/sample_contract.pdf \
  --specialists financial,rights_clearance

# Agent mode (orchestrator selects specialists)
RESULTS_BUCKET=media-contracts-results-dev \
uv run python run_pipeline.py samples/sample_contract.pdf \
  --agent-mode
```

Outputs are written to `outputs/{contract_name}/` and uploaded to S3.

---

## Prompt Development

Prompts are XML files in `media_contracts_agents/`. Edit locally, then sync to S3:

```bash
CONFIG_BUCKET=media-contracts-config-dev
aws s3 sync media_contracts_agents/ s3://$CONFIG_BUCKET/prompts/agents/
```

The `PromptLoader` caches prompts in memory per process. For the local pipeline, restart the process to pick up changes. For deployed Lambda functions, the cache resets on cold start.

To test a prompt change without deploying:

```bash
# Unset CONFIG_BUCKET to force local filesystem mode
unset CONFIG_BUCKET
uv run python run_pipeline.py samples/sample_contract.pdf
```

---

## CDK Development

```bash
cd deployment
uv sync

# Synthesize without deploying
DEPLOYMENT_ID=dev cdk synth --app "python app.py"

# Diff against deployed stack
DEPLOYMENT_ID=dev cdk diff --app "python app.py" MediaContractsSpecialists
```

---

## Type Checking

```bash
uv run mypy agentcore/ utils/ --ignore-missing-imports
```

---

## Linting

```bash
uv run pylint agentcore/ utils/
```

Pre-commit hooks are configured in `.pre-commit-config.yaml`. Install with:

```bash
uv run pre-commit install
```

---

## Project Layout Reference

```
agentcore/
├── orchestrator/
│   ├── main.py              # AgentCore Runtime entrypoint (Strands agent)
│   ├── Dockerfile
│   └── requirements.txt
├── specialist_lambda/
│   └── handler.py           # Shared Lambda handler (3-call pattern: identify → retrieve → analyze)
├── specialists/             # Specialist-specific logic modules
├── auto_trigger/            # S3 pipeline/ event → Lambda → invoke Runtime
├── kb_sync/                 # S3 results/terms event → Lambda → KB ingestion
└── shared/
    ├── bedrock_client.py    # Model ID → inference profile ARN resolution
    ├── job_state.py         # DynamoDB read/write helpers
    ├── logging_config.py    # Structured JSON logging setup
    ├── metrics.py           # CloudWatch custom metrics
    └── tracing.py           # X-Ray annotation helpers

deployment/
├── app.py                   # CDK app, stack wiring
├── cdk.json
├── requirements.txt
├── scripts/
│   ├── build_and_push.sh    # Build + push orchestrator container
│   ├── generate_ui_env.sh   # Generate ui/config/.env from stack outputs
│   └── sync_prompts.py      # Sync local prompts to S3
└── stacks/
    ├── agentcore_runtimes_stack.py
    ├── auto_trigger_stack.py
    ├── cognito_stack.py
    ├── dashboard_stack.py
    ├── dynamodb_stack.py
    ├── ecr_stack.py
    ├── ecs_stack.py
    ├── gateway_stack.py
    ├── iam_stack.py
    ├── inference_profiles_stack.py
    ├── kb_sync_stack.py
    ├── knowledge_base_stack.py
    ├── s3_stack.py
    ├── specialist_lambdas_stack.py
    ├── terms_kb_stack.py
    ├── vpc_stack.py
    └── xray_stack.py

media_contracts_agents/
├── foundation/              # Shared foundation prompt XML files
├── extractor/               # Extractor agent prompts
├── financial/
├── rights_clearance/
├── talent_guild_compliance/
├── regulatory_compliance/
├── risk_strategist/
└── handwriting_analyzer/

utils/
├── agent_factory.py         # Creates Strands agents from prompt files (local path)
├── glossary_lookup.py       # Glossary lookup tool (local path)
├── orchestrator.py          # Local pipeline orchestrator (no AgentCore)
├── pdf_to_images.py         # PDF → JPEG page images
└── prompt_loader.py         # S3/local XML prompt assembly

ui/
├── server/
│   ├── index.js             # Express app, auth middleware, CORS, SSM config
│   └── routes.js            # API route handlers
└── src/
    ├── App.jsx
    └── components/
        ├── Chat.jsx
        ├── CostCalculator.jsx
        ├── Header.jsx
        ├── Home.jsx
        ├── JobStatus.jsx
        ├── KBChat.jsx
        ├── LegalTeam.jsx
        ├── Login.jsx
        └── ResultsBrowser.jsx
```
