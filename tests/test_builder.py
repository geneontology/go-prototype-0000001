"""Tests for the gocam-py builder."""

from __future__ import annotations

import json

import pytest
import yaml
from gocam.datamodel import Model

from gocam_prototype.builder import GoCamBuilder, write_model_and_ledger
from gocam_prototype.provenance import (
    alliance,
    figure,
    go_annotation,
    instinct,
    literature,
    orthology,
)


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


def test_evidence_minted_for_db_sources_not_for_flagged_tiers() -> None:
    """Database-backed / literature sources mint a real LinkML EvidenceItem (#52);
    the deliberately-unverified tiers (figure/instinct) stay sidecar-only, and a
    fabricated ECO:0000314 is never emitted."""
    import yaml

    b, aid_a, _ = _build_two_activity_model()
    model, _ = b.build()
    act_a = next(a for a in model.activities if a.id == aid_a)

    # enabled_by used an alliance source with no GAF code -> EvidenceItem with the
    # unknown-evidence ECO root, NEVER a fabricated direct-assay ECO:0000314.
    assert act_a.enabled_by.evidence
    assert act_a.enabled_by.evidence[0].term == "ECO:0000000"
    # part_of used a go_annotation source -> now gets an EvidenceItem too.
    assert act_a.part_of.evidence
    # occurs_in used instinct -> NO gocam evidence (flagged tier; sidecar only).
    assert act_a.occurs_in.evidence in (None, [])
    # molecular_function used literature -> evidence carries the PMID reference.
    assert act_a.molecular_function.evidence
    assert act_a.molecular_function.evidence[0].reference == "PMID:111"
    # No fabricated direct-assay code anywhere in the model.
    assert "ECO:0000314" not in yaml.safe_dump(model.model_dump(exclude_none=True, mode="json"))


def test_go_annotation_evidence_code_maps_to_eco_with_reference() -> None:
    """A go_annotation source carrying a real GAF code + reference lands as a
    correct EvidenceItem(term=<ECO>, reference=<PMID/GO_REF>) with the ECO label
    in objects[] (#52 pts 1,2,3)."""
    b = GoCamBuilder(model_id="gomodel:ev", title="ev", contributor_orcid="ORCID:0000-0002-1234")
    aid = b.add_activity("a", enabled_by_gene="WB:WBGene1",
                         enabled_by_source=alliance(source_id="WB:WBGene1"))
    b.set_molecular_function(aid, "GO:0004510",
        source=go_annotation(source_id="GO:0004510", evidence_code="IBA",
                             reference="GO_REF:0000033", term_label="tryptophan 5-monooxygenase activity",
                             tool_name="go_api.gene_annotations"),
        label="tryptophan 5-monooxygenase activity")
    model, _ = b.build()
    act = next(a for a in model.activities if a.id == aid)
    ev = act.molecular_function.evidence[0]
    assert ev.term == "ECO:0000318"            # IBA
    assert ev.reference == "GO_REF:0000033"
    assert ev.provenances[0].contributor == ["ORCID:0000-0002-1234"]
    objs = {o.id: o.label for o in model.objects}
    assert objs["ECO:0000318"] == "biological aspect of ancestor evidence used in manual assertion"


def test_orthology_evidence_has_iss_and_with_objects() -> None:
    b = GoCamBuilder(model_id="gomodel:o", title="o")
    aid = b.add_activity("a", enabled_by_gene="WB:WBGene1",
                         enabled_by_source=alliance(source_id="WB:WBGene1"))
    b.set_part_of(aid, "GO:0042427",
        source=orthology(ortholog_curie="HGNC:11178", ortholog_species="Homo sapiens",
                         from_annotation="GO:0042427"))
    model, _ = b.build()
    ev = next(a for a in model.activities if a.id == aid).part_of.evidence[0]
    assert ev.term == "ECO:0000250"            # orthology defaults to ISS -> ECO:0000250
    assert ev.reference == "GO_REF:0000024"
    assert "HGNC:11178" in (ev.with_objects or [])


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
    # part_of's primary go_annotation now also mints evidence, so the added
    # literature evidence is appended — assert it's present, not the only one.
    assert "PMID:999" in refs


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


