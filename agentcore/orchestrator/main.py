"""MediaContracts Orchestrator — AgentCore Runtime entrypoint.

The orchestrator is a Strands agent that:
  1. Extracts the contract (vision-based for PDF, text-based for DOCX)
  2. Connects to the AgentCore Gateway as an MCP client
  3. In agent mode: reasons freely over all available specialist tools
  4. In user mode: constrained to the user-selected specialist tools only
  5. Runs risk synthesis and summary
  6. Writes all outputs to S3 and updates DynamoDB

Environment variables (set by CDK at deploy time):
  CONFIG_BUCKET          — S3 bucket for prompt XML files
  RESULTS_BUCKET         — S3 bucket for pipeline outputs
  JOBS_TABLE_NAME        — DynamoDB table for job state
  GATEWAY_URL            — AgentCore Gateway MCP endpoint URL
  COGNITO_SECRET_ARN     — Secrets Manager ARN for Cognito client credentials
  MODEL_ID               — Bedrock model ID (default: us.anthropic.claude-sonnet-4-6)
  AWS_DEFAULT_REGION

Payload schema:
  {
    "job_id":        "uuid",
    "contract_path": "s3://bucket/key.pdf",
    "specialists":   ["financial", "rights_clearance"],  # null = agent decides
    "agent_mode":    true   # if true, agent selects from all available tools
  }
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from concurrent.futures import as_completed
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import boto3
import requests
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPClient
from strands.types.exceptions import MaxTokensReachedException

from agentcore.shared.job_state import (
    create_pending,
    mark_running,
    mark_complete,
    mark_failed,
    get_record,
)
from agentcore.shared.logging_config import configure_logging
from agentcore.shared.logging_hooks import AgentLoggingHooks
from agentcore.shared.metrics import emit_job_metrics
from agentcore.shared.bedrock_client import make_model
from agentcore.shared import kb_writer
from agentcore.shared.summary_hook import SummaryGenerationHook
from utils.orchestrator import _download_s3
from utils.pdf_to_images import pdf_to_page_images
from utils.prompt_loader import PromptLoader

configure_logging("orchestrator")
logger = logging.getLogger("orchestrator")

# ── OTEL telemetry (Strands-native, no ADOT botocore patching) ──────
try:
    from strands.telemetry import StrandsTelemetry

    _telemetry = StrandsTelemetry()
    _telemetry.setup_otlp_exporter()
    logger.info("StrandsTelemetry OTLP exporter enabled")
except Exception as e:
    logger.warning("StrandsTelemetry setup failed (tracing disabled): %s", e)

# ── Config ──────────────────────────────────────────────────────────
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET", "")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "")
COGNITO_SECRET_ARN = os.environ.get("COGNITO_SECRET_ARN", "")
COGNITO_GATEWAY_CLIENT_ID = os.environ.get("COGNITO_GATEWAY_CLIENT_ID", "")
COGNITO_TOKEN_ENDPOINT = os.environ.get("COGNITO_TOKEN_ENDPOINT", "")

app = BedrockAgentCoreApp()

# ── Prompt loader (cold-start warm-up) ──────────────────────────────
_loader = PromptLoader()
_loader.warm_up("extractor")
_loader.warm_up("orchestrator")
_extractor_prompt = _loader.load_agent_prompt("extractor")
_orchestrator_prompt = _loader.load_agent_prompt("orchestrator")


# ── Cognito token helper ─────────────────────────────────────────────
def _get_gateway_token() -> str:
    """Fetch a fresh Cognito client credentials token for each Gateway call.

    No caching — tokens are short-lived (1 hour) and the orchestrator runs
    multi-minute jobs, so the extra round-trip is negligible compared to
    keeping a plaintext token in process memory.
    """
    t0 = time.perf_counter()
    logger.info("step=cognito_token status=fetching")

    sm = boto3.client("secretsmanager", region_name=REGION)
    client_secret = sm.get_secret_value(SecretId=COGNITO_SECRET_ARN)["SecretString"]

    data = {
        "grant_type": "client_credentials",
        "client_id": COGNITO_GATEWAY_CLIENT_ID,
        "client_secret": client_secret,
        "scope": "agentcore-gateway/invoke",
    }

    resp = requests.post(
        COGNITO_TOKEN_ENDPOINT,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    token_data = resp.json()

    if "access_token" not in token_data:
        raise RuntimeError("Token response missing access_token")

    elapsed = time.perf_counter() - t0
    logger.info("step=cognito_token status=ok elapsed=%.2fs", elapsed)
    return str(token_data["access_token"])


# ── S3 helpers ───────────────────────────────────────────────────────
_s3 = None


def _get_s3():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3", region_name=REGION)
    return _s3


def _upload(bucket: str, key: str, body: str) -> None:
    logger.info("step=s3_upload key=%s size=%d", key, len(body))
    _get_s3().put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))


# ── Extraction ───────────────────────────────────────────────────────


_FENCE_RE = re.compile(r"^```\w*\n?", re.MULTILINE)
_XML_DECL_RE = re.compile(r"<\?xml[^?]*\?>\s*", re.IGNORECASE)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences and XML declarations from model output."""
    text = _FENCE_RE.sub("", text).strip()
    text = _XML_DECL_RE.sub("", text).strip()
    return _normalize_typography(text)


