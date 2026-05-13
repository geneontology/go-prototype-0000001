"""Claude tool-use loop that turns a CuratorIntent into a gocam-py Model.

The orchestrator gives the model two flavours of tools:

* RETRIEVAL — read-only lookups against the public GO and Alliance APIs.
* BUILD — methods that mutate a `GoCamBuilder` instance (add activity,
  set MF/BP/CC, add causal edge, finalize).

Every BUILD tool requires a `source` parameter describing where the
assertion came from (literature / database / amigo / instinct). The
SourceObject validator rejects instinct without justification and the
other types without a source_id, so the agent cannot quietly fabricate
citations even by accident.

The loop terminates when the model calls `finalize_model` or stops
emitting tool_use blocks (or hits `max_turns`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
from anthropic import AnthropicVertex
from gocam.datamodel import Model

from gocam_prototype import alliance, go_api
from gocam_prototype.builder import GoCamBuilder
from gocam_prototype.llm import VertexConfig, make_client
from gocam_prototype.provenance import ProvenanceLedger, SourceObject
from gocam_prototype.vision import CuratorIntent

SOURCE_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source_type": {
            "type": "string",
            "enum": ["literature", "database", "amigo", "instinct"],
        },
        "source_id": {
            "type": "string",
            "description": "PMID/GO_REF/CURIE/URL. Required unless source_type='instinct'.",
        },
        "snippet": {"type": "string"},
        "justification": {
            "type": "string",
            "description": "Required when source_type=='instinct'. Explain why no real evidence was found.",
        },
        "tool_name": {"type": "string"},
    },
    "required": ["source_type"],
}


SYSTEM_PROMPT = """\
You are an automated biocurator constructing a GO-CAM model from a research-paper pathway figure. \
The vision pass has already produced a curator-intent JSON listing the species, compartments, gene \
mentions, and tentative causal edges visible in the figure. Your job is to turn that intent into a \
complete, well-cited GO-CAM.

WORKFLOW

1. For each gene mention, call `alliance_resolve_symbol` to obtain a stable CURIE (e.g. tph-1 -> \
   WB:WBGene00006600). If the resolver returns null, you may also try `alliance_gene_info` with a \
   guessed CURIE, or fall back to using the symbol itself in a source_type='instinct' add_activity \
   with a clear justification.
2. For each resolved gene, call `go_gene_annotations` to pull existing GO annotations. Use the most \
   informative annotations to choose:
     - molecular function (MF, GO 'function' aspect)
     - biological process (BP, GO 'process' aspect)
     - cellular component / anatomy (CC, GO 'component' aspect, or a CL: term)
3. Create one Activity per gene via `add_activity` (set source from the resolver/lookup), then call \
   `set_molecular_function`, `set_part_of`, `set_occurs_in` as appropriate. Each call requires a \
   source.
4. For each tentative_edge in the curator intent, map the natural-language relation to a Relation \
   Ontology (RO) predicate. Common picks:
     - RO:0002629  directly positively regulates
     - RO:0002630  directly negatively regulates
     - RO:0002411  causally upstream of
     - RO:0002413  directly provides input for
     - RO:0002304  causally upstream of, positive effect
     - RO:0002305  causally upstream of, negative effect
   Then call `add_causal` with the predicate and a source.
5. When the model is complete, call `finalize_model`.

NON-NEGOTIABLE RULES

* Every assertion you attach to the model carries a source object.
* source_type='literature' means a PMID you ACTUALLY found via a tool — never invent a PMID.
* source_type='database' / 'amigo' must carry a real source_id (the CURIE or annotation key you found).
* source_type='instinct' is ONLY for assertions you are making without external evidence; it requires \
  a non-empty `justification`. Use this sparingly — it is the weakest evidence tier.
* If a gene's annotations don't include an obvious MF, set MF to the most specific function you find \
  with source_type='database' citing the annotation. Do not invent a function.
* Prefer general RO predicates ("causally upstream of, positive effect") over "directly positively \
  regulates" unless the figure makes the directness clear.

PRACTICAL

