"""Structured CloudWatch logging for MediaContracts AgentCore runtimes.

Emits JSON log records so CloudWatch Logs Insights can query by job_id,
specialist, status, and elapsed time without regex parsing.

Usage (at top of each runtime's main.py):
    from agentcore.shared.logging_config import configure_logging
    configure_logging("financial")
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON for CloudWatch Logs Insights."""

    def __init__(self, runtime_name: str) -> None:
        super().__init__()
        self.runtime_name = runtime_name

    def format(self, record: logging.LogRecord) -> str:
        log: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "runtime": self.runtime_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Extract structured fields from the message if present
        # Supports key=value pairs: job=xxx specialist=yyy elapsed=1.2s
        msg = record.getMessage()
        for token in msg.split():
            if "=" in token:
                k, _, v = token.partition("=")
                if k in (
                    "job",
                    "job_id",
                    "specialist",
                    "elapsed",
                    "status",
                    "s3_key",
                    "attempt",
                    "retry_count",
                    "step",
                    "event",
                    "agent",
                    "tool",
                    "tool_id",
                    "call_number",
                    "stop_reason",
                    "model_calls",
                    "tool_calls",
                    "tool_count",
                    "pages",
                    "page",
                    "type",
                    "chars",
                    "output_len",
                    "response_len",
                    "size",
                    "messages",
                    "agent_mode",
                ):
                    log[k] = v

        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)

        return json.dumps(log, default=str)


def configure_logging(runtime_name: str, level: str = "INFO") -> None:
    """Configure root logger with JSON formatter for CloudWatch.

    Call once at module level in each runtime entrypoint.
    """
    log_level = os.environ.get("LOG_LEVEL", level).upper()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(runtime_name))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level, logging.INFO))

    # Suppress noisy third-party loggers
    for noisy in ("boto3", "botocore", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configured runtime=%s level=%s", runtime_name, log_level
    )
