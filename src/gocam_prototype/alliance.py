"""Wrapper for the Alliance of Genome Resources REST API.

The agent uses Alliance as a fallback when standard GO annotations are
insufficient, and as the canonical orthology source aligned with GO
curation practice.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import httpx

BASE_URL = "https://www.alliancegenome.org"
DEFAULT_TIMEOUT = 30.0


@contextmanager
def _session(client: httpx.Client | None) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
        return
    with httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT, follow_redirects=True) as c:
        yield c


# Alliance migrated its API (verified 2026-06-05): gene records nest under a
# `gene` key with {displayText/formatText} fields; symbol search moved to
# /api/search_autocomplete (old /api/search?category=gene now returns 0);
# molecular interactions moved to /molecular-interactions; orthology results
# nest under geneToGeneOrthologyGenerated. These wrappers normalize the new shapes.

# Species -> Alliance CURIE prefix: the reliable signal for disambiguating a
# symbol shared across organisms (autocomplete results carry the CURIE).
_SPECIES_CURIE_PREFIX = {
    "caenorhabditis elegans": "WB:",
    "homo sapiens": "HGNC:",
    "mus musculus": "MGI:",
    "rattus norvegicus": "RGD:",
    "danio rerio": "ZFIN:",
    "drosophila melanogaster": "FB:",
    "saccharomyces cerevisiae": "SGD:",
    "xenopus laevis": "Xenbase:",
    "xenopus tropicalis": "Xenbase:",
}


def _txt(value) -> str | None:
    """Alliance now wraps display strings as {displayText, formatText}."""
    if isinstance(value, dict):
        return value.get("displayText") or value.get("formatText")
    return value


def gene_info(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    """Return a normalized gene record (the API nests it under `gene` and renames
    fields: geneSymbol / geneFullName / taxon / primaryExternalId)."""
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}")
        r.raise_for_status()
        g = (r.json() or {}).get("gene") or {}
    taxon = g.get("taxon") or {}
    return {
        "id": g.get("primaryExternalId") or gene_curie,
        "symbol": _txt(g.get("geneSymbol")),
        "name": _txt(g.get("geneFullName")),
        "systematic_name": _txt(g.get("geneSystematicName")),
        "species": {"name": taxon.get("name"), "curie": taxon.get("curie")},
        "synonyms": [s for s in (_txt(x) for x in (g.get("geneSynonyms") or [])) if s],
    }


def gene_orthologs(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}/orthologs", params={"limit": 50})
        r.raise_for_status()
        return r.json()


def gene_phenotypes(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}/phenotypes", params={"limit": 50})
        r.raise_for_status()
        return r.json()


def gene_interactions(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}/molecular-interactions", params={"limit": 50})
        r.raise_for_status()
        return r.json()


def search_genes(query: str, *, client: httpx.Client | None = None) -> dict:
    """Autocomplete gene search -> {results: [{symbol, curie, nameKey, category}]}."""
    with _session(client) as c:
        r = c.get("/api/search_autocomplete", params={"q": query})
        r.raise_for_status()
        return r.json()


def resolve_symbol_to_curie(
    symbol: str, *, species_name: str | None = None, client: httpx.Client | None = None
) -> str | None:
    """Resolve a gene symbol to its Alliance CURIE via autocomplete.

    Prefers an exact symbol match; when `species_name` is given, restricts to
    the matching organism by CURIE prefix (e.g. C. elegans -> WB:). Returns the
    CURIE of the best match, or None.
    """
    payload = search_genes(symbol, client=client)
    results = [
        r for r in payload.get("results", [])
        if r.get("category") == "gene_search_result"
    ]
    exact = [r for r in results if (r.get("symbol") or "").lower() == symbol.lower()]
    candidates = exact or results
    if species_name:
        prefix = _SPECIES_CURIE_PREFIX.get(species_name.strip().lower())
        if prefix:
            scoped = [r for r in candidates if (r.get("curie") or "").startswith(prefix)]
            candidates = scoped or candidates
    pick = candidates[0] if candidates else None
    return pick.get("curie") if pick else None
