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
