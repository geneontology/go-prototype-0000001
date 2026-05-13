"""Anthropic-on-Vertex client wrapper.

Loads configuration from environment variables (a `.env` file is read
automatically via python-dotenv) and exposes a configured `AnthropicVertex`
client to the rest of the agent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from anthropic import AnthropicVertex
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class VertexConfig:
    """Resolved Vertex AI configuration."""

    project_id: str
    region: str
    credentials_path: str
    sonnet_model: str
    opus_model: str
    haiku_model: str

    @classmethod
    def from_env(cls) -> VertexConfig:
        return cls(
            project_id=_require("ANTHROPIC_VERTEX_PROJECT_ID"),
            region=os.environ.get("CLOUD_ML_REGION", "us-east5"),
            credentials_path=_require("GOOGLE_APPLICATION_CREDENTIALS"),
            sonnet_model=os.environ.get(
                "ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6@default"
            ),
            opus_model=os.environ.get(
                "ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-opus-4-6@default"
            ),
            haiku_model=os.environ.get(
                "ANTHROPIC_DEFAULT_HAIKU_MODEL", "claude-haiku-4-5@20251001"
            ),
        )


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name!r} is not set")
    return value


def make_client(config: VertexConfig | None = None) -> AnthropicVertex:
    """Return a configured AnthropicVertex client."""
    cfg = config or VertexConfig.from_env()
    return AnthropicVertex(project_id=cfg.project_id, region=cfg.region)
