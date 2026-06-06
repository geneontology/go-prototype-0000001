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
                "ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-opus-4-8"
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


def make_client(
    config: VertexConfig | None = None, *, region: str | None = None
) -> AnthropicVertex:
    """Return a configured AnthropicVertex client.

    `region` overrides the configured region. Opus 4.8 is only provisioned on
    the Vertex **global** endpoint for this project (regional endpoints return
    429/404), so callers that use Opus 4.8 must pass region="global".
    """
    cfg = config or VertexConfig.from_env()
    return AnthropicVertex(project_id=cfg.project_id, region=region or cfg.region)


def create_message(
    client: AnthropicVertex,
    *,
    model: str,
    messages: list,
    system=None,
    tools: list | None = None,
    max_tokens: int = 16000,
    effort: str | None = None,
    adaptive_thinking: bool = False,
    **kwargs,
):
    """Single entry point for Vertex Messages calls with Opus-4.8 controls.

    On Opus 4.8/4.7 the effort level lives under `output_config.effort`
    (low/medium/high/xhigh/max) and thinking is adaptive (`thinking.type ==
    "adaptive"`); manual `budget_tokens`, `temperature`/`top_p`/`top_k`, and
    assistant prefill are unsupported. The installed anthropic SDK has no
    native `effort`/`output_config` kwarg, so we pass them through `extra_body`.

    The call is STREAMED (via `client.messages.stream(...).get_final_message()`).
    The SDK refuses a *non-streaming* request whose `max_tokens` could exceed the
    10-minute server limit — Opus 4.8 with a large `max_tokens` (32000, needed so
    a dense figure's adaptive-thinking turn isn't truncated) trips that guard, so
    streaming is required. The accumulated final Message is returned, so callers
    see the same shape (`.content` / `.stop_reason` / `.usage`) as before.
    """
    extra: dict = {}
    if effort:
        extra["output_config"] = {"effort": effort}
    if adaptive_thinking:
        extra["thinking"] = {"type": "adaptive"}

    params: dict = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system is not None:
        params["system"] = system
    if tools is not None:
        params["tools"] = tools
    if extra:
        params["extra_body"] = extra
    params.update(kwargs)
    with client.messages.stream(**params) as stream:
        return stream.get_final_message()
