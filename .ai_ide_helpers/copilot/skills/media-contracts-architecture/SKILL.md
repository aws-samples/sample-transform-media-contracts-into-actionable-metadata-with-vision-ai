---
name: media-contracts-architecture
description: Runtime architecture of the Media Contract Analyzer — the upload to extract to specialist to synthesis pipeline, the AgentCore Runtime orchestrator, the MCP Gateway, the specialist Lambdas, S3/DynamoDB/Knowledge Base layouts, and per-component environment variables. Use when asked how this system works, where a component lives, what a module does, how a job flows end to end, or when tracing job state, S3 keys, SSE progress, or a pipeline failure.
license: MIT-0
metadata:
  project: media-contracts-analyzer
  verified-against: repository state, September 2026
---

# Media Contract Analyzer — Architecture

AI contract review. A user uploads a contract PDF; the system extracts it page by page with a
vision model, fans out to domain specialists that ground their findings in a glossary knowledge
base, synthesises cross-cutting risk, and writes an executive summary. Results land in S3 and are
ingested into a Bedrock Knowledge Base for follow-up Q&A.

Derived from `aws-samples/sample-badgers`. Licence MIT-0.

## Ground rules for working in this repo

- **Read the code, not just the docs.** `.github/documentation/` is thorough but has drifted in
  specific places. Known-stale claims are listed at the end of this file.
- **`agentcore/` is the deployed path. `utils/orchestrator.py` is legacy.** The deployed
  orchestrator imports exactly one symbol from it (`_download_s3`). Its specialist-routing logic
  (`_SPECIALIST_MAP`, `_detect_specialists`) is dead in production.
- **Specialists never receive contract text over the wire.** They receive an S3 prefix and read
  extraction pages themselves. This is deliberate — it keeps the orchestrator's context window and
  the MCP payload small.
- **Two independent name shapes.** Stack names are `MC-{Name}-{DEPLOYMENT_ID}-{SUFFIX}`; resource
  names use `{DEPLOYMENT_ID}-{SUFFIX}`. See the `media-contracts-deployment` skill.

## Repo map

| Path | What lives here |
| --- | --- |
| `agentcore/orchestrator/main.py` | AgentCore Runtime entrypoint. The only Strands agent in the deployed path. |
| `agentcore/specialist_lambda/handler.py` | One shared handler for **all** specialists. Identity comes from `SPECIALIST_NAME`. |
| `agentcore/specialists/*/` | **Empty directories.** Vestigial from a per-specialist-runtime design. Do not add code here. |
| `agentcore/auto_trigger/handler.py` | S3 `ObjectCreated` on `pipeline/*.pdf` → invoke the orchestrator runtime. Bypasses the UI. |
| `agentcore/kb_sync/handler.py` | S3 event → `StartIngestionJob` on a Bedrock KB. 48 lines. |
| `agentcore/shared/` | Cross-component libraries: Bedrock model factory, DynamoDB job state, dual-prefix S3 writer, logging, metrics, tracing, summary hook. |
| `utils/` | Prompt loader, PDF→images, legacy local orchestrator, glossary helpers. Bundled into the Lambda package. |
| `media_contracts_agents/` | XML system prompts, one directory per analyzer. See `media-contracts-prompts-and-schema`. |
| `schemas/base/` | MCS v1.0 base schema and validator. |
| `schemas/specialists/*.json` | MCP tool schemas the Gateway serves, one per specialist. |
| `deployment/` | CDK app (17 stacks), helper scripts, glossary source data. |
| `ui/server/` | Express API (`index.js` bootstrap + auth, `routes.js` all routes). |
| `ui/src/` | React app. `Chat.jsx` drives upload and SSE consumption. |
| `prompts/main-agent.xml`, `prompts/terms-kb.xml` | UI-server prompts. **Not** loaded by `PromptLoader`. |

## End-to-end flow

### 1. Upload (browser → S3 directly)

`ui/src/components/Chat.jsx` → `handleFileUpload` rejects non-`.pdf`, POSTs to `/api/upload-url`,
then `PUT`s the file straight to S3 with the presigned URL.

