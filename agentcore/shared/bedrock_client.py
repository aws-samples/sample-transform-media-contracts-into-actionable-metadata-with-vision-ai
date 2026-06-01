"""Bedrock model factory for MediaContracts runtimes.

Selects the correct Application Inference Profile ARN based on the
requested model ID, falling back to the model ID directly if no
profile is configured.

Profile ARNs are injected as environment variables by CDK:
  SONNET_46_PROFILE_ARN
  OPUS_46_PROFILE_ARN
  SONNET_45_PROFILE_ARN
  HAIKU_45_PROFILE_ARN

Usage:
    from agentcore.shared.bedrock_client import make_model

    model = make_model()                          # uses MODEL_ID env var
    model = make_model("us.anthropic.claude-sonnet-4-6")
"""

from __future__ import annotations

import os

from botocore.config import Config
from strands.models import BedrockModel, CacheConfig

# Map model ID patterns to env var names holding the profile ARN
_PROFILE_ENV_MAP = {
    "claude-sonnet-4-6": "SONNET_46_PROFILE_ARN",
    "claude-opus-4-6": "OPUS_46_PROFILE_ARN",
    "claude-sonnet-4-5": "SONNET_45_PROFILE_ARN",
    "claude-haiku-4-5": "HAIKU_45_PROFILE_ARN",
}

DEFAULT_MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "16000"))


def _resolve_model_id(model_id: str) -> str:
    """Return the inference profile ARN if available, else the model ID."""
    for pattern, env_key in _PROFILE_ENV_MAP.items():
        if pattern in model_id:
            arn = os.environ.get(env_key, "")
            if arn:
                return arn
    return model_id


def make_model(
    model_id: str | None = None,
    max_tokens: int | None = None,
) -> BedrockModel:
    """Create a BedrockModel using the inference profile ARN when available."""
    resolved_id = _resolve_model_id(model_id or DEFAULT_MODEL_ID)
    return BedrockModel(
        model_id=resolved_id,
        max_tokens=max_tokens or DEFAULT_MAX_TOKENS,
        cache_config=CacheConfig(strategy="auto"),
        boto_client_config=Config(
            read_timeout=600,
            connect_timeout=10,
            retries={"max_attempts": 3, "mode": "adaptive"},
        ),
    )
