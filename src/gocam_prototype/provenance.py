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
    # Figure-derived: a claim read directly off the uploaded figure by the
    # vision pass — not a database lookup or a citation. Requires a snippet
    # describing what the figure shows; cite the saved transcription.md /
    # figure region. Keeps figure-gleaned claims visually distinct from DB
    # lookups so curators know exactly where each statement came from (#40).
    "figure",
    # Not actually a source for an assertion — a curator-visible record
    # that the agent wanted a GO term that does not exist yet. Lives in
    # the sidecar so the dream-workflow step "file an upstream GO ticket"
    # has a per-run, per-gap durable artifact. Per repo policy we do NOT
    # auto-file upstream; the curator escalates manually.
    "go_term_request",
]


class SourceObject(BaseModel):
    """The per-assertion source record."""

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    source_id: str | None = Field(default=None, description="PMID / GO_REF / CURIE / URL — required unless type is 'instinct'.")
    snippet: str | None = Field(default=None, description="Quoted text or short summary of what the source says.")
    justification: str | None = Field(default=None, description="Required when source_type == 'instinct'.")
    tool_name: str | None = Field(default=None, description="Audit trail: which retrieval tool produced this source.")
    # Structured evidence for database-backed claims (#52). For a go_annotation /
    # alliance / orthology source these carry the cited annotation's real GAF
    # evidence code, its reference, and the source term's label — so the builder
    # can mint a correct LinkML EvidenceItem(term=<ECO>, reference=<PMID/GO_REF>)
    # instead of a hard-coded ECO:0000314, and the viewer can show id + label.
    evidence_code: str | None = Field(default=None, description="GAF evidence code of the cited annotation (IDA/IBA/ISS/…). Mapped to an ECO CURIE at build time.")
    reference: str | None = Field(default=None, description="PMID / GO_REF for the cited annotation — distinct from source_id (which for go_annotation is the GO term CURIE).")
    supporting_text: str | None = Field(default=None, description="Quoted supporting text from the reference, if available (#52 pt2).")
    term_label: str | None = Field(default=None, description="Human label of source_id (e.g. 'tryptophan 5-monooxygenase activity' for GO:0004510) so the panel shows id + label (#52 pt3).")
    extra: dict[str, str] | None = Field(default=None, description="Kind-specific fields (ortholog_species, resource, pathway_url, orcid, …).")
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _check_required(self) -> "SourceObject":
        if self.source_type == "instinct":
            if not (self.justification and self.justification.strip()):
                raise ValueError("source_type='instinct' requires a non-empty justification")
        elif self.source_type == "figure":
            # Figure-derived: the "source" is the figure itself, so no source_id is
            # required; the snippet must describe what the figure shows.
            if not (self.snippet and self.snippet.strip()):
                raise ValueError("source_type='figure' requires a non-empty snippet (what the figure shows)")
        elif self.source_type == "go_term_request":
            # The "source" is a request, not a citation. Justification carries the
            # rationale; snippet carries the suggested label/definition; extra may
            # carry aspect, related_terms, etc.
            if not (self.justification and self.justification.strip()):
                raise ValueError("source_type='go_term_request' requires a non-empty justification")
        else:
            if not (self.source_id and self.source_id.strip()):
                raise ValueError(
                    f"source_type={self.source_type!r} requires a non-empty source_id"
                )
        return self


# Convenience constructors — make the agent / demo code read naturally.

def literature(*, pmid: str, snippet: str | None = None, tool_name: str | None = None) -> SourceObject:
    return SourceObject(source_type="literature", source_id=pmid, snippet=snippet, tool_name=tool_name)


def go_annotation(
    *,
    source_id: str,
    snippet: str | None = None,
    tool_name: str | None = None,
    evidence_code: str | None = None,
    reference: str | None = None,
    term_label: str | None = None,
    supporting_text: str | None = None,
) -> SourceObject:
    """An existing GO annotation pulled via the GO API. `source_id` is the GO TERM
    CURIE; `evidence_code` is the annotation's GAF code (IDA/IBA/…), `reference`
    is its PMID/GO_REF, `term_label` is the term's label."""
    return SourceObject(
        source_type="go_annotation", source_id=source_id, snippet=snippet, tool_name=tool_name,
        evidence_code=evidence_code, reference=reference, term_label=term_label,
        supporting_text=supporting_text,
    )


def alliance(
    *,
    source_id: str,
    snippet: str | None = None,
    tool_name: str | None = None,
    evidence_code: str | None = None,
    reference: str | None = None,
    term_label: str | None = None,
) -> SourceObject:
    """Alliance gene info / phenotypes / interactions / expression / ortholog lookup."""
    return SourceObject(
        source_type="alliance", source_id=source_id, snippet=snippet, tool_name=tool_name,
        evidence_code=evidence_code, reference=reference, term_label=term_label,
    )


def amigo(
    *,
    source_id: str,
    snippet: str | None = None,
    tool_name: str | None = None,
    evidence_code: str | None = None,
    reference: str | None = None,
    term_label: str | None = None,
) -> SourceObject:
    return SourceObject(
        source_type="amigo", source_id=source_id, snippet=snippet, tool_name=tool_name,
        evidence_code=evidence_code, reference=reference, term_label=term_label,
    )


def orthology(
    *,
    ortholog_curie: str,
    ortholog_species: str,
    from_annotation: str | None = None,
    snippet: str | None = None,
    tool_name: str | None = None,
    evidence_code: str | None = None,
    reference: str | None = None,
    term_label: str | None = None,
) -> SourceObject:
    """By-orthology inference. `source_id` is the ortholog's CURIE; species (and the originating
    annotation, if known) ride in `extra`. Defaults to ISS evidence (GO_REF:0000024) for the
    transferred term unless the caller overrides."""
    extra: dict[str, str] = {"ortholog_species": ortholog_species}
    if from_annotation:
        extra["from_annotation"] = from_annotation
    return SourceObject(
        source_type="orthology",
        source_id=ortholog_curie,
        snippet=snippet,
        tool_name=tool_name,
        evidence_code=evidence_code or "ISS",
        reference=reference or "GO_REF:0000024",
        term_label=term_label,
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


def figure(*, snippet: str, source_id: str | None = None, tool_name: str | None = None) -> SourceObject:
    """A claim read directly off the uploaded figure by the vision pass. `snippet`
    describes what the figure shows; `source_id` may point at the saved
    transcription / figure region. Keeps figure-derived claims distinct from DB
    lookups (#40)."""
    return SourceObject(source_type="figure", snippet=snippet, source_id=source_id, tool_name=tool_name)


class ProvenanceLedger(BaseModel):
    """The full sidecar object that lives next to model.yaml."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    # v2: each assertion key maps to a LIST of sources so a single statement can
    # carry separately-attributed claims (id-resolution vs the biological fact);
    # see #40. v1 files (single object per key) are read back-compat by the viewer
    # and by cli.summarize_provenance.
    version: int = 2
    assertions: dict[str, list[SourceObject]] = Field(default_factory=dict)

    def attach(self, assertion_id: str, source: SourceObject) -> None:
        """Append a source for an assertion (each slot/edge may carry multiple
        distinct claims; #40). Exact-duplicate sources are skipped."""
        existing = self.assertions.setdefault(assertion_id, [])
        sig = (source.source_type, source.source_id, source.justification, source.snippet)
        if any((s.source_type, s.source_id, s.justification, s.snippet) == sig for s in existing):
            return
        existing.append(source)

    def count_by_source_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sources in self.assertions.values():
            for src in sources:
                counts[src.source_type] = counts.get(src.source_type, 0) + 1
        return counts
