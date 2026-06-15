"""Tests for the curation-plan (framing) pass. The LLM call is not exercised
here (that needs the live API); these cover the schema + rendering + injection."""

from __future__ import annotations

from gocam_prototype.builder import GoCamBuilder
from gocam_prototype.orchestrator import Orchestrator
from gocam_prototype.planning import CurationPlan, GenePlan, MoleculePlan, render_plan
from gocam_prototype.vision import CuratorIntent


def _sample_plan() -> CurationPlan:
    return CurationPlan(
        pathway_summary="A test pathway.",
        genes=[
            GenePlan(symbol="ser-6", mf_class="signaling_receptor", note="octopamine GPCR"),
            GenePlan(symbol="tbh-1", mf_class="enzyme", note="makes octopamine"),
        ],
        molecules=[
            MoleculePlan(label="octopamine", role="direct_activator", acts_on="ser-6",
                         directness_note="binds the GPCR"),
            MoleculePlan(label="pyocyanin", role="upstream_stimulus", acts_on=None,
                         directness_note="pathogen toxin sensed upstream, not a direct ligand"),
        ],
    )


def test_render_plan_includes_classes_roles_and_hints() -> None:
    text = render_plan(_sample_plan())
    # MF-classes surface per gene.
    assert "ser-6: signaling_receptor" in text
    assert "tbh-1: enzyme" in text
    # A direct activator routes to add_activator with its target; the directness
    # note rides along.
    assert "octopamine" in text and "add_activator (RO:0012001)" in text
    assert "[ser-6]" in text
    # An upstream stimulus is explicitly steered AWAY from a direct activator.
    assert "pyocyanin" in text
    assert "NOT a direct activator" in text


def test_curation_plan_text_injected_into_initial_message() -> None:
    o = Orchestrator(
        builder=GoCamBuilder(model_id="gomodel:x", title="x"),
        client=None, model_name="claude-opus-4-8",
        curation_plan_text="CURATION PLAN: do the thing",
    )
    msg = o._initial_user_message(CuratorIntent(species="C. elegans"))
    assert "CURATION PLAN: do the thing" in msg


def test_cellular_context_block_empty_without_grounding() -> None:
    # Offline (no GOCAM_RUN_LIVE_TESTS), resolve_cell_type returns None, so the
    # block is empty rather than guessing — and the initial message still builds.
    from gocam_prototype.vision import Compartment

    o = Orchestrator(
        builder=GoCamBuilder(model_id="gomodel:x", title="x", taxon="NCBITaxon:6239"),
        client=None, model_name="claude-opus-4-8",
    )
    intent = CuratorIntent(
        species="C. elegans",
        compartments=[Compartment(label="Intestinal cell", kind="cell_type",
                                  confidence=0.9, snippet="box")],
    )
    assert o._cellular_context_block(intent) == ""
