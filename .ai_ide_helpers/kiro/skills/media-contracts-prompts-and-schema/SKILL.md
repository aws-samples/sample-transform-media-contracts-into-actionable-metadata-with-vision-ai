---
name: media-contracts-prompts-and-schema
description: How the Media Contract Analyzer composes its XML system prompts from media_contracts_agents/ via utils/prompt_loader.py, the Media Contracts Schema (MCS) v1.0 output contract in schemas/base/, the validate_mcs.py validator, the MCP tool schemas in schemas/specialists/, and the exact end-to-end steps to add or change a specialist analyzer. Use when editing prompt XML, changing analyzer output format, adding a specialist, syncing prompts to S3, or when MCS validation fails.
license: MIT-0
metadata:
  project: media-contracts-analyzer
  verified-against: repository state, September 2026
---

# Prompt System and MCS v1.0

Two separate contracts govern analyzer behaviour: the **prompt system** (what goes into the model)
and the **Media Contracts Schema** (what must come out). Both are file-convention driven, so a
misnamed file fails silently or fails validation rather than raising at import time.

## Prompt directory convention

One directory per analyzer under `media_contracts_agents/`, named with the snake_case analyzer id.
Every XML file inside is prefixed with a **short name** plus a functional suffix:
`{short_name}_{aspect}.xml`.

**The prefix is not always the directory name.** This is the most common source of mistakes:

| Directory | File prefix |
| --- | --- |
| `extractor/` | `extractor_` |
| `financial/` | `financial_` |
| `handwriting_analyzer/` | `handwriting_` |
| `regulatory_compliance/` | `regulatory_` |
| `rights_clearance/` | `rights_` |
| `risk_strategist/` | `risk_` |
| `talent_guild_compliance/` | `talent_` |
| `foundation/` | `foundation_` |
| `orchestrator/` | none — a single `system.xml` |

### Suffix roles

| Suffix | Root element | Purpose |
| --- | --- | --- |
| `_job_role.xml` | `<{prefix}_job_role>` | Agent identity: `<agent_id>`, `<agent_name>`, `<role>`, `<job_description>` with `<summary>`, `<core_mandate>`, `<responsibilities>`. |
| `_rules.xml` | `<{prefix}_rules>` | Flat `<rule>` children. Hard constraints layered on `foundation_rules.xml`; on conflict the agent-specific file wins. |
| `_tasks.xml` | `<{prefix}_tasks>` | Ordered `<task>` (with optional `<sub_task>`) analysis procedure. |
| `_format.xml` | `<response_format>` | **The MCS output template.** The only files `validate_mcs.py` inspects. |
| `_stakeholders.xml` | `<{prefix}_stakeholders>` | `<role id="...">` entries with `<title>`, `<seniority>`, `<organization>`, `<relevance_to_agent>`, `<analysis_lens>`. |
| `_verification.xml` | `<{prefix}_verification…>` | Self-check pass the agent runs before emitting output. |

Every analyzer has all six except `handwriting_analyzer`, which has **no `_stakeholders.xml`** and
four extra files:

- `handwriting_context.xml` — `<context>/<item>`. Frames the vision task: the leading images are
  few-shot examples that "should NEVER be analyzed under any circumstances"; only the final image is
  the target.
- `handwriting_gestalt.xml` — `<gestalt_perception analyzer="handwriting">` with `<prescan>/<step>`
  and `<principles_emphasis>`. Overrides `foundation_gestalt.xml`.
- `handwriting_help.xml` — transcription technique manual: `<critical_instructions>`,
  `<handwriting_definition>`, `<analysis_methodology>`.
- `handwriting_conversation_example.xml` — scripted `<user>`/`<assistant>` few-shot dialogue.
- `few-shot-examples/` — the images themselves. **Excluded** from `sync_prompts.py` via `SKIP_DIRS`.

### Foundation files

| File | Root | Contents |
| --- | --- | --- |
| `foundation_contract_knowledge.xml` | `<foundation_contract_knowledge>` | Shared domain knowledge. `<contract_elements_to_identify>` → `<category name="…">` → `<element>`. Explicitly defines no tasks, formats, or agent behaviour. |
| `foundation_dictionary.xml` | `<foundation_dictionary>` | `<contract_types>` (`content_licensing_agreement`, `talent_performance_agreement`, `music_synchronization_license`, `distribution_agreement`, `digital_rights_ugc_license`) and `<provision_categories>`. Note: this file has **no XML declaration**. |
| `foundation_gestalt.xml` | `<foundation_gestalt>` | Visual pre-scan instructions and gestalt `<principle>` guidance. |
| `foundation_rules.xml` | `<foundation_rules>` | `<section name="integrity">`, `<section name="extraction_fidelity">`, etc. Header states it must load **before** any agent-specific rules. |

