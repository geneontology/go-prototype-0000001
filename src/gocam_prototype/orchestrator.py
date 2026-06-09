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
from pathlib import Path
from typing import Any, Callable

import httpx
from anthropic import AnthropicVertex
from gocam.datamodel import Model

from gocam_prototype import alliance, go_api
from gocam_prototype.builder import GoCamBuilder
from gocam_prototype.llm import VertexConfig, create_message, make_client
from gocam_prototype.provenance import ProvenanceLedger, SourceObject
from gocam_prototype.vision import CuratorIntent

# The GO/GO-CAM curation guidelines (knowledge/go-curation-guidelines.md) are
# injected into the system prompt so the agent reasons under GO standards.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUIDELINES_PATH = _REPO_ROOT / "knowledge" / "go-curation-guidelines.md"


def _load_guidelines() -> str:
    try:
        return _GUIDELINES_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


SOURCE_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "source_type": {
            "type": "string",
            "enum": [
                "literature",
                "go_annotation",
                "alliance",
                "amigo",
                "orthology",
                "pathway_resource",
                "expert_review",
                "figure",
                "instinct",
                "go_term_request",
            ],
        },
        "source_id": {
            "type": "string",
            "description": "PMID/GO_REF/CURIE/URL. Required unless source_type is 'instinct' or "
                           "'figure'. For orthology: the ortholog's CURIE. "
                           "For pathway_resource: the Reactome/WikiPathways pathway id.",
        },
        "snippet": {
            "type": "string",
            "description": "Quoted text / short summary of what the source says. REQUIRED for "
                           "source_type='figure' — describe exactly what the figure shows "
                           "(e.g. 'box labelled tph-1 in the 5-HT neuron, arrow to intestine').",
        },
        "justification": {
            "type": "string",
            "description": "Required when source_type='instinct'. Explain why no real evidence was "
                           "found AND why the figure does not directly show this (if it does, use "
                           "source_type='figure' instead).",
        },
        "tool_name": {"type": "string"},
        "evidence_code": {
            "type": "string",
            "description": "For go_annotation/alliance/orthology: the cited annotation's GAF evidence "
                           "code EXACTLY as go_gene_annotations returned it (e.g. 'IDA', 'IBA', 'ISS'). "
                           "Copy it; do NOT invent one. Mapped to an ECO term at build time.",
        },
        "reference": {
            "type": "string",
            "description": "For go_annotation/alliance/orthology: the cited annotation's reference "
                           "(PMID:… or GO_REF:…) from go_gene_annotations — DISTINCT from source_id, "
                           "which for go_annotation is the GO TERM CURIE.",
        },
        "term_label": {
            "type": "string",
            "description": "Human label of source_id (e.g. 'tryptophan 5-monooxygenase activity' for "
                           "GO:0004510) — copy object_label from the retrieval result so the panel can "
                           "show id + label.",
        },
        "supporting_text": {
            "type": "string",
            "description": "Quoted supporting text from the reference, if you actually have it.",
        },
        "extra": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "description": "Kind-specific fields. For orthology use {ortholog_species, from_annotation}. "
                           "For pathway_resource use {resource, pathway_url}. "
                           "For expert_review use {orcid, contributor_name}.",
        },
    },
    "required": ["source_type"],
}


# The GO API leaves `association.aspect` null and instead types the term via
# `object.category` (['molecular_activity'] / ['biological_process'] /
# ['cellular_component']). Without this the agent can't tell a CC annotation
# from an MF/BP one — the root of issue #52 pt7 (occurs_in suggesting a CL term
# when a real GO CC annotation exists).
_CATEGORY_TO_ASPECT = {
    "molecular_activity": "molecular_function",
    "molecular_function": "molecular_function",
    "biological_process": "biological_process",
    "cellular_component": "cellular_component",
}

_REFERENCE_PREFIXES = ("PMID:", "PMC", "GO_REF:", "DOI:", "Reactome:")


def _annotation_aspect(assoc: dict) -> str | None:
    cats = (assoc.get("object") or {}).get("category") or []
    for c in cats:
        a = _CATEGORY_TO_ASPECT.get(str(c).lower())
        if a:
            return a
    return None


def _annotation_reference(assoc: dict) -> str | None:
    """The citable reference (PMID / GO_REF / …) for an annotation. The GO API
    exposes this as `reference` (e.g. ['GO_REF:0000033'] for IBA); fall back to
    `publications` when needed. Returns the first real-looking reference."""
    candidates: list = []
    ref = assoc.get("reference")
    candidates.extend(ref if isinstance(ref, list) else ([ref] if ref else []))
    candidates.extend((p or {}).get("id") for p in (assoc.get("publications") or []))
    for c in candidates:
        if isinstance(c, str) and c.startswith(_REFERENCE_PREFIXES):
            return c
    return None


