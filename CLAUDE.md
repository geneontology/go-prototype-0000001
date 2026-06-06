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
