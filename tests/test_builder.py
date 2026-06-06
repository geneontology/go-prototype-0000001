"""Tests for the gocam-py builder."""

from __future__ import annotations

import json

import pytest
import yaml
from gocam.datamodel import Model

from gocam_prototype.builder import GoCamBuilder, write_model_and_ledger
from gocam_prototype.provenance import alliance, figure, go_annotation, instinct, literature


def _build_two_activity_model() -> tuple[GoCamBuilder, str, str]:
    b = GoCamBuilder(
        model_id="gomodel:test-tph1-mod1-0001",
        title="Test: tph-1 → mod-1 (serotonin signaling)",
        taxon="NCBITaxon:6239",
    )
    aid_a = b.add_activity(
        "act-A",
        enabled_by_gene="WB:WBGene00006600",
        enabled_by_source=alliance(source_id="WB:WBGene00006600",
                                   tool_name="alliance.resolve_symbol_to_curie"),
        gene_label="tph-1",
    )
    b.set_molecular_function(aid_a, "GO:0004510",
                             source=literature(pmid="PMID:111", snippet="IDA"),
                             label="tryptophan 5-monooxygenase activity")
    b.set_part_of(aid_a, "GO:0042427",
                  source=go_annotation(source_id="GO:0042427",
                                       tool_name="go_api.gene_annotations"),
                  label="serotonin biosynthetic process")
    b.set_occurs_in(aid_a, "CL:0000540",
                    source=instinct(justification="figure labels neurons; CL:0000540 is the canonical neuron CL term"),
                    label="neuron")

    aid_b = b.add_activity(
        "act-B",
        enabled_by_gene="WB:WBGene00003185",
        enabled_by_source=alliance(source_id="WB:WBGene00003185",
                                   tool_name="alliance.resolve_symbol_to_curie"),
        gene_label="mod-1",
    )
    b.set_molecular_function(aid_b, "GO:0005230",
                             source=literature(pmid="PMID:222", snippet="electrophysiology"),
                             label="extracellular ligand-gated ion channel activity")

    b.add_causal(aid_a, aid_b,
                 predicate="RO:0002629",
                 source=literature(pmid="PMID:333",
                                   snippet="tph-1 activity required for mod-1-dependent response"),
                 predicate_label="directly positively regulates")
    return b, aid_a, aid_b


def test_builder_constructs_validating_model() -> None:
    b, aid_a, aid_b = _build_two_activity_model()
    model, ledger = b.build()

    # Model itself must round-trip through pydantic validation.
    dumped = model.model_dump(exclude_none=True, mode="json")
    Model.model_validate(dumped)

    # Both activities present, in declaration order.
    ids = [a.id for a in model.activities or []]
    assert ids == [aid_a, aid_b]

    # objects[] populated for genes, MFs, BPs, CCs, predicates, PMIDs, taxon.
    obj_ids = {o.id for o in model.objects or []}
    assert {
        "WB:WBGene00006600",  # tph-1
        "WB:WBGene00003185",  # mod-1
        "GO:0004510",
        "GO:0005230",
        "GO:0042427",
        "CL:0000540",
        "RO:0002629",
        "PMID:111",
        "PMID:222",
        "PMID:333",
        "NCBITaxon:6239",
    } <= obj_ids


def test_builder_ledger_has_all_assertions() -> None:
    b, aid_a, aid_b = _build_two_activity_model()
    _, ledger = b.build()
    keys = set(ledger.assertions.keys())
    assert keys == {
        f"{aid_a}/enabled_by",
        f"{aid_a}/molecular_function",
        f"{aid_a}/part_of",
        f"{aid_a}/occurs_in",
        f"{aid_b}/enabled_by",
        f"{aid_b}/molecular_function",
        f"{aid_a}/causal/{aid_b}",
    }
    # Source-type mix reflects the test data.
    counts = ledger.count_by_source_type()
    assert counts == {"alliance": 2, "go_annotation": 1, "literature": 3, "instinct": 1}


def test_evidence_only_attached_for_literature() -> None:
    """Non-literature sources must NOT synthesize an EvidenceItem into the
    canonical gocam model; their provenance lives in the sidecar only."""
    b, aid_a, _ = _build_two_activity_model()
    model, _ = b.build()
    act_a = next(a for a in model.activities if a.id == aid_a)

    # enabled_by used a database source -> no gocam evidence.
    assert act_a.enabled_by.evidence in (None, [])
    # part_of used a database source -> no gocam evidence.
    assert act_a.part_of.evidence in (None, [])
    # occurs_in used instinct -> no gocam evidence.
    assert act_a.occurs_in.evidence in (None, [])
    # molecular_function used literature -> has gocam evidence.
    assert act_a.molecular_function.evidence
    assert act_a.molecular_function.evidence[0].reference == "PMID:111"


def test_add_source_layers_extra_claim_on_a_slot() -> None:
    """add_source attaches a second, separately-attributed claim to an existing
    assertion — e.g. figure-shown gene box + Alliance id resolution (#40)."""
    b, aid_a, aid_b = _build_two_activity_model()
    key = b.add_source(
        aid_a, "enabled_by",
        figure(snippet="box labelled tph-1 in the 5-HT neuron"),
    )
    assert key == f"{aid_a}/enabled_by"
    srcs = b._ledger.assertions[key]  # noqa: SLF001
    assert [s.source_type for s in srcs] == ["alliance", "figure"]


def test_add_source_literature_appends_evidence_item() -> None:
    """A literature extra source also lands in the gocam association's evidence
    list (associations may carry several EvidenceItems)."""
    b, aid_a, _ = _build_two_activity_model()
    # part_of's primary source was a go_annotation -> no evidence yet.
    b.add_source(
        aid_a, "part_of",
        literature(pmid="PMID:999", snippet="serotonin biosynthesis shown directly"),
    )
    model, _ = b.build()
    act_a = next(a for a in model.activities if a.id == aid_a)
    refs = [e.reference for e in (act_a.part_of.evidence or [])]
    assert refs == ["PMID:999"]


def test_add_source_causal_requires_existing_edge() -> None:
    b, aid_a, aid_b = _build_two_activity_model()
    # Valid: the A->B edge exists.
    key = b.add_source(
        aid_a, "causal",
        instinct(justification="figure arrow corroborates the regulation"),
        target_activity_id=aid_b,
    )
    assert key == f"{aid_a}/causal/{aid_b}"
    # Invalid: no edge B->A.
    with pytest.raises(ValueError):
        b.add_source(aid_b, "causal", instinct(justification="x"), target_activity_id=aid_a)


def test_add_source_rejects_unset_slot_and_bad_slot() -> None:
    b, _, aid_b = _build_two_activity_model()
    # act-B never had occurs_in set.
    with pytest.raises(ValueError):
        b.add_source(aid_b, "occurs_in", figure(snippet="x"))
    with pytest.raises(ValueError):
        b.add_source(aid_b, "not_a_slot", figure(snippet="x"))


def test_write_model_and_ledger(tmp_path) -> None:
    b, _, _ = _build_two_activity_model()
    model, ledger = b.build()
    model_path, ledger_path = write_model_and_ledger(model, ledger, tmp_path / "run-001")

    assert model_path.name == "model.yaml"
    assert ledger_path.name == "provenance.json"

    loaded_model = yaml.safe_load(model_path.read_text())
    assert loaded_model["id"] == b.model_id
    assert isinstance(loaded_model["activities"], list)

    loaded_ledger = json.loads(ledger_path.read_text())
    assert loaded_ledger["model_id"] == b.model_id
