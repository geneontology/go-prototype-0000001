"""Tests for the provenance sidecar schema and convenience constructors."""

from __future__ import annotations

import json

import pytest

from gocam_prototype.provenance import (
    ProvenanceLedger,
    SourceObject,
    alliance,
    amigo,
    expert_review,
    figure,
    go_annotation,
    instinct,
    literature,
    orthology,
    pathway_resource,
)


def test_literature_source_requires_id() -> None:
    s = literature(pmid="PMID:12345678", snippet="Figure 2 shows…")
    assert s.source_type == "literature"
    assert s.source_id == "PMID:12345678"

    with pytest.raises(Exception):
        SourceObject(source_type="literature")


def test_instinct_requires_justification() -> None:
    s = instinct(justification="No evidence in GO; figure clearly shows the arrow.")
    assert s.source_type == "instinct"
    assert s.justification

    with pytest.raises(Exception):
        instinct(justification="   ")
    with pytest.raises(Exception):
        SourceObject(source_type="instinct")


def test_go_annotation_source_is_typed() -> None:
    s = go_annotation(source_id="GO:0042427", snippet="Annotated to gene", tool_name="go_api.gene_annotations")
    assert s.source_type == "go_annotation"
    assert s.source_id == "GO:0042427"
    assert s.tool_name == "go_api.gene_annotations"


def test_alliance_source_is_typed() -> None:
    s = alliance(source_id="WB:WBGene00006600", tool_name="alliance.resolve_symbol_to_curie")
    assert s.source_type == "alliance"
    assert s.source_id == "WB:WBGene00006600"


def test_amigo_source_is_typed() -> None:
    s = amigo(source_id="WB:WBGene00006600", tool_name="golr.annotations_for_gene")
    assert s.source_type == "amigo"
    assert s.source_id == "WB:WBGene00006600"


def test_orthology_carries_species_and_origin_in_extra() -> None:
    s = orthology(
        ortholog_curie="HGNC:17431",
        ortholog_species="Homo sapiens",
        from_annotation="GO:0004806",
        snippet="Human PNPLA2 has the experimental annotation; transferred.",
    )
    assert s.source_type == "orthology"
    assert s.source_id == "HGNC:17431"
    assert s.extra == {"ortholog_species": "Homo sapiens", "from_annotation": "GO:0004806"}


def test_pathway_resource_carries_resource_in_extra() -> None:
    s = pathway_resource(
        resource="Reactome",
        source_id="R-HSA-163560",
        pathway_url="https://reactome.org/PathwayBrowser/#/R-HSA-163560",
    )
    assert s.source_type == "pathway_resource"
    assert s.extra == {
        "resource": "Reactome",
        "pathway_url": "https://reactome.org/PathwayBrowser/#/R-HSA-163560",
    }


def test_expert_review_carries_orcid_in_extra() -> None:
    s = expert_review(
        source_id="curator-note-001",
        orcid="0000-0001-0000-0000",
        contributor_name="Test Curator",
    )
    assert s.source_type == "expert_review"
    assert s.extra == {"orcid": "0000-0001-0000-0000", "contributor_name": "Test Curator"}


def test_ledger_serializes() -> None:
    ledger = ProvenanceLedger(model_id="gomodel:test-0001")
    ledger.attach("gomodel:test-0001/A/molecular_function",
                  literature(pmid="PMID:1", snippet="..."))
    ledger.attach("gomodel:test-0001/A/causal/gomodel:test-0001/B",
                  instinct(justification="figure shows arrow only"))

    blob = json.loads(ledger.model_dump_json(exclude_none=True))
    assert blob["model_id"] == "gomodel:test-0001"
    assert set(blob["assertions"].keys()) == {
        "gomodel:test-0001/A/molecular_function",
        "gomodel:test-0001/A/causal/gomodel:test-0001/B",
    }

    # Round-trip back through the model.
    reloaded = ProvenanceLedger.model_validate(blob)
    assert reloaded.count_by_source_type() == {"literature": 1, "instinct": 1}


def test_figure_source_requires_snippet() -> None:
    s = figure(snippet="Arrow from 5-HT neuron to intestine", source_id="transcription.md")
    assert s.source_type == "figure"
    assert s.snippet.startswith("Arrow")
    # No source_id is fine — the figure itself is the source.
    assert figure(snippet="bare arrow, no label").source_id is None
    # …but an empty snippet is not.
    with pytest.raises(Exception):
        SourceObject(source_type="figure", snippet="   ")
    with pytest.raises(Exception):
        SourceObject(source_type="figure")


def test_attach_appends_multiple_sources_per_key() -> None:
    """v2: one assertion key can carry several distinct claims (#40)."""
    ledger = ProvenanceLedger(model_id="gomodel:test-0002")
    key = "gomodel:test-0002/A/enabled_by"
    ledger.attach(key, figure(snippet="gene box labelled tph-1"))
    ledger.attach(key, alliance(source_id="WB:WBGene00006600", tool_name="resolve_symbol"))
    assert len(ledger.assertions[key]) == 2
    assert [s.source_type for s in ledger.assertions[key]] == ["figure", "alliance"]
    assert ledger.count_by_source_type() == {"figure": 1, "alliance": 1}


def test_attach_dedups_exact_duplicates() -> None:
    ledger = ProvenanceLedger(model_id="gomodel:test-0003")
    key = "gomodel:test-0003/A/molecular_function"
    ledger.attach(key, go_annotation(source_id="GO:0004871"))
    ledger.attach(key, go_annotation(source_id="GO:0004871"))  # exact dup → skipped
    ledger.attach(key, go_annotation(source_id="GO:0004871", snippet="differs"))  # kept
    assert len(ledger.assertions[key]) == 2


def test_ledger_version_is_two() -> None:
    assert ProvenanceLedger(model_id="gomodel:x").version == 2
