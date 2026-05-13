"""Source-of-information ledger for GO-CAM assertions.

The gocam-py LinkML schema attaches `EvidenceItem` and `ProvenanceInfo` to
each assertion. That covers what GO already expects: ECO code + reference
(PMID/GO_REF) + contributor/date.

This sidecar adds the *source-type discriminator* the prototype's viewer
needs: was an assertion grounded in a literature passage, a structured
database lookup, an AmiGO/Golr lookup, or "instinct" (LLM-only, no
external evidence)? "instinct" requires a justification — by construction
we cannot tag something `instinct` without writing down WHY, which keeps
the agent honest.

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

SourceType = Literal["literature", "database", "amigo", "instinct"]


class SourceObject(BaseModel):
    """The per-assertion source record."""

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    source_id: str | None = Field(default=None, description="PMID, GO_REF, CURIE, URL — required unless type is 'instinct'")
    snippet: str | None = Field(default=None, description="Quoted text or short summary of what the source says")
    justification: str | None = Field(default=None, description="Required when source_type == 'instinct'")
    tool_name: str | None = Field(default=None, description="Audit trail: which retrieval tool produced this")
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


# Convenience constructors — make the agent code read naturally.

def literature(*, pmid: str, snippet: str | None = None, tool_name: str | None = None) -> SourceObject:
    return SourceObject(source_type="literature", source_id=pmid, snippet=snippet, tool_name=tool_name)


def database(*, source_id: str, snippet: str | None = None, tool_name: str | None = None) -> SourceObject:
    return SourceObject(source_type="database", source_id=source_id, snippet=snippet, tool_name=tool_name)


def amigo(*, source_id: str, snippet: str | None = None, tool_name: str | None = None) -> SourceObject:
    return SourceObject(source_type="amigo", source_id=source_id, snippet=snippet, tool_name=tool_name)


def instinct(*, justification: str, tool_name: str | None = None) -> SourceObject:
    """LLM-only assertion. Justification is REQUIRED — the model cannot silently
    fall back to 'instinct' with an empty explanation."""
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