def test_add_input_output_molecular_associations() -> None:
    """has_input/has_output land in molecular_associations with the right RO
    predicate, ChEBI vs gene-product term kind, and per-molecule ledger keys."""
    from gocam.datamodel import Model

    b, aid_a, _ = _build_two_activity_model()
    k_in = b.add_input(aid_a, "CHEBI:28815",
                       source=figure(snippet="pyocyanin drawn entering the cell"),
                       label="pyocyanin")
    k_tgt = b.add_input(aid_a, "WB:WBGene00000001",
                        source=literature(pmid="PMID:1"), molecule_kind="gene_product",
                        label="target gene")
    k_out = b.add_output(aid_a, "CHEBI:350546",
                         source=literature(pmid="PMID:2"), label="serotonin")
    assert k_in == f"{aid_a}/has_input/CHEBI:28815"
    assert k_out == f"{aid_a}/has_output/CHEBI:350546"

    model, ledger = b.build()
    act = next(a for a in model.activities if a.id == aid_a)
    ma = [(m.predicate, m.molecule) for m in (act.molecular_associations or [])]
    assert ("RO:0002233", "CHEBI:28815") in ma
    assert ("RO:0002233", "WB:WBGene00000001") in ma
    assert ("RO:0002234", "CHEBI:350546") in ma
    # All three keys recorded in the sidecar.
    assert {k_in, k_tgt, k_out} <= set(ledger.assertions.keys())
    # The ChEBI molecule is typed as a molecule term object; the model validates.
    Model.model_validate(model.model_dump(exclude_none=True, mode="json"))
    obj_kinds = {o.id: type(o).__name__ for o in model.objects}
    assert obj_kinds["CHEBI:28815"] == "MoleculeTermObject"
    assert obj_kinds["WB:WBGene00000001"] == "GeneProductTermObject"


def test_add_activator_inhibitor_molecular_associations() -> None:
    """A receptor/channel ligand lands as has small molecule activator|inhibitor
    (RO:0012001/0012002), ChEBI-typed, with a per-molecule ledger key (#53)."""
    b, aid_a, aid_b = _build_two_activity_model()
    # aid_b is the ligand-gated channel; octopamine/serotonin activate it.
    k_act = b.add_activator(aid_b, "CHEBI:17234",
                            source=figure(snippet="serotonin drawn opening the channel"),
                            label="serotonin")
    k_inh = b.add_inhibitor(aid_b, "CHEBI:16236",
                            source=literature(pmid="PMID:9"), label="ethanol")
    assert k_act == f"{aid_b}/has_small_molecule_activator/CHEBI:17234"
    assert k_inh == f"{aid_b}/has_small_molecule_inhibitor/CHEBI:16236"

    model, ledger = b.build()
    act = next(a for a in model.activities if a.id == aid_b)
    ma = [(m.predicate, m.molecule) for m in (act.molecular_associations or [])]
    assert ("RO:0012001", "CHEBI:17234") in ma
    assert ("RO:0012002", "CHEBI:16236") in ma
    assert {k_act, k_inh} <= set(ledger.assertions.keys())
    Model.model_validate(model.model_dump(exclude_none=True, mode="json"))
    obj_kinds = {o.id: type(o).__name__ for o in model.objects}
    assert obj_kinds["CHEBI:17234"] == "MoleculeTermObject"
    # The relation labels are remembered for the viewer.
    labels = {o.id: o.label for o in model.objects}
    assert labels["RO:0012001"] == "has small molecule activator"


def test_add_input_rejects_bad_kind_and_missing_activity() -> None:
    b, aid_a, _ = _build_two_activity_model()
    with pytest.raises(ValueError):
        b.add_input(aid_a, "CHEBI:1", source=figure(snippet="x"), molecule_kind="chemical")
    with pytest.raises(ValueError):
        b.add_input("gomodel:test/none", "CHEBI:1", source=figure(snippet="x"))


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