## Composition (`utils/prompt_loader.py`)

```python
loader = PromptLoader()                      # auto-detects mode
prompt = loader.load_agent_prompt("financial")
```

- **Mode**: S3 when `CONFIG_BUCKET` is set, else local filesystem rooted at `agents_dir`
  (default `"media_contracts_agents"`).
- `load_agent_prompt(name)` returns `f"{foundation}\n\n{agent_specific}"` — foundation always first.
- Within each group, files are concatenated **sorted lexicographically by filename / S3 key** and
  joined with `"\n\n"`. No manifest, no ordering metadata. If order matters, encode it in the filename.
- Content is cached per key in `self._cache`. `warm_up(name)` pre-fetches at container start so a bad
  bucket or key fails on deploy rather than on the first request.
- `_SKIP_DIRS = {"foundation", "version_1", "__pycache__", ".DS_Store"}` are excluded from
  `list_agents()`.
- Raises `FileNotFoundError` if a prefix yields no `.xml`.

Concrete order for `financial`:

```
foundation_contract_knowledge.xml
foundation_dictionary.xml
foundation_gestalt.xml
foundation_rules.xml
financial_format.xml       ← note: _format sorts before _job_role
financial_job_role.xml
financial_rules.xml
financial_stakeholders.xml
financial_tasks.xml
financial_verification.xml
```

The concatenation is **not valid single-document XML** — multiple roots, multiple declarations. It is
prompt text, never parsed. Do not "fix" it by adding a wrapper root.

S3 prefixes: `_FOUNDATION_PREFIX = "prompts/foundation"`, `_AGENTS_PREFIX = "prompts/agents"`.

## Orchestrator prompt

`media_contracts_agents/orchestrator/system.xml`, root `<system_prompt>`. Sections, in order:
`<role>`, `<execution_rules>` (`<rule priority="critical|high|medium">`), `<workflow>`
(`<step number="1">`…`6`), `<tool_selection_guidance>`, `<available_tools>{tools_list}</available_tools>`,
`<error_handling>`.

`{tools_list}` is filled by a literal `str.replace` in `agentcore/orchestrator/main.py` — not an
f-string or `.format()`, so other braces in the prompt are safe.

`<tool_selection_guidance>` holds the tag→tool routing table as
`<route tags="…" tool="…"/>` entries, using **hyphenated** tool names (`rights-clearance`,
`talent-guild-compliance`). `risk-strategist` is routed with `tags="ALWAYS — run last to synthesize
all findings"`.

The orchestrator also receives the full foundation block, because it goes through
`load_agent_prompt("orchestrator")` like any other agent.

## UI prompts (separate system)

`prompts/main-agent.xml` and `prompts/terms-kb.xml` are **not** touched by `PromptLoader`. They are
fetched from S3 by `ui/server/routes.js` `loadPrompt(key)` and memoised in `promptCache`.

- `prompts/main-agent.xml` — system prompt for the UI chat assistant (`POST /api/chat`).
- `prompts/terms-kb.xml` — a Bedrock KB **RAG prompt template** applied only to the Terms KB in
  `POST /api/kb-query`. Contains Bedrock substitution variables `$output_format_instructions$`,
  `$search_results$`, `$query$`, plus a `<knowledge_base_coverage>` inventory of the nine glossaries
  with term counts. Those counts are duplicated in `ui/config/glossaries.json` — keep them in sync
  by hand.

## MCS v1.0

Canonical template: `schemas/base/mcs_base_schema.xml`. Current version is **1.0**; the envelope must
carry `schema_version="1.0"`.

### The seven parts

| Part | Name | Requirement |
| --- | --- | --- |
| 1 | Envelope | Required, all analyzers |
| 2 | Core Metadata | Required, all analyzers |
| 3 | Common Spine | Optional — document analyzers |
| 4 | Topical Analysis | Optional |
| 5 | Specialized Section | Required, analyzer-specific |
| 6 | Findings | Required, specialist analyzers |
| 7 | Tags | Required |

### Envelope and metadata (verbatim)