SYSTEM_PROMPT = """\
You are an automated biocurator constructing a GO-CAM model from a research-paper pathway figure. \
The vision pass has already produced a curator-intent JSON listing the species, compartments, gene \
mentions, and tentative causal edges visible in the figure. Your job is to turn that intent into a \
complete, well-cited GO-CAM.

MODELING FIDELITY vs EVIDENCE SCRUTINY (the governing principle)

Hand the curator a model that already MATCHES THE FIGURE, with the easy/concrete work done and \
the uncertain parts clearly flagged for them to dig into. Two SEPARATE standards:

* FIDELITY (reproduce everything): model EVERY gene mention as an activity and EVERY tentative_edge \
  as a causal edge. Inclusion is NOT gated by how strong the evidence is. Never drop a node or edge \
  because you could not find a citation — only omit an element the figure genuinely does not support.
* EVIDENCE SCRUTINY (be strict HERE): back each assertion with the strongest REAL evidence you can \
  find (literature / go_annotation / alliance / pathway_resource / orthology) and use that as the \
  source. ONLY when no real database/citation source can be found, fall back — these are the two \
  WEAKEST tiers, used as a last resort, never in preference to a real lookup:
    - source_type='instinct' — an LLM INFERENCE with no external source (e.g. choosing a specific GO \
      CURIE the figure does not name, or a mechanism the figure only implies). justification REQUIRED.
    - source_type='figure' — the WEAKEST tier, below instinct: a raw reading of the figure with no \
      external backing (a label/box/arrow you transcribed off the image). It is just "what the \
      picture appears to show" — unverified machine reading, the curator's first thing to check. Use \
      it only for a claim that is drawn in the figure AND has no real source; snippet = what you read.
  Either way STILL INCLUDE the element — never fabricate a citation, never silently drop it. instinct \
  and figure (and low confidence) are exactly how the curator sees "verify this one". Prefer a real \
  source over both; prefer instinct (reasoned) over figure (raw read) only when nothing is drawn.

Read the injected GO/GO-CAM guidelines accordingly: "incomplete models are valid" and "quality over \
quantity" mean do NOT invent unknown aspects (use root terms) and do NOT pad one gene with junk \
terms — they are NOT license to skip genes or edges the figure shows. Full figure fidelity is \
required here; the evidence tier (concrete vs instinct) is what carries the uncertainty.

WORKFLOW

1. For each gene mention, call `alliance_resolve_symbol` to obtain a stable CURIE (e.g. tph-1 -> \
   WB:WBGene00006600). The resolution itself is a source_type='alliance' source — its source_id is \
   the CURIE you got back, tool_name is 'alliance.resolve_symbol_to_curie'.
2. For each resolved gene, call `go_gene_annotations` to pull existing GO annotations. Each result \
   carries object_id + object_label, aspect (molecular_function/biological_process/cellular_component), \
   evidence_code (the GAF code, e.g. IDA/IBA/ISS), and reference (PMID/GO_REF). When you derive an \
   MF / BP / CC slot from one, tag it source_type='go_annotation' and COPY the annotation's real \
   metadata into the source: source_id = the GO term CURIE; evidence_code = the GAF code EXACTLY as \
   returned (NEVER invent one); reference = the PMID/GO_REF; term_label = object_label. The builder \
   turns evidence_code into the correct ECO term — a wrong/missing code yields wrong evidence in the \
   model, so copy faithfully.
3. If the gene has no useful GO annotations, fall back to:
     - `alliance_gene_info` / phenotype / interactions / expression — tag as source_type='alliance'
     - `alliance_gene_orthologs` — if you transfer an annotation by orthology, tag as \
       source_type='orthology'. Set source_id to the ortholog's CURIE and put ortholog_species \
       (e.g. 'Homo sapiens') in `extra`. Put the originating annotation's id in extra.from_annotation.
4. Create one Activity for EVERY gene mention in the intent via `add_activity`, then call \
   `set_molecular_function`, `set_part_of`, `set_occurs_in` as appropriate. Each call requires a \
   source — use the STRONGEST real source you have for that specific claim: for `enabled_by`, the \
   source_type='alliance' resolution from step 1 (source_id = the resolved CURIE); for the function / \
   process / component slots, the source_type='go_annotation' (or alliance / orthology / etc.) you \
   derived it from. Do NOT auto-attach a figure source to a gene you successfully resolved — figure is \
   the weakest fallback (see EVIDENCE SCRUTINY), so use it ONLY when no real source backs the claim \
   (e.g. you could not resolve the gene, or a compartment is only a label in the figure with no GO/CL \
   term). Do not skip a gene because its evidence looks thin — model it and let the source tier carry \
   the uncertainty. If ONE claim genuinely rests on several REAL sources (e.g. a localization backed \
   by both a go_annotation and a pathway_resource), record the primary on the set_* call and layer the \
   other(s) with `add_source(activity_id, slot=..., source=...)` — but that is for multiple real \
   sources, not for tacking figure onto an already-resolved claim.
   occurs_in (CC) PREFERENCE: when go_gene_annotations returns an annotation with \
   aspect='cellular_component' (a real GO CC term, GO:0005575 descendant) for the gene, PREFER it for \
   `set_occurs_in` over a cell-type (CL) term you inferred from the figure's compartment box — even \
   if the CC annotation is IBA — and tag it source_type='go_annotation' with its evidence_code/ \
   reference. A CL/WBbt cell-type term stays valid ONLY when the gene has no usable GO CC annotation; \
   the figure's compartment still informs which CC/cell to pick. (e.g. tph-1 has GO:0043005 'neuron \
   projection' — use that, not CL:0000540 'neuron'.)
5. For each tentative_edge in the curator intent, map the natural-language relation to a Relation \
   Ontology (RO) predicate. Common picks:
     - RO:0002629  directly positively regulates
     - RO:0002630  directly negatively regulates
     - RO:0002407  indirectly positively regulates
     - RO:0002409  indirectly negatively regulates
     - RO:0002411  causally upstream of
     - RO:0002413  directly provides input for
     - RO:0002304  causally upstream of, positive effect
     - RO:0002305  causally upstream of, negative effect
   Use a DIRECT relation only when the two activities act in immediate succession with no \
   intervening activity. Use an INDIRECT relation when a reusable module sits between them — in \
   particular a transcription factor / nuclear receptor relates to its TARGET gene's activity via \
   `indirectly positively/negatively regulates` (transcription + translation are the intervening \
   steps), NOT a direct relation. See mf_activity_unit_patterns in the injected curation guidelines.
   Then call `add_causal` with the predicate and a source.
   A causal edge connects TWO gene-product ACTIVITIES. If a tentative_edge's endpoint is NOT another \
   gene's activity, it is NOT a causal edge — route it per INPUTS/OUTPUTS & PATHWAY BOUNDARY below \
   (a stimulus MOLECULE source -> add_input; a compartment like Nucleus -> occurs_in; a process or a \
   transcriptional-output GENE SET -> the TF's part_of regulation-of-transcription + add_input the \
   named target gene). NEVER create a causal edge whose target is a compartment, a process, or a gene set.
6. Add the figure's INPUTS and OUTPUTS (see that section): stimulus/ligand molecules as add_input \
   (ChEBI) on the receiving activity, TF target genes as add_input (gene_product), biosynthetic \
   products as add_output. This is how molecules and target genes enter the model.
7. Call `finalize_model` ONLY after every gene mention is an activity and every tentative_edge is a \
   causal edge OR correctly routed (input/output/occurs_in/part_of) OR recorded as figure-unmappable. \
   Do NOT finalize a partial model just because the well-evidenced core is done — fidelity to the \
   figure comes first; uncertain elements stay in, marked as instinct/low-confidence.

INPUTS / OUTPUTS & THE PATHWAY BOUNDARY (participant-role grid — from the GO-CAM guidelines)

A signaling pathway BEGINS at ligand–receptor and ENDS at "regulation of" a downstream process. The \
downstream RESPONSE itself — transcription and the SETS of genes it produces ("antimicrobial defence \
genes", "cellular stress response genes", "ESRE", "Translation") — is OUTSIDE the pathway. Do NOT \
create activity nodes for those gene sets and do NOT wire causal edges to them. Route each figure \
participant by role:
* stimulus / ligand / input small molecule (e.g. a bacterial toxin entering the cell): `add_input` it \
  on the RECEIVING activity (the receptor / first transducer), molecule_kind='molecule', source_id = \
  a ChEBI CURIE (resolve the chemical; tag the resolution source_type='alliance'/'amigo' or, if only \
  the figure shows it, 'figure'). It is NOT a causal edge and its source is NOT another activity.
* transcription factor: `set_molecular_function` to its DNA-binding TF MF AND `set_part_of` \
  regulation of transcription, DNA-templated (GO:0006355); then for each NAMED target gene the figure \
  shows it regulating, `add_input` that gene (molecule_kind='gene_product'). If the figure also draws \
  the target gene as its own activity, additionally `add_causal` TF -> target with an INDIRECT \
  relation. A TF pointing only at a gene SET (not a named gene) gets the part_of + a process BP, no edge.
* biosynthetic / enzymatic activity that produces a signal (e.g. an amine): `add_output` the product \
  (ChEBI). Downstream, a receptor for that product `add_input`s it — chaining the two activities.
* a figure arrow into a COMPARTMENT box (Nucleus, Mitochondria) is `occurs_in`, never a causal edge.
Connectivity comes from causal edges between the signaling RELAYS plus shared inputs/outputs — not \
from node-ifying the excluded downstream gene sets.

SOURCE TYPES (taxonomy is mandatory — the right type for the right action)

* `literature`        — a PMID you actually found via a tool. source_id is the PMID. NEVER fabricate.
* `go_annotation`     — an existing GO annotation pulled via the GO API. source_id is the GO term CURIE;
                        ALSO set evidence_code (the GAF code), reference (PMID/GO_REF), and term_label
                        (object_label) from the retrieval result. APPLIES TO PER-GENE SLOTS ONLY
                        (MF / BP / CC). NEVER for causal edges — see below.
* `alliance`          — Alliance gene info / phenotypes / interactions / expression / orthologs.
                        source_id is whatever CURIE / identifier the Alliance API returned; set
                        evidence_code/reference/term_label too when it cites a specific annotation.
* `amigo`             — a direct Golr / AmiGO Solr query result. Set evidence_code/reference/term_label.
* `orthology`         — by-orthology inference. source_id = ortholog CURIE; extra.ortholog_species and
                        extra.from_annotation give the surrounding context. Defaults to evidence_code
                        'ISS' + reference 'GO_REF:0000024' unless the transfer warrants otherwise.
* `pathway_resource`  — Reactome / WikiPathways cross-reference. source_id = pathway id;
                        extra.resource = 'Reactome' or 'WikiPathways'; extra.pathway_url optional.
* `expert_review`     — curator-asserted or expert-vetted. Use sparingly; not common in v0.
* `instinct`          — LLM INFERENCE with no external source. REQUIRES a non-empty justification. \
                        A last-resort tier — use ONLY when no real evidence is available. Stronger \
                        than 'figure' (it is reasoned), weaker than every real source.
* `figure`            — the WEAKEST tier: a raw, unverified reading off the uploaded figure (a drawn \
                        box/label/arrow) with NO external backing. REQUIRES snippet = what the figure \
                        shows; no source_id needed. Use ONLY as a last resort for a claim that is \
                        drawn in the figure but that you could NOT back with any real source (a gene \
                        you could not resolve, a compartment that is only a figure label). NEVER use \
                        it for a claim a real lookup already supports — it is the curator's first \
                        thing to re-check, so reserve it for genuinely unverified figure reads.
* `go_term_request`   — NOT a source for an assertion. A separate record that no existing GO term \
                        fits a slot. Created via `request_go_term`, not by passing this as a slot's \
                        source. Use when go_term_lookup turns up nothing usable AND the closest \
                        existing term is materially wrong. Prefer recording the request + picking a \
                        broader existing term to silently picking a wrong specific term.

EDGES ARE THE CENTERPIECE — RESEARCH THEM SEPARATELY

The whole point of a GO-CAM is its causal edges. The activity nodes only exist to be the
endpoints of edges. Treat every causal edge as its own research target — never as a tail step
that inherits a source from one of its endpoints.

BEFORE every add_causal call you SHOULD attempt:

  1. `alliance_gene_interactions` on one or both endpoints — surfaces curated interactions with
     PMIDs you can cite directly as source_type='literature'.
  2. `europepmc_search` with a query like "<gene_a> <gene_b> <species> <process_term>" —
     returns titles + PMIDs of relevant papers.
  3. `pathway_search` with the relevant process / gene names — returns Reactome pathway hits.
     If a pathway contains this exact regulatory step, cite it as source_type='pathway_resource'
     with source_id=<stId> and extra={resource: 'Reactome', pathway_url: <detail URL>}.

If any of these returns relevant evidence, use it. Only when none yield useful evidence, fall back to
the two weakest tiers: source_type='instinct' if the edge is your reasoned inference, or
source_type='figure' (the WEAKEST — a raw read of a drawn arrow) if the edge is literally drawn in
the figure but you found no real source.

Concrete rules for `add_causal` source objects:

* DO NOT use source_type='go_annotation' on a causal edge. GO annotations are per-gene-to-term
  assertions; they do not encode causal edges between two genes' activities. Tagging an edge as
  go_annotation just because both endpoint genes happen to be GO-annotated is WRONG. The
  `add_causal` tool will return is_error if you try.
* Acceptable types for causal edges, in descending preference (weakest last):
    - `literature`: a PMID that describes the specific regulatory relationship (gene A's product
       directly affects gene B's activity). The `snippet` must quote or paraphrase the relevant
       passage from the paper. Use whatever literature-search tools are available.
    - `pathway_resource`: a Reactome / WikiPathways pathway that contains this exact step.
       Put the pathway id in `source_id` and `{resource, pathway_url}` in `extra`.
    - `orthology`: an ortholog pair (in another species) where the relationship IS curated.
       `source_id` is the ortholog CURIE in the source organism; `extra.ortholog_species` +
       `extra.from_annotation` carry the rest.
    - `expert_review`: a curator has personally vetted this edge.
    - `instinct`: your reasoned INFERENCE of the edge with no external source. The `justification`
       must explain the inference and why no real source applies. A last resort.
    - `figure`: the WEAKEST tier — the arrow is DRAWN in the figure but no external source can be
       located, so all you have is the raw read of the picture. `snippet` describes the drawn arrow
       ("Panel E shows a dashed arrow labelled 'endocrine signal' from NEURONS to INTESTINE…"). Use
       only when nothing stronger applies; it is the curator's first thing to verify.
* Always include the predicate's natural-language form in the `snippet` (e.g. "tph-1 product
  is causally upstream, positive effect, of mod-1 in serotonin signalling"), so the panel reader
  doesn't have to translate the RO CURIE in their head.
* If the curator-intent edge names an intermediate molecule (e.g. via 5-HT), record that
  intermediate in the `snippet` — that's a key biological detail.

PER-COMPARTMENT EDGES — DO NOT DROP THEM

Compartment-level edges in the curator intent (e.g. NEURONS → INTESTINE 'endocrine signal')
must NOT be discarded. Model them as a single causal edge between the most plausible upstream
activity in the source compartment and the most plausible downstream activity in the target
compartment, and explain that interpretation in the `snippet`.

LEAF ACTIVITIES ARE FINE — DO NOT INVENT A DOWNSTREAM GENE

Causal edges connect ONE gene's activity to ANOTHER gene's activity. They are NOT for capturing
\"this gene contributes to <process>\" — that goes in `set_part_of`, the BP slot. Concretely:

* If the figure shows `<gene> → <process>` (e.g. atgl-1 → β-oxidation, ser-6 → fat loss), do
  NOT pick the nearest gene activity and wire `add_causal` to it just to give the upstream
  activity a downstream. The arrow is captured by `set_part_of` on the upstream gene, with a
  GO BP term for the process (lipid catabolic process, fatty acid beta-oxidation, etc.).
* If a gene's downstream in the figure is a process with no downstream gene activity in your
  model, that gene's activity is a LEAF. Leaves are valid GO-CAM nodes — finalize without an
  outgoing causal edge.
* `add_causal` will hard-reject self-loops (source_activity_id == target_activity_id). The
  guard is there because the agent has historically synthesized cycles back into an upstream
  gene when the figure's real downstream was a process; don't do that.

NON-NEGOTIABLE RULES

* Every assertion attached to the model carries a source object whose source_type is the most \
  specific applicable type from the taxonomy above.
* Never invent a PMID. literature requires a real PMID returned by a tool.
* Prefer database-grounded types (go_annotation / alliance / amigo / orthology / pathway_resource) \
  over instinct whenever any external lookup produced relevant evidence.
* Prefer general RO predicates ("causally upstream of, positive effect" / "negative effect") over \
  "directly positively/negatively regulates" unless the figure makes the directness clear.
* Always fill `snippet` with a brief summary of what the source actually says — even for database \
  sources. The viewer panel relies on it for human-readable context.

PRACTICAL

* Keep activity local_part short and stable (e.g. 'tph1', 'mod1', 'nhr76').
* Re-use the activity_id returned by add_activity for set_* and add_causal calls.
* Plan briefly before each tool call; do not narrate at length between calls.
"""


