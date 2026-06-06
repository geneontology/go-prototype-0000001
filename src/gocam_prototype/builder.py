"""High-level builder that constructs a gocam-py Model and a parallel
provenance ledger, then writes both to disk.

Design notes:

* Each assertion the builder records is paired with a SourceObject in the
  ledger. The agent passes the SourceObject in; this module never invents
  one.
* The gocam-py `EvidenceItem.reference` is populated ONLY when the source
  is a real literature reference (e.g. PMID). For database / amigo /
  instinct sources we intentionally leave the gocam evidence list empty,
  so the prototype never synthesizes a fake citation into the canonical
  model — every non-literature provenance is captured in the sidecar
  `provenance.json` instead.
* `objects[]` (the gocam-py denormalized label cache) is populated
  automatically from labels the builder learns as the model is assembled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import yaml
from gocam.datamodel import (
    Activity,
    BiologicalProcessAssociation,
    BiologicalProcessTermObject,
    CausalAssociation,
    CellularAnatomicalEntityAssociation,
    CellularAnatomicalEntityTermObject,
    EnabledByGeneProductAssociation,
    EvidenceItem,
    EvidenceTermObject,
    GeneProductTermObject,
    Model,
    MolecularFunctionAssociation,
    MolecularFunctionTermObject,
    MoleculeAssociation,
    MoleculeTermObject,
    PredicateTermObject,
    ProvenanceInfo,
    PublicationObject,
    TaxonTermObject,
)

from gocam_prototype.provenance import ProvenanceLedger, SourceObject

TermKind = Literal[
    "gene_product",
    "molecular_function",
    "biological_process",
    "cellular_component",
    "molecule",
    "predicate",
    "publication",
    "evidence",
    "taxon",
]

_KIND_TO_CLS: dict[str, type] = {
    "gene_product": GeneProductTermObject,
    "molecular_function": MolecularFunctionTermObject,
    "biological_process": BiologicalProcessTermObject,
    "cellular_component": CellularAnatomicalEntityTermObject,
    "molecule": MoleculeTermObject,
    "predicate": PredicateTermObject,
    "publication": PublicationObject,
    "evidence": EvidenceTermObject,
    "taxon": TaxonTermObject,
}


@dataclass
class GoCamBuilder:
    """Stateful builder. One instance per model under construction."""

    model_id: str
    title: str
    taxon: str = "NCBITaxon:6239"  # default to C. elegans (v0 test case)
    contributor_orcid: str | None = None

    _activities: dict[str, Activity] = field(default_factory=dict)
    _labels: dict[str, str] = field(default_factory=dict)
    _term_kinds: dict[str, TermKind] = field(default_factory=dict)
    _ledger: ProvenanceLedger = field(init=False)

    def __post_init__(self) -> None:
        self._ledger = ProvenanceLedger(model_id=self.model_id)

    # ------------------------------------------------------------------ labels

    def remember(self, curie: str, label: str, kind: TermKind) -> None:
        """Cache a CURIE→label mapping; ends up in `Model.objects` at build-time."""
        self._labels[curie] = label
        self._term_kinds[curie] = kind

    # -------------------------------------------------------- evidence helper

    def _evidence(self, eco: str, source: SourceObject) -> list[EvidenceItem]:
        if source.source_type != "literature" or not source.source_id:
            return []
        prov = ProvenanceInfo(
            contributor=[self.contributor_orcid] if self.contributor_orcid else None,
            date=datetime.now(timezone.utc).date().isoformat(),
            provided_by=[source.tool_name] if source.tool_name else None,
        )
        self.remember(source.source_id, source.snippet or source.source_id, "publication")
        return [EvidenceItem(term=eco, reference=source.source_id, provenances=[prov])]

    # ----------------------------------------------------------- public API

    def activity_id(self, local_part: str) -> str:
        return f"{self.model_id}/{local_part}"

    def add_activity(
        self,
        local_part: str,
        *,
        enabled_by_gene: str,
        enabled_by_source: SourceObject,
        enabled_by_eco: str = "ECO:0000314",
        gene_label: str | None = None,
    ) -> str:
        aid = self.activity_id(local_part)
        if aid in self._activities:
            raise ValueError(f"activity {aid!r} already exists")
        activity = Activity(
            id=aid,
            enabled_by=EnabledByGeneProductAssociation(
                term=enabled_by_gene,
                evidence=self._evidence(enabled_by_eco, enabled_by_source),
            ),
        )
        self._activities[aid] = activity
        self._ledger.attach(f"{aid}/enabled_by", enabled_by_source)
        self.remember(enabled_by_gene, gene_label or enabled_by_gene, "gene_product")
        return aid

    def set_molecular_function(
        self,
        activity_id: str,
        term: str,
        *,
        source: SourceObject,
        eco: str = "ECO:0000314",
        label: str | None = None,
    ) -> None:
        act = self._require_activity(activity_id)
        act.molecular_function = MolecularFunctionAssociation(
            term=term, evidence=self._evidence(eco, source),
        )
        self._ledger.attach(f"{activity_id}/molecular_function", source)
        self.remember(term, label or term, "molecular_function")

    def set_part_of(
        self,
        activity_id: str,
        term: str,
        *,
        source: SourceObject,
        eco: str = "ECO:0000314",
        label: str | None = None,
    ) -> None:
        act = self._require_activity(activity_id)
        act.part_of = BiologicalProcessAssociation(
            term=term, evidence=self._evidence(eco, source),
        )
        self._ledger.attach(f"{activity_id}/part_of", source)
        self.remember(term, label or term, "biological_process")

    def set_occurs_in(
        self,
        activity_id: str,
        term: str,
        *,
        source: SourceObject,
        eco: str = "ECO:0000314",
        label: str | None = None,
    ) -> None:
        act = self._require_activity(activity_id)
        act.occurs_in = CellularAnatomicalEntityAssociation(
            term=term, evidence=self._evidence(eco, source),
        )
        self._ledger.attach(f"{activity_id}/occurs_in", source)
        self.remember(term, label or term, "cellular_component")

    def add_causal(
        self,
        source_activity_id: str,
        target_activity_id: str,
        *,
        predicate: str,
        source: SourceObject,
        eco: str = "ECO:0000314",
        predicate_label: str | None = None,
    ) -> None:
        act = self._require_activity(source_activity_id)
        if target_activity_id not in self._activities:
            raise ValueError(f"target activity {target_activity_id!r} not declared yet")
        if act.causal_associations is None:
            act.causal_associations = []
        act.causal_associations.append(
            CausalAssociation(
                predicate=predicate,
                downstream_activity=target_activity_id,
                evidence=self._evidence(eco, source),
            )
        )
        self._ledger.attach(
            f"{source_activity_id}/causal/{target_activity_id}", source
        )
        self.remember(predicate, predicate_label or predicate, "predicate")

    # has_input / has_output (RO:0002233 / RO:0002234). Stored in the activity's
    # molecular_associations list. `molecule_kind` is 'molecule' for a ChEBI
    # chemical (e.g. a stimulus ligand) or 'gene_product' for a TF-target gene.
    def add_input(
        self,
        activity_id: str,
        molecule: str,
        *,
        source: SourceObject,
        eco: str = "ECO:0000314",
        label: str | None = None,
        molecule_kind: TermKind = "molecule",
    ) -> str:
        """has_input (RO:0002233): substrate / binding partner / TF-target gene.
        Returns the assertion key."""
        return self._add_molecule(
            activity_id, molecule, "RO:0002233", "has_input",
            source=source, eco=eco, label=label, molecule_kind=molecule_kind,
        )

    def add_output(
        self,
        activity_id: str,
        molecule: str,
        *,
        source: SourceObject,
        eco: str = "ECO:0000314",
        label: str | None = None,
        molecule_kind: TermKind = "molecule",
    ) -> str:
        """has_output (RO:0002234): product (incl. a modified protein form).
        Returns the assertion key."""
        return self._add_molecule(
            activity_id, molecule, "RO:0002234", "has_output",
            source=source, eco=eco, label=label, molecule_kind=molecule_kind,
        )

    def _add_molecule(
        self, activity_id: str, molecule: str, predicate: str, slot: str,
        *, source: SourceObject, eco: str, label: str | None, molecule_kind: TermKind,
    ) -> str:
        act = self._require_activity(activity_id)
        if molecule_kind not in ("molecule", "gene_product"):
            raise ValueError(
                f"molecule_kind must be 'molecule' or 'gene_product', got {molecule_kind!r}"
            )
        if act.molecular_associations is None:
            act.molecular_associations = []
        act.molecular_associations.append(
            MoleculeAssociation(
                predicate=predicate, molecule=molecule,
                evidence=self._evidence(eco, source),
            )
        )
        # Per-molecule key (an activity may carry several inputs/outputs).
        key = f"{activity_id}/{slot}/{molecule}"
        self._ledger.attach(key, source)
        self.remember(molecule, label or molecule, molecule_kind)
        self.remember(predicate, "has input" if slot == "has_input" else "has output", "predicate")
        return key

    _SLOT_ATTRS = {
        "enabled_by": "enabled_by",
        "molecular_function": "molecular_function",
        "part_of": "part_of",
        "occurs_in": "occurs_in",
    }

    def add_source(
        self,
        activity_id: str,
        slot: str,
        source: SourceObject,
        *,
        target_activity_id: str | None = None,
        eco: str = "ECO:0000314",
    ) -> str:
        """Attach an ADDITIONAL source to an assertion that already exists.

        One statement may rest on separately-attributed claims — e.g. the
        figure shows the gene box (source_type='figure') while Alliance
        resolved its CURIE (source_type='alliance'). The primary source is
        passed to add_activity / set_* / add_causal; layer further claims on
        with this. Returns the assertion key. (#40)

        The slot/edge must already exist (set it first) so the ledger never
        points at an assertion absent from the model. If the extra source is a
        real citation, it is also appended to the gocam association's evidence
        list, keeping the canonical model faithful (associations may carry
        several EvidenceItems).
        """
        act = self._require_activity(activity_id)
        if slot == "causal":
            if not target_activity_id:
                raise ValueError("slot='causal' requires target_activity_id")
            key = f"{activity_id}/causal/{target_activity_id}"
            assoc = next(
                (a for a in (act.causal_associations or [])
                 if a.downstream_activity == target_activity_id),
                None,
            )
            if assoc is None:
                raise ValueError(
                    f"no causal edge {activity_id} -> {target_activity_id}; "
                    "call add_causal first"
                )
        elif slot in self._SLOT_ATTRS:
            key = f"{activity_id}/{slot}"
            assoc = getattr(act, self._SLOT_ATTRS[slot])
            if assoc is None:
                raise ValueError(
                    f"slot {slot!r} is not set on {activity_id}; set it first"
                )
        else:
            raise ValueError(
                f"unknown slot {slot!r}; expected one of "
                "enabled_by/molecular_function/part_of/occurs_in/causal"
            )

        ev = self._evidence(eco, source)
        if ev:
            if assoc.evidence is None:
                assoc.evidence = []
            assoc.evidence.extend(ev)
        self._ledger.attach(key, source)
        return key

    # --------------------------------------------------------------- build

    def build(self) -> tuple[Model, ProvenanceLedger]:
        objects: list = []
        for curie, label in self._labels.items():
            kind = self._term_kinds.get(curie, "gene_product")
            cls = _KIND_TO_CLS[kind]
            objects.append(cls(id=curie, label=label))
        if self.taxon and self.taxon not in self._labels:
            objects.append(TaxonTermObject(id=self.taxon, label=self.taxon))
        model = Model(
            id=self.model_id,
            title=self.title,
            taxon=self.taxon,
            status="development",
            activities=list(self._activities.values()),
            objects=objects,
        )
        return model, self._ledger

    def _require_activity(self, activity_id: str) -> Activity:
        try:
            return self._activities[activity_id]
        except KeyError as e:
            raise ValueError(f"activity {activity_id!r} not declared yet") from e


# --------------------------------------------------------------------- I/O


def write_model_and_ledger(
    model: Model, ledger: ProvenanceLedger, out_dir: Path | str
) -> tuple[Path, Path]:
    """Emit `model.yaml` and `provenance.json` into `out_dir`."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.yaml"
    ledger_path = out_dir / "provenance.json"
    model_path.write_text(
        yaml.safe_dump(
            model.model_dump(exclude_none=True, mode="json"),
            sort_keys=False,
            allow_unicode=True,
        )
    )
    ledger_path.write_text(ledger.model_dump_json(indent=2, exclude_none=True))
    return model_path, ledger_path
