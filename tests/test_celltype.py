"""Tests for the cell-type resolver (#54). Network is never hit: seed lookups
need none, and the OLS path is exercised with a fake httpx client."""

from __future__ import annotations

import httpx

from gocam_prototype.celltype import resolve_cell_type


def test_seed_hit_needs_no_network() -> None:
    # A seeded generic label resolves offline (allow_network stays off).
    assert resolve_cell_type("neuron") == ("CL:0000540", "neuron")
    # Normalization: case + extra whitespace.
    assert resolve_cell_type("  Sensory   Neuron ") == ("CL:0000101", "sensory neuron")


def test_unknown_label_without_network_is_none() -> None:
    assert resolve_cell_type("body wall muscle cell") is None
    assert resolve_cell_type("") is None


class _FakeResponse:
    def __init__(self, docs):
        self._docs = docs

    def raise_for_status(self):
        pass

    def json(self):
        return {"response": {"docs": self._docs}}


class _FakeClient:
    """Records the ontology each search was issued against; returns canned docs."""

    def __init__(self, by_ontology):
        self._by_ontology = by_ontology
        self.calls: list[str] = []

    def get(self, url, params=None):
        onto = (params or {}).get("ontology")
        self.calls.append(onto)
        return _FakeResponse(self._by_ontology.get(onto, []))


def test_ols_exact_match_via_fake_client() -> None:
    # A non-seeded label drives the OLS path; the exact-label CL hit is returned.
    client = _FakeClient({"cl": [{"obo_id": "CL:0000158", "label": "club cell"}]})
    assert resolve_cell_type("club cell", client=client) == ("CL:0000158", "club cell")
    assert client.calls == ["cl"]


def test_taxon_prefers_species_ontology_then_cl() -> None:
    # C. elegans prefers WBbt; a WBbt hit short-circuits before CL is queried.
    # Use a non-seeded label so resolution actually reaches OLS.
    client_q = _FakeClient(
        {"wbbt": [{"obo_id": "WBbt:0005772", "label": "pharyngeal muscle cell"}]}
    )
    assert resolve_cell_type("pharyngeal muscle cell", taxon="NCBITaxon:6239",
                             client=client_q) == ("WBbt:0005772", "pharyngeal muscle cell")
    assert client_q.calls == ["wbbt"]

    # When WBbt has no hit, it falls through to CL.
    client_fall = _FakeClient({"wbbt": [], "cl": [{"obo_id": "CL:0000158", "label": "club cell"}]})
    assert resolve_cell_type("club cell", taxon="NCBITaxon:6239",
                             client=client_fall) == ("CL:0000158", "club cell")
    assert client_fall.calls == ["wbbt", "cl"]


def test_non_exact_label_is_rejected() -> None:
    # OLS returns a near-but-not-exact label -> no match (conservative).
    client = _FakeClient(
        {"cl": [{"obo_id": "CL:0000100", "label": "motor neuron (sensu something)"}]}
    )
    assert resolve_cell_type("motoneuron", client=client) is None


def test_network_error_degrades_to_none() -> None:
    class _BoomClient:
        def get(self, url, params=None):
            raise httpx.ConnectError("boom")

    assert resolve_cell_type("club cell", client=_BoomClient()) is None
