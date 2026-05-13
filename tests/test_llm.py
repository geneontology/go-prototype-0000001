"""Tests for the Vertex client wrapper.

The round-trip test is skipped automatically when Vertex credentials are
not configured, so the test suite stays green on machines without the
service account key.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

# Mirror what gocam_prototype.llm does at import time, so the HAS_VERTEX
# probe sees the same env the production code will.
load_dotenv()

CREDS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
PROJECT_ID = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
_HAS_VERTEX = bool(CREDS_PATH and PROJECT_ID and os.path.isfile(CREDS_PATH))


def test_config_loads_from_env_when_available() -> None:
    from gocam_prototype.llm import VertexConfig

    if _HAS_VERTEX:
        cfg = VertexConfig.from_env()
        assert cfg.project_id == PROJECT_ID
        assert cfg.region
        assert cfg.sonnet_model.startswith("claude-sonnet")
    else:
        # Without env vars, from_env must fail loudly rather than silently
        # returning a half-built config.
        with pytest.raises(RuntimeError):
            VertexConfig.from_env()


@pytest.mark.skipif(not _HAS_VERTEX, reason="Vertex credentials not configured")
def test_vertex_round_trip() -> None:
    from gocam_prototype.llm import VertexConfig, make_client

    cfg = VertexConfig.from_env()
    client = make_client(cfg)
    msg = client.messages.create(
        model=cfg.sonnet_model,
        max_tokens=16,
        messages=[{"role": "user", "content": "Reply with exactly: VERTEX_OK"}],
    )
    text = msg.content[0].text
    assert "VERTEX_OK" in text
