"""Tests for the GO-CAM model validator (rules.yaml -> code enforcement)."""

from __future__ import annotations

from types import SimpleNamespace

from gocam_prototype.validate import validate_model


def _assoc(term):
    return SimpleNamespace(term=term) if term else None


def _act(aid, *, mf=None, bp=None, enabled="WB:WBGene00000001", causal=None):
    return SimpleNamespace(
        id=aid,
        molecular_function=_assoc(mf),
        part_of=_assoc(bp),
        occurs_in=None,
        enabled_by=_assoc(enabled),
        causal_associations=causal or [],
    )


def _edge(predicate, target):
    return SimpleNamespace(predicate=predicate, downstream_activity=target)


def test_tf_direct_relation_is_flagged() -> None:
    # nuclear receptor (GO:0004879) wired with directly-positively-regulates -> warn (issue #39).
    model = SimpleNamespace(activities=[
        _act("m/nhr76", mf="GO:0004879", causal=[_edge("RO:0002629", "m/atgl1")]),
        _act("m/atgl1", mf="GO:0004806"),
    ])
    rules = {f["rule"] for f in validate_model(model)}
    assert "tf-target-must-be-indirect" in rules


def test_tf_indirect_relation_is_clean() -> None:
    model = SimpleNamespace(activities=[
        _act("m/nhr76", mf="GO:0004879", causal=[_edge("RO:0002407", "m/atgl1")]),
        _act("m/atgl1", mf="GO:0004806"),
    ])
    assert not any(f["rule"] == "tf-target-must-be-indirect" for f in validate_model(model))


def test_self_loop_and_missing_enabler() -> None:
    model = SimpleNamespace(activities=[
        _act("m/x", mf="GO:0004510", enabled=None, causal=[_edge("RO:0002304", "m/x")]),
    ])
    rules = {f["rule"] for f in validate_model(model)}
    assert "no-self-causal-edge" in rules
    assert "activity-needs-enabler" in rules


def test_go_annotation_on_causal_edge_is_error() -> None:
    model = SimpleNamespace(activities=[])
    ledger = SimpleNamespace(
        assertions={"m/a/causal/m/b": SimpleNamespace(source_type="go_annotation")}
    )
    findings = validate_model(model, ledger)
    assert any(f["rule"] == "no-go-annotation-on-causal-edge" for f in findings)


def _ma(predicate, molecule):
    return SimpleNamespace(predicate=predicate, molecule=molecule)


def _obj(oid, label):
    return SimpleNamespace(id=oid, label=label)


def test_receptor_chebi_has_input_is_flagged() -> None:
    # A receptor activity taking a ChEBI ligand as has_input should use an
    # activator/inhibitor relation instead (#53).
    act = _act("m/ser6", mf="GO:0008227")
    act.molecular_associations = [_ma("RO:0002233", "CHEBI:17234")]
    model = SimpleNamespace(
        activities=[act],
        objects=[_obj("GO:0008227", "G protein-coupled amine receptor activity")],
    )
    rules = {f["rule"] for f in validate_model(model)}
    assert "receptor-ligand-not-has-input" in rules


def test_receptor_activator_relation_is_clean() -> None:
    # Same receptor, but the ligand is attached as an activator -> no finding.
    act = _act("m/ser6", mf="GO:0008227")
    act.molecular_associations = [_ma("RO:0012001", "CHEBI:17234")]
    model = SimpleNamespace(
        activities=[act],
        objects=[_obj("GO:0008227", "G protein-coupled amine receptor activity")],
    )
    assert not any(
        f["rule"] == "receptor-ligand-not-has-input" for f in validate_model(model)
    )


def test_enzyme_chebi_has_input_is_clean() -> None:
    # An enzyme substrate as has_input is correct -> the lint must NOT fire.
    act = _act("m/tph1", mf="GO:0004510")
    act.molecular_associations = [_ma("RO:0002233", "CHEBI:16828")]
    model = SimpleNamespace(
        activities=[act],
        objects=[_obj("GO:0004510", "tryptophan 5-monooxygenase activity")],
    )
    assert not any(
        f["rule"] == "receptor-ligand-not-has-input" for f in validate_model(model)
    )
