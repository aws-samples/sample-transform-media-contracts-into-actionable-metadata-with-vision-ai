"""X-Ray tracing helpers for MediaContracts AgentCore runtimes.

Adds structured annotations to X-Ray segments so traces from all 6
microVMs (orchestrator + 5 specialists) can be correlated by job_id
in the X-Ray console and CloudWatch Transaction Search.

Annotations indexed for querying:
  annotation.job_id      — correlates all spans for one contract review
  annotation.specialist  — which specialist produced this span
  annotation.status      — COMPLETE | FAILED | RUNNING
  annotation.contract    — contract filename stem (no extension)

Usage:
    from agentcore.shared.tracing import annotate_job, record_error

    annotate_job(job_id="abc-123", specialist="financial", contract="my_contract")
    # ... do work ...
    annotate_job(job_id="abc-123", specialist="financial", status="COMPLETE")
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# X-Ray SDK is optional — if not installed (local dev), tracing is a no-op
try:
    from aws_xray_sdk.core import xray_recorder

    _XRAY_AVAILABLE = True
except ImportError:
    _XRAY_AVAILABLE = False
    logger.debug("aws-xray-sdk not available — tracing disabled")


def annotate_job(
    job_id: str,
    specialist: str,
    status: str | None = None,
    contract: str | None = None,
) -> None:
    """Add X-Ray annotations to the current segment.

    Safe to call even when X-Ray SDK is not installed or no segment is active.
    """
    if not _XRAY_AVAILABLE:
        return

    try:
        segment = xray_recorder.current_segment()
        if segment is None:
            return

        segment.put_annotation("job_id", job_id)
        segment.put_annotation("specialist", specialist)

        if status:
            segment.put_annotation("status", status)
        if contract:
            segment.put_annotation("contract", contract)

        # Also add as metadata for richer debugging (not indexed, not queryable)
        segment.put_metadata("job_id", job_id, namespace="media_contracts")
        segment.put_metadata("specialist", specialist, namespace="media_contracts")

    except Exception as e:
        # Never let tracing failures affect the main execution path
        logger.debug("X-Ray annotation failed: %s", e)


def record_error(error: Exception, job_id: str = "", specialist: str = "") -> None:
    """Record an exception in the current X-Ray segment."""
    if not _XRAY_AVAILABLE:
        return

    try:
        segment = xray_recorder.current_segment()
        if segment is None:
            return

        segment.add_exception(error, fatal=False)
        if job_id:
            segment.put_annotation("job_id", job_id)
        if specialist:
            segment.put_annotation("specialist", specialist)
        segment.put_annotation("status", "FAILED")

    except Exception as e:
        logger.debug("X-Ray error recording failed: %s", e)
