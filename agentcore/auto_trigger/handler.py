"""Auto-trigger Lambda — fires when a PDF lands in source-bucket/pipeline/.

Invoked by S3 event notification on s3:ObjectCreated:* with prefix=pipeline/
and suffix=.pdf.

Reads the orchestrator runtime ARN from SSM, generates a job_id, writes a
PENDING DynamoDB record, then calls InvokeAgentRuntime in agent mode.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
JOBS_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME", "")
ORCHESTRATOR_RUNTIME_ARN_PARAM = "/media-contracts/orchestrator-runtime-arn"

_ssm = boto3.client("ssm", region_name=REGION)
_agentcore = boto3.client("bedrock-agentcore", region_name=REGION)
_dynamodb = boto3.resource("dynamodb", region_name=REGION)

_runtime_arn: str | None = None


def _get_runtime_arn() -> str:
    global _runtime_arn
    if not _runtime_arn:
        resp = _ssm.get_parameter(Name=ORCHESTRATOR_RUNTIME_ARN_PARAM)
        _runtime_arn = resp["Parameter"]["Value"]
    return _runtime_arn


def _write_pending(job_id: str, contract_path: str) -> None:
    if not JOBS_TABLE_NAME:
        return
    ttl = int(time.time()) + (30 * 86400)
    _dynamodb.Table(JOBS_TABLE_NAME).put_item(
        Item={
            "job_id": job_id,
            "specialist": "orchestrator",
            "status": "PENDING",
            "contract_path": contract_path,
            "trigger": "auto",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": 0,
            "ttl": ttl,
        },
        ConditionExpression="attribute_not_exists(job_id)",
    )


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    records = event.get("Records", [])
    results = []

    for record in records:
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]
        contract_path = f"s3://{bucket}/{key}"

        logger.info("Auto-trigger: %s", contract_path)

        job_id = str(uuid.uuid4())

        try:
            _write_pending(job_id, contract_path)
        except Exception as e:
            # ConditionalCheckFailedException = already triggered, skip
            logger.warning("DynamoDB write skipped for %s: %s", job_id, e)
            results.append({"job_id": job_id, "status": "skipped", "reason": str(e)})
            continue

        payload = json.dumps(
            {
                "job_id": job_id,
                "contract_path": contract_path,
                "specialists": None,
                "agent_mode": True,
            }
        ).encode()

        try:
            runtime_arn = _get_runtime_arn()
            _agentcore.invoke_agent_runtime(
                agentRuntimeArn=runtime_arn,
                qualifier="DEFAULT",
                payload=payload,
            )
            logger.info("job=%s invoked runtime for %s", job_id, contract_path)
            results.append(
                {"job_id": job_id, "status": "invoked", "contract_path": contract_path}
            )
        except Exception as e:
            logger.exception("job=%s failed to invoke runtime: %s", job_id, e)
            results.append({"job_id": job_id, "status": "error", "error": str(e)})

    return {"triggered": len(results), "results": results}
