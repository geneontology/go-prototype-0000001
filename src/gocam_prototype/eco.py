"""GO (GAF) evidence code → ECO CURIE mapping.

The GO API returns annotations tagged with a GAF evidence *code* (IDA, IBA,
ISS, …). The gocam-py LinkML model's `EvidenceItem.term` wants an **ECO
CURIE**. This module is the bridge so the builder can stamp a real ECO term
(not a hard-coded `ECO:0000314`) onto every database-backed assertion.

The mapping is a **vendored snapshot** of the canonical GOC table — the
"Default" (equivalence) rows of `gaf-eco-mapping-derived.txt`:

    http://purl.obolibrary.org/obo/eco/gaf-eco-mapping-derived.txt
    (evidenceontology repo; see PMID:34986598)

Snapshot taken 2026-06-09 — all 26 GAF codes that carry an equivalent ECO term.
Per repo policy (no upstream runtime dependency) we vendor it here rather than
fetch at run-time; refresh from the URL above if GO adds/changes codes. Labels
are the official ECO term labels (EBI OLS4, fetched 2026-06-09) so the viewer
shows a real evidence label, not the CURIE echoed.
"""

from __future__ import annotations

# Fallback when a code has no known ECO mapping. NEVER silently substitute a
# specific code (e.g. ECO:0000314/IDA) — that fabricates evidence. ECO:0000000
# is the ontology root ("evidence"); pairing it with a sidecar note makes the
# gap visible instead of wrong.
ECO_UNKNOWN = "ECO:0000000"

# GAF evidence code -> ECO CURIE (the "Default"/equivalent mappings).
GO_CODE_TO_ECO: dict[str, str] = {
    "EXP": "ECO:0000269",
    "HDA": "ECO:0007005",
    "HEP": "ECO:0007007",
    "HGI": "ECO:0007003",
    "HMP": "ECO:0007001",
    "HTP": "ECO:0006056",
    "IBA": "ECO:0000318",
    "IBD": "ECO:0000319",
    "IC":  "ECO:0000305",
    "IDA": "ECO:0000314",
    "IEA": "ECO:0000501",
    "IEP": "ECO:0000270",
    "IGC": "ECO:0000317",
    "IGI": "ECO:0000316",
    "IKR": "ECO:0000320",
    "IMP": "ECO:0000315",
    "IPI": "ECO:0000353",
    "IRD": "ECO:0000321",
    "ISA": "ECO:0000247",
    "ISM": "ECO:0000255",
    "ISO": "ECO:0000266",
    "ISS": "ECO:0000250",
    "NAS": "ECO:0000303",
    "ND":  "ECO:0000307",
    "RCA": "ECO:0000245",
    "TAS": "ECO:0000304",
}

# ECO CURIE -> official label (so the builder can remember() a real label and the
# panel shows "experimental evidence …" rather than the bare CURIE).
ECO_LABELS: dict[str, str] = {
    "ECO:0000000": "evidence",
    "ECO:0000245": "automatically integrated combinatorial evidence used in manual assertion",
    "ECO:0000247": "sequence alignment evidence used in manual assertion",
    "ECO:0000250": "sequence similarity evidence used in manual assertion",
    "ECO:0000255": "match to sequence model evidence used in manual assertion",
    "ECO:0000266": "sequence orthology evidence used in manual assertion",
    "ECO:0000269": "experimental evidence used in manual assertion",
    "ECO:0000270": "expression pattern evidence used in manual assertion",
    "ECO:0000303": "author statement without traceable support used in manual assertion",
    "ECO:0000304": "author statement supported by traceable reference used in manual assertion",
    "ECO:0000305": "curator inference used in manual assertion",
    "ECO:0000307": "no evidence data found used in manual assertion",
    "ECO:0000314": "direct assay evidence used in manual assertion",
    "ECO:0000315": "mutant phenotype evidence used in manual assertion",
    "ECO:0000316": "genetic interaction evidence used in manual assertion",
    "ECO:0000317": "genomic context evidence used in manual assertion",
    "ECO:0000318": "biological aspect of ancestor evidence used in manual assertion",
    "ECO:0000319": "biological aspect of descendant evidence used in manual assertion",
    "ECO:0000320": "phylogenetic determination of loss of key residues evidence used in manual assertion",
    "ECO:0000321": "rapid divergence from ancestral sequence evidence used in manual assertion",
    "ECO:0000353": "physical interaction evidence used in manual assertion",
    "ECO:0000501": "evidence used in automatic assertion",
    "ECO:0006056": "high throughput evidence used in manual assertion",
    "ECO:0007001": "high throughput mutant phenotypic evidence used in manual assertion",
    "ECO:0007003": "high throughput genetic interaction phenotypic evidence used in manual assertion",
    "ECO:0007005": "high throughput direct assay evidence used in manual assertion",
    "ECO:0007007": "high throughput expression pattern evidence used in manual assertion",
}


def eco_for_go_code(code: str | None) -> str | None:
    """Return the ECO CURIE for a GAF evidence code (e.g. 'IBA' -> 'ECO:0000318'),
    or None if the code is unknown/blank. Case-insensitive; tolerates an already-
    ECO CURIE passed through (returns it unchanged)."""
    if not code:
        return None
    code = code.strip()
    if code.upper().startswith("ECO:"):
        return code
    return GO_CODE_TO_ECO.get(code.upper())


def eco_label(eco: str | None) -> str:
    """Human label for an ECO CURIE; falls back to the CURIE itself."""
    return ECO_LABELS.get(eco or "", eco or "")
