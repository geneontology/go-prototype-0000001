"""Wrapper for the public Golr Solr endpoint at golr.geneontology.org.

The legacy aux endpoint (`golr-aux.geneontology.io`) 301-redirects here, so
we point straight at production. Three document categories matter for the
agent: `annotation` (gene→term assertions), `bioentity` (gene products),
`ontology_class` (terms).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable, Iterator

import httpx

BASE_URL = "https://golr.geneontology.org"
SELECT_PATH = "/solr/select"
DEFAULT_TIMEOUT = 30.0


@contextmanager
def _session(client: httpx.Client | None) -> Iterator[httpx.Client]:
    if client is not None:
        yield client
        return
    with httpx.Client(base_url=BASE_URL, timeout=DEFAULT_TIMEOUT, follow_redirects=True) as c:
        yield c


def search(
    *,
    q: str = "*:*",
    fq: Iterable[str] = (),
    fl: Iterable[str] = (),
    rows: int = 10,
    start: int = 0,
    client: httpx.Client | None = None,
) -> dict:
    """Raw Solr query. Returns the decoded JSON (`{response: {numFound, docs}, ...}`).

    Multi-valued `fq` filters are passed as repeated parameters, which is the
    Solr convention and is what golr.geneontology.org expects.
    """
    params: list[tuple[str, str]] = [("q", q), ("wt", "json"), ("rows", str(rows)), ("start", str(start))]
    params.extend(("fq", f) for f in fq)
    if fl:
        params.append(("fl", ",".join(fl)))
    with _session(client) as c:
        r = c.get(SELECT_PATH, params=params)
        r.raise_for_status()
        return r.json()


def annotations_for_gene(
    gene_curie: str, *, rows: int = 50, client: httpx.Client | None = None
) -> dict:
    """All `annotation` docs for a single bioentity."""
    return search(
        fq=[
            'document_category:"annotation"',
            f'bioentity:"{gene_curie}"',
        ],
        rows=rows,
        client=client,
    )


def ontology_class_lookup(
    term_id: str, *, client: httpx.Client | None = None
) -> dict:
    """Fetch a single GO term document from the `ontology_class` category."""
    return search(
        fq=[
            'document_category:"ontology_class"',
            f'id:"{term_id}"',
        ],
        rows=1,
        client=client,
    )
