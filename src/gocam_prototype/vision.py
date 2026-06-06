"""Claude vision pass: research-paper figure → curator-intent JSON.

Research-backed two-stage (+verify) design (see
knowledge/research/figure-to-intent.md). Pathway-figure benchmarks show that
nodes extract well but directional causal edges are the weak point on a single
monolithic pass ("nodes are early, edges are late"), so:

  Stage A — perception: Opus 4.8 (Vertex global, high-res, adaptive thinking,
            explicit glyph legend, image-first) transcribes the figure
            exhaustively as free text.
  Stage B — structure: a regional model converts that transcription into the
            CuratorIntent schema via forced tool_use (no thinking).
  Stage C — verify: Opus 4.8 re-checks each candidate edge against the image and
            drops/corrects unconfirmable ones (cheap insurance vs hallucinated
            edges, the dominant failure mode).

Output is a Pydantic model so the orchestrator gets a typed, validated handle.
"""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import Literal

from anthropic import AnthropicVertex
from pydantic import BaseModel, ConfigDict, Field

from gocam_prototype.llm import VertexConfig, create_message, make_client

CompartmentKind = Literal[
    "cell_type",
    "tissue",
    "organelle",
    "cellular_component",
    "subcellular_region",
    "other",
]


class Compartment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(description="Compartment label as it appears in the figure (e.g., NEURONS, INTESTINE).")
    kind: CompartmentKind = Field(description="Best-guess kind for this compartment.")
    confidence: float = Field(ge=0, le=1)
    snippet: str = Field(description="Brief description of where this compartment appears in the figure.")


class GeneMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(description="Gene symbol exactly as it appears in the figure.")
    in_compartment: str | None = Field(
        default=None,
        description="Label of the compartment this gene appears in (must match a Compartment.label).",
    )
    confidence: float = Field(ge=0, le=1)
    snippet: str = Field(description="How the gene is depicted (shape, color, position).")


class TentativeEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_symbol: str | None = Field(default=None, description="Source gene symbol (for gene→gene edges).")
    to_symbol: str | None = Field(default=None, description="Target gene symbol (for gene→gene edges).")
    from_compartment: str | None = Field(default=None, description="Source compartment label (for compartment-level edges).")
    to_compartment: str | None = Field(default=None, description="Target compartment label (for compartment-level edges).")
    relation: str = Field(description="Natural-language relation, e.g. 'positively regulates', 'endocrine signal'.")
    via: str | None = Field(default=None, description="Intermediate molecule labeled on the arrow, if any (e.g. '5-HT').")
    confidence: float = Field(ge=0, le=1)
    snippet: str = Field(description="Where in the figure this edge appears.")


class CuratorIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    species: str = Field(description="Free-text species, ideally exactly as the paper labels it.")
    species_taxon: str | None = Field(
        default=None,
        description="NCBITaxon CURIE if you can identify it with high confidence; otherwise null.",
    )
    processes_hinted: list[str] = Field(default_factory=list)
    compartments: list[Compartment] = Field(default_factory=list)
    genes: list[GeneMention] = Field(default_factory=list)
    tentative_edges: list[TentativeEdge] = Field(default_factory=list)


GLYPH_LEGEND = """Glyph conventions:
- Solid pointed arrow (-->): ACTIVATION / positive regulation.
- Blunt T-bar (--|): INHIBITION / negative regulation.
- Dashed arrow: INDIRECT effect, or transport across distance (e.g. a secreted / endocrine signal between cells).
- Box / cell outline: a compartment or cell; an arrow crossing a boundary is an inter-cellular step."""

PERCEPTION_SYSTEM = (
    "You have perfect vision and pay meticulous attention to detail. You are "
    "transcribing a research-paper pathway figure for a biocurator. Transcribe "
    "EVERYTHING the figure shows, exhaustively and literally, BEFORE any biological "
    "interpretation:\n"
    "- Every gene / protein / molecule label, exactly as written (flag illegible ones).\n"
    "- Every compartment or cell box/outline (e.g. NEURONS, INTESTINE, nucleus) and "
    "exactly which labels sit inside each.\n"
    "- Every arrow / connector as its own line: SOURCE -> TARGET, the arrow's END "
    "TYPE, and any molecule written on the arrow.\n\n"
    + GLYPH_LEGEND
    + "\n\nOutput an itemized transcription (lists, not prose). Capture the figure with "
    "MAXIMUM FIDELITY — every node, every edge, every labelled cell/compartment, even small "
    "or peripheral ones. Do not infer biology that is not drawn. Attend to each arrow END "
    "individually — confusing a pointed arrowhead with a T-bar flips the biological meaning. "
    "If a label is faint or ambiguous, transcribe your best reading AND mark it uncertain "
    "(e.g. \"ADF? — faint\"); never silently normalize or guess a label."
)

