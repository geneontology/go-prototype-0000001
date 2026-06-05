"""Shape-validation tests for the Alliance wrapper, including symbol resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from gocam_prototype import alliance

FIXTURES = Path(__file__).parent / "fixtures"


def _serve(fixture_name: str, expected_path_substr: str) -> httpx.Client:
    payload = json.loads((FIXTURES / fixture_name).read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert expected_path_substr in request.url.path, (
            f"unexpected path {request.url.path!r}"
        )
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url=alliance.BASE_URL)


def test_gene_info_returns_typed_dict() -> None:
    with _serve("alliance_gene.json", "/api/gene/HGNC:11998") as c:
        result = alliance.gene_info("HGNC:11998", client=c)
    assert result["symbol"] == "TP53"
    assert result["species"]["name"] == "Homo sapiens"


def test_gene_orthologs_shape() -> None:
    with _serve("alliance_orthologs.json", "/api/gene/") as c:
        result = alliance.gene_orthologs("WB:WBGene00006600", client=c)
    assert "results" in result


def test_resolve_symbol_to_curie_uses_autocomplete() -> None:
    payload = json.loads((FIXTURES / "alliance_autocomplete.json").read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/search_autocomplete"
        assert dict(request.url.params)["q"] == "tph-1"
        return httpx.Response(200, json=payload)

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url=alliance.BASE_URL
    ) as c:
        curie = alliance.resolve_symbol_to_curie(
            "tph-1", species_name="Caenorhabditis elegans", client=c
        )
    # Species filter picks the WB: (C. elegans) hit over the human/mouse ones.
    assert curie == "WB:WBGene00006600"


def test_resolve_symbol_no_match_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [], "total": 0})

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url=alliance.BASE_URL
    ) as c:
        curie = alliance.resolve_symbol_to_curie("does-not-exist", client=c)
    assert curie is None


@pytest.mark.skipif(
    not os.environ.get("GOCAM_RUN_LIVE_TESTS"),
    reason="set GOCAM_RUN_LIVE_TESTS=1 to hit the live Alliance API",
)
def test_live_resolve_tph1_drift_canary() -> None:
    """Hits the real Alliance API so future shape drift (issue #48) is caught."""
    assert (
        alliance.resolve_symbol_to_curie("tph-1", species_name="Caenorhabditis elegans")
        == "WB:WBGene00006600"
    )
