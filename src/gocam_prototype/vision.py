"""Claude vision pass: research-paper figure → curator-intent JSON.

The agent in v0 uses this to seed model construction with the genes,
compartments, and tentative causal edges visible in the figure. Output
is a Pydantic model so the orchestrator gets a typed, validated handle.
We force structured output via tool-use (single tool, required choice)
because that's more reliable than asking the model to emit free-form
JSON.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Literal

from anthropic import AnthropicVertex
from pydantic import BaseModel, ConfigDict, Field

from gocam_prototype.llm import VertexConfig, make_client

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


SYSTEM_PROMPT = """\
You are an assistant biocurator helping construct a GO-CAM (Gene Ontology Causal Activity Model) from a \
research-paper pathway figure. You will receive an image and a short context. Your job is to extract a \
structured curator-intent JSON capturing only what the figure ACTUALLY shows: species, biological \
processes hinted at by labels/captions, compartments (NEURONS / INTESTINE / nucleus / etc.), gene \
symbols and which compartment each is in, and tentative causal edges.

Strict rules:
1. Only extract content visible in the image. When uncertain, lower the confidence and explain in the snippet.
2. Use gene symbols EXACTLY as written.
3. For edges that connect whole compartments (e.g. an endocrine signal between NEURONS and INTESTINE), use \
   from_compartment / to_compartment instead of from_symbol / to_symbol.
4. For edges that connect specific genes, use from_symbol / to_symbol. If the arrow passes through an \
   intermediate molecule like a neurotransmitter, name it in `via`.
5. Do not invent genes, compartments, or edges. If a label is illegible, skip it.
6. Call `submit_curator_intent` exactly once with the complete result.
"""


def extract_curator_intent(
    image_path: str | Path,
    *,
    species_hint: str | None = None,
    process_hint: str | None = None,
    client: AnthropicVertex | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
) -> CuratorIntent:
    """Run Claude vision on the given image and return a typed CuratorIntent."""
    image_path = Path(image_path)
    media_type = _guess_media_type(image_path)
    image_b64 = base64.b64encode(image_path.read_bytes()).decode()

    chosen_model = (
        model
        or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL")
        or "claude-sonnet-4-6@default"
    )

    cli = client or make_client(VertexConfig.from_env())

    user_text_parts: list[str] = ["Extract a curator-intent JSON for this figure."]
    if species_hint:
        user_text_parts.append(f"Species hint: {species_hint}.")
    if process_hint:
        user_text_parts.append(f"Process hint: {process_hint}.")
    user_text = " ".join(user_text_parts)

    response = cli.messages.create(
        model=chosen_model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
        tools=[
            {
                "name": "submit_curator_intent",
                "description": "Submit the extracted curator-intent JSON for the figure.",
                "input_schema": CuratorIntent.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "submit_curator_intent"},
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_curator_intent":
            return CuratorIntent.model_validate(block.input)
    raise RuntimeError("Vision call did not return submit_curator_intent")


def _guess_media_type(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "image/png")
