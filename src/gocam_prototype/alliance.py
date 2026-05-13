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


def gene_info(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}")
        r.raise_for_status()
        return r.json()


def gene_orthologs(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}/orthologs")
        r.raise_for_status()
        return r.json()


def gene_phenotypes(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}/phenotypes")
        r.raise_for_status()
        return r.json()


def gene_interactions(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}/interactions")
        r.raise_for_status()
        return r.json()


def gene_expression(gene_curie: str, *, client: httpx.Client | None = None) -> dict:
    with _session(client) as c:
        r = c.get(f"/api/gene/{gene_curie}/expression-summary")
        r.raise_for_status()
        return r.json()


def search_genes(
    query: str, *, limit: int = 10, client: httpx.Client | None = None
) -> dict:
    with _session(client) as c:
        r = c.get(
            "/api/search",
            params={"q": query, "category": "gene", "limit": limit},
        )
        r.raise_for_status()
        return r.json()


def resolve_symbol_to_curie(
    symbol: str, *, species_name: str | None = None, client: httpx.Client | None = None
) -> str | None:
    """Try to resolve a gene symbol to an Alliance CURIE.

    If `species_name` is provided (e.g., `"Caenorhabditis elegans"`), restrict
    to results matching that species. Returns the CURIE of the best match,
    or None if no acceptable hit is found.
    """
    payload = search_genes(symbol, limit=20, client=client)
    candidates = [r for r in payload.get("results", []) if r.get("category") == "gene"]
    if species_name:
        candidates = [r for r in candidates if r.get("species") == species_name]
    # Prefer exact symbol match, then any match.
    exact = [r for r in candidates if r.get("symbol", "").lower() == symbol.lower()]
    pick = (exact or candidates or [None])[0]
    return pick["id"] if pick else None