```xml
<response analyzer="{ANALYZER_ID}"
         schema_version="1.0"
         job_id="{JOB_ID}"
         timestamp="{ISO_8601_TIMESTAMP}">
    <metadata>
        <analyzer_name>{ANALYZER_ID}</analyzer_name>
        <schema_version>1.0</schema_version>
        <timestamp>{ISO_8601_TIMESTAMP}</timestamp>
        <source_document>{DOCUMENT_TITLE_OR_REFERENCE}</source_document>
        <!-- Optional fields commonly used -->
        <page_reference>{PAGE_NUMBER_IF_APPLICABLE}</page_reference>
        <element_count>{COUNT_OF_PRIMARY_ELEMENTS_OR_FINDINGS}</element_count>
        <confidence>{high|medium|low}</confidence>
    </metadata>
```

Other part shapes:

- `<common_spine element_count="…">` → `<element id="elem_001" tag="{STRUCTURAL_TAG}" order="1" page="…"><text>…</text></element>`.
  Documented tags: `P`, `H1`/`H2`/`H3`, `Note`, `Table`, `List`. Element ids are `elem_001`, `elem_002`, …
- `<topical_analysis>`
- `<specialized type="{ANALYZER_TYPE}">` — the `type` attribute is mandatory.
- `<findings>` → `<risks>/<risk>` (`<description>`, `<severity>{HIGH|MEDIUM|LOW}</severity>`,
  `<category>`, `<section_reference>`, `<rationale>`), `<gaps>/<gap>` (…`<impact>`),
  `<ambiguities>/<ambiguity>`, `<cross_references>/<cross_reference agent="…" note="…"/>`.
- `<tags>/<tag>`

Confidence values are `high`, `medium`, `low`. Timestamps are ISO 8601, e.g. `2024-03-21T14:30:00Z`.
Versioning is semver: major = breaking required-field change, minor = new optional field, patch = docs.

### Required parts per analyzer — trust the validator

The four docs in the repo disagree with each other. `schemas/base/validate_mcs.py` `REQUIRED_PARTS` is
what actually gates, and matches `schemas/base/README.md`:

```python
"extractor":               ["Part 1", "Part 2", "Part 3", "Part 7"]
"handwriting_analyzer":    ["Part 1", "Part 2", "Part 3", "Part 7"]
"financial":               ["Part 1", "Part 2", "Part 5", "Part 6", "Part 7"]
"rights_clearance":        ["Part 1", "Part 2", "Part 5", "Part 6", "Part 7"]
"regulatory_compliance":   ["Part 1", "Part 2", "Part 5", "Part 6", "Part 7"]
"talent_guild_compliance": ["Part 1", "Part 2", "Part 5", "Part 6", "Part 7"]
"risk_strategist":         ["Part 1", "Part 2", "Part 5", "Part 7"]   # Part 6 embedded in Part 5
```

`schemas/base/IMPLEMENTATION_MATRIX.md` and the table in `README.md` /
`media_contracts_agents/README.md` list Parts 4 and 5 differently for the document analyzers. That
disagreement is real and unresolved in the repo — do not "reconcile" it by editing the validator.

## Validator

```bash
python3 schemas/base/validate_mcs.py media_contracts_agents/
python3 schemas/base/validate_mcs.py media_contracts_agents/financial/financial_format.xml
```

Exactly one positional argument. Directory mode does `rglob("*_format.xml")`, so `_rules.xml`,
`_tasks.xml`, and friends are **never** checked. Parsing uses `defusedxml.ElementTree`.

Exit codes: `0` all valid; `1` for no argument (prints usage), a non-existent path, or any invalid file.
**Warnings never fail the run** — `is_valid = len(errors) == 0`.

What it checks:

- Analyzer name is inferred **from the file path** by `_detect_analyzer_name()`, a hardcoded chain
  matching the seven names against `file_path.parts`. A format file outside a correctly named
  directory errors with `Could not determine analyzer name from file path`.
- Finds the response element via `root.find(".//response")`, falling back to `root` when
  `root.tag == "response"` — which is why `_format.xml` can wrap it in `<response_format>`.
- **Part 1 errors**: missing `analyzer`, `schema_version`, `job_id`, or `timestamp`.
  **Warnings**: `analyzer` not matching the detected name; `schema_version != "1.0"`.
- **Part 2 error**: missing `<metadata>`. Missing entries from `STANDARD_METADATA_FIELDS`
  (`analyzer_name`, `schema_version`, `timestamp`, `source_document`, `element_count`, `confidence`)
  are warnings only.
- **Part 3**: `<common_spine>` is an error only for `extractor` and `handwriting_analyzer`. Empty
  spine or a missing `element_count` attribute are warnings.
- **Part 4**: presence of `<topical_analysis>` just marks it implemented. Never an error.
- **Part 5 errors**: missing `<specialized>`, or `<specialized>` without a `type` attribute.
  Empty is a warning.