_TYPO_MAP = str.maketrans(
    {
        "\u2013": "-",  # en dash  → hyphen
        "\u2014": "-",  # em dash  → hyphen
        "\u2018": "'",  # left single curly quote
        "\u2019": "'",  # right single curly quote / apostrophe
        "\u201c": '"',  # left double curly quote
        "\u201d": '"',  # right double curly quote
        "\u2026": "...",  # ellipsis
        "\u00a0": " ",  # non-breaking space
        "\u200b": "",  # zero-width space
        "\u2009": " ",  # thin space
        "\u202f": " ",  # narrow no-break space
    }
)


def _normalize_typography(text: str) -> str:
    """Replace typographic Unicode characters with ASCII equivalents."""
    return text.translate(_TYPO_MAP)


_TAG_RE = re.compile(r"<tag>(.*?)</tag>", re.DOTALL)
_CONTRACT_TYPE_RE = re.compile(r"<contract_type>(.*?)</contract_type>", re.DOTALL)
_TOPICAL_RE = re.compile(r"<topical_analysis>(.*?)</topical_analysis>", re.DOTALL)


def _parse_extraction_tags(page_extractions: dict[int, str]) -> dict:
    """Parse tags, contract_type, and topical_analysis from page extraction XMLs.

    Returns a dict with:
        tags: deduplicated sorted list of all tags across pages
        contract_type: first non-empty contract_type found
        topical_summary: first non-empty topical_analysis found
    """
    all_tags: set[str] = set()
    contract_type = ""
    topical_summary = ""

    for _page_num, xml_text in sorted(page_extractions.items()):
        for m in _TAG_RE.finditer(xml_text):
            tag = m.group(1).strip()
            if tag:
                all_tags.add(tag)

        if not contract_type:
            m = _CONTRACT_TYPE_RE.search(xml_text)
            if m and m.group(1).strip():
                contract_type = m.group(1).strip()

        if not topical_summary:
            m = _TOPICAL_RE.search(xml_text)
            if m and m.group(1).strip():
                topical_summary = m.group(1).strip()

    return {
        "tags": sorted(all_tags),
        "contract_type": contract_type,
        "topical_summary": topical_summary,
    }


