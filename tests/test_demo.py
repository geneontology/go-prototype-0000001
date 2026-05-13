"""Smoke test for the hand-crafted demo artifact builder."""

from __future__ import annotations

import json
from pathlib import Path

from gocam_prototype.demo import build_demo


def test_build_demo_writes_three_files(tmp_path: Path) -> None:
    summary = build_demo(tmp_path)

    assert (tmp_path / "model.yaml").is_file()
    assert (tmp_path / "provenance.json").is_file()
    assert (tmp_path / "viewer.json").is_file()

    assert summary["activities"] == 4
    assert summary["sidecar_entries"] >= 14
    # Demo deliberately exercises all four source types except amigo.
    # The demo deliberately exercises every entry in the taxonomy.
    assert {
        "alliance",
        "amigo",
        "expert_review",
        "go_annotation",
        "instinct",
        "literature",
        "orthology",
        "pathway_resource",
    } == set(summary["source_mix"])

    viewer = json.loads((tmp_path / "viewer.json").read_text())
    assert set(viewer.keys()) == {"id", "individuals", "facts", "annotations"}
    assert viewer["facts"], "expected at least one fact (causal edge / part_of / etc.)"

    prov = json.loads((tmp_path / "provenance.json").read_text())
    # Every assertion key in the ledger must look like an assertion id pattern.
    for key in prov["assertions"]:
        assert key.startswith("gomodel:") and "/" in key
