"""Tests for the vision (image → curator-intent) tool."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from gocam_prototype.vision import (
    Compartment,
    CuratorIntent,
    GeneMention,
    TentativeEdge,
    extract_curator_intent,
)

FIGURE_1 = Path(__file__).resolve().parents[1] / "inputs" / "figure1-celegans-serotonin-fat-loss.png"
CREDS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
PROJECT = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
_HAS_VERTEX = bool(CREDS and PROJECT and os.path.isfile(CREDS))


# ---------- pure-pydantic / schema tests --------------------------------------

def test_curator_intent_schema_top_level_keys() -> None:
    schema = CuratorIntent.model_json_schema()
    assert schema["type"] == "object"
    top = set(schema["properties"].keys())
    assert {"species", "compartments", "genes", "tentative_edges"} <= top
    # extra="forbid" is reflected in the schema
    assert schema.get("additionalProperties") is False


def test_curator_intent_validates_realistic_payload() -> None:
    intent = CuratorIntent.model_validate(
        {
            "species": "Caenorhabditis elegans",
            "species_taxon": "NCBITaxon:6239",
            "processes_hinted": ["serotonin signaling", "fat metabolism"],
            "compartments": [
                {"label": "NEURONS", "kind": "cell_type", "confidence": 0.95, "snippet": "labeled NEURONS box"},
            ],
            "genes": [
                {"symbol": "tph-1", "in_compartment": "NEURONS", "confidence": 0.95, "snippet": "in NEURONS box"},
            ],
            "tentative_edges": [
                {
                    "from_compartment": "NEURONS",
                    "to_compartment": "INTESTINE",
                    "relation": "endocrine signal",
                    "confidence": 0.9,
                    "snippet": "dashed arrow labeled endocrine signal",
                }
            ],
        }
    )
    assert intent.species == "Caenorhabditis elegans"
    assert isinstance(intent.compartments[0], Compartment)
    assert isinstance(intent.genes[0], GeneMention)
    assert isinstance(intent.tentative_edges[0], TentativeEdge)


# ---------- mocked-client unit test -------------------------------------------

class _MockAnthropic:
    """Tiny stand-in for an AnthropicVertex client."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.last_kwargs: dict | None = None

        class _Messages:
            def __init__(_self, parent: "_MockAnthropic") -> None:
                _self._parent = parent

            def create(_self, **kwargs):
                _self._parent.last_kwargs = kwargs
                tool_use = SimpleNamespace(
                    type="tool_use",
                    name="submit_curator_intent",
                    input=_self._parent._payload,
                )
                return SimpleNamespace(content=[tool_use])

        self.messages = _Messages(self)


def test_extract_curator_intent_two_stage(tmp_path, monkeypatch) -> None:
    fake_image = tmp_path / "tiny.png"
    # 1x1 PNG (smallest valid). Anthropic doesn't see this in the mock anyway.
    fake_image.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000a49444154789c63000100000500010d0a2db40000000049454e44ae"
            "426082"
        )
    )

    payload = {
        "species": "Caenorhabditis elegans",
        "species_taxon": "NCBITaxon:6239",
        "processes_hinted": ["serotonin signaling"],
        "compartments": [
            {"label": "NEURONS", "kind": "cell_type", "confidence": 0.9, "snippet": "labeled NEURONS"},
        ],
        "genes": [
            {"symbol": "tph-1", "in_compartment": "NEURONS", "confidence": 0.9, "snippet": "triangle in NEURONS"},
        ],
        "tentative_edges": [],
    }
    client = _MockAnthropic(payload)  # Stage B (structure) returns the forced tool_use

    # Stage A (perception) goes through llm.create_message — fake it and capture its input.
    captured: dict = {}

    def fake_create_message(_client, **kwargs):
        captured["messages"] = kwargs.get("messages")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="- tph-1 in NEURONS box")])

    monkeypatch.setattr("gocam_prototype.vision.create_message", fake_create_message)
    monkeypatch.setattr("gocam_prototype.vision.make_client", lambda *a, **k: client)
    monkeypatch.setattr("gocam_prototype.vision.VertexConfig.from_env", lambda: SimpleNamespace())

    intent = extract_curator_intent(
        fake_image, species_hint="C. elegans", client=client, model="claude-sonnet-4-6@default"
    )

    assert intent.species == "Caenorhabditis elegans"
    assert intent.genes[0].symbol == "tph-1"
    # Stage A carried the image as a base64 block, image-first.
    blocks = captured["messages"][0]["content"]
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/png"
    # Stage B forced the single tool choice (text-only structuring).
    assert client.last_kwargs["tool_choice"] == {"type": "tool", "name": "submit_curator_intent"}


# ---------- optional live test against figure 1 -------------------------------

@pytest.mark.skipif(
    not (_HAS_VERTEX and FIGURE_1.is_file()),
    reason="requires Vertex creds + the v0 test image at inputs/figure1-...png",
)
@pytest.mark.skipif(
    not os.environ.get("GOCAM_RUN_LIVE_TESTS"),
    reason="set GOCAM_RUN_LIVE_TESTS=1 to hit the Vertex API",
)
def test_live_vision_on_figure_1() -> None:
    intent = extract_curator_intent(FIGURE_1, species_hint="Caenorhabditis elegans")
    assert intent.species
    # The figure shows clear NEURONS and INTESTINE compartments and several genes.
    labels = {c.label.lower() for c in intent.compartments}
    assert any("neuron" in label for label in labels)
    assert any("intest" in label for label in labels)
    symbols = {g.symbol.lower() for g in intent.genes}
    # At least one of the canonical genes should appear.
    assert symbols & {"tph-1", "mod-1", "tbh-1", "ser-6", "nhr-76", "atgl-1", "atgl"}