- **Part 6**: skipped entirely for `extractor`, `handwriting_analyzer`, `risk_strategist`. For the
  other four it searches, in order: `findings`, `financial_findings`, `rights_findings`,
  `regulatory_findings`, `talent_findings`, `risk_findings`. None found → error.
- **Part 7 error**: missing `<tags>`. No `<tag>` children is a warning.
- The first 1000 chars must contain the literal `"Media Contracts Schema"` or `"MCS"`, else a warning.

Failure output:

```
❌ INVALID: financial_format.xml
  Parts implemented: Part 1, Part 2, Part 5, Part 7
  Errors (1):
    - Part 6: Missing findings section (specialist analyzers must have findings)
```

## MCP tool schemas (`schemas/specialists/*.json`)

Six files, one per Gateway target. Each is a **JSON array containing a single tool object** with
`name`, `description`, `inputSchema`, `outputSchema`.
`deployment/stacks/gateway_stack.py:221` binds them by `object_key=f"schemas/specialists/{specialist_name}.json"`.

The shape is uniform. Only `name` and the two `description` strings vary:

```json
[
  {
    "name": "financial",
    "description": "Analyzes deal economics, revenue share, minimum guarantees, MFN provisions, payment terms, and audit rights. Use for contracts involving money, compensation, licensing fees, or revenue splits.",
    "inputSchema": {
      "type": "object",
      "description": "Input payload for the financial specialist.",
      "properties": {
        "job_id":               { "type": "string", "description": "Unique identifier for the contract-review job." },
        "extraction_s3_prefix": { "type": "string", "description": "S3 prefix where per-page extraction XML files are stored. The specialist reads extraction pages directly from S3." },
        "s3_prefix":            { "type": "string", "description": "Per-job S3 key prefix (directory name) where specialist outputs are written." },
        "results_bucket":       { "type": "string", "description": "S3 bucket name for reading extractions and writing results." }
      },
      "required": ["job_id", "extraction_s3_prefix", "s3_prefix", "results_bucket"]
    },
    "outputSchema": {
      "type": "object",
      "description": "Result of the financial specialist analysis.",
      "properties": {
        "status":     { "type": "string", "description": "Result status: COMPLETE or FAILED." },
        "specialist": { "type": "string", "description": "Specialist identifier that produced this result." },
        "output":     { "type": "string", "description": "Status message confirming analysis completion and S3 location of the full output." },
        "s3_key":     { "type": "string", "description": "Canonical S3 key where the XML output was written." },
        "elapsed":    { "type": "number", "description": "Wall-clock time in seconds the specialist took to complete." },
        "error":      { "type": "string", "description": "Error message (populated only when status is FAILED)." }
      },
      "required": ["status", "specialist", "output"]
    }
  }
]
```

`output` is deliberately a thin status string. The analysis XML goes to S3 and never through the tool
response. Keep it that way — the orchestrator's context budget depends on it.

`gateway_stack.py` appends an MD5 fingerprint of all schema files to the target description so CDK
detects schema edits and updates the target.

## Adding a new specialist — full checklist

Miss any of these and the specialist either never runs, silently loses S3 write permission, or fails
MCS validation.

1. **Prompt directory** `media_contracts_agents/<name>/` with `<prefix>_job_role.xml`,
   `_rules.xml`, `_tasks.xml`, `_format.xml`, `_verification.xml`, `_stakeholders.xml`, and a
   `README.md`. Directory name must be the snake_case id used everywhere else. Add the
   `Media Contracts Schema` header comment to `_format.xml`.
2. **`schemas/base/validate_mcs.py`** — add the name to `REQUIRED_PARTS` **and** to the
   `_detect_analyzer_name()` chain. Neither README checklist mentions this, but validation of the new
   `_format.xml` fails without it.
3. **`schemas/specialists/<name>.json`** — array-of-one, same input/output shape as above.
4. **`deployment/stacks/gateway_stack.py`** — add a human description to the `SPECIALIST_DESCRIPTIONS`
   dict (line ~44). It falls back to `f"{specialist_name} specialist"` if absent.
5. **`deployment/stacks/specialist_lambdas_stack.py`** — append to the module-level `SPECIALISTS` list
   (line 31):

   ```python
   SPECIALISTS = [
       "financial",
       "rights_clearance",
       "talent_guild_compliance",
       "regulatory_compliance",
       "risk_strategist",
       "handwriting_analyzer",
   ]
   ```

   This list drives the Lambda functions **and** the object-level IAM grants: reading
   `schemas/specialists/{specialist}.json`, and writing
   `jobs-canonical-versions/*/specialists/{specialist}.xml` (+ `.metadata.json`) and
   `jobs-kb-versions/*/specialists/{specialist}.txt` (+ `.metadata.json`). No new handler code is
   needed — `SPECIALIST_NAME` selects the prompt.