`POST /api/upload-url` (`ui/server/routes.js:584`) — sanitises the filename
(`/[^a-zA-Z0-9._-]/g → _`), builds the key `testing/{cognito_sub}/{uuid}-{safeFilename}`, and
presigns a `PutObjectCommand` with `expiresIn: 900`. Returns `{uploadUrl, s3Uri, key}`.

### 2. Kick off (`POST /api/analyze`, `ui/server/routes.js:204`)

1. Resolves per-user session state from an **in-memory `Map`** keyed on Cognito `sub`
   (`userSessions`, `routes.js:44`). Resets on server restart.
   `DEFAULT_SPECIALISTS = ['financial','rights_clearance','talent_guild_compliance','regulatory_compliance']`.
2. Sets SSE headers and flushes.
3. **Idempotency gate** — DynamoDB query on `job_id` + `specialist = 'orchestrator'`. If already
   `COMPLETE`, emits `progress`/`done` with `cached: true` and returns without invoking anything.
4. Builds `runtimeSessionId = "{username}--{jobId}"`, clamped to 256 chars. AgentCore requires
   33–256; the 36-char UUID guarantees the floor.
5. **Fire-and-forget** `InvokeAgentRuntimeCommand` with `qualifier: 'DEFAULT'` and payload
   `{job_id, contract_path, specialists, agent_mode}`. The promise is only `.catch()`-ed — progress
   comes from DynamoDB, never from the response.
6. Polls DynamoDB and re-emits transitions as SSE. See *Job state* below.

`@aws-sdk/client-bedrock-agentcore` is CJS-only, so it is loaded via `createRequire`
(`routes.js:6-8`). Keep that pattern if you touch those imports.

### 3. Orchestrator (`agentcore/orchestrator/main.py`)

`@app.entrypoint def handler(payload, _context)` at `main.py:393`:

- Reads `job_id`, `contract_path`, `specialists`, `agent_mode` (default `True`).
- Pulls `session_id` off the AgentCore context for log correlation.
- Second idempotency check via `get_record(job_id, "orchestrator")`.
- `create_pending` → `mark_running` → `app.add_async_task("contract_review", ...)` → `_run_pipeline`
  → `mark_complete`/`mark_failed` → `app.complete_async_task`.

`_run_pipeline` (`main.py:449`) computes the per-job S3 prefix:

```
s3_prefix = f"{session_id}-{contract_stem}_{YYYYMMDDTHHMMSSZ}"   # UI path
s3_prefix = f"{contract_stem}_{YYYYMMDDTHHMMSSZ}"                # auto-trigger (no session id)
```

Stages:

1. **Download** — `s3://` inputs go to a `NamedTemporaryFile(suffix=".pdf")`, `os.unlink`ed in a
   `finally`.
2. **Extraction** (`_extract_contract`, `main.py:228`). PDF branch renders pages with
   `pdf_to_page_images(local_path, dpi=128)`, then one Claude vision call per page —
   `ThreadPoolExecutor(max_workers=min(total_pages, 8))`, `make_model(MODEL_ID, 16000)`. Each page
   gets `[{text: instructions}, {image: {...}}]` and is told to set `page="N"`,
   `<contract_completeness>PARTIAL_MULTI_PAGE</contract_completeness>`, `<page_count>1</page_count>`.
   Writes `extraction/page_{n:03d}.xml` per page plus a combined `extraction.xml`
   (`_build_assessment_envelope`) for backward compatibility. `_parse_extraction_tags` regex-scrapes
   `<tag>`, `<contract_type>`, `<topical_analysis>` into `{tags, contract_type, topical_summary}`.
   Non-PDF branch is a single call at 64000 tokens.
3. **Specialist analysis** (`main.py:518`). `_get_gateway_token()` reads the Cognito client secret
   from Secrets Manager and does a `client_credentials` grant with
   `scope="agentcore-gateway/invoke"`. **No token caching** — deliberate, tokens live 1 h and jobs
   run for minutes. Then `MCPClient(streamablehttp_client(GATEWAY_URL, Bearer))` →
   `list_tools_sync()` → filter → one `orchestrator_agent(analysis_prompt)` call.
4. **Summary** — *not* an inline stage. `SummaryGenerationHook` fires on `AfterInvocationEvent`
   inside step 3.
