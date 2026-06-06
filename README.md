# go-prototype-0000001

GO-CAM curation prototype: an LLM agent reads a research-paper pathway figure
(or a list of genes), constructs a GO-CAM model using `gocam-py`, and renders
it as an interactive page where every node and edge surfaces its source —
literature, database lookup, AmiGO lookup, or explicitly flagged LLM
"instinct."

This is an experimental prototype; it doesn't aim to replace any existing
GO Consortium tooling.

## v0 thin slice

End-to-end:

1. **Input.** Either a research-paper pathway figure (e.g.,
   `inputs/figure1-celegans-serotonin-fat-loss.png`) or a list of genes + a
   species + an optional process hint.
2. **Vision pass** — two-stage (Opus 4.8 perceives the figure → a model
   structures it into the curator-intent schema → an edge-verify pass) extracts
   genes, compartments, and tentative causal edges.
3. **Retrieval.** GO API + Golr + Alliance of Genome Resources, in that
   order of authority. Existing GO-CAMs and standard annotations first;
   Alliance phenotypes / interactions / expression second.
4. **Construction.** Agent assembles a `gocam-py` `Model`. Every assertion
   carries a `source object` (`literature` / `database` / `amigo` / `instinct`).
   The agent never fabricates citations — if it has no evidence, it tags
   the source as `instinct` with a justification.
5. **Rendering.** Static page in `docs/` wraps the published
   `<go-gocam-viewer>` web component, injects the model via
   `setModelData(...)`, exposes both node and edge clicks, and renders a
   custom provenance panel.

The plan is broken into 12 GitHub issues (`v0` label). Open issues are the
project journal: each commit references and closes the issue it implements.

## Architecture

```
   curator submits ──► GH Issue Form ──► GH Actions (issues: run-agent-request)
   image / genes        │
                        ├─ Vision: two-stage (Opus 4.8 perceive → structure → edge-verify)
                        ├─ GO API / Golr / Alliance retrieval tools
                        ├─ Orchestrator: Claude tool-use loop (Opus 4.8, effort=xhigh),
                        │    grounded in knowledge/go-curation-guidelines.md → gocam-py Model
                        ├─ Validator: lint vs knowledge/go-curation-rules.yaml
                        ▼
   docs/runs/<run-id>/  (committed; published via GH Pages)
     model.yaml         (gocam-py LinkML YAML)
     provenance.json    (sidecar: per-assertion source object)
     viewer.json        (bbop-graph "active model" the viewer injects)
     validation.json    (GO-CAM lint findings)
     figure.<ext>       (the source figure)
     index.html         (loads @geneontology/web-components, custom provenance panel)
```

The agent is grounded in a GO best-practices **knowledge pack** (`knowledge/`,
mined from the GO docs, the GO-CAM relations vocabulary, `go-shapes`, and the GO
MF-annotation guide — see `knowledge/research/figure-to-intent.md` for the
vision-step rationale). `go-curation-guidelines.md` is injected into the agent's
prompt; `go-curation-rules.yaml` drives the validator. The agent reproduces the
figure with full fidelity and marks low-evidence assertions `instinct` rather
than dropping them, so curators get a matching model with the uncertain parts
flagged.

## Backend

The LLM agent runs against **Anthropic on Google Cloud Vertex AI**. The
`anthropic` Python SDK's `AnthropicVertex` client picks up the relevant env
vars from `.env`:

```
CLAUDE_CODE_USE_VERTEX=1
ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project-id
CLOUD_ML_REGION=us-east5
GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa-key.json
ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-6@default
ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-4-8
ANTHROPIC_VERTEX_OPUS_REGION=global
```

Copy `.env.example` to `.env` and fill in the credentials path. The
GitHub Actions runner takes the service account JSON from the
`GCP_VERTEX_SA_KEY` repo secret.

The orchestrator and the vision *perception* stage run **Opus 4.8 at
`effort=xhigh`** with adaptive thinking; the vision *structuring* stage uses
Sonnet 4.6. For this project Opus 4.8 is served only on the Vertex **`global`**
endpoint (regional endpoints return quota errors), hence
`ANTHROPIC_VERTEX_OPUS_REGION=global`. Effort/thinking are passed via the SDK's
`extra_body` — see `src/gocam_prototype/llm.py:create_message`.

## Local setup

```sh
uv sync --extra dev
uv run pytest -q
```

The Vertex round-trip test in `tests/test_llm.py` is skipped automatically
when `GOOGLE_APPLICATION_CREDENTIALS` is not set or points to a file that
doesn't exist.

## Constraints

- **No upstream forks.** Changes that would normally land in
  `geneontology/gocam-py` or `geneontology/web-components` are vendored
  here instead. Revisit upstreaming after v0 demonstrably works.
- **Issue-driven workflow.** Each unit of work has a filed issue; every
  commit references and closes one via `Closes #N`. Issues are the
  project journal in lieu of PR review.
- **Never fabricate citations.** Either a real `source_id` or
  `source_type: instinct` with a justification.

## License

BSD-3-Clause. See `LICENSE`.
