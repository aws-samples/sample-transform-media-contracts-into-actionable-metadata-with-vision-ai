# Agents & Prompting

[← Home](../../README.md) | [Architecture](ARCHITECTURE.md) | [Deployment](DEPLOYMENT.md) | [Authentication](AUTHENTICATION.md) | [UI](UI.md) | [Local Dev](LOCAL_DEV.md)

---

## Orchestrator

The orchestrator is a **Strands agent** running inside an AgentCore Runtime container. It is the only component that uses an agent framework — all specialists are plain Bedrock API calls.

**Entry point:** `agentcore/orchestrator/main.py`
**Container:** `agentcore/orchestrator/Dockerfile`

### What it does

1. Downloads the contract PDF from S3
2. Renders pages to images (128 DPI JPEG) via `utils/pdf_to_images.py`
3. Runs parallel page extraction — up to 8 concurrent Claude vision calls, each with the extractor system prompt
4. Concatenates page extractions in order
5. Fetches a Cognito M2M token from Secrets Manager
6. Connects to the AgentCore Gateway as an MCP client
7. Runs the Strands agent with the extraction text and available specialist tools
8. In **agent mode**: agent selects tools freely based on contract content
9. In **user mode**: tool list is filtered to the user's selected specialists
10. Runs a summary `Converse` call to produce the executive summary
11. Writes all outputs to S3, updates DynamoDB, emits CloudWatch metrics

### Why Strands here

The orchestrator needs to reason about which specialists to invoke, handle multi-turn tool use, and manage the MCP connection lifecycle. That's what an agent framework is for.

---

## Specialists

Six specialists, each a Lambda function sharing the same handler code (`agentcore/specialist_lambda/handler.py`). The `SPECIALIST_NAME` environment variable selects the prompt.

| Specialist                | Domain                                                                         |
| ------------------------- | ------------------------------------------------------------------------------ |
| `financial`               | Revenue share, MFN clauses, payment terms, royalties, audit rights             |
| `rights_clearance`        | IP ownership, chain of title, licensing scope, territorial rights, reversions  |
| `talent_guild_compliance` | SAG-AFTRA, WGA, DGA obligations, residuals, credit requirements                |
| `regulatory_compliance`   | GDPR, content quotas, accessibility, export controls, age ratings              |
| `risk_strategist`         | Cross-cutting risk synthesis, negotiation roadmap, prioritized recommendations |
| `handwriting_analyzer`    | Handwritten annotations, margin notes, signatures, handwritten amendments      |

### Three-call pattern (no agent framework)

Each specialist makes exactly three Bedrock API calls:

```
Call 1 — Converse (512 tokens max)
  Prompt: "Given this extraction, what domain terms should I look up?"
  Output: list of search queries

Call 2 — Retrieve (bedrock-agent-runtime)
  Query: the terms from call 1
  KB: glossary knowledge base
  Results: up to 10 chunks

Call 3 — Converse (MAX_TOKENS)
  Input: system prompt + glossary definitions + extraction
  Output: specialist XML analysis
```

The glossary grounding in call 3 is explicit — the prompt instructs the specialist to cite glossary entries when a term or clause matches.

---

## Prompt System

Prompts are modular XML files assembled at runtime by `utils/prompt_loader.py`.

### S3 Layout

```
s3://media-contracts-config-{id}/prompts/
├── foundation/
│   ├── foundation_rules.xml
│   ├── foundation_context.xml
│   └── ...
└── agents/
    ├── extractor/
    │   ├── extractor_job_role.xml
    │   ├── extractor_tasks.xml
    │   ├── extractor_rules.xml
    │   ├── extractor_format.xml
    │   └── extractor_verification.xml
    ├── financial/
    │   └── ...
    └── {specialist}/
        └── ...
```

Local mirror: `media_contracts_agents/`

### Assembly

`load_agent_prompt(agent_name)` concatenates:
1. All files under `foundation/` (sorted alphabetically)
2. All files under `agents/{agent_name}/` (sorted alphabetically)

The result is the system prompt passed to every Bedrock `Converse` call for that specialist.

### Updating Prompts

In production: `aws s3 cp new_file.xml s3://media-contracts-config-{id}/prompts/agents/{name}/`

Changes take effect on the next Lambda cold start (prompts are cached in memory per container instance). For the orchestrator, restart the AgentCore Runtime session.

---

## Glossary Knowledge Base

The glossary KB is a Bedrock Knowledge Base (S3 Vectors backend) containing domain definitions for media contract terminology.

**KB ID** is passed to specialists via the `GLOSSARY_KB_ID` environment variable. Set `GLOSSARY_KB_ID=<id>` before deploying the Specialists stack.

If `GLOSSARY_KB_ID` is not set, specialists skip the retrieve step and proceed with call 3 using only the system prompt and extraction.

The IAM policy for `bedrock-agent-runtime:Retrieve` is scoped to the specific KB ARN when the ID is known at deploy time.

---

## Results Knowledge Base

A separate KB (`KnowledgeBaseStack`) ingests specialist outputs and summaries from the results S3 bucket. This powers the KB Chat tab in the UI — users can ask questions about past contract analyses.

Data source prefixes ingested:
- `*/specialists/` — all specialist XML outputs
- `*/risk_synthesis.xml`
- `*/final-executive-summary.md`

---

## Local Orchestrator (`utils/orchestrator.py`)

A standalone Python orchestrator used by `run_pipeline.py` for local testing. It uses Strands agents directly (no AgentCore Runtime) and writes outputs to `outputs/`. This path does not use the Lambda specialists — it runs specialist agents in-process.

See [Local Development](LOCAL_DEV.md) for usage.
