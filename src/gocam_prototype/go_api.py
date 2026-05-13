"""Wrapper for the public GO REST API at api.geneontology.org.

Functions return decoded JSON dictionaries; we deliberately don't model the
shape with pydantic in v0 — the agent layer adapts these into gocam-py
objects, and overfitting to the GO API's evolving shape now would cost
more than it saves.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import httpx

BASE_URL = "https://api.geneontology.org"
DEFAULT_TIMEOUT = 30.0


@contextmanager
def _session(client: httpx.Client | None) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
        return
    with httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT, follow_redirects=True) as c:
        yield c


def gene_annotations(
    gene_curie: str, *, rows: int = 100, client: httpx.Client | None = None
) -> dict:
    """Functional annotations for a gene.

    `gene_curie` is e.g. `"WB:WBGene00006600"` (tph-1) or `"HGNC:11998"` (TP53).
    Returns the raw `{associations: [...]}` payload.
    """
    with _session(client) as c:
        r = c.get(f"/api/bioentity/gene/{gene_curie}/function", params={"rows": rows})
        r.raise_for_status()
        return r.json()


def term_lookup(term_id: str, *, client: httpx.Client | None = None) -> dict:
    """Metadata for a GO term."""
    with _session(client) as c:
        r = c.get(f"/api/ontology/term/{term_id}")
        r.raise_for_status()
        return r.json()


def genes_for_term(
    term_id: str, *, rows: int = 100, client: httpx.Client | None = None
) -> dict:
    """Genes annotated to a GO term (and its closure)."""
    with _session(client) as c:
        r = c.get(f"/api/bioentity/function/{term_id}/genes", params={"rows": rows})
        r.raise_for_status()
        return r.json()


def go_cam_get(model_id: str, *, client: httpx.Client | None = None) -> dict:
    """Fetch a published GO-CAM in the bbop-graph-noctua "active model" shape.

    `model_id` should be the bare gomodel ID (no `gomodel:` prefix), e.g.
    `"568b0f9600000284"`. This is the shape `<go-gocam-viewer>.setModelData()`
    consumes; we use it as ground truth when validating the LinkML→viewer
    translator (issue #9).
    """
    bare = model_id.removeprefix("gomodel:")
    with _session(client) as c:
        r = c.get(f"/api/go-cam/{bare}")
        r.raise_for_status()
        return r.json()
