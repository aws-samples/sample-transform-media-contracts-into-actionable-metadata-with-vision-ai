"""Shared DynamoDB job state helper for MediaContracts AgentCore runtimes.

All runtimes (orchestrator + specialists) use this module to read and write
job state. The table schema is:

  PK  job_id     (String)
  SK  specialist (String)

  status        : PENDING | RUNNING | COMPLETE | FAILED
  result_s3_key : S3 key where output was written (set on COMPLETE)
  started_at    : ISO-8601 (set on RUNNING)
  completed_at  : ISO-8601 (set on COMPLETE or FAILED)
  error         : error message (set on FAILED)
  retry_count   : int
  ttl           : epoch seconds (auto-expire after 30 days)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_TABLE_NAME = os.environ.get("JOBS_TABLE_NAME", "")
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
_TTL_DAYS = 30

_dynamodb = None


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=_REGION)
    return _dynamodb.Table(_TABLE_NAME)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ttl() -> int:
    return int(time.time()) + (_TTL_DAYS * 86400)


# ── Write helpers ───────────────────────────────────────────────────


def mark_running(job_id: str, specialist: str) -> None:
    """Transition a job record to RUNNING."""
    _table().update_item(
        Key={"job_id": job_id, "specialist": specialist},
        UpdateExpression="SET #s = :s, started_at = :t, #ttl = :ttl",
        ExpressionAttributeNames={"#s": "status", "#ttl": "ttl"},
        ExpressionAttributeValues={
            ":s": "RUNNING",
            ":t": _now_iso(),
            ":ttl": _ttl(),
        },
    )


def mark_complete(job_id: str, specialist: str, result_s3_key: str) -> None:
    """Transition a job record to COMPLETE and record the S3 output key."""
    _table().update_item(
        Key={"job_id": job_id, "specialist": specialist},
        UpdateExpression=("SET #s = :s, completed_at = :t, result_s3_key = :k"),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "COMPLETE",
            ":t": _now_iso(),
            ":k": result_s3_key,
        },
    )


def mark_failed(job_id: str, specialist: str, error: str) -> None:
    """Transition a job record to FAILED."""
    _table().update_item(
        Key={"job_id": job_id, "specialist": specialist},
        UpdateExpression=("SET #s = :s, completed_at = :t, #e = :e"),
        ExpressionAttributeNames={"#s": "status", "#e": "error"},
        ExpressionAttributeValues={
            ":s": "FAILED",
            ":t": _now_iso(),
            ":e": error,
        },
    )


def create_pending(job_id: str, specialist: str, session_id: str = "") -> None:
    """Create a PENDING record (idempotent — skips if already exists)."""
    item: dict[str, Any] = {
        "job_id": job_id,
        "specialist": specialist,
        "status": "PENDING",
        "retry_count": 0,
        "ttl": _ttl(),
    }
    if session_id:
        item["session_id"] = session_id
    try:
        _table().put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(job_id)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise


# ── Read helpers ────────────────────────────────────────────────────


def get_record(job_id: str, specialist: str) -> dict[str, Any]:
    """Fetch a single job record. Returns {} if not found."""
    resp = _table().get_item(Key={"job_id": job_id, "specialist": specialist})
    return resp.get("Item", {})


def get_retry_count(job_id: str, specialist: str) -> int:
    """Return current retry_count for a job record (0 if not found)."""
    item = get_record(job_id, specialist)
    return int(item.get("retry_count", 0))


def increment_retry(job_id: str, specialist: str) -> int:
    """Atomically increment retry_count. Returns new value."""
    resp = _table().update_item(
        Key={"job_id": job_id, "specialist": specialist},
        UpdateExpression="ADD retry_count :one",
        ExpressionAttributeValues={":one": 1},
        ReturnValues="UPDATED_NEW",
    )
    return int(resp["Attributes"]["retry_count"])


def get_all_specialist_records(job_id: str) -> list[dict[str, Any]]:
    """Fetch all records for a job_id (all specialists)."""
    resp = _table().query(
        KeyConditionExpression="job_id = :jid",
        ExpressionAttributeValues={":jid": job_id},
    )
    return resp.get("Items", [])


def all_complete(job_id: str, specialists: list[str]) -> bool:
    """Return True if every specialist in the list has status COMPLETE."""
    records = {r["specialist"]: r for r in get_all_specialist_records(job_id)}
    return all(records.get(s, {}).get("status") == "COMPLETE" for s in specialists)
