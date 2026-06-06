"""Translate a gocam-py `Model` into the bbop-graph "active model" JSON that
`<go-gocam-viewer>.setModelData()` consumes (same shape returned by
`GET https://api.geneontology.org/api/go-cam/{id}`).

Shape:

    {
      "id":          "gomodel:...",
      "individuals": [{"id", "type":[{type,id,label}], "root-type":[...], "annotations":[...]}],
      "facts":       [{"subject", "property", "property-label", "object",
                       "annotations": [{key:"evidence", value:<ECO individual IRI>, value-type:"IRI"}]}],
      "annotations": [{key, value, value-type?}]
    }

The viewer's `NoctuaGraphService.getCam(model)` walks `individuals` to build
`Activity` / `Evidence` objects and walks `facts` (plus the evidence
annotations on each fact) to wire causal relations.

We mint **deterministic IRIs** keyed off the activity id + slot, so the
translator output is byte-stable for a given input — which makes snapshot
tests cleanly reproducible and lets the static viewer page reference
individuals by predictable id.
"""

from __future__ import annotations

from gocam.datamodel import Model

_ROOT_TYPE = {
    "gene_product": [
        {"type": "class", "id": "CHEBI:33695", "label": "information biomacromolecule"}
    ],
    "molecular_function": [
        {"type": "class", "id": "GO:0003674", "label": "molecular_function"}
    ],
    "biological_process": [
        {"type": "class", "id": "GO:0008150", "label": "biological_process"}
    ],
    "cellular_component": [
        {"type": "class", "id": "GO:0005575", "label": "cellular_component"}
    ],
    "molecule": [
        {"type": "class", "id": "CHEBI:24431", "label": "chemical entity"}
    ],
    "evidence": [
        {"type": "class", "id": "ECO:0000000", "label": "evidence"}
    ],
}


def linkml_to_viewer_json(model: Model) -> dict:
    """Convert a gocam-py Model into the viewer's expected dict."""
    label_of = {o.id: (o.label or o.id) for o in (model.objects or [])}

    def lbl(curie: str) -> str:
        return label_of.get(curie, curie)

    individuals: list[dict] = []
    facts: list[dict] = []

    def add_individual(iri: str, term: str, kind: str, annotations: list | None = None) -> None:
        individuals.append({
            "id": iri,
            "type": [{"type": "class", "id": term, "label": lbl(term)}],
            "root-type": _ROOT_TYPE.get(kind, []),
            "annotations": list(annotations) if annotations else [],
        })

    def add_fact(subject: str, predicate: str, obj: str, evidence_iris: list[str]) -> None:
        anns = [{"key": "evidence", "value": ev, "value-type": "IRI"} for ev in evidence_iris]
        facts.append({
            "subject": subject,
            "property": predicate,
            "property-label": lbl(predicate),
            "object": obj,
            "annotations": anns,
        })

    def materialize_evidence(slot_iri: str, evlist) -> list[str]:
        out: list[str] = []
        for idx, ev in enumerate(evlist or []):
            ev_iri = f"{slot_iri}/ev-{idx}"
            annotations = []
            if ev.reference:
                annotations.append({"key": "source", "value": ev.reference})
            add_individual(ev_iri, ev.term, "evidence", annotations=annotations)
            out.append(ev_iri)
        return out

    for act in (model.activities or []):
        # The activity IS the molecular function instance.
        mf_iri = act.id
        mf_term = act.molecular_function.term if act.molecular_function else "GO:0003674"
        add_individual(mf_iri, mf_term, "molecular_function")

        if act.enabled_by:
            gp_iri = f"{act.id}/enabled_by"
            add_individual(gp_iri, act.enabled_by.term, "gene_product")
            add_fact(
                mf_iri, "RO:0002333", gp_iri,
                materialize_evidence(gp_iri, act.enabled_by.evidence),
            )

        if act.part_of:
            bp_iri = f"{act.id}/part_of"
            add_individual(bp_iri, act.part_of.term, "biological_process")
            add_fact(
                mf_iri, "BFO:0000050", bp_iri,
                materialize_evidence(bp_iri, act.part_of.evidence),
            )

        if act.occurs_in:
            cc_iri = f"{act.id}/occurs_in"
            add_individual(cc_iri, act.occurs_in.term, "cellular_component")
            add_fact(
                mf_iri, "BFO:0000066", cc_iri,
                materialize_evidence(cc_iri, act.occurs_in.evidence),
            )

        for ca in (act.causal_associations or []):
            edge_iri = f"{act.id}/causal/{ca.downstream_activity}"
            add_fact(
                mf_iri, ca.predicate, ca.downstream_activity,
                materialize_evidence(edge_iri, ca.evidence),
            )

        # has_input / has_output (molecular_associations): render the molecule /
        # target gene as its own individual + a fact, so the stimulus chemicals
        # and TF targets are visible and clickable. IRI == the provenance ledger
        # key so the panel resolves the source on click.
        for ma in (act.molecular_associations or []):
            mol = ma.molecule
            if not mol:
                continue
            slot = "has_input" if ma.predicate == "RO:0002233" else "has_output"
            mol_iri = f"{act.id}/{slot}/{mol}"
            kind = "molecule" if mol.startswith("CHEBI:") else "gene_product"
            add_individual(mol_iri, mol, kind)
            add_fact(
                mf_iri, ma.predicate, mol_iri,
                materialize_evidence(mol_iri, ma.evidence),
            )

    annotations: list[dict] = [
        {"key": "title", "value": model.title or ""},
        {"key": "http://www.geneontology.org/formats/oboInOwl#id", "value": model.id},
    ]
    if model.taxon:
        annotations.append({
            "key": "https://w3id.org/biolink/vocab/in_taxon",
            "value": model.taxon,
            "value-type": "IRI",
        })
    if model.status:
        annotations.append({"key": "state", "value": model.status})

    return {
        "id": model.id,
        "individuals": individuals,
        "facts": facts,
        "annotations": annotations,
    }