6. **`media_contracts_agents/orchestrator/system.xml`** — add a
   `<route tags="…" tool="<name-with-hyphens>"/>` entry. Without it the tool is in `{tools_list}` but
   has no tag-based reason to be called.
7. **`ui/config/specialists.json`** — add `{id, name, emoji, description, category}`. `id` must be the
   snake_case name. Existing categories: `"Core Specialists"`, `"Experimental"`. Omit the entry if the
   specialist should always run (that is why `risk_strategist` is absent).
8. **Sync to S3, then deploy** Specialists and Gateway. See below.
9. **Validate**: `python3 schemas/base/validate_mcs.py media_contracts_agents/`.

Prompt-only IAM note: grants for `prompts/foundation/*` and `prompts/agents/*` are wildcarded, so a
new agent folder needs no IAM change. `schemas/specialists/{name}.json` grants are enumerated per
specialist, so that one does.

## Syncing prompts to S3

Two supported paths.

**`deploy.sh` option 2** (submenu `6` = all) runs five syncs:

```bash
aws s3 sync media_contracts_agents/            s3://$CONFIG/prompts/agents/
aws s3 sync media_contracts_agents/foundation/ s3://$CONFIG/prompts/foundation/
aws s3 sync prompts/                           s3://$CONFIG/prompts/
aws s3 sync schemas/                           s3://$CONFIG/schemas/
aws s3 sync deployment/glossaries/             s3://$TERMS/          # + KB ingestion kick-off
```

**`deployment/scripts/sync_prompts.py`** — boto3, `--dry-run` supported, does **not** sync `schemas/`:

```bash
python deployment/scripts/sync_prompts.py --bucket media-contracts-config-dev [--dry-run]
```

Manifest: `foundation/*.xml` → `prompts/foundation/{name}`; each non-skipped agent dir's `*.xml` →
`prompts/agents/{dir}/{name}`; `prompts/*.xml` → `prompts/{name}`. Uploads with
`ContentType="application/xml"`. `SKIP_DIRS = {"foundation", "__pycache__", ".DS_Store", "few-shot-examples"}`
plus dot-dirs. `head_bucket` preflight exits 1 on failure.

**Prompt updates need no container rebuild** — `s3 cp` plus a container restart or the next cold start.
Rollback by restoring a previous S3 object version (versioning is on for the config bucket).

## Glossary source data

`deployment/glossaries/` has nine domains: `broadcast_fcc`, `film_tv_production`, `media_rights_legal`,
`music_rights_licensing`, `odrl`, `podcast_digital_audio`, `publishing_literary_rights`, `sag_aftra`,
`vfx`. 1572 `.txt` files, each with a `.txt.metadata.json` sidecar — a strict 1:1 pairing.

`TermsKBStack` ingests with `chunking_strategy="NONE"`, so **one file = one chunk = one vector**. That
is why the `.txt` bodies are small and pre-formatted:

```
Term: Agreement Subtype
Glossary: sag_aftra
Definition: …
Usage Context: …
Source: …
```

```json
{"metadataAttributes": {
  "glossary": {"value": {"type": "STRING", "stringValue": "sag_aftra"}, "includeForEmbedding": true},
  "term":     {"value": {"type": "STRING", "stringValue": "Agreement Subtype"}, "includeForEmbedding": true}}}
```

When adding glossary entries, keep one term per file and always write the sidecar.

## `ui/config/*.json`

Served by `loadConfig(filename)` in `ui/server/routes.js` — S3 first at
`{CONFIG_BUCKET_PREFIX}{filename}` (default prefix `ui-config/`), falling back to the local
`ui/config/` file on any error, guarded by a `safeJoin` path-traversal check.

| File | Purpose |
| --- | --- |
| `branding.json` | `appName`, `appEmoji`, `appSubtitle`, `appDescription`, `appLogo`, `appLogoHeight`, `theme`. Has a `.sample`. |
| `glossaries.json` | UI glossary catalog: `id`, `name`, `termCount`, `description`, `source`. Counts mirror `prompts/terms-kb.xml`. |
| `specialists.json` | Specialist toggles. See step 7 above. |
| `pricing.json` | Cost-calculator data: `document_constants` plus a `models` array of `{family, name, input_per_1m, output_per_1m}`. |
| `knowledge_bases.json` | **No discoverable consumer.** The server reads KB ids from `TERMS_KB_ID` / `CONTRACT_KB_ID` env vars instead. Treat as possibly stale; verify before relying on it. |