5. **Write outputs** — `timings.json` to the canonical prefix only (no sidecar, not KB-ingested).
6. **Metrics** — `emit_job_metrics(...)`.

`MaxTokensReachedException` is caught and swallowed (`main.py:604`) because specialist outputs are
already in S3 by then.

#### Gateway tool filtering — the naming trap

Gateway tool names are `"target-name___schema-name"`. Targets are created with
`specialist_name.replace("_","-")`, so a tool looks like
`talent-guild-compliance___talent-guild-compliance`. The UI sends bare underscore ids
(`talent_guild_compliance`). `main.py` normalises **both sides to hyphens** before comparing, then
drops any tool whose name starts with `x_amz_` (the Gateway's built-in search tool). Real tool names
are injected into the system prompt by literal string replace of `{tools_list}`.

#### Ordering is prompt-only

Both prompt variants say "always run risk-strategist last". There is **no code-level enforcement**;
parallelism is whatever the model emits as concurrent `toolUse` blocks in one turn. `risk_strategist`
is not a distinct pipeline stage — it is just another Gateway tool on the same shared Lambda.

### 4. Specialist Lambda (`agentcore/specialist_lambda/handler.py`)

One handler, six deployments. `SPECIALIST_NAME = os.environ["SPECIALIST_NAME"]` (required, no
default) selects the S3 prompt at cold start.

MCP input — all four required: `job_id`, `extraction_s3_prefix`, `s3_prefix`, `results_bucket`.

`_read_extraction_from_s3` (`handler.py:310`) lists the prefix, sorts `.xml` keys, gets each, joins
with `"\n\n"`.

Three sequential Bedrock calls, each in an optional OTel span:

| Step | Call | Notes |
| --- | --- | --- |
| `identify_lookup_terms` | `bedrock-runtime.converse`, `maxTokens: 512` | Asks for newline-separated glossary search queries. |
| `retrieve_glossary` | `bedrock-agent-runtime.retrieve`, `numberOfResults: 10` | Against `GLOSSARY_KB_ID`. Returns `""` and logs a warning on failure or unset id — **non-fatal**. |
| `analyze` | `bedrock-runtime.converse`, `maxTokens: MAX_TOKENS` | Grounded analysis; prompt asks it to cite matching glossary entries. |

Output passes through `_strip_fences` (removes ```` ``` ```` fences and the `<?xml ?>` declaration)
then `_normalize_typography` (`_TYPO_MAP` folds en/em dashes, curly quotes, ellipsis, NBSP, ZWSP,
thin/narrow spaces to ASCII). Written via `kb_writer.write_pair(relative_key=f"specialists/{SPECIALIST_NAME}.xml", kind="xml")`.

The return value is a **thin status envelope**, not the XML:
`{status, specialist, output: "Analysis complete. Written to s3://...", s3_key, elapsed}`. It matches
`outputSchema` in `schemas/specialists/*.json`.

Note: this handler has **local copies** of the DynamoDB helpers (`_mark_running`, `_mark_complete`,
`_mark_failed`, `handler.py:157-207`) and of `_resolve_model_id`, duplicating
`agentcore/shared/job_state.py` and `agentcore/shared/bedrock_client.py`. Its `update_item` calls
upsert, so rows created this way have no `retry_count` or `ttl`. Change both copies together.

### 5. Summary (`agentcore/shared/summary_hook.py`)

`SummaryGenerationHook` registers only `AfterInvocationEvent`.

- `_read_specialist_outputs()` lists `jobs-canonical-versions/{s3_prefix}/specialists/`, skips
  `.metadata.json`, labels each blob `[{specialist_name}]:`, and also *tries*
  `.../risk_synthesis.xml` (tolerating `NoSuchKey`).
- `_generate_summary()` builds a fresh `Agent` with `make_model(model_id, 64000)`, `tools=[]`, and a
  hardcoded inline prompt: "senior media business affairs advisor" producing (1) Contract Overview,
  (2) Key Findings, (3) Top Risks, (4) Recommended Actions.
- `_write_summary()` → `write_pair(relative_key="final-executive-summary.md", kind="md")`.
- Side effects: mutates the caller's `timings["summary"]` and appends `"summary"` to `agents_used`.
- Returns early if there are no specialist outputs; **re-raises** other exceptions.

## Storage layout

### Source bucket

```
testing/{cognito_sub}/{uuid}-{filename}.pdf    # UI uploads
pipeline/*.pdf                                 # auto-trigger watch prefix
```

### Results bucket — dual prefix, from `agentcore/shared/kb_writer.py`

```
jobs-canonical-versions/{s3_prefix}/extraction/page_001.xml … page_NNN.xml
jobs-canonical-versions/{s3_prefix}/extraction.xml
jobs-canonical-versions/{s3_prefix}/specialists/{specialist}.xml        (+ .metadata.json)
jobs-canonical-versions/{s3_prefix}/final-executive-summary.md          (+ .metadata.json)
jobs-canonical-versions/{s3_prefix}/timings.json
jobs-kb-versions/{s3_prefix}/specialists/{specialist}.txt               (+ .metadata.json)
jobs-kb-versions/{s3_prefix}/final-executive-summary.md                 (+ .metadata.json)
```

`write_pair(...)` writes **four** objects and returns
`{canonical_key, canonical_metadata_key, kb_key, kb_metadata_key}`. `kind` must be `"xml"` or `"md"`
(else `ValueError`). For `"xml"` the KB copy has its declaration stripped and `.xml` → `.txt`, because
Bedrock KB will not index a file starting with `<?xml ?>`.

`kb_metadata_sidecar` converts the internal attribute dict to Bedrock's
`{"metadataAttributes": {name: {"value": {...}, "includeForEmbedding": bool}}}`. `STRING` gets
`includeForEmbedding: True`; `NUMBER`/`BOOLEAN` get `False`. **`STRING_LIST` is flattened to a
`"; "`-joined `STRING`** — sidecars do not support lists.

Extraction pages and `extraction.xml` use the plain `_upload` helper, so they exist **only** under the
canonical prefix, have no sidecar, and are never KB-ingested.

### Config bucket

```
prompts/foundation/*.xml          prompts/agents/{agent}/*.xml
prompts/main-agent.xml            prompts/terms-kb.xml
schemas/**                        {CONFIG_BUCKET_PREFIX}*.json   # default prefix: ui-config/
```

## Job state and SSE progress

DynamoDB table `contract_review_jobs`. Contract documented at `agentcore/shared/job_state.py:1-19`.

- PK `job_id`, SK `specialist`. The orchestrator's own row uses the literal sentinel
  `specialist = "orchestrator"`.
- `status` ∈ `PENDING | RUNNING | COMPLETE | FAILED`.
- `result_s3_key`, `started_at`, `completed_at`, `error`, `retry_count`, `ttl`
  (`now + 30*86400`), and `session_id` when non-empty.
- On the orchestrator row, `result_s3_key` holds the **`s3_prefix`**, not a real object key.
- GSI `status-index`, queried by `GET /api/jobs`.
- `status` is a DynamoDB reserved word — every update uses `ExpressionAttributeNames={"#s": "status"}`.

Progress is **polling, not push** (`routes.js:296-378`): `POLL_INTERVAL_MS = 2000`,
`MAX_POLLS = 450` (15 min, matching the AgentCore Runtime timeout),
`TERMINAL_STATUSES = {'COMPLETE','FAILED'}`. A separate 15 s `setInterval` writes the SSE comment
`': keepalive\n\n'` to stop ALBs closing the connection. Transitions are deduped on
`` `${specialist}:${status}` `` so each is emitted once. The stream ends when the `orchestrator` row
reaches a terminal status.

Client-side cancel uses `AbortController`, which stops the polling. Because the runtime was invoked
fire-and-forget, **the backend job keeps running** — the UI warning "Navigating away will cancel the
pipeline" (`Chat.jsx:298`) is inaccurate.

## Environment variables

**Orchestrator runtime** — `AWS_DEFAULT_REGION` (default `us-west-2`), `MODEL_ID` (default
`us.anthropic.claude-sonnet-4-6`), `RESULTS_BUCKET`, `CONFIG_BUCKET`, `SOURCE_BUCKET`,
`JOBS_TABLE_NAME`, `GATEWAY_URL`, `COGNITO_SECRET_ARN`, `COGNITO_GATEWAY_CLIENT_ID`,
`COGNITO_TOKEN_ENDPOINT`, `MAX_TOKENS`, `LOG_LEVEL`, and the four
`{SONNET_46,OPUS_46,SONNET_45,HAIKU_45}_PROFILE_ARN`.

**Specialist Lambdas** — required `SPECIALIST_NAME`; plus `AWS_DEFAULT_REGION`, `MODEL_ID`,
`MAX_TOKENS` (default `16000`), `RESULTS_BUCKET`, `JOBS_TABLE_NAME`, `GLOSSARY_KB_ID`,
`CONFIG_BUCKET`, `LOG_LEVEL`, the four profile ARNs, `POWERTOOLS_SERVICE_NAME`,
`POWERTOOLS_LOG_LEVEL`.

**Auto-trigger Lambda** — `AWS_DEFAULT_REGION`, `JOBS_TABLE_NAME`, `LOG_LEVEL`. The runtime ARN comes
from a hardcoded SSM path, not an env var (see the bug note below).

**KB sync Lambda** — required `KB_ID`, `DATA_SOURCE_ID`; optional `LOG_LEVEL`.

**Express UI server** — `AWS_REGION`, `AWS_PROFILE`, `PORT` (default `7870`), `NODE_ENV`,
`ALLOWED_ORIGIN`, `COGNITO_USER_POOL_ID`, `COGNITO_UI_CLIENT_ID`, `COGNITO_DOMAIN`,
`ORCHESTRATOR_RUNTIME_ARN`, `JOBS_TABLE_NAME`, `CONFIG_BUCKET`, `CONFIG_BUCKET_PREFIX` (default
`ui-config/`), `RESULTS_BUCKET`, `SOURCE_BUCKET`, `SOURCE_PREFIX`, `CHAT_MODEL`, `AGENT_MODE`,
`CONTRACT_KB_ID`, `TERMS_KB_ID`. In ECS these arrive as SSM `valueFrom` references, so no plaintext
secrets sit in the task definition.

## `agentcore/shared/` reference

| Module | Contents |
| --- | --- |
| `bedrock_client.py` | `make_model(model_id=None, max_tokens=None) -> BedrockModel`. `_resolve_model_id` maps a substring to a profile env var via `_PROFILE_ENV_MAP`, falling back to the raw id. Always sets `CacheConfig(strategy="auto")` and `Config(read_timeout=600, connect_timeout=10, retries={"max_attempts":3,"mode":"adaptive"})`. |
| `job_state.py` | `mark_running`, `mark_complete`, `mark_failed`, `create_pending` (conditional put, swallows only `ConditionalCheckFailedException`), `get_record`, `get_retry_count`, `increment_retry` (atomic `ADD`), `get_all_specialist_records`, `all_complete`. `_TTL_DAYS = 30`. |
| `kb_writer.py` | `CANONICAL_PREFIX`, `KB_PREFIX`, `strip_xml_declaration`, `kb_metadata_sidecar`, `canonical_key`, `kb_key`, `write_pair`. |
| `logging_config.py` | `JsonFormatter` emits one-line JSON and **scrapes `key=value` tokens out of the message text**, promoting ~25 allowlisted keys (`job_id`, `specialist`, `elapsed`, `step`, `event`, `tool`, …) to top-level JSON fields for Logs Insights. This is why orchestrator log calls are written as `"step=… elapsed=…"` strings — keep that style. `configure_logging(runtime_name, level="INFO")` also pins boto/urllib3 to WARNING. |
| `logging_hooks.py` | `AgentLoggingHooks(HookProvider)` subscribing the six Before/After Invocation, ModelCall, ToolCall events. Counts model and tool calls; classifies tool results as success / error / cancelled, truncating error text to 500 chars. |
| `metrics.py` | `NAMESPACE = "MediaContracts/Pipeline"`, single dimension `Mode ∈ {agent, user}`. Always emits `JobDuration`, `SpecialistsInvoked`, and `JobCompleted`/`JobFailed`. Wrapped in try/except so metrics never break a job. |
| `summary_hook.py` | See *Summary* above. |
| `tracing.py` | `annotate_job(...)`, `record_error(...)`. Imports X-Ray inside try/except; both become no-ops when unavailable. Indexed annotations: `job_id`, `specialist`, `status`, `contract`. |

## `utils/` reference

| Module | Contents |
| --- | --- |
| `prompt_loader.py` | `PromptLoader`. S3 when `CONFIG_BUCKET` is set, else local filesystem. See `media-contracts-prompts-and-schema`. |
| `pdf_to_images.py` | `PageImage` dataclass and `pdf_to_page_images(pdf_path, dpi=128, max_size_mb=3.5, ...)`. Needs poppler. Sets `Image.MAX_IMAGE_PIXELS = None`, caps any side at 8000 px (Bedrock Converse limit), then walks quality 85→15 and downscales 25 % per outer attempt (max 10) to fit the 3.5 MB budget. |
| `orchestrator.py` | **Legacy** in-process pipeline (`ContractReviewOrchestrator`, `ReviewResult`, `_SPECIALIST_MAP`). Only `_download_s3` is used in production. |
| `agent_factory.py` | `AgentFactory`. Constructs `BedrockModel` directly, so it gets **no** inference-profile resolution and **no** prompt caching. Not on the deployed path. |
| `glossary_lookup.py`, `glossary_search_idf.py` | Stdlib-only exact/fuzzy lookup and IDF search over glossary JSON. **Not imported** by the orchestrator or the specialist handler — deployed glossary grounding is Bedrock KB retrieval. Still bundled into the Lambda package. |

## Known code-vs-doc discrepancies

Trust the code. These are documented inaccuracies, not things to "fix" in passing.

1. **SSM path mismatch — a real bug.** Every stack writes `/mc-{stack_suffix}/…`
   (15 `ssm.StringParameter` calls across `deployment/stacks/`). But
   `agentcore/auto_trigger/handler.py:30` hardcodes `/media-contracts/orchestrator-runtime-arn`, and
   `ui/server/index.js:22-33` maps 12 `/media-contracts/…` paths. The ECS container is unaffected
   because `ecs_stack.py` injects env vars by `valueFrom` on `/mc-{suffix}/…`, so the Express SSM
   backfill is a local-dev-only fallback. The auto-trigger Lambda's lookup, however, will not resolve
   — and `specialist_lambdas_stack.py:270` grants read on `/mc-{sfx}/*` anyway.
2. `/media-contracts/…` in `ecs_stack.py:8-19` and `cognito_stack.py:15,22-26` are **stale comments**.
3. **`risk_synthesis.xml` is effectively unreachable.** `summary_hook` tries to read it, but the
   specialist Lambda always writes `specialists/{name}.xml`. The only writer is legacy
   `utils/orchestrator.py`. `.github/documentation/AGENTS.md` still lists it as a KB data source.
4. `.github/documentation/AGENTS.md` describes the summary as step 10, "a summary `Converse` call".
   It is actually produced by `SummaryGenerationHook` on `AfterInvocationEvent`.
5. `.github/documentation/AGENTS.md` names `foundation_context.xml`. The real foundation files are
   `foundation_contract_knowledge.xml`, `foundation_dictionary.xml`, `foundation_gestalt.xml`,
   `foundation_rules.xml`.
6. `EstimatedCostUSD` is never emitted. `metrics.py` computes it only when tokens are non-zero, and
   `main.py:654` never passes `input_tokens`/`output_tokens`.
7. `elapsed` in the SSE progress payload is dead code — `routes.js:339-341` resolves to `undefined`
   on both branches.
8. The client handles an SSE `stdout` event with a `RESULT:` prefix, but the server never emits
   `stdout`. The final chat message is always the generic "Analysis complete."
9. `SOURCE_PREFIX` (default `'xml-versions/'`, `routes.js:581`) is read and never used.
10. `GET /api/s3-browse` honours `?prefix=` unconditionally (`routes.js:610`), so any authenticated
    user can list any prefix in the source bucket, not just their own `testing/{sub}/`.
11. `requireAuth` (`ui/server/index.js:102`) **skips auth entirely** when `COGNITO_USER_POOL_ID` is
    unset. That is the local-dev escape hatch; never ship a deployment without it set.
12. `handwriting_analyzer` is deployed and has a Gateway schema and a `ui/config/specialists.json`
    entry under category `Experimental`. `risk_strategist` is deliberately absent from that file
    because it always runs.
