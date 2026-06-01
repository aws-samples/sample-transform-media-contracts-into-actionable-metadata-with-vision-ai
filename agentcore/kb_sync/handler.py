"""KB Sync Lambda — triggers Bedrock KB ingestion on S3 object events.

Invoked by S3 event notifications when files land in:
  - results bucket (jobs-kb-versions/ prefix) → Contract Analysis KB
  - terms bucket (any prefix) → Terms KB

Calls bedrock-agent:StartIngestionJob so the KB re-indexes new data.
"""

import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

client = boto3.client("bedrock-agent")


def lambda_handler(event, context):
    kb_id = os.environ["KB_ID"]
    ds_id = os.environ["DATA_SOURCE_ID"]

    records = event.get("Records", [])
    if not records:
        logger.info("No S3 records in event, skipping")
        return {"statusCode": 200}

    bucket = records[0].get("s3", {}).get("bucket", {}).get("name", "")
    key = records[0].get("s3", {}).get("object", {}).get("key", "")
    logger.info("S3 event: s3://%s/%s (%d records)", bucket, key, len(records))

    # Skip metadata sidecar files — they accompany the main file
    # and we only need to trigger ingestion once per batch
    if key.endswith(".metadata.json"):
        logger.info("Skipping metadata sidecar file")
        return {"statusCode": 200}

    resp = client.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id,
    )
    job_id = resp["ingestionJob"]["ingestionJobId"]
    status = resp["ingestionJob"]["status"]
    logger.info("Started ingestion job %s (status: %s)", job_id, status)

    return {"statusCode": 200, "ingestionJobId": job_id}
