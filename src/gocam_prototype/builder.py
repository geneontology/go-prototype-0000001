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