STRUCTURE_SYSTEM = (
    "You convert an exhaustive transcription of a pathway figure into a structured "
    "curator-intent JSON for GO-CAM construction. The downstream goal is MAXIMUM FIDELITY "
    "to the figure with uncertainty flagged (not dropped). Rules:\n"
    "1. Include EVERY gene, compartment, and edge present in the transcription — do not omit "
    "anything the figure shows, and do not invent anything it does not.\n"
    "2. Use gene symbols exactly as transcribed.\n"
    "3. Map each arrow to a natural-language relation by its END TYPE: pointed arrow -> "
    "'positively regulates'; T-bar -> 'negatively regulates'; dashed -> name the indirect "
    "signal (e.g. 'endocrine signal'). Preserve any molecule on the arrow in `via`.\n"
    "4. Compartment `kind`: a tissue / cell-group label (e.g. NEURONS, INTESTINE) is "
    "'tissue' or 'cell_type'; an individual named cell (e.g. ADF, URX, RIC, a specific "
    "neuron) is 'cell_type'. Keep these distinct rather than collapsing them.\n"
    "5. CONFIDENCE carries uncertainty: set a low confidence (<=0.4) on any gene, compartment, "
    "or edge whose transcription was marked faint/ambiguous/uncertain, and explain in `snippet`. "
    "Keep the item — never drop it for being uncertain.\n"
    "6. Edges between whole compartments use from_compartment/to_compartment; gene-gene edges "
    "use from_symbol/to_symbol.\n"
    "7. Call submit_curator_intent exactly once with the complete result."
)

EDGE_VERIFY_SYSTEM = (
    "You have perfect vision. You are double-checking candidate causal edges against the actual "
    "figure. The goal is to FLAG uncertainty, not to delete edges: for each candidate decide "
    "whether the figure VISUALLY shows that connector in that direction, and whether the sign "
    "matches the arrow end. If it is not clearly drawn, mark it NOT confirmed (it will be kept but "
    "flagged low-confidence for the curator to scrutinize). If the arrow end implies a different "
    "sign/relation, give the corrected relation.\n\n"
    + GLYPH_LEGEND
)


def _image_block(image_b64: str, media_type: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}}


def _resize_for_vision(raw: bytes, *, max_long_edge: int = 2576) -> tuple[bytes, str]:
    """Downscale to <= max_long_edge on the long edge (never upscale) and re-encode as
    lossless PNG. Opus 4.8's native vision tops out at 2576px; resizing client-side
    controls downsample quality (preserving thin arrows/T-bars and small labels) and
    keeps us under Vertex's 5MB base64 cap. Falls back to raw bytes if Pillow or
    decoding is unavailable."""
    try:
        from PIL import Image
    except Exception:
        return raw, "image/png"
    try:
        im = Image.open(io.BytesIO(raw))
        if im.mode in ("RGBA", "P", "LA"):
            im = im.convert("RGB")
        w, h = im.size
        if max(w, h) > max_long_edge:
            s = max_long_edge / max(w, h)
            im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    except Exception:
        return raw, "image/png"


def _hint_text(species_hint: str | None, process_hint: str | None) -> str:
    parts = []
    if species_hint:
        parts.append(f"Species hint: {species_hint}.")
    if process_hint:
        parts.append(f"Process hint: {process_hint}.")
    return (" " + " ".join(parts)) if parts else ""