* Keep the local_part for activity ids short and stable (e.g. 'tph1', 'mod1', 'nhr76').
* Re-use the same activity_id when wiring causal edges (the strings you got back from add_activity).
* Plan briefly in prose before each tool call. Do not narrate at length between calls.
"""


@dataclass
class Orchestrator:
    builder: GoCamBuilder
    client: AnthropicVertex
    model_name: str
    max_turns: int = 60

    _tools: list[dict] = field(default_factory=list, init=False)
    _handlers: dict[str, Callable[[dict], dict]] = field(default_factory=dict, init=False)
    _finalized: bool = field(default=False, init=False)
    events: list[dict] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._register_tools()

    # -- tool registration -------------------------------------------------

    def _register(self, name: str, description: str, input_schema: dict, handler: Callable[[dict], dict]) -> None:
        self._tools.append({"name": name, "description": description, "input_schema": input_schema})
        self._handlers[name] = handler

    def _register_tools(self) -> None:
        self._register(
            "alliance_resolve_symbol",
            "Resolve a gene symbol (e.g. 'tph-1') to an Alliance CURIE. Use BEFORE add_activity.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "symbol": {"type": "string"},
                    "species_name": {"type": "string"},
                },
                "required": ["symbol"],
            },
            self._t_resolve_symbol,
        )
        self._register(
            "go_gene_annotations",
            "Fetch existing GO annotations for a gene CURIE. Returns a slim list with the GO term id, "
            "label, aspect, evidence ECO, and up to 3 publications.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "gene_curie": {"type": "string"},
                    "rows": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
                },
                "required": ["gene_curie"],
            },
            self._t_gene_annotations,
        )
        self._register(
            "go_term_lookup",
            "Look up metadata for a GO term (label, definition).",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"term_id": {"type": "string"}},
                "required": ["term_id"],
            },
            self._t_term_lookup,
        )
        self._register(
            "alliance_gene_info",
            "Fetch summary info for a gene CURIE (symbol, name, species, synonyms).",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"gene_curie": {"type": "string"}},
                "required": ["gene_curie"],
            },
            self._t_gene_info,
        )
        self._register(
            "add_activity",
            "Create a new Activity. Returns its activity_id — keep it for subsequent set_* / add_causal.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "local_part": {"type": "string"},
                    "enabled_by_gene": {"type": "string", "description": "Gene CURIE."},
                    "gene_label": {"type": "string"},
                    "source": SOURCE_OBJECT_SCHEMA,
                },
                "required": ["local_part", "enabled_by_gene", "source"],
            },
            self._t_add_activity,
        )
        self._register(
            "set_molecular_function",
            "Set the molecular function slot on an existing activity. Term is a GO MF CURIE.",
            self._slot_schema("term"),
            self._t_set_mf,
        )
        self._register(
            "set_part_of",
            "Set the biological process (part_of) slot on an existing activity.",
            self._slot_schema("term"),
            self._t_set_bp,
        )
        self._register(
            "set_occurs_in",
            "Set the cellular component / anatomy (occurs_in) slot.",
            self._slot_schema("term"),
            self._t_set_cc,
        )
        self._register(
            "add_causal",
            "Add a causal edge between two existing activities using an RO predicate.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source_activity_id": {"type": "string"},
                    "target_activity_id": {"type": "string"},
                    "predicate": {"type": "string"},
                    "predicate_label": {"type": "string"},
                    "source": SOURCE_OBJECT_SCHEMA,
                },
                "required": [
                    "source_activity_id",
                    "target_activity_id",
                    "predicate",
                    "source",
                ],
            },
            self._t_add_causal,
        )
        self._register(
            "finalize_model",
            "Signal that the model is complete. Call after all activities and causal edges.",
            {"type": "object", "additionalProperties": False, "properties": {}},
            self._t_finalize,
        )

    @staticmethod
    def _slot_schema(term_field: str) -> dict:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "activity_id": {"type": "string"},
                term_field: {"type": "string"},
                "label": {"type": "string"},
                "source": SOURCE_OBJECT_SCHEMA,
            },
            "required": ["activity_id", term_field, "source"],
        }

    # -- handlers ----------------------------------------------------------

    def _make_source(self, raw: dict) -> SourceObject:
        return SourceObject.model_validate(raw)

    def _t_resolve_symbol(self, inp: dict) -> dict:
        try:
            curie = alliance.resolve_symbol_to_curie(
                inp["symbol"], species_name=inp.get("species_name")
            )
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}
        return {"symbol": inp["symbol"], "curie": curie}

    def _t_gene_annotations(self, inp: dict) -> dict:
        try:
            raw = go_api.gene_annotations(inp["gene_curie"], rows=inp.get("rows", 25))
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}
        slim: list[dict[str, Any]] = []
        for a in (raw.get("associations") or [])[: inp.get("rows", 25)]:
            slim.append({
                "object_id": (a.get("object") or {}).get("id"),
                "object_label": (a.get("object") or {}).get("label"),
                "aspect": a.get("aspect"),
                "evidence_type": a.get("evidence_type"),
                "publications": [(p or {}).get("id") for p in (a.get("publications") or [])][:3],
                "qualifiers": a.get("qualifiers") or [],
            })
        return {"associations": slim}

    def _t_term_lookup(self, inp: dict) -> dict:
        try:
            t = go_api.term_lookup(inp["term_id"])
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}
        return {
            "id": t.get("goid"),
            "label": t.get("label"),
            "definition": t.get("definition"),
        }

    def _t_gene_info(self, inp: dict) -> dict:
        try:
            g = alliance.gene_info(inp["gene_curie"])
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}
        species = g.get("species") or {}
        return {
            "id": g.get("id"),
            "symbol": g.get("symbol"),
            "name": g.get("name"),
            "species": species.get("name") if isinstance(species, dict) else species,
            "synonyms": g.get("synonyms") or [],
        }

    def _t_add_activity(self, inp: dict) -> dict:
        try:
            src = self._make_source(inp["source"])
            aid = self.builder.add_activity(
                inp["local_part"],
                enabled_by_gene=inp["enabled_by_gene"],
                enabled_by_source=src,
                gene_label=inp.get("gene_label"),
            )
        except Exception as e:
            return {"error": str(e)}
        return {"activity_id": aid}

    def _t_set_mf(self, inp: dict) -> dict:
        return self._slot_call(inp, self.builder.set_molecular_function)

    def _t_set_bp(self, inp: dict) -> dict:
        return self._slot_call(inp, self.builder.set_part_of)

    def _t_set_cc(self, inp: dict) -> dict:
        return self._slot_call(inp, self.builder.set_occurs_in)

    def _slot_call(self, inp: dict, fn: Callable) -> dict:
        try:
            src = self._make_source(inp["source"])
            fn(inp["activity_id"], inp["term"], source=src, label=inp.get("label"))
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True}

    def _t_add_causal(self, inp: dict) -> dict:
        try:
            src = self._make_source(inp["source"])
            self.builder.add_causal(
                inp["source_activity_id"],
                inp["target_activity_id"],
                predicate=inp["predicate"],
                source=src,
                predicate_label=inp.get("predicate_label"),
            )
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True}

    def _t_finalize(self, inp: dict) -> dict:
        self._finalized = True
        return {"ok": True, "summary": self.builder._ledger.count_by_source_type()}  # noqa: SLF001

    # -- loop ---------------------------------------------------------------

    def run(self, intent: CuratorIntent) -> tuple[Model, ProvenanceLedger]:
        messages: list[dict] = [
            {"role": "user", "content": self._initial_user_message(intent)},
        ]
        for turn in range(self.max_turns):
            response = self.client.messages.create(
                model=self.model_name,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=self._tools,
            )
            usage = getattr(response, "usage", None)
            self.events.append({
                "turn": turn,
                "stop_reason": getattr(response, "stop_reason", None),
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            })

            # Mirror the assistant's blocks back into messages, in the
            # shape the Anthropic API expects on the next turn.
            assistant_content: list[dict] = []
            for block in response.content:
                btype = getattr(block, "type", None)
                if btype == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif btype == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            messages.append({"role": "assistant", "content": assistant_content})

            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                break  # model is done speaking

            tool_results: list[dict] = []
            for tu in tool_uses:
                handler = self._handlers.get(tu.name)
                if handler is None:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps({"error": f"unknown tool {tu.name!r}"}),
                        "is_error": True,
                    })
                    continue
                try:
                    result = handler(tu.input or {})
                except Exception as e:  # defensive — handlers also catch internally
                    result = {"error": f"handler raised: {e}"}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result),
                    **({"is_error": True} if "error" in result else {}),
                })

            messages.append({"role": "user", "content": tool_results})

            if self._finalized:
                break
        else:
            raise RuntimeError(
                f"Orchestrator hit max_turns={self.max_turns} without finalize_model; "
                "model may be looping. Inspect orch.events for usage."
            )

        return self.builder.build()

    @staticmethod
    def _initial_user_message(intent: CuratorIntent) -> str:
        return (
            "Build a GO-CAM model from the following curator-intent JSON. "
            "Plan briefly, then start calling tools.\n\n"
            "```json\n"
            + intent.model_dump_json(indent=2, exclude_none=True)
            + "\n```"
        )


def orchestrate(
    intent: CuratorIntent,
    builder: GoCamBuilder,
    *,
    client: AnthropicVertex | None = None,
    model_name: str | None = None,
    max_turns: int = 60,
) -> tuple[Model, ProvenanceLedger]:
    """Convenience entry point. Pulls Vertex config from env if no client given."""
    cli = client or make_client(VertexConfig.from_env())
    mdl = (
        model_name
        or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or "claude-sonnet-4-6@default"
    )
    orch = Orchestrator(builder=builder, client=cli, model_name=mdl, max_turns=max_turns)
    return orch.run(intent)
