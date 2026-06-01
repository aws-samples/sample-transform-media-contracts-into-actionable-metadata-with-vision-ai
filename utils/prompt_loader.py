"""Prompt Loader — loads and assembles XML system prompts for contract analysis agents.

Production mode (CONFIG_BUCKET env var set):
  Fetches prompt files from S3 on first access, caches in memory for the
  lifetime of the container session. Prompt update = s3 cp + container restart
  (or next cold start). No container rebuild required.

  S3 layout:
    s3://{CONFIG_BUCKET}/prompts/foundation/{file}.xml
    s3://{CONFIG_BUCKET}/prompts/agents/{agent_name}/{file}.xml

  Rollback: S3 versioning is enabled on the config bucket. Restore a previous
  version of any XML file and restart the runtime session.

Local mode (CONFIG_BUCKET not set):
  Falls back to reading from the local filesystem at agents_dir, preserving
  the original behaviour for local development and testing.

Usage:
    loader = PromptLoader()                          # auto-detects mode
    prompt = loader.load_agent_prompt("financial")
    agents = loader.list_agents()
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# S3 key prefixes
_FOUNDATION_PREFIX = "prompts/foundation"
_AGENTS_PREFIX = "prompts/agents"

# Directories to exclude when listing agents
_SKIP_DIRS = {"foundation", "version_1", "__pycache__", ".DS_Store"}


class PromptLoader:
    """Loads and assembles multi-file XML system prompts.

    Automatically selects S3 or local filesystem based on the CONFIG_BUCKET
    environment variable.
    """

    def __init__(
        self,
        agents_dir: str | Path = "media_contracts_agents",
        config_bucket: Optional[str] = None,
        region: str = "us-west-2",
    ) -> None:
        self._agents_dir = Path(agents_dir)
        self._foundation_dir = self._agents_dir / "foundation"
        self._config_bucket = config_bucket or os.environ.get("CONFIG_BUCKET")
        self._region = os.environ.get("AWS_DEFAULT_REGION", region)

        # In-memory cache: s3_key or local_path → file content
        self._cache: dict[str, str] = {}

        # S3 client — lazy initialised only when needed
        self._s3 = None

        mode = "S3" if self._config_bucket else "local filesystem"
        logger.info(
            "PromptLoader initialised in %s mode (bucket=%s)",
            mode,
            self._config_bucket or "n/a",
        )

    # ── Public API ──────────────────────────────────────────────────

    def list_agents(self) -> list[str]:
        """Return sorted list of available agent names."""
        if self._config_bucket:
            return self._list_agents_s3()
        return self._list_agents_local()

    def load_foundation(self) -> str:
        """Load all foundation XML files concatenated."""
        if self._config_bucket:
            return self._load_s3_prefix(f"{_FOUNDATION_PREFIX}/")
        return self._concat_xml(self._foundation_dir)

    def load_agent_prompt(self, agent_name: str) -> str:
        """Load full system prompt: foundation + agent-specific XMLs."""
        foundation = self.load_foundation()
        agent_specific = self.load_agent_specific(agent_name)
        return f"{foundation}\n\n{agent_specific}"

    def load_agent_specific(self, agent_name: str) -> str:
        """Load only the agent-specific XML files (no foundation)."""
        if self._config_bucket:
            return self._load_s3_prefix(f"{_AGENTS_PREFIX}/{agent_name}/")
        agent_dir = self._agents_dir / agent_name
        if not agent_dir.is_dir():
            raise FileNotFoundError(f"Agent directory not found: {agent_dir}")
        return self._concat_xml(agent_dir)

    # ── S3 implementation ───────────────────────────────────────────

    def _get_s3(self):
        if self._s3 is None:
            import boto3

            self._s3 = boto3.client("s3", region_name=self._region)
        return self._s3

    def _list_agents_s3(self) -> list[str]:
        """List agent names by scanning S3 prefixes under prompts/agents/."""
        s3 = self._get_s3()
        paginator = s3.get_paginator("list_objects_v2")
        agents: set[str] = set()
        for page in paginator.paginate(
            Bucket=self._config_bucket,
            Prefix=f"{_AGENTS_PREFIX}/",
            Delimiter="/",
        ):
            for cp in page.get("CommonPrefixes", []):
                # cp["Prefix"] = "prompts/agents/financial/"
                name = cp["Prefix"].rstrip("/").split("/")[-1]
                if name not in _SKIP_DIRS:
                    agents.add(name)
        return sorted(agents)

    def _load_s3_prefix(self, prefix: str) -> str:
        """Fetch all XML objects under an S3 prefix, sorted by key, concatenated."""
        s3 = self._get_s3()
        paginator = s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self._config_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".xml"):
                    keys.append(obj["Key"])

        if not keys:
            raise FileNotFoundError(
                f"No XML files found at s3://{self._config_bucket}/{prefix}"
            )

        parts: list[str] = []
        for key in sorted(keys):
            parts.append(self._fetch_s3_object(key))
        return "\n\n".join(parts)

    def _fetch_s3_object(self, key: str) -> str:
        """Fetch a single S3 object, using the in-memory cache."""
        if key in self._cache:
            return self._cache[key]

        s3 = self._get_s3()
        logger.debug("Fetching s3://%s/%s", self._config_bucket, key)
        response = s3.get_object(Bucket=self._config_bucket, Key=key)
        content: str = response["Body"].read().decode("utf-8")
        self._cache[key] = content
        return content

    # ── Local filesystem implementation ────────────────────────────

    def _list_agents_local(self) -> list[str]:
        return sorted(
            d.name
            for d in self._agents_dir.iterdir()
            if d.is_dir() and d.name not in _SKIP_DIRS
        )

    @staticmethod
    def _concat_xml(folder: Path, glob: str = "*.xml") -> str:
        parts = []
        for f in sorted(folder.glob(glob)):
            if f.is_file():
                parts.append(f.read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    # ── Warm-up ─────────────────────────────────────────────────────

    def warm_up(self, agent_name: str) -> None:
        """Pre-fetch and cache all prompts for a specific agent.

        Call this at container startup so the first real invocation
        doesn't pay the S3 fetch latency, and so a misconfigured
        bucket/key fails fast on deploy rather than on the first request.
        """
        logger.info("Warming up prompts for agent: %s", agent_name)
        self.load_agent_prompt(agent_name)
        logger.info("Prompt warm-up complete for agent: %s", agent_name)

    def __repr__(self) -> str:
        mode = (
            f"s3://{self._config_bucket}"
            if self._config_bucket
            else str(self._agents_dir)
        )
        return f"PromptLoader(source={mode}, cached_keys={len(self._cache)})"