def _extract_contract(
    local_path: str, results_bucket: str, s3_prefix: str
) -> tuple[str, dict]:
    """Run vision-based extraction for PDF, text-based for DOCX/TXT.

    Writes per-page extraction files to S3 so downstream specialists can
    read them directly without the orchestrator passing the full text
    through its context window.

    Returns the S3 prefix where extraction pages were written:
        jobs-canonical-versions/{s3_prefix}/extraction/

    Also writes a combined extraction.xml for backward compatibility.
    """
    extraction_prefix = f"{kb_writer.CANONICAL_PREFIX}/{s3_prefix}/extraction"

    if local_path.lower().endswith(".pdf"):
        pages = pdf_to_page_images(local_path, dpi=128)
        total_pages = len(pages)
        logger.info("step=extraction type=pdf pages=%d", total_pages)
        page_extractions: dict[int, str] = {}

        def _extract_page(page):
            t0 = time.perf_counter()
            model = make_model(MODEL_ID, 16000)
            agent = Agent(model=model, system_prompt=_extractor_prompt, tools=[])
            content_blocks = [
                {
                    "text": (
                        f"Extract all provisions from page {page.page_number} of "
                        f"{total_pages} of this contract. "
                        "Analyze the page image visually — read all text, tables, "
                        "signatures, annotations, and formatting directly from the image. "
                        "Output only the extraction for this single page.\n\n"
                        "CRITICAL: You MUST respond using ONLY the XML format defined in "
                        "your <response_format /> tags. Do NOT use markdown, code blocks, "
                        "headers, or any other format. Output raw XML only.\n\n"
                        f'Set page="{page.page_number}" on all elements. '
                        f"Set <contract_completeness>PARTIAL_MULTI_PAGE</contract_completeness> "
                        f"and <page_count>1</page_count> in metadata."
                    )
                },
                {
                    "image": {
                        "format": page.format,
                        "source": {"bytes": page.image_bytes},
                    }
                },
            ]
            result = _strip_fences(str(agent(content_blocks)))
            elapsed = time.perf_counter() - t0
            logger.info(
                "step=extraction page=%d elapsed=%.1fs output_len=%d",
                page.page_number,
                elapsed,
                len(result),
            )
            return page.page_number, result

        with ThreadPoolExecutor(max_workers=min(total_pages, 8)) as pool:
            futures = {pool.submit(_extract_page, p): p for p in pages}
            for future in as_completed(futures):
                page_num, output = future.result()
                page_extractions[page_num] = output

        # Write individual page extractions to S3
        for page_num in sorted(page_extractions):
            page_key = f"{extraction_prefix}/page_{page_num:03d}.xml"
            _upload(results_bucket, page_key, page_extractions[page_num])
        logger.info(
            "step=extraction status=pages_written pages=%d prefix=%s",
            total_pages,
            extraction_prefix,
        )

        # Also write combined envelope for backward compatibility
        full_extraction = _build_assessment_envelope(page_extractions, total_pages)
        _upload(
            results_bucket,
            f"{kb_writer.CANONICAL_PREFIX}/{s3_prefix}/extraction.xml",
            full_extraction,
        )
        logger.info(
            "step=extraction status=complete pages=%d total_chars=%d",
            total_pages,
            len(full_extraction),
        )
        extraction_meta = _parse_extraction_tags(page_extractions)
        logger.info(
            "step=extraction tags=%s contract_type=%s",
            extraction_meta["tags"],
            extraction_meta["contract_type"],
        )
        return extraction_prefix, extraction_meta
    else:
        logger.info("step=extraction type=text path=%s", local_path)
        model = make_model(MODEL_ID, 64000)
        agent = Agent(model=model, system_prompt=_extractor_prompt, tools=[])
        result = _strip_fences(
            str(
                agent(
                    "Extract all provisions from the contract document. "
                    "CRITICAL: You MUST respond using ONLY the XML format defined in "
                    "your <response_format /> tags. Do NOT use markdown, code blocks, "
                    "headers, or any other format. Output raw XML only."
                )
            )
        )
        # Write as a single page extraction
        _upload(results_bucket, f"{extraction_prefix}/page_001.xml", result)
        # Also write combined for backward compatibility
        _upload(
            results_bucket,
            f"{kb_writer.CANONICAL_PREFIX}/{s3_prefix}/extraction.xml",
            result,
        )
        logger.info("step=extraction status=complete output_len=%d", len(result))
        extraction_meta = _parse_extraction_tags({1: result})
        return extraction_prefix, extraction_meta


