"""CLI entry point: ``gocam-prototype run --image ... --species ...``.

Drives the full agent pipeline (vision → orchestrator → viewer translator)
and writes a run directory under ``docs/runs/<run-id>/`` containing
everything the static viewer page needs:

* ``curator_intent.json`` — the structured output from the vision pass
* ``model.yaml`` — the gocam-py model
* ``provenance.json`` — the sidecar ledger
* ``viewer.json`` — bbop-graph "active model" JSON for setModelData()
* ``index.html`` — the per-run viewer page (copied from a template)

After writing the run, refreshes the top-level ``docs/index.html`` so the
landing page lists the new run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml

from gocam_prototype.builder import GoCamBuilder, write_model_and_ledger
from gocam_prototype.orchestrator import orchestrate
from gocam_prototype.validate import validate_model
from gocam_prototype.viewer import linkml_to_viewer_json
from gocam_prototype.vision import extract_curator_intent

# Repo-level paths (resolved at import time so tests can override via cwd).
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOCS = REPO_ROOT / "docs"
DEFAULT_RUNS = DEFAULT_DOCS / "runs"
RUN_TEMPLATE = DEFAULT_RUNS / "demo" / "index.html"

DEFAULT_TAXON = "NCBITaxon:6239"  # C. elegans (v0 test case)


# ----------------------------------------------------------- pipeline ----


def _slugify(s: str, max_len: int = 60) -> str:
    out = "".join(c if c.isalnum() or c == "-" else "-" for c in s.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")[:max_len] or "run"


# Inputs come from the `Fetch input image` workflow step as
# `/tmp/agent-input/figure` (no extension), so sniff magic bytes.
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n",                         ".png"),
    (b"\xff\xd8\xff",                              ".jpg"),
    (b"GIF87a",                                    ".gif"),
    (b"GIF89a",                                    ".gif"),
)

def _detect_image_extension(path: Path) -> str:
    head = path.read_bytes()[:16]
    for magic, ext in _IMAGE_MAGIC:
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return path.suffix.lower() or ".bin"


def _find_run_figure(run_dir: Path) -> Path | None:
    """Return the saved source-figure path for a run, or None."""
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        p = run_dir / f"figure{ext}"
        if p.is_file():
            return p
    return None


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_pipeline(
    image_path: Path,
    species: str,
    *,
    species_taxon: str | None = None,
    process_hint: str | None = None,
    run_id: str | None = None,
    docs_dir: Path | None = None,
    max_turns: int = 80,
) -> dict:
    docs_dir = (docs_dir or DEFAULT_DOCS).resolve()
    run_id = run_id or _default_run_id()
    out_dir = docs_dir / "runs" / _slugify(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Preserve the source figure under runs/<id>/figure.<ext> so the landing
    # list and the viewer page can show a thumbnail.
    fig_ext = _detect_image_extension(image_path)
    shutil.copy(image_path, out_dir / f"figure{fig_ext}")

    print(f"[1/4] Vision pass on {image_path}", flush=True)
    intent = extract_curator_intent(
        image_path, species_hint=species, process_hint=process_hint,
        transcript_out=out_dir / "transcription.md",
    )
    (out_dir / "curator_intent.json").write_text(
        intent.model_dump_json(indent=2, exclude_none=True)
    )

    print("[2/4] Orchestrator (Claude tool-use loop)", flush=True)
    builder = GoCamBuilder(
        model_id=f"gomodel:run-{_slugify(run_id)}",
        title=f"Agent run {run_id}: {species}"
              + (f" — {process_hint}" if process_hint else ""),
        taxon=species_taxon or DEFAULT_TAXON,
    )
    model, ledger = orchestrate(
        intent, builder, max_turns=max_turns,
        events_out=out_dir / "orchestrator_events.json",
    )
    n_act = len(model.activities or [])
    n_gene = len(getattr(intent, "genes", None) or [])
    if n_act == 0 and n_gene > 0:
        print(
            f"[WARN] orchestrator produced 0 activities from {n_gene} gene mention(s) — "
            f"the model is EMPTY. Inspect {out_dir / 'orchestrator_events.json'} "
            "(stop_reason per turn) before trusting this run.",
            flush=True,
        )

    print("[3/4] Writing model + provenance + viewer JSON", flush=True)
    write_model_and_ledger(model, ledger, out_dir)
    viewer_json = linkml_to_viewer_json(model)
    (out_dir / "viewer.json").write_text(json.dumps(viewer_json, indent=2))

    # Lint the model against the machine-checkable GO-CAM rules (rules.yaml -> code).
    findings = validate_model(model, ledger)
    (out_dir / "validation.json").write_text(json.dumps(findings, indent=2))
    n_err = sum(1 for f in findings if f.get("severity") == "error")
    n_warn = sum(1 for f in findings if f.get("severity") == "warn")
    print(f"[validate] {n_err} error(s), {n_warn} warning(s) -> {out_dir / 'validation.json'}", flush=True)

    if RUN_TEMPLATE.is_file():
        shutil.copy(RUN_TEMPLATE, out_dir / "index.html")

    print("[4/4] Regenerating landing page", flush=True)
    regenerate_landing(docs_dir)

    summary = {
        "run_id": _slugify(run_id),
        "out_dir": str(out_dir),
        "activities": len(model.activities or []),
        "sidecar_entries": len(ledger.assertions),
        "source_mix": ledger.count_by_source_type(),
        "viewer_individuals": len(viewer_json["individuals"]),
        "viewer_facts": len(viewer_json["facts"]),
        "validation": {"errors": n_err, "warnings": n_warn},
    }
    return summary


# ----------------------------------------------------------- landing page -


_LANDING_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GO-CAM curation prototype — draft models</title>
  <link rel="stylesheet" href="assets/styles.css">
</head>
<body class="landing-body">
  <header class="site-header">
    <h1>GO-CAM curation prototype</h1>
    <p class="tagline">An LLM agent reads a research-paper figure and builds a GO-CAM that a curator
       can review, dispute, or refine. Every clickable element on each draft model traces back to its
       source.</p>
    <p><a href="https://github.com/geneontology/go-prototype-0000001">source &amp; issues on GitHub</a></p>
  </header>

  <main class="landing-main">

    <div class="landing-top">

      <section class="submit-card">
        <h2>Submit a figure</h2>
        <p class="card-intro">The fields below preview what the GitHub Issue Form asks for but
           aren't wired up yet — click <strong>Open GitHub form</strong> and fill them in there.
           Submitting on GitHub fires the workflow, and the agent comments the draft model URL
           back on the issue when it finishes.</p>
        <form id="submit-form" class="submit-form" aria-disabled="true">
          <label>
            <span class="field-label">Image URL</span>
            <input type="url" name="image_url" placeholder="https://…/figure.png" disabled>
          </label>
          <label>
            <span class="field-label">Species</span>
            <input type="text" name="species" value="Caenorhabditis elegans" disabled>
          </label>
          <div class="form-row">
            <label class="grow">
              <span class="field-label">Species taxon</span>
              <input type="text" name="species_taxon" placeholder="NCBITaxon:6239" disabled>
            </label>
            <label class="grow">
              <span class="field-label">Run id</span>
              <input type="text" name="run_id" placeholder="(auto: UTC timestamp)" disabled>
            </label>
          </div>
          <label>
            <span class="field-label">Process hint</span>
            <textarea name="process_hint" rows="2"
                      placeholder="Free-text hint describing the biological process the figure depicts"
                      disabled></textarea>
          </label>
          <div class="form-actions">
            <button type="button" class="primary" disabled aria-disabled="true"
                    title="Not wired up — use Open GitHub form">Queue draft model</button>
            <a class="primary-link"
               href="https://github.com/geneontology/go-prototype-0000001/issues/new?template=run-agent.yml"
               target="_blank" rel="noopener noreferrer">Open GitHub form ↗</a>
          </div>
        </form>
      </section>

      <section class="runs-list">
        <header class="runs-list-header">
          <h2>Draft models</h2>
          <p class="legend" aria-label="Source-type key">
            <span class="legend-label">Source types:</span>
            <span class="badge literature">📚 literature</span>
            <span class="badge go_annotation">🗂️ GO annotation</span>
            <span class="badge alliance">🧬 Alliance</span>
            <span class="badge amigo">🔍 AmiGO</span>
            <span class="badge orthology">↗️ orthology</span>
            <span class="badge pathway_resource">🛤️ pathway</span>
            <span class="badge expert_review">✔️ expert review</span>
            <span class="badge instinct">⚠️ instinct</span>
            <span class="badge figure">🚩 figure</span>
            <span class="badge go_term_request">❓ GO term request</span>
          </p>
        </header>
        <ul>
"""

