"""Framing / curation-plan pass (#53/#54 Tier 2).

A short deliberation pass between the vision pass and the orchestrator. Given the
curator-intent + the figure transcription, it pre-classifies, up front:

* each gene's **MF-class** (receptor / channel / nuclear receptor / enzyme /
  kinase / transcription factor / adaptor / transporter), and
* each small molecule's **participant role** — the DIRECTNESS call that the
  build loop keeps getting wrong under load: a direct (non-covalent) activator/
  inhibitor of a specific activity, vs an enzyme substrate, vs an UPSTREAM
  stimulus a cascade merely senses (e.g. a pathogen toxin), vs a pathway output.

The orchestrator injects the rendered plan into its first message as a DRAFT to
execute and revise with evidence — reason-first, then build, the modeling analog
of the vision pass's transcribe-before-extract. Best-effort: a failure here must
never break the pipeline (the caller falls back to no plan).
"""

from __future__ import annotations

import os
from typing import Literal

from anthropic import AnthropicVertex
from pydantic import BaseModel, ConfigDict, Field

from gocam_prototype.llm import VertexConfig, make_client
from gocam_prototype.vision import CuratorIntent

PLAN_SYSTEM = (
    "You are a senior GO-CAM curator planning how to model a pathway figure BEFORE the "
    "model is built. You are given the curator-intent JSON and the figure transcription. "
    "Produce a concise CURATION PLAN that the builder will execute. Do NOT build the model; "
    "classify roles so the builder does not have to improvise.\n\n"
    "For EACH gene, assign an mf_class from its likely molecular function:\n"
    "- signaling_receptor / ligand_gated_channel / nuclear_receptor — a receptor or channel;\n"
    "- enzyme / kinase — a catalytic activity;\n"
    "- transcription_factor — a DNA-binding/transcription regulator;\n"
    "- signaling_adaptor / transporter / other — as fits.\n\n"
    "For EACH small molecule the figure shows (arrow `via` labels and any chemical), assign a "
    "participant role — this is the key DIRECTNESS judgment:\n"
    "- direct_activator / direct_inhibitor: the molecule DIRECTLY (non-covalently) binds and "
    "regulates a SPECIFIC activity (a receptor/channel ligand, OR an allosteric activator/"
    "inhibitor of an enzyme/kinase). Set acts_on to that gene. This maps to "
    "has_small_molecule_activator/inhibitor (RO:0012001/0012002).\n"
    "- enzyme_substrate: a substrate an enzyme consumes/transforms (has_input). Set acts_on.\n"
    "- pathway_output: a product an activity makes (has_output). Set acts_on to the producer.\n"
    "- upstream_stimulus: a signal/toxin/metabolite that the pathway SENSES or responds to but "
    "that does NOT directly bind the downstream enzymes/TFs (e.g. a pathogen toxin upstream of a "
    "kinase cascade). Do NOT pin it as a direct activator of a cascade component — it belongs in "
    "causal flow or as input to the sensing step. acts_on may be null.\n"
    "- cofactor_or_currency: ATP/ADP/metal ions etc. usually OMITTED.\n"
    "CHECK THE SIGN: a molecule that drives a target's DEGRADATION (via an intermediary) is an "
    "inhibitor of that target's accumulation, NOT an activator — flag such indirect/opposite "
    "cases as upstream_stimulus or note the intermediary. When a molecule is produced by one "
    "activity and consumed by another, say so (a producer->consumer relay).\n"
    "Be faithful to the figure; flag uncertainty in the notes rather than dropping it."
)


class GenePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(description="Gene symbol exactly as in the intent.")
    mf_class: Literal[
        "signaling_receptor", "ligand_gated_channel", "nuclear_receptor",
        "enzyme", "kinase", "transcription_factor", "signaling_adaptor",
        "transporter", "other",
    ]
    note: str = Field(description="One line: this gene's role in the pathway.")


class MoleculePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(description="Molecule label as the figure shows it (e.g. 'pyocyanin').")
    role: Literal[
        "direct_activator", "direct_inhibitor", "enzyme_substrate",
        "pathway_output", "upstream_stimulus", "cofactor_or_currency", "other",
    ]
    acts_on: str | None = Field(
        default=None,
        description="Gene symbol this molecule directly acts on / is produced by, for "
                    "activator/inhibitor/substrate/output roles; null for an upstream stimulus.",
    )
    directness_note: str = Field(
        description="WHY this role — for upstream_stimulus / indirect / wrong-sign cases, say so.",
    )


class CurationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pathway_summary: str = Field(description="2-3 sentences: what the pathway does + boundaries.")
    genes: list[GenePlan] = Field(default_factory=list)
    molecules: list[MoleculePlan] = Field(default_factory=list)


def make_curation_plan(
    intent: CuratorIntent,
    transcription: str | None = None,
    *,
    client: AnthropicVertex | None = None,
    model: str | None = None,
    max_tokens: int = 8000,
) -> CurationPlan:
    """Run the planning pass and return a CurationPlan (forced tool use).

    Raises on a truncated/empty plan so the caller can fall back. Uses the Vertex
    Opus global endpoint by default (same as the orchestrator)."""
    if client is None:
        cfg = VertexConfig.from_env()
        region = os.environ.get("ANTHROPIC_VERTEX_OPUS_REGION", "global")
        client = make_client(cfg, region=region)
        model = model or cfg.opus_model
    user = (
        "Plan how to model this figure. CURATOR-INTENT JSON:\n```json\n"
        + intent.model_dump_json(indent=2, exclude_none=True)
        + "\n```"
    )
    if transcription:
        user += "\n\nFIGURE TRANSCRIPTION:\n" + transcription
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=PLAN_SYSTEM,
        messages=[{"role": "user", "content": user}],
        tools=[{"name": "submit_curation_plan",
                "description": "Submit the curation plan for the figure.",
                "input_schema": CurationPlan.model_json_schema()}],
        tool_choice={"type": "tool", "name": "submit_curation_plan"},
    )
    if getattr(resp, "stop_reason", None) == "max_tokens":
        raise RuntimeError(
            "Curation-plan pass hit max_tokens — the plan JSON was truncated "
            "(molecules is the last field, so molecule roles are dropped first). Raise max_tokens."
        )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "submit_curation_plan":
            return CurationPlan.model_validate(block.input)
    raise RuntimeError("Planning pass did not return submit_curation_plan")


def render_plan(plan: CurationPlan) -> str:
    """Format a CurationPlan as a prompt block for injection into the orchestrator."""
    lines = [
        "CURATION PLAN (a DRAFT from a planning pass — execute it, but REVISE any item you "
        "find evidence against; it is guidance, not ground truth):",
        f"Pathway: {plan.pathway_summary}",
    ]
    if plan.genes:
        lines.append("Genes (MF-class -> how to model):")
        for g in plan.genes:
            lines.append(f"  - {g.symbol}: {g.mf_class} — {g.note}")
    if plan.molecules:
        lines.append("Small molecules (role -> how to attach):")
        _ROLE_HINT = {
            "direct_activator": "add_activator (RO:0012001) on its acts_on activity",
            "direct_inhibitor": "add_inhibitor (RO:0012002) on its acts_on activity",
            "enzyme_substrate": "add_input on its acts_on activity",
            "pathway_output": "add_output on its acts_on (producer) activity",
            "upstream_stimulus": "NOT a direct activator — causal flow / sensing-step input",
            "cofactor_or_currency": "usually OMIT (currency/cofactor)",
            "other": "curator judgment",
        }
        for m in plan.molecules:
            on = f" [{m.acts_on}]" if m.acts_on else ""
            lines.append(
                f"  - {m.label}: {m.role}{on} -> {_ROLE_HINT.get(m.role, '')}. {m.directness_note}"
            )
    return "\n".join(lines)
