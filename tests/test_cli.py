"""Tests for the CLI surface — landing-page regeneration in particular."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from gocam_prototype.cli import regenerate_landing, summarize_provenance


def _write_model(path: Path, title: str, n_activities: int) -> None:
    path.write_text(yaml.safe_dump({
        "id": f"gomodel:{path.parent.name}",
        "title": title,
        "activities": [{"id": f"a{i}"} for i in range(n_activities)],
    }))


def _write_prov(path: Path, types: dict[str, int]) -> None:
    assertions: dict[str, dict] = {}
    for source_type, count in types.items():
        for i in range(count):
            key = f"gomodel:test/{source_type}-{i}"
            assertion = {"source_type": source_type, "retrieved_at": "2026-01-01T00:00:00Z"}
            if source_type == "instinct":
                assertion["justification"] = "test"
            else:
                assertion["source_id"] = "X:1"
            assertions[key] = assertion
    path.write_text(json.dumps({"model_id": "gomodel:test", "version": 1, "assertions": assertions}))


def test_regenerate_landing_lists_draft_models(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    runs = docs / "runs"
    runs.mkdir(parents=True)

    (runs / "demo").mkdir()
    _write_model(runs / "demo" / "model.yaml", "Demo run x", 2)
    _write_prov(runs / "demo" / "provenance.json",
                {"literature": 1, "go_annotation": 3, "instinct": 1})

    (runs / "20260512T123000Z").mkdir()
    _write_model(runs / "20260512T123000Z" / "model.yaml", "Agent run y", 1)
    _write_prov(runs / "20260512T123000Z" / "provenance.json",
                {"alliance": 1, "orthology": 1})

    # A directory without model.yaml must be ignored.
    (runs / "no-model").mkdir()

    out = regenerate_landing(docs)
    html = out.read_text()

    # Curator-facing terminology
    assert "Draft models" in html
    assert "Submit a figure" in html

    # Both models listed
    assert "Demo run x" in html
    assert "Agent run y" in html
    assert "no-model" not in html

    # Tag cloud renders for each model
    assert 'class="tag literature"' in html
    assert 'class="tag go_annotation"' in html
    assert 'class="tag instinct"' in html
    assert 'class="tag alliance"' in html
    assert 'class="tag orthology"' in html


def test_regenerate_landing_handles_empty_runs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "runs").mkdir(parents=True)
    out = regenerate_landing(docs)
    html = out.read_text()
    assert "No draft models yet" in html
    # Submit-figure form is always present.
    assert "Submit a figure" in html


def test_summarize_provenance_counts(tmp_path: Path) -> None:
    p = tmp_path / "provenance.json"
    _write_prov(p, {"literature": 2, "instinct": 1, "go_annotation": 3})
    counts = summarize_provenance(p)
    assert counts == {"literature": 2, "instinct": 1, "go_annotation": 3}


def test_summarize_provenance_counts_v2_lists(tmp_path: Path) -> None:
    """v2 provenance maps each key to a LIST of sources; counts span the list (#40)."""
    p = tmp_path / "provenance.json"
    p.write_text(json.dumps({
        "model_id": "gomodel:test",
        "version": 2,
        "assertions": {
            "gomodel:test/A/enabled_by": [
                {"source_type": "figure", "snippet": "box labelled tph-1"},
                {"source_type": "alliance", "source_id": "WB:WBGene00006600"},
            ],
            "gomodel:test/A/molecular_function": [
                {"source_type": "go_annotation", "source_id": "GO:0004871"},
            ],
        },
    }))
    assert summarize_provenance(p) == {"figure": 1, "alliance": 1, "go_annotation": 1}


def test_summarize_provenance_missing_file(tmp_path: Path) -> None:
    assert summarize_provenance(tmp_path / "does-not-exist.json") == {}