_LANDING_TAIL = """        </ul>
      </section>

    </div>

    <p class="footer-note">Hand-built reference drafts and live agent runs both land in the same
      <code>docs/runs/&lt;run-id&gt;/</code> layout. Each draft is ready for a curator to review,
      confirm, dispute, or refine.</p>

  </main>
  <script src="assets/landing.js"></script>
</body>
</html>
"""


_BADGE_META: dict[str, tuple[str, str]] = {
    "literature":       ("📚", "literature"),
    "go_annotation":    ("🗂️", "GO annotation"),
    "alliance":         ("🧬", "Alliance"),
    "amigo":            ("🔍", "AmiGO"),
    "orthology":        ("↗️", "orthology"),
    "pathway_resource": ("🛤️", "pathway"),
    "expert_review":    ("✔️", "expert review"),
    "instinct":         ("⚠️", "instinct"),
    # Weakest tier — a raw reading of the figure (below instinct). Flagged so a
    # curator treats it as "verify this".
    "figure":           ("🚩", "figure"),
    "go_term_request":  ("❓", "GO term request"),
}


def summarize_provenance(provenance_path: Path) -> dict[str, int]:
    """Return source-type → count from a provenance.json file.

    Dual-reads both shapes: v2 (each key → list of sources) and v1 (each key →
    a single source object), so existing committed runs still summarize.
    """
    try:
        prov = json.loads(provenance_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    counts: dict[str, int] = {}
    for val in (prov.get("assertions") or {}).values():
        sources = val if isinstance(val, list) else [val]
        for src in sources:
            t = (src or {}).get("source_type", "unknown")
            counts[t] = counts.get(t, 0) + 1
    return counts


def _render_tag_cloud(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    chips: list[str] = []
    # Render in a stable order (taxonomy order, then unknown trailing).
    for key in list(_BADGE_META) + sorted(k for k in counts if k not in _BADGE_META):
        if key not in counts:
            continue
        emoji, label = _BADGE_META.get(key, ("?", key))
        chips.append(
            f'<li class="tag {key}" title="{counts[key]} {label} assertion(s)">'
            f'{emoji} {counts[key]}</li>'
        )
    return f'<ul class="tag-cloud">{"".join(chips)}</ul>'


# Cache-busting. GH Pages serves docs/assets/*.{js,css} with cache-control:
# max-age=600 and no version string, so an asset change (e.g. viewer.js) is not
# picked up until the browser/CDN cache expires — every change needs a manual
# hard-refresh. We append a per-asset content hash (`?v=<hash>`) to each asset
# URL so a changed asset gets a new URL and reloads immediately. Re-stamped on
# every regenerate_landing (and thus every run), idempotent.
_ASSET_URL_RE = re.compile(
    r'((?:href|src)=")((?:\.\./)*assets/([A-Za-z0-9_.-]+\.(?:js|css)))(?:\?v=[^"]*)?(")'
)


def _asset_version(assets_dir: Path, name: str) -> str:
    try:
        return hashlib.sha256((assets_dir / name).read_bytes()).hexdigest()[:8]
    except OSError:
        return "0"


def _stamp_assets(docs_dir: Path) -> int:
    """Rewrite asset URLs in the landing + every run page to `...asset?v=<hash>`,
    where the hash is the asset's current content. Returns the count of pages
    changed."""
    assets_dir = docs_dir / "assets"

    def repl(m: re.Match) -> str:
        ver = _asset_version(assets_dir, m.group(3))
        return f"{m.group(1)}{m.group(2)}?v={ver}{m.group(4)}"

    pages = [docs_dir / "index.html", *sorted((docs_dir / "runs").glob("*/index.html"))]
    changed = 0
    for page in pages:
        if not page.is_file():
            continue
        original = page.read_text()
        stamped = _ASSET_URL_RE.sub(repl, original)
        if stamped != original:
            page.write_text(stamped)
            changed += 1
    return changed


def regenerate_landing(docs_dir: Path) -> Path:
    runs_dir = docs_dir / "runs"
    entries: list[dict] = []
    if runs_dir.is_dir():
        for run in sorted(runs_dir.iterdir()):
            if not run.is_dir():
                continue
            model_path = run / "model.yaml"
            if not model_path.is_file():
                continue
            try:
                data = yaml.safe_load(model_path.read_text()) or {}
            except yaml.YAMLError:
                continue
            counts = summarize_provenance(run / "provenance.json")
            figure = _find_run_figure(run)
            entries.append({
                "run_id": run.name,
                "title": data.get("title") or run.name,
                "n_activities": len(data.get("activities") or []),
                "modified": datetime.fromtimestamp(
                    model_path.stat().st_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%d"),
                "source_counts": counts,
                "figure_filename": figure.name if figure else None,
            })

    li_blocks: list[str] = []
    for e in entries:
        tag_cloud = _render_tag_cloud(e["source_counts"])
        body_html = (
            f'          <a class="draft-title" href="runs/{e["run_id"]}/">{_escape(e["title"])}</a>\n'
            f'          <span class="run-meta">{e["n_activities"]} activities · '
            f'updated {e["modified"]} · <code>{e["run_id"]}</code></span>\n'
            f'          {tag_cloud}'
        )
        thumb_html = ""
        if e["figure_filename"]:
            thumb_html = (
                f'\n          <a class="run-thumb-link" href="runs/{e["run_id"]}/" '
                f'aria-label="Open draft model for {_escape(e["run_id"])}">'
                f'<img class="run-thumb" loading="lazy" '
                f'src="runs/{e["run_id"]}/{e["figure_filename"]}" '
                f'alt="Source figure for {_escape(e["run_id"])}"></a>'
            )
        li_blocks.append(
            '        <li class="draft-model">\n'
            f'          <div class="draft-body">\n{body_html}\n          </div>'
            f'{thumb_html}\n'
            '        </li>'
        )
    body = "\n".join(li_blocks) + "\n" if li_blocks else (
        '        <li class="footer-note">No draft models yet. Submit a figure above to create one.</li>\n'
    )
    landing = _LANDING_HEAD + body + _LANDING_TAIL
    landing_path = docs_dir / "index.html"
    landing_path.write_text(landing)
    # Cache-bust the landing + every run page against the current asset contents.
    _stamp_assets(docs_dir)
    return landing_path


def _escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


# ----------------------------------------------------------- CLI -----


def main() -> None:
    parser = argparse.ArgumentParser(prog="gocam-prototype")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run the full agent pipeline on an image")
    run_p.add_argument("--image", required=True, type=Path)
    run_p.add_argument("--species", default="Caenorhabditis elegans",
                       help="Free-text species name (default: Caenorhabditis elegans)")
    run_p.add_argument("--species-taxon", default=None,
                       help="NCBITaxon CURIE (default: NCBITaxon:6239 for C. elegans)")
    run_p.add_argument("--process-hint", default=None)
    run_p.add_argument("--run-id", default=None,
                       help="Override the generated UTC-timestamp run id")
    run_p.add_argument("--docs", type=Path, default=None,
                       help="Override docs/ root (default: REPO_ROOT/docs)")
    run_p.add_argument("--max-turns", type=int, default=80)

    idx_p = sub.add_parser("regenerate-index",
                           help="Refresh docs/index.html from docs/runs/*")
    idx_p.add_argument("--docs", type=Path, default=DEFAULT_DOCS)

    args = parser.parse_args()
    if args.cmd == "run":
        summary = run_pipeline(
            args.image,
            args.species,
            species_taxon=args.species_taxon,
            process_hint=args.process_hint,
            run_id=args.run_id,
            docs_dir=args.docs,
            max_turns=args.max_turns,
        )
        print("\nDone.")
        for k, v in summary.items():
            print(f"  {k:20s} {v}")
    elif args.cmd == "regenerate-index":
        path = regenerate_landing(args.docs)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
