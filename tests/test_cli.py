"""Tests for the CLI surface — landing-page regeneration in particular."""

from __future__ import annotations

from pathlib import Path

import yaml

from gocam_prototype.cli import regenerate_landing


def test_regenerate_landing_lists_runs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    runs = docs / "runs"
    runs.mkdir(parents=True)

    (runs / "demo").mkdir()
    (runs / "demo" / "model.yaml").write_text(yaml.safe_dump({
        "id": "gomodel:demo-x",
        "title": "Demo run x",
        "activities": [{"id": "a"}, {"id": "b"}],
    }))

    (runs / "20260512T123000Z").mkdir()
    (runs / "20260512T123000Z" / "model.yaml").write_text(yaml.safe_dump({
        "id": "gomodel:run-y",
        "title": "Agent run y",
        "activities": [{"id": "c"}],
    }))

    # A directory without model.yaml must be ignored.
    (runs / "no-model").mkdir()

    out = regenerate_landing(docs)
    html = out.read_text()
    assert "Demo run x" in html
    assert "Agent run y" in html
    assert "no-model" not in html
    assert "2 activities" in html
    assert "1 activities" in html


def test_regenerate_landing_handles_empty_runs(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    (docs / "runs").mkdir(parents=True)
    out = regenerate_landing(docs)
    html = out.read_text()
    assert "No runs yet" in html
