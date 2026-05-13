"""Hand-crafted demo GO-CAM for the static viewer page.

This is NOT the agent's output — it's a deterministic artifact that mirrors
figure 1 (C. elegans serotonin/octopamine → intestinal fat loss) and lets us
wire up the static viewer page (issue #10) without burning Vertex tokens on
every iteration. Once the GH Actions workflow (issue #11) is in place,
real agent runs land in the same `docs/runs/<run-id>/` layout.

Run with:

    uv run python -m gocam_prototype.demo
"""

from __future__ import annotations

import json
from pathlib import Path

from gocam_prototype.builder import GoCamBuilder, write_model_and_ledger
from gocam_prototype.provenance import database, instinct, literature
from gocam_prototype.viewer import linkml_to_viewer_json


def build_demo(out_dir: Path) -> dict:
    b = GoCamBuilder(
        model_id="gomodel:demo-celegans-fat-loss",
        title="Demo: C. elegans serotonin/octopamine → intestinal fat loss (figure 1, hand-built)",
        taxon="NCBITaxon:6239",
    )

    # tph-1: tryptophan hydroxylase in neurons.
    tph1 = b.add_activity(
        "tph1",
        enabled_by_gene="WB:WBGene00006600",
        enabled_by_source=database(
            source_id="WB:WBGene00006600",
            tool_name="alliance.resolve_symbol_to_curie",
            snippet="tph-1 resolved via Alliance gene search",
        ),
        gene_label="tph-1",
    )
    b.set_molecular_function(
        tph1, "GO:0004510",
        source=database(
            source_id="GO:0004510",
            tool_name="go_api.gene_annotations",
            snippet="Existing GO annotation: tryptophan 5-monooxygenase activity, IDA",
        ),
        label="tryptophan 5-monooxygenase activity",
    )
    b.set_part_of(
        tph1, "GO:0042427",
        source=database(
            source_id="GO:0042427",
            tool_name="go_api.gene_annotations",
            snippet="Existing GO annotation: serotonin biosynthetic process",
        ),
        label="serotonin biosynthetic process",
    )
    b.set_occurs_in(
        tph1, "CL:0000540",
        source=instinct(
            justification="Figure 1 panel E places tph-1 inside the labeled NEURONS box; CL:0000540 (neuron) is the canonical cell-type term.",
        ),
        label="neuron",
    )

    # mod-1: serotonin-gated chloride channel in neurons.
    mod1 = b.add_activity(
        "mod1",
        enabled_by_gene="WB:WBGene00003533",
        enabled_by_source=database(
            source_id="WB:WBGene00003533",
            tool_name="alliance.resolve_symbol_to_curie",
        ),
        gene_label="mod-1",
    )
    b.set_molecular_function(
        mod1, "GO:0022824",
        source=literature(
            pmid="PMID:11099056",
            snippet="Ranganathan, Cannon & Horvitz 2000 — mod-1 encodes a serotonin-gated chloride channel.",
            tool_name="europepmc.search",
        ),
        label="transmitter-gated monoatomic ion channel activity",
    )
    b.set_occurs_in(
        mod1, "CL:0000540",
        source=instinct(
            justification="Figure shows mod-1 in the NEURONS box alongside tph-1.",
        ),
        label="neuron",
    )

    # nhr-76: nuclear hormone receptor in intestine.
    nhr76 = b.add_activity(
        "nhr76",
        enabled_by_gene="WB:WBGene00003640",
        enabled_by_source=database(
            source_id="WB:WBGene00003640",
            tool_name="alliance.resolve_symbol_to_curie",
        ),
        gene_label="nhr-76",
    )
    b.set_molecular_function(
        nhr76, "GO:0004879",
        source=database(
            source_id="GO:0004879",
            tool_name="go_api.gene_annotations",
            snippet="Existing GO annotation: nuclear receptor transcription factor activity",
        ),
        label="nuclear receptor activity",
    )
    b.set_part_of(
        nhr76, "GO:0006357",
        source=database(
            source_id="GO:0006357",
            tool_name="go_api.gene_annotations",
            snippet="Existing GO annotation: regulation of transcription by RNA polymerase II",
        ),
        label="regulation of transcription by RNA polymerase II",
    )
    b.set_occurs_in(
        nhr76, "CL:0000584",
        source=instinct(
            justification="Figure shows nhr-76 inside the labeled INTESTINE compartment; CL:0000584 (enterocyte) is the canonical intestinal cell-type term.",
        ),
        label="enterocyte",
    )

    # atgl-1: adipose triglyceride lipase in intestine.
    atgl1 = b.add_activity(
        "atgl1",
        enabled_by_gene="WB:WBGene00010532",
        enabled_by_source=database(
            source_id="WB:WBGene00010532",
            tool_name="alliance.resolve_symbol_to_curie",
        ),
        gene_label="atgl-1",
    )
    b.set_molecular_function(
        atgl1, "GO:0004806",
        source=database(
            source_id="GO:0004806",
            tool_name="go_api.gene_annotations",
            snippet="Existing GO annotation: triacylglycerol lipase activity",
        ),
        label="triacylglycerol lipase activity",
    )
    b.set_part_of(
        atgl1, "GO:0019433",
        source=database(
            source_id="GO:0019433",
            tool_name="go_api.gene_annotations",
            snippet="Existing GO annotation: triglyceride catabolic process",
        ),
        label="triglyceride catabolic process",
    )
    b.set_occurs_in(
        atgl1, "CL:0000584",
        source=instinct(
            justification="Figure shows atgl-1 inside the INTESTINE compartment downstream of nhr-76.",
        ),
        label="enterocyte",
    )

    # Causal edges.
    b.add_causal(
        tph1, mod1,
        predicate="RO:0002304",
        source=literature(
            pmid="PMID:11099056",
            snippet="tph-1 supplies the serotonin signal that mod-1 responds to (Ranganathan et al. 2000).",
        ),
        predicate_label="causally upstream of, positive effect",
    )
    b.add_causal(
        mod1, nhr76,
        predicate="RO:0002304",
        source=instinct(
            justification="Figure 1 panel E draws an 'endocrine signal' arrow from the NEURONS compartment (containing mod-1) to the INTESTINE compartment (containing nhr-76); the directionality is shown but no direct molecular link is annotated in GO yet.",
        ),
        predicate_label="causally upstream of, positive effect",
    )
    b.add_causal(
        nhr76, atgl1,
        predicate="RO:0002629",
        source=database(
            source_id="GO:0006357",
            tool_name="go_api.gene_annotations",
            snippet="nhr-76 is annotated as a transcriptional regulator; figure indicates atgl-1 as a direct downstream target.",
        ),
        predicate_label="directly positively regulates",
    )

    model, ledger = b.build()
    out_dir.mkdir(parents=True, exist_ok=True)
    write_model_and_ledger(model, ledger, out_dir)
    viewer_json = linkml_to_viewer_json(model)
    (out_dir / "viewer.json").write_text(json.dumps(viewer_json, indent=2))

    return {
        "model_id": model.id,
        "activities": len(model.activities),
        "sidecar_entries": len(ledger.assertions),
        "source_mix": ledger.count_by_source_type(),
        "viewer_individuals": len(viewer_json["individuals"]),
        "viewer_facts": len(viewer_json["facts"]),
    }


def main() -> None:
    out_dir = Path(__file__).resolve().parents[2] / "docs" / "runs" / "demo"
    summary = build_demo(out_dir)
    print(f"wrote demo artifacts to {out_dir}")
    for k, v in summary.items():
        print(f"  {k:20s} {v}")


if __name__ == "__main__":
    main()