@dataclass
class Orchestrator:
    builder: GoCamBuilder
    client: AnthropicVertex
    model_name: str
    max_turns: int = 60
    effort: str = "xhigh"            # Opus 4.8 effort for the agentic build loop
    adaptive_thinking: bool = True   # let the model reason about ambiguous edges
    # Room for a turn's adaptive thinking PLUS its tool calls. Dense figures
    # (figure2: 17 genes / 29 edges) blew the old 16000 budget mid-thinking, so
    # the turn truncated before any tool_use and the loop silently produced an
    # empty model — see _empty_streak recovery below. 32000 gives planning turns
    # headroom.
    max_tokens: int = 32000
    max_empty_nudges: int = 3        # consecutive no-tool turns tolerated before giving up

    _tools: list[dict] = field(default_factory=list, init=False)
    _handlers: dict[str, Callable[[dict], dict]] = field(default_factory=dict, init=False)
    _finalized: bool = field(default=False, init=False)
    _empty_streak: int = field(default=0, init=False)
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
            "Fetch existing GO annotations for a gene CURIE. Returns a slim list per annotation: "
            "object_id (GO term CURIE) + object_label, aspect (molecular_function/biological_process/"
            "cellular_component), evidence_code (the GAF code, e.g. IDA/IBA/ISS), reference (PMID or "
            "GO_REF for the annotation), publications, and qualifiers. When you derive an MF/BP/CC "
            "slot from one of these, COPY its evidence_code, reference, and object_label into the "
            "go_annotation source — do not invent an evidence code.",
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
            "alliance_gene_orthologs",
            "Fetch orthologs for a gene CURIE across model organisms. Use this when the gene has "
            "no useful direct annotation — you can then transfer an ortholog's annotation and tag "
            "the resulting assertion as source_type='orthology' (source_id=<ortholog CURIE>, "
            "extra.ortholog_species, extra.from_annotation).",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"gene_curie": {"type": "string"}},
                "required": ["gene_curie"],
            },
            self._t_gene_orthologs,
        )
        self._register(
            "alliance_gene_interactions",
            "Fetch documented interactions (genetic + physical) for a gene CURIE. Often returns "
            "interaction pairs with PMIDs — use this BEFORE add_causal to find literature-backed "
            "evidence for the edge you're about to wire. The PMID you get back becomes "
            "source_type='literature' for the causal edge.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"gene_curie": {"type": "string"}},
                "required": ["gene_curie"],
            },
            self._t_gene_interactions,
        )
        self._register(
            "pathway_search",
            "Search Reactome for pathways relevant to a gene / process / edge. "
            "Use BEFORE add_causal as a pathway_resource source candidate: if a "
            "Reactome pathway contains this exact regulatory step, cite the "
            "pathway stId (e.g. 'R-HSA-380615') with source_type='pathway_resource', "
            "extra.resource='Reactome', extra.pathway_url=<detail URL>.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "species": {
                        "type": "string",
                        "description": "Reactome species name, e.g. 'Caenorhabditis elegans', "
                                       "'Homo sapiens'. Optional — omit to search across all species.",
                    },
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "required": ["query"],
            },
            self._t_pathway_search,
        )
        self._register(
            "europepmc_search",
            "Free-text Europe PMC search. Use to find a PMID for the SPECIFIC regulatory "
            "relationship between two genes (e.g., 'tph-1 mod-1 Caenorhabditis elegans "
            "serotonin signalling'). Returns the top results' titles + PMIDs. The PMID you "
            "pick becomes source_type='literature' for the causal edge.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                },
                "required": ["query"],
            },
            self._t_europepmc_search,
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
            "Set the cellular component / anatomy (occurs_in) slot. PREFER an existing GO CC "
            "(GO:0005575 descendant) annotation for the gene over a figure-inferred CL cell-type "
            "term; use CL/WBbt only when no GO CC annotation exists.",
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
            "add_input",
            "Add has_input (RO:0002233) to an existing activity: the entity it acts on — a "
            "ChEBI small molecule (stimulus ligand / substrate) OR, for a transcription "
            "factor, its TARGET gene. Use molecule_kind='molecule' for a ChEBI CURIE, "
            "'gene_product' for a target-gene CURIE. This is how a stimulus molecule "
            "(e.g. a bacterial toxin entering the cell) and a TF's target gene enter the "
            "model — NOT as a causal edge to a compartment.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "activity_id": {"type": "string"},
                    "molecule": {"type": "string", "description": "ChEBI CURIE (chemical) or gene CURIE (TF target)."},
                    "molecule_kind": {"type": "string", "enum": ["molecule", "gene_product"]},
                    "label": {"type": "string"},
                    "source": SOURCE_OBJECT_SCHEMA,
                },
                "required": ["activity_id", "molecule", "source"],
            },
            self._t_add_input,
        )
        self._register(
            "add_output",
            "Add has_output (RO:0002234) to an existing activity: the product it makes — a "
            "ChEBI small molecule (molecule_kind='molecule') or a gene product "
            "(molecule_kind='gene_product'). E.g. a biosynthetic activity's product amine.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "activity_id": {"type": "string"},
                    "molecule": {"type": "string", "description": "ChEBI CURIE (chemical) or gene CURIE."},
                    "molecule_kind": {"type": "string", "enum": ["molecule", "gene_product"]},
                    "label": {"type": "string"},
                    "source": SOURCE_OBJECT_SCHEMA,
                },
                "required": ["activity_id", "molecule", "source"],
            },
            self._t_add_output,
        )
        self._register(
            "add_source",
            "Attach an ADDITIONAL source to an assertion that already exists "
            "(slot or causal edge), when ONE claim genuinely rests on more than one "
            "REAL source — e.g. a localization supported by BOTH a go_annotation and a "
            "pathway_resource, or a causal edge with two corroborating PMIDs. Record the "
            "primary on the add_activity/set_*/add_causal call, then layer the extra real "
            "source(s) here. Do NOT use it to tack a weak 'figure' read onto a claim a real "
            "lookup already supports. The slot/edge must already be set. "
            "Slot is one of enabled_by/molecular_function/part_of/occurs_in/causal; "
            "for 'causal' also pass target_activity_id.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "activity_id": {"type": "string"},
                    "slot": {
                        "type": "string",
                        "enum": [
                            "enabled_by", "molecular_function",
                            "part_of", "occurs_in", "causal",
                        ],
                    },
                    "target_activity_id": {
                        "type": "string",
                        "description": "Required only when slot='causal'.",
                    },
                    "source": SOURCE_OBJECT_SCHEMA,
                },
                "required": ["activity_id", "slot", "source"],
            },
            self._t_add_source,
        )
        self._register(
            "request_go_term",
            "Record that a needed GO term does not exist in the ontology. Use this when "
            "go_term_lookup returns nothing usable for an MF/BP/CC slot AND you cannot find "
            "a close-enough existing term. Does NOT modify the model; appends a "
            "go_term_request entry to the provenance sidecar so the curator can review and "
            "(optionally) escalate to a real go-ontology issue. Prefer using an existing "
            "broader GO term + this request over picking a wrong term silently.",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "suggested_label": {
                        "type": "string",
                        "description": "What the missing term should be called, e.g. "
                                       "'positive regulation of intestinal lipid droplet lipolysis by neuroendocrine signal'.",
                    },
                    "aspect": {
                        "type": "string",
                        "enum": ["molecular_function", "biological_process", "cellular_component"],
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why no existing GO term fits. Reference the activity/slot the gap blocks.",
                    },
                    "related_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "GO CURIEs of the closest existing terms you considered.",
                    },
                },
                "required": ["suggested_label", "aspect", "rationale"],
            },
            self._t_request_go_term,
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
            obj = a.get("object") or {}
            slim.append({
                "object_id": obj.get("id"),
                "object_label": obj.get("label"),           # term label (#52 pt3)
                "aspect": _annotation_aspect(a),            # GO API leaves aspect null; derive it
                "evidence_code": a.get("evidence_type"),    # GAF code: IDA / IBA / ISS … (#52 pt1)
                "reference": _annotation_reference(a),      # PMID / GO_REF for the cited annotation (#52 pt2)
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

    def _t_gene_orthologs(self, inp: dict) -> dict:
        try:
            raw = alliance.gene_orthologs(inp["gene_curie"])
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}
        slim: list[dict] = []
        for o in (raw.get("results") or [])[:10]:
            og = o.get("geneToGeneOrthologyGenerated") or {}
            obj = og.get("objectGene") or {}
            species = obj.get("taxon") or {}
            sym = obj.get("geneSymbol")
            slim.append({
                "ortholog_curie": obj.get("primaryExternalId"),
                "ortholog_symbol": sym.get("displayText") if isinstance(sym, dict) else sym,
                "ortholog_species": (
                    species.get("name") if isinstance(species, dict) else species
                ),
                "best_score": (og.get("isBestScore") or {}).get("name"),
                "prediction_methods_matched": og.get("predictionMethodsMatched"),
            })
        return {"orthologs": slim}

    def _t_gene_interactions(self, inp: dict) -> dict:
        try:
            raw = alliance.gene_interactions(inp["gene_curie"])
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}
        slim: list[dict] = []
        for r in (raw.get("results") or [])[:20]:
            partner = r.get("interactor") or r.get("geneInteractor") or {}
            slim.append({
                "interactor_curie": partner.get("id") or partner.get("primaryKey"),
                "interactor_symbol": partner.get("symbol"),
                "interaction_type": r.get("interactionType")
                                    or r.get("type")
                                    or r.get("interactionDirection"),
                "publications": [
                    (p or {}).get("pubMedId") or (p or {}).get("primaryKey")
                    for p in (r.get("publications") or r.get("references") or [])
                ][:3],
            })
        return {"interactions": slim}

    def _t_pathway_search(self, inp: dict) -> dict:
        """Reactome ContentService /search/query.

        WikiPathways' classic REST went read-only on 2026-05-01; their
        SPARQL endpoint is the current alternative but adds dependency
        weight. Reactome alone covers the v0.2 use case (Reactome has
        pathways across most model organisms via PANTHER inference) and
        is sufficient to actually exercise the pathway_resource source
        taxonomy end to end. Add WikiPathways via SPARQL in a follow-up
        if the prototype demonstrates value.
        """
        import re
        import httpx as _httpx
        query = inp["query"]
        max_results = max(1, min(int(inp.get("max_results", 5)), 20))
        params = {
            "query": query,
            "types": "Pathway",
            "rows": max_results,
        }
        if inp.get("species"):
            params["species"] = inp["species"]
        try:
            with _httpx.Client(
                base_url="https://reactome.org/ContentService",
                timeout=20.0,
                follow_redirects=True,
            ) as c:
                r = c.get("/search/query", params=params)
                if r.status_code == 404:
                    return {"results": []}  # 404 = no hits, not an error
                r.raise_for_status()
                payload = r.json()
        except _httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}

        def _clean(name: str | None) -> str:
            return re.sub(r"<[^>]+>", "", name or "").strip()

        hits: list[dict] = []
        # Reactome wraps hits in groups by type; entries[] is what we want.
        for group in (payload.get("results") or []):
            for entry in (group.get("entries") or []):
                st_id = entry.get("stId") or entry.get("id")
                if not st_id:
                    continue
                hits.append({
                    "pathway_id": st_id,
                    "name": _clean(entry.get("name")),
                    "species": entry.get("species") or [],
                    "resource": "Reactome",
                    "pathway_url": f"https://reactome.org/content/detail/{st_id}",
                })
                if len(hits) >= max_results:
                    break
            if len(hits) >= max_results:
                break
        return {"results": hits}

    def _t_europepmc_search(self, inp: dict) -> dict:
        import httpx as _httpx
        query = inp["query"]
        max_results = max(1, min(int(inp.get("max_results", 5)), 20))
        try:
            with _httpx.Client(
                base_url="https://www.ebi.ac.uk/europepmc/webservices/rest",
                timeout=20.0,
                follow_redirects=True,
            ) as c:
                r = c.get(
                    "/search",
                    params={
                        "query": query,
                        "format": "json",
                        "pageSize": max_results,
                        "resultType": "core",
                    },
                )
                r.raise_for_status()
                payload = r.json()
        except _httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}
        results: list[dict] = []
        for it in ((payload.get("resultList") or {}).get("result") or [])[:max_results]:
            pmid = it.get("pmid") or it.get("id")
            doi = it.get("doi")
            results.append({
                "pmid": f"PMID:{pmid}" if pmid and pmid.isdigit() else (it.get("id") or ""),
                "doi": f"DOI:{doi}" if doi else None,
                "title": it.get("title"),
                "authors": it.get("authorString"),
                "journal": (it.get("journalInfo") or {}).get("journal", {}).get("title"),
                "year": it.get("pubYear"),
                "is_open_access": it.get("isOpenAccess") == "Y",
            })
        return {"results": results}

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
        except Exception as e:
            return {"error": str(e)}
        # Refuse self-loops: the agent has historically synthesized cycles back into
        # an upstream activity when the figure's real downstream was a process
        # (e.g. atgl-1 → β-oxidation → fat loss), inventing atgl-1 → nhr-76 because
        # nhr-76 was the nearest upstream gene. Leaf activities are valid — the
        # figure's process arrow belongs in set_part_of, not add_causal (see #24).
        if inp.get("source_activity_id") == inp.get("target_activity_id"):
            return {
                "error": (
                    "self-loop edges are not allowed. If the figure shows this gene "
                    "feeding into a downstream PROCESS (not another gene's activity), "
                    "capture that with set_part_of on the upstream activity using the "
                    "appropriate GO BP term — do not invent a back-edge into an "
                    "already-upstream gene. Leaf activities (with no outgoing causal "
                    "edge) are valid GO-CAM nodes."
                )
            }
        # GO annotations are per-gene-to-term assertions; they cannot encode a causal
        # edge between two activities. Refuse the assignment rather than letting the
        # agent quietly mis-cite a BP term as 'edge evidence' (see issue #20).
        if src.source_type == "go_annotation":
            return {
                "error": (
                    "source_type='go_annotation' is invalid for causal edges. GO annotations "
                    "are per-gene-to-term assertions and do not encode causal relationships "
                    "between activities. Pick the most authoritative reachable type instead: "
                    "'literature' (call europepmc_search for a PMID describing the specific "
                    "regulatory relationship, then cite it), 'alliance' (call "
                    "alliance_gene_interactions for a documented genetic / physical interaction "
                    "with a PMID), 'pathway_resource' (Reactome / WikiPathways pathway "
                    "containing this step), 'orthology' (annotated ortholog pair), "
                    "'figure' (the arrow is drawn in the figure — snippet describes it), or "
                    "'instinct' (your inference, not drawn in the figure — justification required)."
                )
            }
        try:
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

    def _t_add_input(self, inp: dict) -> dict:
        try:
            src = self._make_source(inp["source"])
            key = self.builder.add_input(
                inp["activity_id"], inp["molecule"], source=src,
                label=inp.get("label"), molecule_kind=inp.get("molecule_kind", "molecule"),
            )
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True, "assertion": key}

    def _t_add_output(self, inp: dict) -> dict:
        try:
            src = self._make_source(inp["source"])
            key = self.builder.add_output(
                inp["activity_id"], inp["molecule"], source=src,
                label=inp.get("label"), molecule_kind=inp.get("molecule_kind", "molecule"),
            )
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True, "assertion": key}

    def _t_add_source(self, inp: dict) -> dict:
        try:
            src = self._make_source(inp["source"])
            key = self.builder.add_source(
                inp["activity_id"],
                inp["slot"],
                src,
                target_activity_id=inp.get("target_activity_id"),
            )
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True, "assertion": key}

    def _t_request_go_term(self, inp: dict) -> dict:
        import re
        label = inp["suggested_label"]
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:60] or "term"
        key = f"{self.builder.model_id}/needs/{slug}"
        extra: dict[str, str] = {
            "kind": "go_term_request",
            "aspect": inp["aspect"],
        }
        related = inp.get("related_terms") or []
        if related:
            extra["related_terms"] = ",".join(related)
        try:
            src = SourceObject(
                source_type="go_term_request",
                justification=inp["rationale"],
                snippet=label,
                extra=extra,
            )
        except Exception as e:
            return {"error": str(e)}
        self.builder._ledger.attach(key, src)  # noqa: SLF001
        return {"ok": True, "request_id": key}

    def _t_finalize(self, inp: dict) -> dict:
        self._finalized = True
        return {"ok": True, "summary": self.builder._ledger.count_by_source_type()}  # noqa: SLF001

    # -- loop ---------------------------------------------------------------

    def run(self, intent: CuratorIntent) -> tuple[Model, ProvenanceLedger]:
        guidelines = _load_guidelines()
        system_text = SYSTEM_PROMPT
        if guidelines:
            system_text += (
                "\n\n# GO / GO-CAM curation guidelines (authoritative)\n\n"
                "Apply these GO standards when choosing terms, relations, and "
                "evidence, and when deciding what to model.\n\n" + guidelines
            )
        # One cached system block — the guidelines are large and constant per run.
        system_blocks = [{
            "type": "text", "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }]

        messages: list[dict] = [
            {"role": "user", "content": self._initial_user_message(intent)},
        ]
        for turn in range(self.max_turns):
            response = create_message(
                self.client,
                model=self.model_name,
                max_tokens=self.max_tokens,
                system=system_blocks,
                messages=messages,
                tools=self._tools,
                effort=self.effort,
                adaptive_thinking=self.adaptive_thinking,
            )
            usage = getattr(response, "usage", None)
            self.events.append({
                "turn": turn,
                "stop_reason": getattr(response, "stop_reason", None),
                "input_tokens": getattr(usage, "input_tokens", 0),
                "output_tokens": getattr(usage, "output_tokens", 0),
            })

            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            stop_reason = getattr(response, "stop_reason", None)

            # Mirror the assistant's blocks back into messages, in the shape the
            # Anthropic API expects on the next turn. Adaptive-thinking blocks MUST
            # be echoed (with signature) ahead of tool_use within a turn — but ONLY
            # when this turn has a tool_use. A turn that produced NO tool call
            # (plain narration, or a max_tokens truncation mid-thinking) carries
            # thinking that may be incomplete/unsigned; echoing it back 400s and we
            # don't need it, so drop thinking from no-tool turns and keep any text.
            assistant_content: list[dict] = []
            for block in response.content:
                btype = getattr(block, "type", None)
                if btype in ("thinking", "redacted_thinking"):
                    if not tool_uses:
                        continue
                    if btype == "thinking":
                        assistant_content.append({
                            "type": "thinking",
                            "thinking": block.thinking,
                            "signature": getattr(block, "signature", ""),
                        })
                    else:
                        assistant_content.append({"type": "redacted_thinking", "data": block.data})
                elif btype == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif btype == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
            if not assistant_content:
                assistant_content = [{"type": "text", "text": "(no content)"}]
            messages.append({"role": "assistant", "content": assistant_content})

            if not tool_uses:
                if self._finalized:
                    break
                # No tool call this turn. Don't silently end with an empty / half-
                # built model — nudge the model back to the tools. Bounded so a model
                # that won't act can't loop forever; the post-loop / pipeline guard
                # surfaces a still-empty model rather than reporting false success.
                if self._empty_streak >= self.max_empty_nudges:
                    break
                self._empty_streak += 1
                nudge = (
                    "Your previous turn was cut off (hit the output-token limit) before "
                    "any tool call. Do NOT write long plans — make ONE tool call now and "
                    "build the model incrementally (a few tool calls per turn)."
                    if stop_reason == "max_tokens" else
                    "You returned no tool call. Keep building the model with the tools "
                    "(add_activity / set_* / add_causal); call finalize_model only once "
                    "every gene and edge is modeled."
                )
                messages.append({"role": "user", "content": nudge})
                continue
            self._empty_streak = 0

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
    events_out: str | Path | None = None,
) -> tuple[Model, ProvenanceLedger]:
    """Convenience entry point. Pulls Vertex config from env if no client given.

    If `events_out` is given, the per-turn event log (turn, stop_reason, token
    usage) is written there — persisted even if the run raises, so a failed /
    empty run is diagnosable after the fact.
    """
    cfg = VertexConfig.from_env()
    # Opus 4.8 is only provisioned on the Vertex *global* endpoint for this
    # project; regional endpoints (us-east5, ...) return 429/404.
    region = os.environ.get("ANTHROPIC_VERTEX_OPUS_REGION", "global")
    cli = client or make_client(cfg, region=region)
    mdl = (
        model_name
        or os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL")
        or "claude-opus-4-8"
    )
    orch = Orchestrator(builder=builder, client=cli, model_name=mdl, max_turns=max_turns)
    try:
        return orch.run(intent)
    finally:
        if events_out is not None:
            try:
                Path(events_out).write_text(json.dumps(orch.events, indent=2))
            except OSError:
                pass