def _build_assessment_envelope(
    page_extractions: dict[int, str], total_pages: int
) -> str:
    """Wrap per-page extractor XML outputs in a full_contract_assessment envelope."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    page_blocks = []
    for page_num in sorted(page_extractions):
        page_xml = page_extractions[page_num]
        page_blocks.append(
            f'    <page number="{page_num}" total_pages="{total_pages}">\n'
            f"      <specialist_outputs>\n"
            f'        <specialist_output specialist="extractor">\n'
            f"          {page_xml}\n"
            f"        </specialist_output>\n"
            f"      </specialist_outputs>\n"
            f"    </page>"
        )

    pages_xml = "\n".join(page_blocks)

    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<response type="full_contract_assessment"\n'
        f'          schema_version="1.0"\n'
        f'          timestamp="{ts}">\n'
        f"  <metadata>\n"
        f"    <specialists>\n"
        f"      <specialist>extractor</specialist>\n"
        f"    </specialists>\n"
        f"    <document_rollups>\n"
        f"      <page_count>{total_pages}</page_count>\n"
        f"    </document_rollups>\n"
        f"  </metadata>\n"
        f"  <pages>\n"
        f"{pages_xml}\n"
        f"  </pages>\n"
        f"</response>"
    )


# ── Orchestrator entrypoint ──────────────────────────────────────────


@app.entrypoint
def handler(payload: dict, _context: dict | None = None) -> dict:
    """AgentCore Runtime entrypoint — validates payload and runs the pipeline."""
    job_id: str = payload.get("job_id", "")
    contract_path: str = payload.get("contract_path", "")
    specialists_override: list[str] | None = payload.get("specialists")
    agent_mode: bool = payload.get("agent_mode", True)

    # Extract runtime session ID from AgentCore context for log correlation
    session_id = ""
    if _context and hasattr(_context, "session_id"):
        session_id = _context.session_id or ""
    elif isinstance(_context, dict):
        session_id = _context.get("session_id", "")

    if not job_id or not contract_path:
        return {"status": "FAILED", "error": "Missing job_id or contract_path"}

    logger.info(
        "job=%s session=%s contract=%s agent_mode=%s specialists=%s",
        job_id,
        session_id,
        contract_path,
        agent_mode,
        specialists_override,
    )

    # ── Idempotency ─────────────────────────────────────────────────
    record = get_record(job_id, "orchestrator")
    if record.get("status") == "COMPLETE":
        logger.info("job=%s already COMPLETE", job_id)
        return {
            "job_id": job_id,
            "status": "COMPLETE",
            "s3_prefix": record.get("result_s3_key", ""),
            "cached": True,
        }

    create_pending(job_id, "orchestrator", session_id=session_id)
    mark_running(job_id, "orchestrator")
    task_id = app.add_async_task("contract_review", {"job_id": job_id})

    try:
        result = _run_pipeline(
            job_id, contract_path, specialists_override, agent_mode, session_id
        )
        mark_complete(job_id, "orchestrator", result.get("s3_prefix", ""))
        app.complete_async_task(task_id)
        return result
    except Exception as e:
        logger.exception("job=%s FAILED: %s", job_id, e)
        mark_failed(job_id, "orchestrator", str(e))
        app.complete_async_task(task_id)
        return {"job_id": job_id, "status": "FAILED", "error": str(e)}


def _run_pipeline(
    job_id: str,
    contract_path: str,
    specialists_override: list[str] | None,
    agent_mode: bool,
    session_id: str = "",
) -> dict:
    timings: dict[str, float] = {}
    agents_used: list[str] = []

    contract_name = Path(contract_path).stem
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if session_id:
        s3_prefix = f"{session_id}-{contract_name}_{ts}"
    else:
        s3_prefix = f"{contract_name}_{ts}"

    # ── Step 1: Download if S3 URI ───────────────────────────────────
    local_path = contract_path
    tmp_file = None
    if contract_path.startswith("s3://"):
        tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_file.close()
        local_path = tmp_file.name
        _download_s3(contract_path, local_path)

    try:
        # ── Step 2: Extract ──────────────────────────────────────────
        logger.info("job=%s step=extraction starting", job_id)
        t0 = time.perf_counter()
        extraction_s3_prefix, extraction_meta = _extract_contract(
            local_path, RESULTS_BUCKET, s3_prefix
        )
        timings["extractor"] = time.perf_counter() - t0
        agents_used.append("extractor")
        logger.info(
            "job=%s step=extraction elapsed=%.1fs prefix=%s",
            job_id,
            timings["extractor"],
            extraction_s3_prefix,
        )

        # ── Step 3: Connect to Gateway and run specialists ───────────
        logger.info("job=%s step=specialist_analysis agent_mode=%s", job_id, agent_mode)
        t0 = time.perf_counter()

        logger.info("job=%s step=gateway_auth", job_id)
        token = _get_gateway_token()

        # Connect to Gateway via MCP, filter tools, build prompt with real names
        logger.info("job=%s step=mcp_connect url=%s", job_id, GATEWAY_URL)
        mcp_client = MCPClient(
            lambda: streamablehttp_client(
                GATEWAY_URL, headers={"Authorization": f"Bearer {token}"}
            )
        )
        with mcp_client:
            t_connect = time.perf_counter()
            tools = mcp_client.list_tools_sync()
            logger.info(
                "job=%s step=mcp_list_tools elapsed=%.2fs tool_count=%d tools=%s",
                job_id,
                time.perf_counter() - t_connect,
                len(tools),
                [t.tool_name for t in tools],
            )

            # In user mode, filter to only the requested specialists.
            # Gateway tool names use the format "target-name___schema-name".
            # After aligning schema names to use hyphens, both segments are
            # identical (e.g. "talent-guild-compliance___talent-guild-compliance").
            # The UI sends bare underscore names (e.g. "talent_guild_compliance").
            # Normalize both sides to hyphens for comparison.
            if not agent_mode and specialists_override:
                allowed_hyphen = {s.replace("_", "-") for s in specialists_override}

                def _matches(tool_name: str) -> bool:
                    parts = tool_name.split("___")
                    return any(p.replace("_", "-") in allowed_hyphen for p in parts)

                tools = [t for t in tools if _matches(t.tool_name)]

            # Exclude the Gateway's built-in search tool from the tool list
            tools = [t for t in tools if not t.tool_name.startswith("x_amz_")]

            logger.info(
                "job=%s filtered_tools=%s",
                job_id,
                [t.tool_name for t in tools],
            )

            # Build the orchestrator system prompt with real tool names
            real_tool_names = [t.tool_name for t in tools]
            tool_list_str = ", ".join(real_tool_names)
            orchestrator_system_prompt = _orchestrator_prompt.replace(
                "{tools_list}", tool_list_str
            )

            if agent_mode or not specialists_override:
                tool_instruction = (
                    "Review this contract using the appropriate specialist tools. "
                    "Select tools based on the contract type and content. "
                    "You may call multiple tools in parallel when their domains are independent. "
                    "Always run risk-strategist last to synthesize all findings.\n\n"
                    "IMPORTANT: You MUST call at least one specialist tool. "
                    "Do NOT analyze the contract yourself — delegate to the specialist tools. "
                    "Each tool call MUST include: job_id, extraction_s3_prefix, s3_prefix, and results_bucket."
                )
            else:
                tool_instruction = (
                    f"You MUST call each of these specialist tools: {tool_list_str}\n\n"
                    "IMPORTANT: Do NOT analyze the contract yourself. You MUST delegate analysis "
                    "to the specialist tools listed above by calling each one. "
                    "Each tool call MUST include these parameters:\n"
                    "- job_id: the Job ID provided below\n"
                    "- extraction_s3_prefix: the S3 prefix where extraction pages are stored\n"
                    "- s3_prefix: the S3 Prefix provided below\n"
                    "- results_bucket: the Results Bucket provided below\n\n"
                    "Do not use any other tools. "
                    "Run risk-strategist last if it is in the list."
                )

            analysis_prompt = (
                f"{tool_instruction}\n\n"
                f"Job ID: {job_id}\n"
                f"S3 Prefix: {s3_prefix}\n"
                f"Results Bucket: {RESULTS_BUCKET}\n"
                f"Extraction S3 Prefix: {extraction_s3_prefix}\n\n"
                f"Contract Type: {extraction_meta.get('contract_type', 'UNKNOWN')}\n"
                f"Contract Tags: {', '.join(extraction_meta.get('tags', []))}\n"
                f"Topical Summary: {extraction_meta.get('topical_summary', 'N/A')}\n"
            )

            model = make_model(MODEL_ID, 64000)
            summary_hook = SummaryGenerationHook(
                job_id=job_id,
                s3_prefix=s3_prefix,
                results_bucket=RESULTS_BUCKET,
                model_id=MODEL_ID,
                agents_used=agents_used,
                timings=timings,
            )
            orchestrator_agent = Agent(
                model=model,
                system_prompt=orchestrator_system_prompt,
                tools=tools,
                hooks=[
                    AgentLoggingHooks(job_id=job_id, agent_name="orchestrator"),
                    summary_hook,
                ],
            )
            logger.info(
                "job=%s step=orchestrator_invoke tool_count=%d agent_mode=%s",
                job_id,
                len(tools),
                agent_mode,
            )
            try:
                analysis_response = str(orchestrator_agent(analysis_prompt))
            except MaxTokensReachedException:
                logger.warning(
                    "job=%s step=orchestrator_invoke MaxTokensReachedException — "
                    "specialist results are already in S3, continuing to summary",
                    job_id,
                )
                analysis_response = (
                    "(orchestrator hit max_tokens — specialist outputs in S3)"
                )
            logger.info(
                "job=%s step=orchestrator_invoke status=complete response_len=%d",
                job_id,
                len(analysis_response),
            )

        timings["analysis"] = time.perf_counter() - t0
        agents_used.extend(specialists_override or ["agent_selected"])
        logger.info(
            "job=%s step=specialist_analysis elapsed=%.1fs",
            job_id,
            timings["analysis"],
        )

        # ── Step 4: Summary (handled by SummaryGenerationHook on AfterInvocationEvent)
        # The hook reads specialist outputs from S3 and generates the summary
        # independently. By this point it has already fired and written to S3.
        # If it failed, the error is logged but we still complete the job.

        # ── Step 5: Write remaining outputs ──────────────────────────
        logger.info("job=%s step=write_outputs", job_id)
        # Timings: canonical-only artifact
        _upload(
            RESULTS_BUCKET,
            f"{kb_writer.CANONICAL_PREFIX}/{s3_prefix}/timings.json",
            json.dumps(timings, indent=2),
        )

        total_duration = sum(timings.values())
        logger.info(
            "job=%s COMPLETE s3_prefix=%s duration=%.1fs",
            job_id,
            s3_prefix,
            total_duration,
        )

        # ── Step 6: Emit custom CloudWatch metrics ───────────────────
        emit_job_metrics(
            job_id=job_id,
            agent_mode=agent_mode,
            duration_seconds=total_duration,
            specialists_used=[
                a
                for a in agents_used
                if a not in ("extractor", "summary", "agent_selected")
            ],
            status="COMPLETE",
        )

        return {
            "job_id": job_id,
            "status": "COMPLETE",
            "summary": "(written to S3 by SummaryGenerationHook)",
            "agents_used": agents_used,
            "timings": timings,
            "s3_prefix": s3_prefix,
        }

    finally:
        if tmp_file:
            os.unlink(tmp_file.name)


if __name__ == "__main__":
    app.run()
