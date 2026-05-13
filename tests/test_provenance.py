"""Tests for the provenance sidecar schema and convenience constructors."""

from __future__ import annotations

import json

import pytest

from gocam_prototype.provenance import (
    ProvenanceLedger,
    SourceObject,
    amigo,
    database,
    instinct,
    literature,
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


def test_database_source_is_typed() -> None:
    s = database(source_id="GO:0042427", snippet="Annotated to gene", tool_name="go_api.gene_annotations")
    assert s.source_type == "database"
    assert s.source_id == "GO:0042427"
    assert s.tool_name == "go_api.gene_annotations"


def test_amigo_source_is_typed() -> None:
    s = amigo(source_id="WB:WBGene00006600", tool_name="golr.annotations_for_gene")
    assert s.source_type == "amigo"
    assert s.source_id == "WB:WBGene00006600"


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
