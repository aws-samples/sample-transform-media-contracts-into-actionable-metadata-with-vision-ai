"""Custom CloudWatch metrics for MediaContracts pipeline.

Emitted by the orchestrator at job completion. These power the three
additional dashboard rows:
  - End-to-end job duration
  - Agent mode vs user mode split
  - Estimated cost per job (token-based approximation)

Namespace: MediaContracts/Pipeline

Metrics emitted:
  JobDuration        — total seconds from extraction start to summary complete
                       Dimensions: Mode (agent|user)
  JobCompleted       — count=1 on success
                       Dimensions: Mode (agent|user)
  JobFailed          — count=1 on failure
                       Dimensions: Mode (agent|user)
  EstimatedCostUSD   — approximate Bedrock cost for the job
                       Dimensions: Mode (agent|user)
  SpecialistsInvoked — how many specialists ran for this job
                       Dimensions: Mode (agent|user)

Usage:
    from agentcore.shared.metrics import emit_job_metrics

    emit_job_metrics(
        job_id="abc-123",
        agent_mode=True,
        duration_seconds=47.3,
        specialists_used=["financial", "rights_clearance"],
        input_tokens=12000,
        output_tokens=8000,
        status="COMPLETE",
    )
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import boto3

logger = logging.getLogger(__name__)

NAMESPACE = "MediaContracts/Pipeline"
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")

# Approximate Bedrock pricing for Claude Sonnet 4.6 (USD per 1M tokens)
# Update if pricing changes — these are used only for the dashboard estimate
_INPUT_PRICE_PER_1M = 3.0
_OUTPUT_PRICE_PER_1M = 15.0

_cw = None


def _get_cw():
    global _cw
    if _cw is None:
        _cw = boto3.client("cloudwatch", region_name=REGION)
    return _cw


def emit_job_metrics(
    job_id: str,
    agent_mode: bool,
    duration_seconds: float,
    specialists_used: list[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
    status: Literal["COMPLETE", "FAILED", "PARTIAL"] = "COMPLETE",
) -> None:
    """Emit all pipeline metrics for a completed job.

    Safe to call even if CloudWatch is unavailable — failures are logged
    but never propagate to the caller.
    """
    mode = "agent" if agent_mode else "user"
    dimensions = [{"Name": "Mode", "Value": mode}]

    estimated_cost = (input_tokens / 1_000_000) * _INPUT_PRICE_PER_1M + (
        output_tokens / 1_000_000
    ) * _OUTPUT_PRICE_PER_1M

    metric_data = [
        {
            "MetricName": "JobDuration",
            "Dimensions": dimensions,
            "Value": duration_seconds,
            "Unit": "Seconds",
        },
        {
            "MetricName": "SpecialistsInvoked",
            "Dimensions": dimensions,
            "Value": float(len(specialists_used)),
            "Unit": "Count",
        },
    ]

    if estimated_cost > 0:
        metric_data.append(
            {
                "MetricName": "EstimatedCostUSD",
                "Dimensions": dimensions,
                "Value": estimated_cost,
                "Unit": "None",  # CloudWatch has no currency unit
            }
        )

    if status == "COMPLETE":
        metric_data.append(
            {
                "MetricName": "JobCompleted",
                "Dimensions": dimensions,
                "Value": 1.0,
                "Unit": "Count",
            }
        )
    else:
        metric_data.append(
            {
                "MetricName": "JobFailed",
                "Dimensions": dimensions,
                "Value": 1.0,
                "Unit": "Count",
            }
        )

    try:
        _get_cw().put_metric_data(
            Namespace=NAMESPACE,
            MetricData=metric_data,
        )
        logger.info(
            "job=%s metrics emitted mode=%s duration=%.1fs specialists=%d cost=$%.4f status=%s",
            job_id,
            mode,
            duration_seconds,
            len(specialists_used),
            estimated_cost,
            status,
        )
    except Exception as e:
        # Never let metrics failures affect the pipeline
        logger.warning("job=%s metrics emission failed: %s", job_id, e)
