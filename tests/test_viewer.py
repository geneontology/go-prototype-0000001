"""Tests for the gocam-py -> bbop-graph viewer-JSON translator.

We build a small synthetic model with `GoCamBuilder`, run it through the
translator, and verify the output:

* Top-level keys match the bbop "active model" shape (id, individuals,
  facts, annotations).
* Every CURIE used in the model produces an individual with the right
  root-type (so the viewer picks a sane glyph).
* Causal edges in `Activity.causal_associations` become facts.
* Each fact carries the right `property` and `subject`/`object` pair.
* Evidence is materialized as its own ECO-typed individuals, referenced by
  fact annotations of type "evidence".
* Translator output is deterministic — same model in, same JSON out.
"""

from __future__ import annotations

import json
from pathlib import Path

from gocam_prototype.builder import GoCamBuilder
from gocam_prototype.provenance import literature
from gocam_prototype.viewer import linkml_to_viewer_json

FIXTURES = Path(__file__).parent / "fixtures"


def _build_demo_model():
    b = GoCamBuilder(
        model_id="gomodel:viewer-test-0001",
        title="viewer test: tph-1 → mod-1",
        taxon="NCBITaxon:6239",
    )
    a = b.add_activity(
        "tph1",
        enabled_by_gene="WB:WBGene00006600",
        enabled_by_source=literature(pmid="PMID:111", snippet="IDA"),
        gene_label="tph-1",
    )
    b.set_molecular_function(
        a, "GO:0004510",
        source=literature(pmid="PMID:111"),
        label="tryptophan 5-monooxygenase activity",
    )
    b.set_part_of(
        a, "GO:0042427",
        source=literature(pmid="PMID:111"),
        label="serotonin biosynthetic process",
    )
    b.set_occurs_in(
        a, "CL:0000540",
        source=literature(pmid="PMID:111"),
        label="neuron",
    )

    c = b.add_activity(
        "mod1",
        enabled_by_gene="WB:WBGene00003185",
        enabled_by_source=literature(pmid="PMID:222"),
        gene_label="mod-1",
    )
    b.set_molecular_function(
        c, "GO:0005230",
        source=literature(pmid="PMID:222"),
        label="extracellular ligand-gated ion channel activity",
    )

    b.add_causal(
        a, c,
        predicate="RO:0002629",
        source=literature(pmid="PMID:333"),
        predicate_label="directly positively regulates",
    )
    return b.build()


def test_top_level_shape() -> None:
    model, _ = _build_demo_model()
    out = linkml_to_viewer_json(model)
    assert set(out.keys()) == {"id", "individuals", "facts", "annotations"}
    assert out["id"] == model.id


def test_individuals_have_root_types() -> None:
    model, _ = _build_demo_model()
    out = linkml_to_viewer_json(model)
    by_id = {ind["id"]: ind for ind in out["individuals"]}

    # Activity IRIs themselves should be molecular_function instances.
    for act in model.activities:
        assert by_id[act.id]["type"][0]["id"] == act.molecular_function.term
        assert by_id[act.id]["root-type"][0]["id"] == "GO:0003674"

    # The /enabled_by individual should have the gene-product root-type.
    a_id = f"gomodel:viewer-test-0001/tph1/enabled_by"
    assert by_id[a_id]["type"][0]["id"] == "WB:WBGene00006600"
    assert by_id[a_id]["type"][0]["label"] == "tph-1"  # picked up from objects[]
    assert by_id[a_id]["root-type"][0]["id"] == "CHEBI:33695"


def test_facts_wire_causal_edge_with_predicate() -> None:
    model, _ = _build_demo_model()
    out = linkml_to_viewer_json(model)
    facts = out["facts"]

    activity_a = "gomodel:viewer-test-0001/tph1"
    activity_b = "gomodel:viewer-test-0001/mod1"

    causal = [f for f in facts if f["property"] == "RO:0002629"]
    assert len(causal) == 1
    assert causal[0]["subject"] == activity_a
    assert causal[0]["object"] == activity_b
    # Predicate label resolved from objects[]
    assert causal[0]["property-label"] == "directly positively regulates"


