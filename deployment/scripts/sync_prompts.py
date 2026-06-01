#!/usr/bin/env python3
"""Sync prompt XML files from media_contracts_agents/ to S3 config bucket.

S3 layout mirrors the local directory structure:
  s3://{bucket}/prompts/foundation/{file}.xml
  s3://{bucket}/prompts/agents/{agent_name}/{file}.xml

Also syncs the main-agent and terms-kb prompts used by the Express server:
  s3://{bucket}/prompts/main-agent.xml
  s3://{bucket}/prompts/terms-kb.xml

Usage:
  python deployment/scripts/sync_prompts.py --bucket media-contracts-config-dev
  python deployment/scripts/sync_prompts.py --bucket media-contracts-config-dev --dry-run

The script prints each upload with its S3 key so you can verify the layout.
On success it prints a summary of files uploaded / skipped (dry-run).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# Directories to skip when scanning agent folders
SKIP_DIRS = {"foundation", "__pycache__", ".DS_Store", "few-shot-examples"}

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "media_contracts_agents"
PROMPTS_DIR = REPO_ROOT / "prompts"


def build_upload_manifest() -> list[tuple[Path, str]]:
    """Return list of (local_path, s3_key) pairs to upload."""
    uploads: list[tuple[Path, str]] = []

    # Foundation prompts
    foundation_dir = AGENTS_DIR / "foundation"
    for f in sorted(foundation_dir.glob("*.xml")):
        uploads.append((f, f"prompts/foundation/{f.name}"))

    # Agent-specific prompts
    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        if agent_dir.name in SKIP_DIRS or agent_dir.name.startswith("."):
            continue
        for f in sorted(agent_dir.glob("*.xml")):
            uploads.append((f, f"prompts/agents/{agent_dir.name}/{f.name}"))

    # Top-level prompts used by Express server chat endpoint
    for f in sorted(PROMPTS_DIR.glob("*.xml")):
        uploads.append((f, f"prompts/{f.name}"))

    return uploads


def sync(bucket: str, dry_run: bool = False) -> None:
    s3 = boto3.client("s3")

    # Verify bucket exists and is accessible
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        print(f"ERROR: Cannot access bucket '{bucket}': {code}", file=sys.stderr)
        sys.exit(1)

    manifest = build_upload_manifest()
    uploaded = 0
    skipped = 0

    for local_path, s3_key in manifest:
        if not local_path.exists():
            print(f"  SKIP (not found): {local_path}")
            skipped += 1
            continue

        content = local_path.read_bytes()

        if dry_run:
            print(f"  DRY-RUN  s3://{bucket}/{s3_key}  ({len(content):,} bytes)")
            uploaded += 1
            continue

        try:
            s3.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=content,
                ContentType="application/xml",
            )
            print(f"  UPLOAD   s3://{bucket}/{s3_key}  ({len(content):,} bytes)")
            uploaded += 1
        except ClientError as e:
            print(f"  ERROR    {s3_key}: {e}", file=sys.stderr)
            skipped += 1

    label = "Would upload" if dry_run else "Uploaded"
    print(f"\n{label} {uploaded} files, skipped {skipped}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync prompt XML files to S3")
    parser.add_argument("--bucket", required=True, help="S3 config bucket name")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be uploaded without uploading",
    )
    args = parser.parse_args()
    sync(args.bucket, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
