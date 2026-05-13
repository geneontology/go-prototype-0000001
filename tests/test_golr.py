"""Shape-validation tests for the Golr wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from gocam_prototype import golr

FIXTURES = Path(__file__).parent / "fixtures"


def test_annotations_for_gene_sends_expected_filters() -> None:
    payload = json.loads((FIXTURES / "golr_annotation.json").read_text())
    captured: dict[str, list[tuple[str, str]]] = {"params": []}

    def handler(request: httpx.Request) -> httpx.Response:
        # httpx exposes the parsed query as a multidict.
        captured["params"] = list(request.url.params.multi_items())
        assert request.url.path == golr.SELECT_PATH
        return httpx.Response(200, json=payload)

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url=golr.BASE_URL
    ) as c:
        result = golr.annotations_for_gene("WB:WBGene00006566", client=c)

    # The two required filters must both be present, as separate fq params.
    fq_values = [v for k, v in captured["params"] if k == "fq"]
    assert 'document_category:"annotation"' in fq_values
    assert 'bioentity:"WB:WBGene00006566"' in fq_values

    # And the wrapper actually parses Solr's response shape.
    assert "response" in result
    assert result["response"]["docs"], "expected at least one doc"