def extract_curator_intent(
    image_path: str | Path,
    *,
    species_hint: str | None = None,
    process_hint: str | None = None,
    client: AnthropicVertex | None = None,   # regional client for Stage B (structure)
    model: str | None = None,                # Stage B structuring model
    # Stage-B output is the FULL curator-intent JSON. A dense figure (figure2:
    # 18 genes + ~30 edges, each with a snippet) blows the old 4096 budget, and
    # because `tentative_edges` is the LAST field in the schema the output
    # truncates right at the edges — genes survive, edges silently vanish (looked
    # like a 0-edge figure). See the truncation guard below.
    max_tokens: int = 16000,
    verify_edges: bool = True,
    transcript_out: str | Path | None = None,
) -> CuratorIntent:
    """Figure -> CuratorIntent via the two-stage (+verify) design (see module docstring).

    If `transcript_out` is given, the Stage-A perception transcription is written
    there — a citable, inspectable record of what the vision pass read off the
    figure (so figure-derived claims are attributable; see #40).
    """
    image_path = Path(image_path)
    raw, media_type = _resize_for_vision(image_path.read_bytes())
    image_b64 = base64.b64encode(raw).decode()

    cfg = VertexConfig.from_env()
    opus_model = os.environ.get("ANTHROPIC_DEFAULT_OPUS_MODEL", "claude-opus-4-8")
    opus_region = os.environ.get("ANTHROPIC_VERTEX_OPUS_REGION", "global")
    structure_model = (
        model or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL") or "claude-sonnet-4-6@default"
    )
    opus_client = make_client(cfg, region=opus_region)
    structure_client = client or make_client(cfg)

    # -- Stage A: perception (image-first, high-res, adaptive thinking) --
    perc = create_message(
        opus_client,
        model=opus_model,
        max_tokens=12000,
        effort="high",
        adaptive_thinking=True,
        system=PERCEPTION_SYSTEM,
        messages=[{"role": "user", "content": [
            _image_block(image_b64, media_type),
            {"type": "text", "text": "Transcribe this pathway figure exhaustively per the instructions."
             + _hint_text(species_hint, process_hint)},
        ]}],
    )
    if getattr(perc, "stop_reason", None) == "max_tokens":
        raise RuntimeError(
            "Stage-A perception hit max_tokens — the figure transcription was truncated "
            "(arrows are listed late, so connectivity is lost first). Raise the Stage-A budget."
        )
    transcription = "".join(
        getattr(b, "text", "") for b in perc.content if getattr(b, "type", None) == "text"
    ).strip()

    if transcript_out and transcription:
        Path(transcript_out).write_text(
            "# Stage-A figure transcription (vision perception pass)\n\n"
            "Verbatim output of the Opus 4.8 perception stage — the figure-derived\n"
            "evidence that the curator-intent and any figure-sourced assertions draw on.\n\n"
            + transcription + "\n",
            encoding="utf-8",
        )

    # -- Stage B: structure (text-only, forced tool, no thinking) --
    resp = structure_client.messages.create(
        model=structure_model,
        max_tokens=max_tokens,
        system=STRUCTURE_SYSTEM,
        messages=[{"role": "user", "content":
            "Produce the curator-intent JSON from this figure transcription."
            + _hint_text(species_hint, process_hint) + "\n\nTRANSCRIPTION:\n" + transcription}],
        tools=[{"name": "submit_curator_intent",
                "description": "Submit the extracted curator-intent JSON for the figure.",
                "input_schema": CuratorIntent.model_json_schema()}],
        tool_choice={"type": "tool", "name": "submit_curator_intent"},
    )
    if getattr(resp, "stop_reason", None) == "max_tokens":
        # The forced-tool JSON was cut off. `tentative_edges` is the last schema
        # field, so a truncated parse yields genes-but-no-edges that still
        # validates — exactly the silent edge-loss this guard prevents.
        raise RuntimeError(
            "Stage-B structuring hit max_tokens — the curator-intent JSON was truncated "
            "(tentative_edges is the last field, so edges are dropped first). Raise max_tokens."
        )
    intent: CuratorIntent | None = None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_curator_intent":
            intent = CuratorIntent.model_validate(block.input)
            break
    if intent is None:
        raise RuntimeError("Structure stage did not return submit_curator_intent")

    # -- Stage C: visual edge verification (best-effort; never breaks extraction) --
    if verify_edges and intent.tentative_edges:
        try:
            intent = _verify_edges_against_figure(intent, image_b64, media_type, opus_client, opus_model)
        except Exception:
            pass
    return intent


def _verify_edges_against_figure(
    intent: CuratorIntent, image_b64: str, media_type: str, client: AnthropicVertex, model: str
) -> CuratorIntent:
    edges = intent.tentative_edges
    listing = "\n".join(
        f"{i}: {(e.from_symbol or e.from_compartment or '?')} --[{e.relation}]--> "
        f"{(e.to_symbol or e.to_compartment or '?')}" + (f" (via {e.via})" if e.via else "")
        for i, e in enumerate(edges)
    )
    tool = {
        "name": "report_edge_checks",
        "description": "Per candidate edge, report whether the figure visually confirms it.",
        "input_schema": {
            "type": "object", "additionalProperties": False,
            "properties": {"checks": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "confirmed": {"type": "boolean"},
                    "corrected_relation": {"type": ["string", "null"]},
                },
                "required": ["index", "confirmed"],
            }}},
            "required": ["checks"],
        },
    }
    resp = client.messages.create(
        model=model, max_tokens=3000, system=EDGE_VERIFY_SYSTEM,
        messages=[{"role": "user", "content": [
            _image_block(image_b64, media_type),
            {"type": "text", "text": "Candidate edges to check against the figure:\n" + listing
             + "\n\nFor each index, set confirmed (is this connector actually drawn, in this "
             "direction?) and corrected_relation if the arrow end implies a different sign (else null)."},
        ]}],
        tools=[tool], tool_choice={"type": "tool", "name": "report_edge_checks"},
    )
    checks: dict = {}
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "report_edge_checks":
            for c in (block.input or {}).get("checks", []):
                checks[c.get("index")] = c
            break
    if not checks:
        return intent
    # Flag, never delete: keep every edge; apply a corrected sign if given; and downweight +
    # annotate edges the figure does not clearly confirm so the curator knows to scrutinize them.
    kept = []
    for i, e in enumerate(edges):
        c = checks.get(i)
        if c is None:
            kept.append(e)
            continue
        update: dict = {}
        cr = c.get("corrected_relation")
        if cr:
            update["relation"] = cr
        if not c.get("confirmed", True):
            update["confidence"] = min((e.confidence if e.confidence is not None else 1.0), 0.3)
            note = (e.snippet or "").rstrip()
            update["snippet"] = (note + " " if note else "") + "[unconfirmed against figure in verification]"
        kept.append(e.model_copy(update=update) if update else e)
    return intent.model_copy(update={"tentative_edges": kept})
