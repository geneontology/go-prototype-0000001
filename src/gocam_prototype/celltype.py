"""Resolve a free-text cell-type label to an ontology CURIE (#54).

A GO-CAM activity's `occurs_in` is a GO cellular component (a *subcellular*
location, e.g. plasma membrane). The cell TYPE it happens in is captured as an
*extension* of that location:
`CellularAnatomicalEntityAssociation.part_of = CellTypeAssociation(term=<cell>)`.
The cell type is a Cell Ontology (CL) class or, for a species with a richer
native anatomy ontology, that ontology (e.g. WBbt for C. elegans).

Resolution is deliberately conservative — we only ever emit a CURIE we can
ground, in two steps:

1. a small **verified** seed map (the common, cross-species-generic cases —
   no network), then
2. a live **OLS4** exact-label class lookup in the taxon's preferred
   ontology(ies).

If neither grounds the label we return ``None`` and the caller omits the
extension rather than fabricating a cell type.

Expandable across species: add a ``taxon -> [ontology, ...]`` entry to
``_TAXON_ONTOLOGIES`` and the OLS path will prefer those ontologies (in order)
before falling back to generic CL. We never hardcode species-specific IDs we
can't verify — OLS supplies them live.
"""

from __future__ import annotations

import os

import httpx

OLS_BASE = "https://www.ebi.ac.uk/ols4/api"
DEFAULT_TIMEOUT = 30.0

# Verified generic Cell Ontology classes (label -> (CURIE, canonical label)),
# confirmed via OLS4 exact search 2026-06-15. Cross-species safe; used before any
# network call. Keep keys lowercase; resolution normalizes the query the same way.
_SEED: dict[str, tuple[str, str]] = {
    "neuron": ("CL:0000540", "neuron"),
    "sensory neuron": ("CL:0000101", "sensory neuron"),
    "motor neuron": ("CL:0000100", "motor neuron"),
    "interneuron": ("CL:0000099", "interneuron"),
    "muscle cell": ("CL:0000187", "muscle cell"),
    "epithelial cell": ("CL:0000066", "epithelial cell"),
    "glial cell": ("CL:0000125", "glial cell"),
    "secretory cell": ("CL:0000151", "secretory cell"),
    "germ cell": ("CL:0000586", "germ cell"),
}

# Per-taxon preferred ontology order for the OLS lookup. The expansion point as
# we add species: a worm model prefers its native WBbt, then generic CL. Unmapped
# taxa use CL only. (OLS grounds whatever it returns, so a preferred-ontology hit
# is still a referenced ID, not a guess.)
_TAXON_ONTOLOGIES: dict[str, list[str]] = {
    "NCBITaxon:6239": ["wbbt", "cl"],  # C. elegans
}
_DEFAULT_ONTOLOGIES = ["cl"]


def _normalize(label: str) -> str:
    return " ".join(label.strip().lower().split())


def _ontologies_for(taxon: str | None) -> list[str]:
    return _TAXON_ONTOLOGIES.get(taxon or "", _DEFAULT_ONTOLOGIES)


def _ols_exact(label: str, ontology: str, client: httpx.Client) -> tuple[str, str] | None:
    """First exact-label class hit for `label` in `ontology` (or None)."""
    r = client.get(
        f"{OLS_BASE}/search",
        params={"q": label, "ontology": ontology, "exact": "true",
                "type": "class", "rows": 5},
    )
    r.raise_for_status()
    norm = _normalize(label)
    onto_lc = ontology.lower()
    for doc in r.json().get("response", {}).get("docs", []):
        obo_id = doc.get("obo_id") or ""
        # The OBO prefix is mixed-case (CL:, WBbt:); compare case-insensitively
        # against the queried ontology so WBbt:… is not rejected by a CL-style
        # upper-case guard.
        prefix = obo_id.split(":", 1)[0].lower()
        if prefix == onto_lc and _normalize(doc.get("label", "")) == norm:
            return obo_id, doc.get("label")
    return None


def resolve_cell_type(
    label: str,
    taxon: str | None = None,
    *,
    client: httpx.Client | None = None,
    allow_network: bool | None = None,
) -> tuple[str, str] | None:
    """Resolve a cell-type `label` to ``(curie, canonical_label)`` or ``None``.

    Seed map first (no network); then an OLS4 exact-label lookup across the
    taxon's preferred ontologies. ``None`` means "could not ground it" — the
    caller must NOT fabricate a cell type. A network failure degrades to the
    seed result (never raises into the build).

    `allow_network` defaults to on, but is forced off in unit tests unless
    `GOCAM_RUN_LIVE_TESTS=1` so the suite never hits OLS; pass a fake `client`
    to exercise the OLS path deterministically.
    """
    if not label or not label.strip():
        return None
    norm = _normalize(label)
    if norm in _SEED:
        return _SEED[norm]

    if allow_network is None:
        allow_network = client is not None or os.environ.get("GOCAM_RUN_LIVE_TESTS") == "1"
    if not allow_network:
        return None

    ontologies = _ontologies_for(taxon)
    own_client = client is None
    c = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
    try:
        for onto in ontologies:
            try:
                hit = _ols_exact(label, onto, c)
            except httpx.HTTPError:
                hit = None
            if hit:
                return hit
    finally:
        if own_client:
            c.close()
    return None
