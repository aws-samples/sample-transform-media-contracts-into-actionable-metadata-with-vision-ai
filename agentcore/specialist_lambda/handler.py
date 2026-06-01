"""Shared Lambda handler for all MediaContracts specialist agents.

The specialist identity is determined by the SPECIALIST_NAME environment
variable. All specialists share this code — only their S3-loaded prompt
differs.

Invoked by the AgentCore Gateway as an MCP tool. The Gateway passes
the tool input as the Lambda event payload.

Input (from Gateway via MCP tool call):
  {
    "job_id":        "uuid",
    "extraction":    "full contract extraction text",
    "s3_prefix":     "contract_name_20260422T...",
    "results_bucket": "media-contracts-results-dev"  # optional override
  }

Output:
  {
    "status":    "COMPLETE" | "FAILED",
    "specialist": "financial",
    "output":    "<?xml ...>",
    "s3_key":    "contract_name_.../specialists/financial.xml",
    "elapsed":   12.3
  }

Flow (three sequential Bedrock calls — no agent framework):
  1. Converse  — identify key terms/concepts to look up for this domain
  2. Retrieve  — query the glossary Knowledge Base with those terms
  3. Converse  — full analysis grounded with retrieved glossary definitions
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from typing import Any

import boto3
from botocore.config import Config

# OpenTelemetry — custom spans for each specialist step.
# The ADOT Lambda layer auto-instruments boto3 calls (Bedrock Converse,
# KB Retrieve, S3 PutObject). These manual spans add semantic labels
# so the trace shows "identify_terms → retrieve_glossary → analyze"
# instead of just raw API calls.
try:
    from opentelemetry import trace

    _tracer = trace.get_tracer("media-contracts-specialist")
except ImportError:
    _tracer = None  # type: ignore[assignment]

# Ensure utils/ is importable when running in Lambda
sys.path.insert(0, "/var/task")

from utils.prompt_loader import PromptLoader
from agentcore.shared.tracing import annotate_job, record_error

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# ── Config ──────────────────────────────────────────────────────────
SPECIALIST_NAME = os.environ["SPECIALIST_NAME"]
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "16000"))
RESULTS_BUCKET = os.environ.get("RESULTS_BUCKET", "")
JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME", "")
GLOSSARY_KB_ID = os.environ.get("GLOSSARY_KB_ID", "")

# Resolve model ID → inference profile ARN if available
_PROFILE_ENV_MAP = {
    "claude-sonnet-4-6": "SONNET_46_PROFILE_ARN",
    "claude-opus-4-6": "OPUS_46_PROFILE_ARN",
    "claude-sonnet-4-5": "SONNET_45_PROFILE_ARN",
    "claude-haiku-4-5": "HAIKU_45_PROFILE_ARN",
}
_RAW_MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")


def _resolve_model_id(model_id: str) -> str:
    for pattern, env_key in _PROFILE_ENV_MAP.items():
        if pattern in model_id:
            arn = os.environ.get(env_key, "")
            if arn:
                return arn
    return model_id


MODEL_ID = _resolve_model_id(_RAW_MODEL_ID)

# ── Cold-start: load and cache prompt ───────────────────────────────
_loader = PromptLoader()
_loader.warm_up(SPECIALIST_NAME)
_system_prompt = _loader.load_agent_prompt(SPECIALIST_NAME)
logger.info("Specialist %s ready (model=%s)", SPECIALIST_NAME, MODEL_ID)

# ── AWS clients ─────────────────────────────────────────────────────
_boto_config = Config(
    read_timeout=600,
    connect_timeout=10,
    retries={"max_attempts": 3, "mode": "adaptive"},
)
_bedrock = boto3.client("bedrock-runtime", region_name=REGION, config=_boto_config)
_bedrock_agent = boto3.client(
    "bedrock-agent-runtime", region_name=REGION, config=_boto_config
)
_s3 = boto3.client("s3", region_name=REGION)
_dynamodb = boto3.resource("dynamodb", region_name=REGION)


def _jobs_table():
    return _dynamodb.Table(JOBS_TABLE_NAME)


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


def _upload(bucket: str, key: str, body: str) -> None:
    _s3.put_object(
        Bucket=bucket, Key=key, Body=body.encode("utf-8"), ContentType="application/xml"
    )


def _mark_running(job_id: str) -> None:
    if not JOBS_TABLE_NAME:
        return
    from datetime import datetime, timezone

    _jobs_table().update_item(
        Key={"job_id": job_id, "specialist": SPECIALIST_NAME},
        UpdateExpression="SET #s = :s, started_at = :t",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "RUNNING",
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )


def _mark_complete(job_id: str, s3_key: str) -> None:
    if not JOBS_TABLE_NAME:
        return
    from datetime import datetime, timezone

    _jobs_table().update_item(
        Key={"job_id": job_id, "specialist": SPECIALIST_NAME},
        UpdateExpression="SET #s = :s, completed_at = :t, result_s3_key = :k",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "COMPLETE",
            ":t": datetime.now(timezone.utc).isoformat(),
            ":k": s3_key,
        },
    )


def _mark_failed(job_id: str, error: str) -> None:
    if not JOBS_TABLE_NAME:
        return
    from datetime import datetime, timezone

    _jobs_table().update_item(
        Key={"job_id": job_id, "specialist": SPECIALIST_NAME},
        UpdateExpression="SET #s = :s, completed_at = :t, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":s": "FAILED",
            ":t": datetime.now(timezone.utc).isoformat(),
            ":e": error,
        },
    )


# ── Step 1: identify terms to look up ───────────────────────────────


def _identify_lookup_terms(extraction: str) -> str:
    """Call 1 — ask the model which domain terms to retrieve from the glossary."""
    resp = _bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": _system_prompt}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"You are about to analyze a contract as the {SPECIALIST_NAME} specialist.\n\n"
                            "Before performing the full analysis, identify the key domain-specific terms, "
                            "clauses, and concepts present in this extraction that you will need to "
                            "verify against the glossary. Return ONLY a concise list of search queries "
                            "(one per line, no numbering, no explanation) that will retrieve the most "
                            "relevant glossary definitions for your analysis.\n\n"
                            f"CONTRACT EXTRACTION:\n{extraction}"
                        )
                    }
                ],
            }
        ],
        inferenceConfig={"maxTokens": 512},
    )
    return resp["output"]["message"]["content"][0]["text"].strip()


# ── Step 2: retrieve glossary context ───────────────────────────────


def _retrieve_glossary(query_text: str) -> str:
    """Call 2 — retrieve relevant glossary definitions from the KB."""
    if not GLOSSARY_KB_ID:
        logger.warning("GLOSSARY_KB_ID not set — skipping KB retrieval")
        return ""

    try:
        resp = _bedrock_agent.retrieve(
            knowledgeBaseId=GLOSSARY_KB_ID,
            retrievalQuery={"text": query_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": 10}
            },
        )
        chunks = []
        for result in resp.get("retrievalResults", []):
            text = result.get("content", {}).get("text", "").strip()
            if text:
                chunks.append(text)
        return "\n\n---\n\n".join(chunks)
    except Exception as e:
        logger.warning("KB retrieval failed — proceeding without glossary: %s", e)
        return ""


# ── Step 3: full grounded analysis ──────────────────────────────────


def _analyze(extraction: str, glossary_context: str) -> str:
    """Call 3 — full specialist analysis grounded with glossary definitions."""
    glossary_section = (
        f"\n\nGLOSSARY DEFINITIONS (retrieved from knowledge base — use these to "
        f"verify and ground your analysis):\n{glossary_context}"
        if glossary_context
        else ""
    )

    resp = _bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": _system_prompt}],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": (
                            f"Analyze the following contract extraction as the {SPECIALIST_NAME} specialist. "
                            "Ground your findings against the provided glossary definitions. "
                            "Where a term or clause matches a glossary entry, cite it explicitly in your output."
                            f"{glossary_section}\n\n"
                            f"CONTRACT EXTRACTION:\n{extraction}"
                        )
                    }
                ],
            }
        ],
        inferenceConfig={"maxTokens": MAX_TOKENS},
    )
    return resp["output"]["message"]["content"][0]["text"]


# ── Read extraction from S3 ──────────────────────────────────────────


def _read_extraction_from_s3(bucket: str, extraction_prefix: str) -> str:
    """Read all per-page extraction XML files from S3 and concatenate them."""
    resp = _s3.list_objects_v2(Bucket=bucket, Prefix=extraction_prefix + "/")
    keys = sorted(
        obj["Key"] for obj in resp.get("Contents", []) if obj["Key"].endswith(".xml")
    )
    if not keys:
        logger.error(
            "No extraction pages found at s3://%s/%s/", bucket, extraction_prefix
        )
        return ""

    parts: list[str] = []
    for key in keys:
        body = _s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
        parts.append(body)
    logger.info(
        "specialist=%s read %d extraction pages from s3://%s/%s/",
        SPECIALIST_NAME,
        len(parts),
        bucket,
        extraction_prefix,
    )
    return "\n\n".join(parts)


# ── Lambda handler ───────────────────────────────────────────────────


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """MCP tool handler — called by AgentCore Gateway."""
    job_id: str = event.get("job_id", "")
    extraction_s3_prefix: str = event.get("extraction_s3_prefix", "")
    s3_prefix: str = event.get("s3_prefix", "")
    results_bucket: str = event.get("results_bucket", RESULTS_BUCKET)

    if not extraction_s3_prefix:
        return {
            "status": "FAILED",
            "error": "Missing extraction_s3_prefix",
            "output": "",
        }

    logger.info(
        "job=%s specialist=%s extraction_prefix=%s",
        job_id,
        SPECIALIST_NAME,
        extraction_s3_prefix,
    )

    # Read extraction pages from S3 and concatenate
    extraction = _read_extraction_from_s3(results_bucket, extraction_s3_prefix)
    if not extraction:
        return {
            "status": "FAILED",
            "error": "No extraction pages found in S3",
            "output": "",
        }

    logger.info("job=%s specialist=%s", job_id, SPECIALIST_NAME)

    if job_id:
        _mark_running(job_id)
        annotate_job(job_id=job_id, specialist=SPECIALIST_NAME, status="RUNNING")

    t0 = time.perf_counter()

    try:
        # Step 1 — identify terms
        logger.info("job=%s specialist=%s step=identify_terms", job_id, SPECIALIST_NAME)
        if _tracer:
            with _tracer.start_as_current_span(
                "identify_lookup_terms",
                attributes={"specialist": SPECIALIST_NAME, "job_id": job_id},
            ):
                query_terms = _identify_lookup_terms(extraction)
        else:
            query_terms = _identify_lookup_terms(extraction)
        logger.info(
            "job=%s specialist=%s terms=%s", job_id, SPECIALIST_NAME, query_terms[:200]
        )

        # Step 2 — retrieve glossary
        logger.info("job=%s specialist=%s step=kb_retrieve", job_id, SPECIALIST_NAME)
        if _tracer:
            with _tracer.start_as_current_span(
                "retrieve_glossary",
                attributes={"specialist": SPECIALIST_NAME, "job_id": job_id},
            ):
                glossary_context = _retrieve_glossary(query_terms)
        else:
            glossary_context = _retrieve_glossary(query_terms)
        logger.info(
            "job=%s specialist=%s glossary_chunks=%d",
            job_id,
            SPECIALIST_NAME,
            len(glossary_context.split("---")) if glossary_context else 0,
        )

        # Step 3 — grounded analysis
        logger.info("job=%s specialist=%s step=analyze", job_id, SPECIALIST_NAME)
        if _tracer:
            with _tracer.start_as_current_span(
                "analyze",
                attributes={"specialist": SPECIALIST_NAME, "job_id": job_id},
            ):
                output = _analyze(extraction, glossary_context)
        else:
            output = _analyze(extraction, glossary_context)
        output = _strip_fences(output)
        elapsed = time.perf_counter() - t0

        # Write to S3 — dual-prefix (canonical XML + KB TXT + metadata sidecars)
        s3_key = ""
        if s3_prefix and results_bucket:
            from agentcore.shared.kb_writer import write_pair

            metadata_attributes = {
                "job_id": {"stringValue": job_id or "", "type": "STRING"},
                "specialist": {"stringValue": SPECIALIST_NAME, "type": "STRING"},
                "analyzed_at": {
                    "stringValue": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "type": "STRING",
                },
                "elapsed_seconds": {
                    "numberValue": round(elapsed, 2),
                    "type": "NUMBER",
                },
            }
            keys = write_pair(
                bucket=results_bucket,
                job_id=s3_prefix,
                relative_key=f"specialists/{SPECIALIST_NAME}.xml",
                content=output,
                metadata_attributes=metadata_attributes,
                kind="xml",
            )
            s3_key = keys["canonical_key"]

        if job_id:
            _mark_complete(job_id, s3_key)
            annotate_job(job_id=job_id, specialist=SPECIALIST_NAME, status="COMPLETE")

        logger.info(
            "job=%s specialist=%s COMPLETE elapsed=%.1fs",
            job_id,
            SPECIALIST_NAME,
            elapsed,
        )

        return {
            "status": "COMPLETE",
            "specialist": SPECIALIST_NAME,
            "output": f"Analysis complete. Written to s3://{results_bucket}/{s3_key}",
            "s3_key": s3_key,
            "elapsed": round(elapsed, 2),
        }

    except Exception as e:
        elapsed = time.perf_counter() - t0
        logger.exception(
            "job=%s specialist=%s FAILED elapsed=%.1fs: %s",
            job_id,
            SPECIALIST_NAME,
            elapsed,
            e,
        )
        if job_id:
            _mark_failed(job_id, str(e))
            record_error(e, job_id=job_id, specialist=SPECIALIST_NAME)
        return {"status": "FAILED", "error": str(e), "output": ""}
