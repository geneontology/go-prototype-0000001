"""Source-of-information ledger for GO-CAM assertions.

The gocam-py LinkML schema attaches `EvidenceItem` and `ProvenanceInfo` to
each assertion. That covers what GO already expects: ECO code + reference
(PMID/GO_REF) + contributor/date.

This sidecar adds the *source-type discriminator* the prototype's viewer
needs. The taxonomy follows the curator's dream-workflow doc:

  literature        — a research paper (PMID / DOI / GO_REF)               (step 4 / 9)
  go_annotation     — an existing GO annotation pulled via the GO API      (step 2)
  alliance          — Alliance gene info / phenotypes / interactions / expression (step 3)
  amigo             — direct Golr / AmiGO Solr query
  orthology         — by-orthology inference from another species' annotation (step 5)
  pathway_resource  — cross-reference to Reactome / WikiPathways           (step 11)
  expert_review     — curator-asserted or expert-vetted                    (step 10)
  instinct          — LLM-only assertion (justification required)

`instinct` REQUIRES a non-empty justification; every other type REQUIRES a
non-empty source_id. The optional `extra` dict carries kind-specific fields
(ortholog_species + from_annotation for orthology, resource + pathway_url
for pathway_resource, orcid for expert_review, etc.) so the schema stays
flat but the panel can still render the right detail.

Sidecar (provenance.json) keys are derived from the gocam-py Model and
follow these conventions so the rendered viewer page can do constant-time
lookups:

* Activity slot:   `<activity_id>/<slot>`           e.g. `gomodel:.../A/molecular_function`
* Causal edge:     `<source_id>/causal/<target_id>` e.g. `gomodel:.../A/causal/gomodel:.../B`
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SourceType = Literal[
    "literature",
    "go_annotation",
    "alliance",
    "amigo",
    "orthology",
    "pathway_resource",
    "expert_review",
    "instinct",
]


class SourceObject(BaseModel):
    """The per-assertion source record."""

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    source_id: str | None = Field(default=None, description="PMID / GO_REF / CURIE / URL — required unless type is 'instinct'.")
    snippet: str | None = Field(default=None, description="Quoted text or short summary of what the source says.")
    justification: str | None = Field(default=None, description="Required when source_type == 'instinct'.")
    tool_name: str | None = Field(default=None, description="Audit trail: which retrieval tool produced this source.")
    extra: dict[str, str] | None = Field(default=None, description="Kind-specific fields (ortholog_species, resource, pathway_url, orcid, …).")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _check_required(self) -> "SourceObject":
        if self.source_type == "instinct":
            if not (self.justification and self.justification.strip()):
                raise ValueError("source_type='instinct' requires a non-empty justification")
        else:
            if not (self.source_id and self.source_id.strip()):
                raise ValueError(
                    f"source_type={self.source_type!r} requires a non-empty source_id"
                )
        return self


# Convenience constructors — make the agent / demo code read naturally.

def literature(*, pmid: str, snippet: str | None = None, tool_name: str | None = None) -> SourceObject:
    return SourceObject(source_type="literature", source_id=pmid, snippet=snippet, tool_name=tool_name)


def go_annotation(*, source_id: str, snippet: str | None = None, tool_name: str | None = None) -> SourceObject:
    """An existing GO annotation pulled via the GO API."""
    return SourceObject(source_type="go_annotation", source_id=source_id, snippet=snippet, tool_name=tool_name)


def alliance(*, source_id: str, snippet: str | None = None, tool_name: str | None = None) -> SourceObject:
    """Alliance gene info / phenotypes / interactions / expression / ortholog lookup."""
    return SourceObject(source_type="alliance", source_id=source_id, snippet=snippet, tool_name=tool_name)


def amigo(*, source_id: str, snippet: str | None = None, tool_name: str | None = None) -> SourceObject:
    return SourceObject(source_type="amigo", source_id=source_id, snippet=snippet, tool_name=tool_name)


def orthology(
    *,
    ortholog_curie: str,
    ortholog_species: str,
    from_annotation: str | None = None,
    snippet: str | None = None,
    tool_name: str | None = None,
) -> SourceObject:
    """By-orthology inference. `source_id` is the ortholog's CURIE; species (and the originating
    annotation, if known) ride in `extra`."""
    extra: dict[str, str] = {"ortholog_species": ortholog_species}
    if from_annotation:
        extra["from_annotation"] = from_annotation
    return SourceObject(
        source_type="orthology",
        source_id=ortholog_curie,
        snippet=snippet,
        tool_name=tool_name,
        extra=extra,
    )


def pathway_resource(
    *,
    resource: str,
    source_id: str,
    pathway_url: str | None = None,
    snippet: str | None = None,
    tool_name: str | None = None,
) -> SourceObject:
    """Cross-reference to Reactome / WikiPathways / similar. `resource` names the source."""
    extra: dict[str, str] = {"resource": resource}
    if pathway_url:
        extra["pathway_url"] = pathway_url
    return SourceObject(
        source_type="pathway_resource",
        source_id=source_id,
        snippet=snippet,
        tool_name=tool_name,
        extra=extra,
    )


def expert_review(
    *,
    source_id: str,
    orcid: str | None = None,
    contributor_name: str | None = None,
    snippet: str | None = None,
    tool_name: str | None = None,
) -> SourceObject:
    """Curator-asserted or expert-vetted. `source_id` is typically a model id or curator note id."""
    extra: dict[str, str] = {}
    if orcid:
        extra["orcid"] = orcid
    if contributor_name:
        extra["contributor_name"] = contributor_name
    return SourceObject(
        source_type="expert_review",
        source_id=source_id,
        snippet=snippet,
        tool_name=tool_name,
        extra=extra or None,
    )


def instinct(*, justification: str, tool_name: str | None = None) -> SourceObject:
    """LLM-only assertion. Justification is REQUIRED — the model cannot silently fall back to
    'I made it up' without writing down why."""
    return SourceObject(source_type="instinct", justification=justification, tool_name=tool_name)


class ProvenanceLedger(BaseModel):
    """The full sidecar object that lives next to model.yaml."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    version: int = 1
    assertions: dict[str, SourceObject] = Field(default_factory=dict)

    def attach(self, assertion_id: str, source: SourceObject) -> None:
        self.assertions[assertion_id] = source

    def count_by_source_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for src in self.assertions.values():
            counts[src.source_type] = counts.get(src.source_type, 0) + 1
        return counts