def test_evidence_individuals_attached_to_facts() -> None:
    model, _ = _build_demo_model()
    out = linkml_to_viewer_json(model)
    by_id = {ind["id"]: ind for ind in out["individuals"]}

    # The enabled_by fact should reference an ECO-typed individual.
    enabled_by_facts = [f for f in out["facts"] if f["property"] == "RO:0002333"]
    assert enabled_by_facts
    ev_anns = [a for a in enabled_by_facts[0]["annotations"] if a["key"] == "evidence"]
    assert ev_anns
    ev_iri = ev_anns[0]["value"]
    assert ev_anns[0]["value-type"] == "IRI"
    assert by_id[ev_iri]["type"][0]["id"].startswith("ECO:")

    # And the ECO individual's annotations include the source PMID.
    src_anns = [a for a in by_id[ev_iri]["annotations"] if a["key"] == "source"]
    assert src_anns[0]["value"] == "PMID:111"


def test_model_level_annotations() -> None:
    model, _ = _build_demo_model()
    out = linkml_to_viewer_json(model)
    keys = [a["key"] for a in out["annotations"]]
    assert "title" in keys
    assert "https://w3id.org/biolink/vocab/in_taxon" in keys
    assert "state" in keys


def test_translator_is_deterministic() -> None:
    """Same model in, byte-identical JSON out — required for snapshot tests
    and for the static viewer page's stable IRIs."""
    model, _ = _build_demo_model()
    a = json.dumps(linkml_to_viewer_json(model), sort_keys=True)
    b = json.dumps(linkml_to_viewer_json(model), sort_keys=True)
    assert a == b


def test_fixture_real_gocam_has_same_top_level_shape() -> None:
    """Sanity check: a real published GO-CAM matches the shape our translator emits."""
    real = json.loads((FIXTURES / "go_cam_model.json").read_text())
    assert set(real.keys()) >= {"id", "individuals", "facts", "annotations"}
    # `facts` use the same field names.
    assert {"subject", "property", "object"} <= set(real["facts"][0].keys())


def test_occurs_in_cell_type_extension_renders_node_and_fact() -> None:
    """The occurs_in cell-type extension (#54) becomes its own CL individual
    (root-type 'cell') linked to the CC individual by a BFO:0000050 fact."""
    from gocam_prototype.provenance import figure, go_annotation

    b = GoCamBuilder(model_id="gomodel:ct-test-0001", title="ct", taxon="NCBITaxon:6239")
    a = b.add_activity("tph1", enabled_by_gene="WB:WBGene00006600",
                       enabled_by_source=literature(pmid="PMID:1"), gene_label="tph-1")
    b.set_molecular_function(a, "GO:0004510", source=literature(pmid="PMID:1"),
                             label="tryptophan 5-monooxygenase activity")
    b.set_occurs_in(a, "GO:0043005",
                    source=go_annotation(source_id="GO:0043005",
                                         tool_name="go_api.gene_annotations"),
                    label="neuron projection",
                    cell_type="CL:0000540", cell_type_label="neuron",
                    cell_type_source=figure(snippet="neuron box"))
    model, _ = b.build()
    out = linkml_to_viewer_json(model)
    by_id = {ind["id"]: ind for ind in out["individuals"]}

    cc_iri = f"{a}/occurs_in"
    ct_iri = f"{a}/occurs_in/cell_type"
    assert by_id[ct_iri]["type"][0]["id"] == "CL:0000540"
    assert by_id[ct_iri]["type"][0]["label"] == "neuron"
    assert by_id[ct_iri]["root-type"][0]["id"] == "CL:0000000"
    # The CC -> cell-type "part of" fact ties them together.
    assert any(f["subject"] == cc_iri and f["property"] == "BFO:0000050"
               and f["object"] == ct_iri for f in out["facts"])
