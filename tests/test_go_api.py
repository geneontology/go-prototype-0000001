"""Shape-validation tests for the GO API wrapper.

Tests use `httpx.MockTransport` to serve real captured responses from
`tests/fixtures/`, so they exercise the parser without hitting the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from gocam_prototype import go_api

FIXTURES = Path(__file__).parent / "fixtures"


def _client_serving(fixture_name: str, expected_path_fragment: str) -> httpx.Client:
    payload = json.loads((FIXTURES / fixture_name).read_text())

    def handler(request: httpx.Request) -> httpx.Response:
        assert expected_path_fragment in request.url.path, (
            f"unexpected path {request.url.path!r}"
        )
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url=go_api.BASE_URL)


def test_gene_annotations_shape() -> None:
    with _client_serving("go_gene_function.json", "/api/bioentity/gene/") as c:
        result = go_api.gene_annotations("WB:WBGene00006600", client=c)
    assert "associations" in result
    assert isinstance(result["associations"], list)
    assert result["associations"], "expected at least one annotation"
    a = result["associations"][0]
    # Subject is the gene, object is the GO term.
    assert "subject" in a and "object" in a
    assert "id" in a["subject"]


def test_term_lookup_shape() -> None:
    with _client_serving("go_term.json", "/api/ontology/term/") as c:
        result = go_api.term_lookup("GO:0042427", client=c)
    assert result["goid"]
    assert result["label"]


def test_genes_for_term_shape() -> None:
    with _client_serving("go_term_genes.json", "/api/bioentity/function/") as c:
        result = go_api.genes_for_term("GO:0042427", client=c)
    assert "associations" in result
    assert isinstance(result["associations"], list)


def test_go_cam_get_strips_gomodel_prefix() -> None:
    fixture = json.loads((FIXTURES / "go_cam_model.json").read_text())
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        return httpx.Response(200, json=fixture)

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url=go_api.BASE_URL
    ) as c:
        result = go_api.go_cam_get("gomodel:568b0f9600000284", client=c)
    assert captured["path"].endswith("/api/go-cam/568b0f9600000284")
    assert result  # non-empty


@pytest.mark.skipif(
    not bool(__import__("os").environ.get("GOCAM_RUN_LIVE_TESTS")),
    reason="set GOCAM_RUN_LIVE_TESTS=1 to hit the real API",
)
def test_live_term_lookup() -> None:
    """Optional live test, off by default."""
    result = go_api.term_lookup("GO:0042427")
    assert result["label"].lower().startswith("serotonin")
