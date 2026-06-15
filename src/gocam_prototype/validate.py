"""Programmatic validation of a built GO-CAM against the machine-checkable GO-CAM
rules documented in knowledge/go-curation-rules.yaml.

This is the first slice of "rules.yaml -> code" enforcement: the guidelines are
injected into the agent's prompt, and here a subset of the machine-checkable
rules are *enforced* on the emitted model so curators get a per-run lint report
(written to <run>/validation.json). Headline check: the transcription-factor ->
target = INDIRECT rule from the MF guide (issue #39).

Checks are intentionally conservative (a curator lint, not a hard gate): each
finding has a `severity` of "error" or "warn" and references the rule id.
"""

from __future__ import annotations

# Direct regulation predicates (RO). A TF / nuclear-receptor activity must NOT use
# these to its transcriptional target — see mf_activity_unit_patterns in the rules.
_DIRECT_REG = {
    "RO:0002629",  # directly positively regulates
    "RO:0002630",  # directly negatively regulates
    "RO:0002578",  # directly regulates
}
# MF terms (and common RNA-Pol-II children) denoting transcription-factor activity.
_TF_MF = {
    "GO:0003700",  # DNA-binding transcription factor activity
    "GO:0000981",  # DNA-binding TF activity, RNA polymerase II-specific
    "GO:0001228",  # DNA-binding transcription activator activity, RNA Pol II-specific
    "GO:0001227",  # DNA-binding transcription repressor activity, RNA Pol II-specific
    "GO:0004879",  # nuclear receptor activity
}
# BP terms that mark an activity as regulating transcription.
_REG_TXN_BP = {
    "GO:0006355",  # regulation of DNA-templated transcription
    "GO:0006357",  # regulation of transcription by RNA polymerase II
    "GO:0045944",  # positive regulation of transcription by RNA Pol II
    "GO:0000122",  # negative regulation of transcription by RNA Pol II
}

# has_input — an enzyme-substrate slot. A signaling-receptor / ligand-gated-
# channel / nuclear-receptor MF should bind its ligand via has small molecule
# activator|inhibitor (RO:0012001/0012002), NOT has_input (#53). This lint has
# no ontology closure, so it recognizes the receptor/channel MF class by its
# label and only fires (warn) when the input molecule is a ChEBI chemical.
_HAS_INPUT = "RO:0002233"


def _label_is_receptor_or_channel(label) -> bool:
    if not label:
        return False
    low = label.lower()
    if "receptor activity" in low:  # signaling + nuclear receptor activities
        return True
    if "gated" in low and "channel" in low:  # ligand-/transmitter-gated channels
        return True
    return False


def _term(assoc):
    return getattr(assoc, "term", None) if assoc is not None else None


def validate_model(model, ledger=None) -> list[dict]:
    """Return a list of {rule, severity, message, ...} findings for the model.

    Empty list == clean. Defensive: never raises on a partial/odd model.
    """
    findings: list[dict] = []
    # id -> label, to recognize receptor/channel MF classes by name.
    label_of = {o.id: getattr(o, "label", None) for o in (getattr(model, "objects", None) or [])}
    acts = getattr(model, "activities", None) or []
    for a in acts:
        aid = getattr(a, "id", None)
        mf = _term(getattr(a, "molecular_function", None))
        bp = _term(getattr(a, "part_of", None))

        if _term(getattr(a, "enabled_by", None)) is None:
            findings.append({
                "rule": "activity-needs-enabler", "severity": "warn", "activity": aid,
                "message": "activity has no enabled_by gene product (every MF activity should be enabled_by one)",
            })

        # Receptor/channel ligand should be an activator/inhibitor, not has_input (#53).
        if _label_is_receptor_or_channel(label_of.get(mf)):
            for ma in (getattr(a, "molecular_associations", None) or []):
                mol = getattr(ma, "molecule", None) or ""
                if getattr(ma, "predicate", None) == _HAS_INPUT and mol.startswith("CHEBI:"):
                    findings.append({
                        "rule": "receptor-ligand-not-has-input",
                        "severity": "warn", "activity": aid,
                        "message": (
                            f"receptor/channel activity ({mf}) takes ChEBI {mol} as has_input; "
                            "a ligand of a signaling receptor / ligand-gated channel / nuclear "
                            "receptor should use has small molecule activator|inhibitor "
                            "(RO:0012001 / RO:0012002), not has_input. See issue #53."
                        ),
                    })

        is_tf = (mf in _TF_MF) or (bp in _REG_TXN_BP)
        for ce in (getattr(a, "causal_associations", None) or []):
            pred = getattr(ce, "predicate", None)
            tgt = getattr(ce, "downstream_activity", None)
            if tgt == aid:
                findings.append({
                    "rule": "no-self-causal-edge", "severity": "error", "activity": aid,
                    "message": "causal edge points to itself",
                })
            if is_tf and pred in _DIRECT_REG:
                findings.append({
                    "rule": "tf-target-must-be-indirect", "severity": "warn", "activity": aid,
                    "message": (
                        f"transcription-factor activity ({mf or bp}) uses a DIRECT relation "
                        f"({pred}) to {tgt}; per the MF guide a TF/nuclear-receptor relates to its "
                        "target via indirectly positively/negatively regulates "
                        "(RO:0002407 / RO:0002409). See issue #39."
                    ),
                })

    if ledger is not None:
        for key, value in (getattr(ledger, "assertions", None) or {}).items():
            if "/causal/" not in key:
                continue
            # v2 maps each key to a LIST of sources; v1 stored a single object.
            # Normalize so the rule fires regardless of shape (#40).
            sources = value if isinstance(value, list) else [value]
            if any(getattr(s, "source_type", None) == "go_annotation" for s in sources):
                findings.append({
                    "rule": "no-go-annotation-on-causal-edge", "severity": "error", "assertion": key,
                    "message": "causal edge tagged source_type=go_annotation (not valid for edges)",
                })
    return findings
