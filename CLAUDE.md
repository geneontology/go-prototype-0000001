# Notes for Claude working on this repo

## Validate `.github/workflows/*.yml` locally before pushing

GitHub Actions silently accepts unparseable workflow YAML: it renders
the file as zero-duration *"failed"* check-suite entries with
`jobs: []` on every push, and meanwhile drops the events the workflow
was supposed to handle (issues, dispatches, etc.) until the file
parses. There is no surfaced error message telling you *why* a run is
failing — the only way to know is to load the file locally:

```sh
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/run-agent.yml'))"
```

Run this any time you edit a workflow file. If parsing fails, the
exception's line/column points straight at the problem.

The whole `run-agent.yml` saga (#37) — months of "failed" pushes, the
agent never actually running on GHA, issue #36 silently dropped — was
a YAML block-scalar indentation bug that one local parse would have
caught immediately.

## Bash / Python parity when both layers process the same identifier

The workflow's *Resolve input* step writes the run-id and the
GH-Pages URL it comments back to the user. The Python CLI
(`src/gocam_prototype/cli.py:_slugify`) lowercases and sanitizes
that run-id before creating `docs/runs/<slug>/`. If bash and Python
disagree on the slug, the comment links to a 404 (GH Pages is
case-sensitive — see #38).

Whenever you touch `_slugify` on either side, update the other and
cross-check on at least: an auto timestamp, free-text with spaces /
punctuation, an already-lowercase id, and the empty string. They
must return identical output.

## The agent reads `guidelines.md`, NOT `rules.yaml`

The knowledge pack has two files. `knowledge/go-curation-guidelines.md`
(prose) is the only one **injected into the orchestrator's system prompt**
(`orchestrator.py` loads it as a cached block). `knowledge/go-curation-rules.yaml`
is the machine-readable companion: it's the spec for the validator
(`src/gocam_prototype/validate.py`) and a reference — it is **not** sent to the
model. So adding or changing a rule only in the YAML will *not* change agent
behavior; mirror anything meant to steer the agent into the markdown. (This bit
us on #39: the MF-class patterns had to go into both.)

## A new `SourceType` must be mirrored into the agent-facing tool schema

`provenance.SourceType` (the Literal) is the *storage* vocabulary. The agent can
only ever emit a source type that is ALSO in `SOURCE_OBJECT_SCHEMA["properties"]
["source_type"]["enum"]` in `orchestrator.py` — that enum is what the tool-use
API validates the model's arguments against. The two lists are maintained by
hand and drift silently: a type present in the Literal but missing from the enum
is un-emittable, and the agent will fall back to the nearest allowed type with
no error. This bit us adding `figure` (#40): the storage type, validator, and
viewer all supported it, but the enum omitted it, so a full figure1 re-run
produced zero `figure` sources (the agent used `instinct` instead). When you add
a source type, update: the Literal (`provenance.py`), the enum + the SOURCE
TYPES prose + any when-to-use guidance (`orchestrator.py`), the viewer
(`SOURCE_META`, `CHIP_SOURCE_ORDER`, badge/legend in `cli.py`), and the CSS
swatch. Grep the old type name to find every site.

## Provenance is per-claim: each assertion key holds a LIST of sources

`ProvenanceLedger.assertions` maps each key to a `list[SourceObject]` (v2). One
statement can carry separately-attributed claims — e.g. an `enabled_by` slot
holds the `figure` source (the figure draws this gene box) AND the `alliance`
source (its CURIE resolution). `builder.add_activity` / `set_*` / `add_causal`
take the *primary* source; layer further claims with `builder.add_source(...)`
(agent tool: `add_source`). Readers must dual-read both shapes — v1 runs stored a
single object per key — so `cli.summarize_provenance`, `validate.py`, and
`viewer.js` (`srcList()`) all normalize list-or-object. The pydantic
`ProvenanceLedger` model itself is v2-only; v1 `provenance.json` files are read as
raw JSON by the summarizer and the JS viewer, never re-validated through the model.

## Opus 4.8 on Vertex: global endpoint, effort/thinking via `extra_body`

The orchestrator and the vision perception pass run `claude-opus-4-8`. For this
project Opus 4.8 is only served on the Vertex **`global`** endpoint — regional
endpoints (us-east5, …) return 429/404 — so build the client with
`region="global"` (env `ANTHROPIC_VERTEX_OPUS_REGION`). The installed `anthropic`
SDK has no native `effort`/`output_config` kwarg, so `llm.create_message`
passes `extra_body={"output_config":{"effort":"xhigh"},"thinking":{"type":"adaptive"}}`.
Gotchas, all verified 2026-06-05 (see [[reference-vertex-ai-go]] in memory):
- `effort` is nested under `output_config` (top-level → 400 "Extra inputs not permitted").
- Opus 4.8 has no `temperature`/`top_p`/`top_k`/prefill and no manual
  `budget_tokens` (adaptive thinking only) — all 400.
- With adaptive thinking + tool use you MUST echo returned `thinking` blocks
  (with signature) back on the next turn, ahead of the `tool_use`, or it 400s.
- `output_config.format` (JSON-schema output) is incompatible with thinking —
  this is why the vision pass is two-stage (reason free-text, then a separate
  no-thinking structuring call forces the schema).

## `has_input`/`has_output` live in `Activity.molecular_associations`, not as direct slots

gocam-py's `Activity` has **no** `has_input`/`has_output` fields. Inputs/outputs are
`MoleculeAssociation` entries in `Activity.molecular_associations`, each with
`predicate` = `RO:0002233` (has_input) / `RO:0002234` (has_output) and `molecule`
= a CURIE (ChEBI for chemicals, a gene CURIE for a TF target). `builder.add_input`/
`add_output` wrap this; the molecule term object is `MoleculeTermObject` for ChEBI
or `GeneProductTermObject` for a gene (builder `TermKind` 'molecule' vs
'gene_product'). The viewer (`viewer.py`) renders each as an individual + fact with
IRI == the provenance key `<activity>/has_input|has_output/<molecule>`, so the panel
resolves the source on click; `viewer.js` `slotOf()` maps those keys back to the slot.
Per the GO-CAM **pathway-boundary** rule, the downstream-response gene-SETS
("antimicrobial defence genes", "ESRE") are deliberately NOT modeled as nodes/edges —
a TF that targets them gets `part_of` regulation-of-transcription (+ `has_input` a
*named* target gene), not a causal edge to a compartment or gene set.

## Dense figures need streaming + a big `max_tokens` — else EMPTY or silently incomplete

The orchestrator loop (`orchestrator.py`) treats a turn with no `tool_use` block
as "model is done" — but a dense figure (figure2: 17 genes / 29 edges) makes a
single adaptive-thinking turn exceed the output-token budget and **truncate**
(`stop_reason=max_tokens`) *before* it emits any tool call. The old behaviour
silently wrote a 0-activity model and printed "Done" — a false success. Two
coupled facts to remember when touching the loop or the LLM wrapper:

- `max_tokens` must hold a planning turn's *thinking + tool calls*. figure2
  peaked at ~19200 output tokens in one turn; the old 16000 truncated it. It's
  now 32000 (`Orchestrator.max_tokens`).
- The Anthropic SDK **refuses a non-streaming request** whose `max_tokens` could
  run past the 10-minute server limit (`ValueError: Streaming is required …`).
  So `llm.create_message` **streams** (`client.messages.stream(...).get_final_message()`).
  If you revert to `.create()`, a large `max_tokens` will raise before any API call.

Guards now in place (don't remove): no-tool turns are *nudged* back to the tools
(bounded by `max_empty_nudges`) instead of silently ending; per-turn events
(stop_reason, usage) persist to `docs/runs/<id>/orchestrator_events.json` even on
raise — check it first when a run looks empty/short; and `cli.run_pipeline`
prints a loud `[WARN]` if it produced 0 activities from a non-empty gene list.

**Same class, second instance — a truncated FORCED-TOOL call drops its last
schema field and still validates.** Vision Stage-B (`vision.py`, the structuring
call) emits the whole `CuratorIntent` as one forced `submit_curator_intent`
tool call. On a dense figure it hit `max_tokens=4096` and truncated mid-JSON —
but because `tentative_edges` is the LAST field of `CuratorIntent`, the partial
tool input still passed `model_validate` (edges just defaulted to `[]`), so the
run looked like a real "0-edge figure" with no error. This is nastier than the
orchestrator case (valid-but-incomplete, not empty). Fixes: Stage-B `max_tokens`
→ 16000, Stage-A → 12000, and **both stages now raise on
`stop_reason == "max_tokens"`** (`0f1e0b1`). Takeaways: any forced-tool /
structured-output call is vulnerable — guard on `stop_reason` and raise loudly,
never trust a truncated parse; and the *last* field of the schema vanishes
first, so adding a field after `tentative_edges` changes which one silently
drops (re-check the guard if you reorder `CuratorIntent`).

## Evidence lands in the LinkML model via the GAF-code→ECO map — never fabricate ECO:0000314

Every database-backed / literature source now mints a real
`EvidenceItem(term=<ECO>, reference=<PMID/GO_REF>, with_objects, provenances)` on
its association (`builder._evidence`, no longer literature-only). The ECO term
comes from the source's actual GAF `evidence_code` (IDA/IBA/ISS…) via
`eco.py:eco_for_go_code` — a **vendored snapshot** of the canonical
`gaf-eco-mapping-derived.txt` (refresh by re-pulling that file). The ONLY
fallback is `ECO:0000000`; a hard-coded `ECO:0000314` (direct assay) must never
be a default — that fabricates evidence (the #52 bug). The agent gets
`evidence_code`/`reference`/`term_label` from `go_gene_annotations` (which derives
`aspect` from `object.category` — the GO API leaves `aspect` null) and copies
them onto the `go_annotation` source; figure/instinct stay sidecar-only (no
EvidenceItem). When adding a slot/source path, route real evidence through
`_evidence`, don't re-introduce a 0000314 default.

## ProvenanceInfo.contributor is a BARE ORCID everywhere — keep new write-sites consistent

A curator/contributor ORCID is written as the bare id (`0000-0002-1190-4481`),
NOT the full `https://orcid.org/…` URL — in `demo.py`, the vendored
`docs/assets/curators.json` (`curators.py` strips the prefix), the
`curator-action.yml` issue template, and `builder._evidence`. gocam-py's LinkML
declares `orcid: https://orcid.org/` as the prefix, so the bare form is the local
convention (not the CURIE `orcid:…` form). Mixing forms keys the same curator as
two distinct `ProvenanceInfo.contributor` values (a review caught this). Any new
path that writes a contributor must emit the bare ORCID. The roster is
`curators.json`, built by `gocam_prototype.curators` from go-site `users.yaml`
allow-edit entries; the viewer's self-id picker is **self-asserted/unverified**
(static GH-Pages has no auth) — verified attribution only via the authenticated
issue→re-run path.

## Alliance API shape drifts — run the drift-canary

`src/gocam_prototype/alliance.py` is pinned to the Alliance REST shape as of
2026-06 (resolution via `/api/search_autocomplete`; gene record nested under
`.gene` with `{displayText}` fields; interactions at `/molecular-interactions`;
orthology under `geneToGeneOrthologyGenerated.objectGene`). When it drifts the
wrappers fail *silently* — `resolve_symbol_to_curie` returns `None`, the agent
falls back to `instinct`, and gene IDs can be guessed *wrong* (this happened: 4
of 6 WBGene IDs were wrong-but-flagged before #48). If gene resolution looks
off, run the live canary:

```sh
GOCAM_RUN_LIVE_TESTS=1 uv run pytest tests/test_alliance.py -q
```

It resolves `tph-1 -> WB:WBGene00006600` against the live API; a failure means
the shape moved again.

## A molecule relation lives in FOUR sites — keep them in lockstep

A small-molecule / target-gene relation slot (`has_input`, `has_output`,
`has_small_molecule_activator` RO:0012001, `has_small_molecule_inhibitor`
RO:0012002) is maintained by hand across four files, and they drift silently:

- `builder._MOLECULE_RELATIONS` (slot → RO predicate + label) — the *write* side;
- `viewer.py:_MOLECULE_PREDICATE_SLOT` (RO predicate → slot) — turns the model
  back into the per-molecule individual IRI / provenance key;
- `viewer.js:MOLECULE_SLOTS` (the slot list driving `slotOf`, the edge-chip
  fallback, and the activity-panel aggregation) **and**
  `viewer.js:MOLECULE_PREDICATE_SLOT` (RO predicate → slot, for relay edges).

Adding a relation means editing all four **plus** the orchestrator tool +
handler + prompt, and the §4b / slot-table prose in `guidelines.md` (the agent
reads the markdown, not rules.yaml). A predicate present in the builder but
missing from `viewer.py`'s map silently renders as `has_input`; missing from the
JS maps and its node loses panel/chip provenance. The small-molecule
activator/inhibitor choice (#53) is RO:0012001/0012002 (MF→ChEBI, shape-grounded),
**not** the WIP RO:0012005/0012006 "is small molecule …of" stubs — `validate.py`'s
`receptor-ligand-not-has-input` lint (label-heuristic, warn-only) guards against
regressing a receptor/channel ligand back to `has_input`.

**Scope: RO:0012001/0012002 are NOT receptor-only.** `go-cam-shapes.shex` puts
`has_small_molecule_activator/inhibitor/regulator` on the `<MolecularFunction>`
shape (any activity, ChEBI object), and the RO defs say "the process is
activated/inhibited by the small molecule" — so they attach to *any* MF the
molecule **directly (non-covalently) binds** (receptor ligand OR allosteric
enzyme/kinase regulator). The real constraint is **directness**, not "is it a
receptor": don't pin an *upstream* stimulus (a toxin a cascade senses) or an
*indirect/opposite* effect (a metabolite driving degradation via an intermediary)
as a direct activator — those go through causal flow / the shared-ChEBI relay.
This is a label-heuristic the validator can't enforce, so it lives in the prompt
+ guidelines §4b. Do **not** re-narrow the tool to receptors (figure2-005 over-
applied it to kinases/TFs, which surfaced the directness rule — not a scope cap).

## occurs_in is a GO CC; the cell type is a part_of EXTENSION (not the term)

`set_occurs_in`'s `term` is ALWAYS a GO cellular component (GO:0005575
descendant). The cell type the activity happens in is the GO-CAM
`CellularAnatomicalEntityAssociation.part_of = CellTypeAssociation(term=<CL>)`
extension (#54), passed as the optional `cell_type` arg and keyed
`<activity>/occurs_in/cell_type` in the sidecar. Do **not** put a CL/WBbt term
in the occurs_in `term` slot (the #52-pt7 confusion). `viewer.py` renders the
cell type as its own CL individual (root-type `CL:0000000` cell) + a BFO:0000050
fact off the CC individual, so the go-gocam-viewer draws it as a connected node.
The cell type is grounded by `celltype.resolve_cell_type` (verified-CL seed →
OLS4 exact-label lookup in the taxon's ontologies — WBbt then CL for worm),
which is deliberately conservative: it returns `None` (→ omit the extension)
rather than guess.

**The resolver's network is OFF by default — production MUST opt in.**
`resolve_cell_type` only hits OLS when `allow_network=True` (or a client is
passed, or `GOCAM_RUN_LIVE_TESTS=1`); otherwise it answers from the **seed map
only** and returns `None` for anything unseeded. This keeps the unit suite
offline, but it silently broke #54 in production: a real `gocam-prototype run`
sets none of those, so `resolve_cell_type('intestinal cell')` returned `None`
and figure2 could never get a cell type — while figure1 worked purely because
`neuron`/`sensory neuron` are *seeded*. The orchestrator now passes
`allow_network=self._cells_online()` at both call sites (`_t_resolve_cell_type`
and `_cellular_context_block`); `_cells_online()` is True in production and
False under pytest (via `PYTEST_CURRENT_TEST`), so live runs reach OLS and the
suite stays offline. Lesson: a default-off network gate keyed on a *test* env
var also disables the feature in production — gate on "am I a test", not "is the
live flag set". Three rounds of #54 work (framing, nudge, auto-complete) chased
a phantom "agent ignores the cell type" when the real cause was this gate
returning `None` before any agent decision.

The cell type the agent omits is also **auto-completed** in `_t_set_cc`: when an
activity's gene sits in a pre-grounded cell (the shared `_gene_cell_map`, by gene
symbol with a sole-cell fallback) and `cell_type` was not supplied, the handler
fills the grounded CURIE with a `figure` source. occurs_in stays the agent's
call; only the dropped extension is completed.

## A ChEBI relay renders as ONE shared node, but provenance stays per-activity

A ChEBI molecule that one activity `has_output`s and another consumes
(`has_input`/activator/inhibitor) is merged by `viewer.py` into a single shared
individual `<model>/molecule/<CHEBI>` that both activities' facts point at (#51)
— the producer↔consumer relay would otherwise be two disconnected copies. Only
ChEBI relays merge; a gene-product `has_input` (a TF target) is never shared.
The shared node's IRI is **not** a provenance key, so the ledger keeps the
per-activity keys (`<act>/<slot>/<mol>`) untouched; `viewer.js` reconstructs
them on click/hover (`handleNodeClick` Case 0 aggregates every key ending in the
CURIE; `edgeChipEmoji` rebuilds `<activity>/<slot>/<curie>` from the edge's
predicate). If you change the shared-IRI shape, update `sharedMoleculeCurie` and
both reconstruction sites together.

## Locations and cell types are PER-ACTIVITY individuals — never merge them (unlike #51)

It is tempting to extend the #51 ChEBI-relay merge to the repeated location/cell
nodes a fan-out figure produces (figure2: 17 activities all `occurs_in` an
intestinal cell → 17 identical cell nodes). **Don't** — per-activity is the
GO-CAM standard, not clutter to dedupe. `Activity.occurs_in` is a
`CellularAnatomicalEntityAssociation` embedded *on each activity* (its `part_of`
cell type hangs off that); the LinkML model has no shared-location slot. A real
published GO-CAM confirms it — `gomodel:568b0f9600000284`
(`api.geneontology.org/api/go-cam/568b0f9600000284`) renders cytoplasm
`GO:0005737` as **five separate individuals**, one per activity. So `viewer.py`
correctly mints `<activity>/occurs_in` and `<activity>/occurs_in/cell_type` per
activity. The #51 merge is justified ONLY because a produced→consumed molecule is
one physical pool *flowing between* activities (a real connectivity edge); a
shared location asserts no such flow, so merging it would invent structure the
model does not state. If clutter is the worry, the standard-safe fix is
cosmetic/viewer-only (CSS/layout), never a model-graph change. (Verified
2026-06-16; the "one shared cell node" idea was rejected on these grounds — see
[[feedback-conform-to-gocam-standards]] in memory.)

## A sparse / disconnected model can be FAITHFUL — don't "fix" a fan-out figure

An overview figure of parallel pathways legitimately yields many disconnected
activity-units; that is correct, not a dropped-edge bug. GO-CAM connectivity
comes from gene→gene causal edges + shared molecules — a figure whose connective
tissue runs through NON-gene entities (a compartment like the nucleus, a
mitochondrial mtROS hub, a pathogen) cannot become causal edges, because those
are not gene-product activities. Concretely (figure2-010): 17 activities, 6
causal edges, 9 singletons — and every singleton's only drawn relationship was an
arrow into a compartment (`TF → Nucleus`), which the pathway-boundary rule turns
into `occurs_in`, not a causal edge. So **before treating disconnection as a bug,
read the curator-intent `tentative_edges`**: if the singletons' only edges point
at compartments/gene-sets, the sparse model is faithful and inventing gene→gene
edges to tidy it would violate the standard. The standard-compliant way to add
real connectivity is each sensor's upstream molecular input where the interaction
is genuinely direct (e.g. nhr-86 `has_small_molecule_activator` phenazine/PCN, a
verified ligand — Peterson et al., Immunity 2023, doi:10.1016/j.immuni.2023.01.027).
