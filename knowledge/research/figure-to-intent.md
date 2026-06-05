# Figure → intent: best models & settings (research brief)

Research on how to turn a research-paper pathway **figure** into a structured
**curator-intent** JSON (genes, compartments/cell-types, tentative causal edges)
for the GO-CAM builder. Scope: C. elegans signaling-pathway figures; backend is
Anthropic-on-Vertex; figures range ~550px panels to ~5000px multi-panel
composites with arrows (activation), T-bars (inhibition), dashed arrows, and
compartment/cell-outline boxes.

> **Verification note.** Findings below were produced by a multi-agent sweep and
> then adversarially source-checked. **8 of 36 raw findings were dropped or
> corrected** for fabricated/mis-attributed citations (a made-up "arrows are
> uncommon in training data" quote; a flowchart paper mis-cited; GOFlowLLM
> mis-framed as GO-CAM when it actually does miRNA GO annotation; a fabricated
> chart count). Only source-verified findings are kept here. Tool:
> `knowledge/tools/` workflows; verified 2026-06-05 against the cited sources.

## The headline

Every source converges on one split: **nodes/genes extract reasonably well;
directional causal edges (arrow vs T-bar) are the hard, unreliable part.** The
most directly applicable benchmark — LLMs on **200 PubMed tumor-signaling
figures** ([PMC13015812](https://pmc.ncbi.nlm.nih.gov/articles/PMC13015812/)) —
measured directional-edge **F1 ≈ 0.65–0.69 even for the best models**
(GPT-4oV 0.691 directional / 0.762 non-directional; Claude-3.5V 0.648 / 0.685;
Gemini-1.5V 0.578 / 0.615). **Implication: keep a human-in-the-loop on edges;
trust nodes more than edges.** This is the empirical form of the self-loop /
back-edge errors we already saw on figure1.

## Why edges are hard — and the pipeline shape it implies

**"Nodes are early, edges are late"** ([arXiv:2603.02865](https://arxiv.org/abs/2603.02865)):
VLMs encode node identity in the vision encoder but edge/direction only in late
language-model tokens. A single monolithic pass is therefore architecturally
weak for edges. The consensus design is **two-stage + verify**:

1. **Perception / describe** — transcribe nodes + every arrow/T-bar/compartment
   in free text first (describe-then-extract gives ~18.5% recall gains —
   SAVANT, [arXiv:2510.18034](https://arxiv.org/abs/2510.18034)).
2. **Structure** — convert that description to the `CuratorIntent` schema.
3. **Self-verify** — re-prompt each extracted edge "can this be visually
   confirmed in the figure?" to prune hallucinated edges (PMC13015812;
   [Frontiers Bioinformatics 2025](https://www.frontiersin.org/journals/bioinformatics/articles/10.3389/fbinf.2025.1687687/xml)).

PFOCR/WikiPathways reinforces the split: 25 years of pathway figures yield
*reliable gene mentions but deliberately no edges*
([PMC7649569](https://pmc.ncbi.nlm.nih.gov/articles/PMC7649569/)). Edge,
direction, and compartment extraction is exactly our value-add and the hard part.

## Model & resolution — biggest lever, favors Opus 4.8 on perception

- **Opus 4.8 native vision resolution = 2576px long edge / ~4784 image tokens;
  Sonnet 4.6 (and all non-Opus-4.7+ models) cap at 1568px**
  ([vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)).
  Our dense, up-to-5000px figures are silently downscaled on Sonnet, degrading
  the thin arrows/T-bars and small labels that matter most. **Opus 4.8 for the
  vision step is justified on resolution alone**, not just reasoning. Cost
  ≈ width·height/750 tokens, ~$0.02 per 3MP image on Opus.
- **Vertex caps base64 images at 5MB and has no Files API** → client-side resize
  is mandatory regardless.

## Image handling (our 550px–5000px range)

- **Resize large figures to ≤2576px long edge client-side** (control the
  downsample; prefer PNG/lossless; avoid heavy JPEG on line art).
- **Don't naive-upscale** small panels for "information," but legibility matters
  (<200px is the documented hallucination zone; 550px is above it, sub-panels
  risky). Modest 1.1–1.3× upscaling for legibility is documented practice.
- **Split dense multi-panel figures into per-panel sub-images** — repeatedly the
  highest-ROI preprocessing step, beating raw upscaling (Idefics
  [arXiv:2405.02246](https://arxiv.org/abs/2405.02246); Frontiers 2025 measured
  gains). Send sub-images in one request labeled "Image 1:", "Image 2:".
- **Image-before-text** ordering in the message (canonical vision-doc guidance).

## Prompting

- **Put an explicit glyph legend in the prompt**: solid arrow = activation,
  T-bar (⊣) = inhibition, dashed = indirect. The benchmark's best results came
  from spelling this out; prompt-optimization raised F1 (PMC13015812).
- **Reason/describe before committing** (chain-of-thought; role-prime "you have
  perfect vision, attend to detail") — cookbook-grounded, and the probing paper
  + SAVANT independently support describe-first.
- **Read labels precisely, then ground symbols → identifiers deterministically
  downstream** (don't trust the LLM for WB IDs) — the SPIRES/OntoGPT pattern
  ([Bioinformatics 2024](https://academic.oup.com/bioinformatics/article/40/3/btae104/7612230)),
  which is GO-ecosystem-native.

## Settings (Opus 4.8 specifics) — one real constraint

- **effort:** `high` floor for extraction; `xhigh` for the densest figures;
  **avoid `max`** (docs warn it can "overthink" structured-output tasks)
  ([effort docs](https://platform.claude.com/docs/en/build-with-claude/effort)).
- **adaptive thinking** on (`thinking:{type:"adaptive"}`, off by default on 4.8)
  so it can reason about ambiguous glyphs.
- **Constraint:** `output_config.format` (JSON-schema forcing) is **not
  compatible with thinking** per the structured-output docs. So you can't force
  the schema *and* think in one call. The **two-stage** design resolves this:
  Stage 1 reasons *with* thinking (free text); Stage 2 converts to JSON via
  `output_config.format` (no thinking; can run on cheaper Sonnet/Haiku). The
  "Format Tax" result ([arXiv:2604.03616](https://arxiv.org/abs/2604.03616))
  also shows hard format-forcing from the first token degrades quality on strong
  models — another reason two-stage wins.
- **max_tokens:** raise from 4096 (thinking + JSON truncates) to ~16k+; stream
  if larger.
- **No `temperature`/`top_p`/`top_k` on Opus 4.8** (they 400). Get sample
  diversity for self-consistency via **independent calls**, then element-level /
  constraint-aware voting on ambiguous edges (≥5 samples;
  [arXiv:2508.00255](https://arxiv.org/abs/2508.00255)).
- **Model-size tradeoff:** strongest model (Opus 4.8) for perception; the
  text-only Stage-2 JSON conversion can run on Sonnet 4.6 / Haiku 4.5 to save
  cost.

## Recommended design for `vision.py`

> **Stage A — perception:** Opus 4.8, region `global`, effort `high` (xhigh for
> dense), adaptive thinking on, image-first + explicit glyph legend, image
> resized to ≤2576px (split multi-panel) → free-text transcription of
> nodes / edges (with head type) / compartments.
> **Stage B — structure:** convert the description to `CuratorIntent` via
> `output_config.format` (Sonnet 4.6/Haiku OK; no thinking).
> **Stage C — verify:** re-check each edge against the image; drop unconfirmable
> edges. Then ground gene symbols → WB IDs deterministically downstream.

Don't assume the old "Claude lags GPT-4o" ordering — the benchmarks predate
Opus 4.8; evaluate it fresh on figure1/figure2.

## Verified sources

- Claude docs (platform.claude.com): vision, effort, adaptive-thinking,
  structured-outputs.
- PMC13015812 — LLMs + prompt optimization on 200 biological pathway figures
  (the directly applicable benchmark; directional-edge F1 numbers).
- arXiv:2603.02865 — "Nodes Are Early, Edges Are Late" (probing diagram reps).
- arXiv:2510.18034 — SAVANT (describe-then-extract recall gains).
- Frontiers Bioinformatics 2025 — panel cropping + two-step verification gains.
- PMC7649569 / PFOCR (WikiPathways) — figures give nodes, not edges.
- Bioinformatics 2024 / arXiv:2304.02711 — SPIRES / OntoGPT schema-constrained,
  grounded extraction.
- PMC10167483 — INDRA (text causal assembly; reusable causal representation).
- arXiv:2405.02246 (Idefics), arXiv:2508.00255 (graph self-consistency),
  arXiv:2604.03616 (format tax) — engineering settings.

## Dropped/corrected (failed source-check) — do not cite as-is

GOFlowLLM (PMC12790822) is miRNA GO **annotation** via flowcharts, **not**
GO-CAM; a "T-bars are the measured dominant failure mode" quote and an "arrows
uncommon in training data" quote were fabricated; a FlowExtract/FlowLearn
mix-up and a 13,858-chart figure were fabricated; a LookPlanGraph "VLM refused
when asked for a format" anecdote is from an unrelated robotics paper. The
underlying advice (two-stage, glyph legend) stands on the other verified
sources above.
