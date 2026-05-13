"""Tests for the Claude tool-use orchestrator.

The unit test drives the orchestrator with a scripted "agent" that returns
preplanned tool_use blocks. This exercises the loop's:
* tool dispatch and result wiring,
* SourceObject validation when the agent supplies bad source params,
* termination on finalize_model,
* assistant-message reconstruction across turns.

A live test against figure 1 is gated on env (GOCAM_RUN_LIVE_TESTS) so it
doesn't burn Vertex tokens by default.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from gocam_prototype.builder import GoCamBuilder
from gocam_prototype.orchestrator import Orchestrator, orchestrate
from gocam_prototype.vision import CuratorIntent

CREDS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
PROJECT = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID")
FIGURE_1 = Path(__file__).resolve().parents[1] / "inputs" / "figure1-celegans-serotonin-fat-loss.png"
_HAS_VERTEX = bool(CREDS and PROJECT and os.path.isfile(CREDS))


# --------------------------------------------------------------------- mocks

def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use(tool_id: str, name: str, **input_kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=input_kwargs)


def _response(*blocks, stop_reason: str = "tool_use") -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks),
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )


class _ScriptedClient:
    """Returns the next pre-baked response each time messages.create is called."""

    def __init__(self, script: list[SimpleNamespace]) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

        class _Messages:
            def __init__(_self, parent: "_ScriptedClient") -> None:
                _self._parent = parent

            def create(_self, **kwargs):
                # Snapshot — the orchestrator mutates the messages list after
                # every turn, so capturing the live reference would lose
                # per-turn state.
                import copy as _copy
                _self._parent.calls.append(_copy.deepcopy(kwargs))
                if not _self._parent._script:
                    raise AssertionError("scripted client ran out of responses")
                return _self._parent._script.pop(0)

        self.messages = _Messages(self)


# --------------------------------------------------------------------- tests

def _make_intent() -> CuratorIntent:
    return CuratorIntent.model_validate({
        "species": "Caenorhabditis elegans",
        "species_taxon": "NCBITaxon:6239",
        "processes_hinted": ["serotonin signaling"],
        "compartments": [
            {"label": "NEURONS", "kind": "cell_type", "confidence": 0.95, "snippet": "NEURONS box"},
        ],
        "genes": [
            {"symbol": "tph-1", "in_compartment": "NEURONS", "confidence": 0.95, "snippet": "in NEURONS"},
            {"symbol": "mod-1", "in_compartment": "NEURONS", "confidence": 0.95, "snippet": "in NEURONS"},
        ],
        "tentative_edges": [
            {"from_symbol": "tph-1", "to_symbol": "mod-1", "relation": "directly positively regulates",
             "confidence": 0.9, "snippet": "arrow tph-1 -> mod-1 via 5-HT"},
        ],
    })


def test_orchestrator_threads_tool_calls_into_builder() -> None:
    builder = GoCamBuilder(model_id="gomodel:test-001", title="orchestrator test")
    script = [
        _response(
            _text("I'll add two activities and a causal edge."),
            _tool_use("tu1", "add_activity",
                      local_part="tph1",
                      enabled_by_gene="WB:WBGene00006600",
                      gene_label="tph-1",
                      source={"source_type": "database",
                              "source_id": "WB:WBGene00006600",
                              "tool_name": "alliance.resolve_symbol_to_curie"}),
        ),
        _response(
            _tool_use("tu2", "add_activity",
                      local_part="mod1",
                      enabled_by_gene="WB:WBGene00003185",
                      gene_label="mod-1",
                      source={"source_type": "database",
                              "source_id": "WB:WBGene00003185",
                              "tool_name": "alliance.resolve_symbol_to_curie"}),
        ),
        _response(
            _tool_use("tu3", "set_molecular_function",
                      activity_id="gomodel:test-001/tph1",
                      term="GO:0004510",
                      label="tryptophan 5-monooxygenase activity",
                      source={"source_type": "database",
                              "source_id": "GO:0004510",
                              "tool_name": "go_api.gene_annotations"}),
        ),
        _response(
            _tool_use("tu4", "add_causal",
                      source_activity_id="gomodel:test-001/tph1",
                      target_activity_id="gomodel:test-001/mod1",
                      predicate="RO:0002629",
                      predicate_label="directly positively regulates",
                      source={"source_type": "instinct",
                              "justification": "Figure 1 panel E shows tph-1 -> mod-1 via 5-HT; "
                                               "no direct annotation found yet."}),
        ),
        _response(_tool_use("tu5", "finalize_model"), stop_reason="tool_use"),
    ]

    orch = Orchestrator(
        builder=builder, client=_ScriptedClient(script),
        model_name="claude-sonnet-4-6@default", max_turns=10,
    )
    model, ledger = orch.run(_make_intent())

    activity_ids = {a.id for a in (model.activities or [])}
    assert activity_ids == {"gomodel:test-001/tph1", "gomodel:test-001/mod1"}

    assert ledger.count_by_source_type() == {"database": 3, "instinct": 1}
    assert orch._finalized  # noqa: SLF001
    # The orchestrator should have made exactly len(script) API calls.
    assert len(orch.events) == len(script)


def test_orchestrator_returns_error_results_on_bad_source() -> None:
    """An instinct source missing justification must come back as an is_error result, NOT crash."""
    builder = GoCamBuilder(model_id="gomodel:test-002", title="bad source test")
    script = [
        _response(
            _tool_use("tu1", "add_activity",
                      local_part="X",
                      enabled_by_gene="WB:Z",
                      source={"source_type": "instinct"}),
        ),
        # The agent "sees" the error and retries with proper justification.
        _response(
            _tool_use("tu2", "add_activity",
                      local_part="X",
                      enabled_by_gene="WB:Z",
                      source={"source_type": "instinct", "justification": "figure shows it"}),
        ),
        _response(_tool_use("tu3", "finalize_model")),
    ]
    orch = Orchestrator(
        builder=builder, client=_ScriptedClient(script),
        model_name="claude-sonnet-4-6@default", max_turns=10,
    )
    model, ledger = orch.run(_make_intent())

    # First call should have been wired back as an is_error tool_result.
    tool_result_msg = orch.client.calls[1]["messages"][-1]
    assert tool_result_msg["role"] == "user"
    first_result = tool_result_msg["content"][0]
    assert first_result["tool_use_id"] == "tu1"
    assert first_result.get("is_error") is True

    # The second attempt should have succeeded.
    assert len(model.activities or []) == 1
    assert ledger.count_by_source_type() == {"instinct": 1}


def test_orchestrator_raises_on_runaway() -> None:
    builder = GoCamBuilder(model_id="gomodel:test-003", title="runaway test")
    # The mock keeps emitting tool_use indefinitely (well, we only stock 3 responses).
    script = [
        _response(_tool_use(f"tu{i}", "go_term_lookup", term_id="GO:0008150"))
        for i in range(3)
    ]
    orch = Orchestrator(
        builder=builder, client=_ScriptedClient(script),
        model_name="claude-sonnet-4-6@default", max_turns=3,
    )
    with pytest.raises(RuntimeError, match="max_turns"):
        orch.run(_make_intent())


# --------------------------------------------------------- live test (gated)


@pytest.mark.skipif(
    not (_HAS_VERTEX and FIGURE_1.is_file()),
    reason="requires Vertex creds + inputs/figure1-...png",
)
@pytest.mark.skipif(
    not os.environ.get("GOCAM_RUN_LIVE_TESTS"),
    reason="set GOCAM_RUN_LIVE_TESTS=1 to run the live end-to-end orchestration",
)
def test_live_end_to_end_on_figure_1() -> None:
    """End-to-end: vision pass on figure 1 → orchestrator → built model. Expensive."""
    from gocam_prototype.vision import extract_curator_intent

    intent = extract_curator_intent(FIGURE_1, species_hint="Caenorhabditis elegans")
    builder = GoCamBuilder(
        model_id="gomodel:e2e-figure1",
        title="E2E test: C. elegans serotonin/octopamine -> intestinal fat loss",
        taxon="NCBITaxon:6239",
    )
    model, ledger = orchestrate(intent, builder, max_turns=80)
    assert (model.activities or []), "agent did not create any activities"
    # No fabricated PMIDs: every literature source_id must look like a real PMID.
    for src in ledger.assertions.values():
        if src.source_type == "literature":
            assert src.source_id and src.source_id.startswith(("PMID:", "DOI:", "GO_REF:"))
        if src.source_type == "instinct":
            assert src.justification and src.justification.strip()
