# Documentation sources for GO-CAM model creation

This catalogs the documentation that drives model building in this prototype:
the two files the agent/validator actually consume at runtime, and the raw
source corpus those two were distilled from.

> Provenance note: the authoritative list is maintained in
> [`go-curation-guidelines.md`](./go-curation-guidelines.md) §9 and mirrored in
> [`go-curation-rules.yaml`](./go-curation-rules.yaml) `meta.source_corpus`.
> This file is a convenience index of both.

## What the agent reads at runtime

| File | Role | Consumed by |
|---|---|---|
| [`go-curation-guidelines.md`](./go-curation-guidelines.md) | Prose curation guide (the narrative "why/how") | **Injected into the orchestrator system prompt** as a cached block (`orchestrator.py:_load_guidelines`) — the *only* knowledge file sent to the model |
| [`go-curation-rules.yaml`](./go-curation-rules.yaml) | Machine-readable ruleset (191 rules, 49 relations, 95 machine-checkable) | The validator (`validate.py`) and a reference — **not sent to the model** |

> A rule added only to the YAML will **not** change agent behavior; mirror
> anything meant to steer the agent into the markdown.

## Source corpus (distilled into the two files above)

Raw material lives under `knowledge/sources/` (plus `extracts/` and the
`tools/` that parse and consolidate it).

> **Committed vs. local-only.** `knowledge/sources/` is **gitignored**
> (`.gitignore`: "Raw research source material (mined locally)") — the GO wiki
> export, the MF-guide Google Doc export, and the `extracts/` are **not in the
> repo**. Only the *distilled* outputs are committed: `go-curation-guidelines.md`,
> `go-curation-rules.yaml`, `research/figure-to-intent.md`, and `tools/*.py`.
> Rebuild the corpus locally from the sources below.

| Source | Where it lives / what it is |
|---|---|
| **GO documentation** | `geneontology.github.io/_docs/` — `go-annotations.md`, `guide-go-evidence-codes.md`, `gocam-overview.md`, `submitting-go-annotations.md`, `annotation-contributors.md` |
| **GO wiki** | `knowledge/sources/wiki/pages/Main/` — a 143-page MediaWiki export (`go-wiki-20260605.xml`): the relation pages, Signaling Curation Manual, Annotating ligand-receptor pathways / regulation / binding / from phenotypes / downstream processes, Occurs_in, Misused_terms, Identifiers, Biological Pathways as GO-CAMs, Tips to Produce High Quality Annotations, and others |
| **go-shapes ShEx** | `go-cam-shapes.shex` / `.shapeMap` — the structural shape constraints (source of truth for CURIEs, cardinalities, ranges) |
| **GO QC rules** | `GORULE:0000002` / `0000004` / `0000005` / `0000008` / `0000017` / `0000018` / `0000036` / `0000046` |
| **MF curation guide** _(Google Doc)_ | `knowledge/sources/mf-curation-guide.md` — verbatim export of GO's "Guide for MF annotation in GO-CAM" **Google Doc** (id `186PR8Ml7JpudB8q23-enpCbXhsLpBkuivXV79Agr15w`, linked by vanaukenk on #39, **fetched via Drive 2026-06-05**; gitignored/local-only) → `mf_activity_unit_patterns` |
| **Primary literature** | PMC3706743 (evidence codes); PMID:31548717 / PMC7012280 (the GO-CAM paper) |
| **Ontology IDs** | ChEBI / NCBITaxon / WormBase canonical IDs (verified) |

### Google Drive / Docs provenance

Not everything comes from public GO web docs — two inputs trace to Google Docs:

- **MF curation guide** — the `mf-curation-guide.md` export above; a Google Doc
  fetched via Drive (see its table row). This is the one gdoc that fed the
  committed knowledge pack.
- **"Dream workflow" Google Doc** — the curator's originating spec for the whole
  prototype. It's not committed as a file, but it's what the `provenance.py`
  `SourceType` taxonomy and the pipeline steps follow.

(Incidental Google Doc links also appear inside some archived GO-wiki
meeting-note pages, but those are not used as curation sources.)

### Quality controls on the corpus

- **The wiki export was adversarially verified** against the canonical GO docs
  and `go-cam-shapes.shex`. Where a wiki claim was unsupported, the rule carries
  a correction note and the guide uses the corrected wording.
- **Every CURIE was validated against the live ontology** via
  `knowledge/tools/validate_curies.py` (→ OLS4 + GO API). This caught obsolete
  terms still used by the older Signaling Curation Manual (e.g. `GO:0005057` and
  its kinase/phosphatase children; `GO:0048018` renamed to "receptor ligand
  activity"). Re-run the validator after any term edits.
- **Three rules are flagged** as project heuristics, not source doctrine
  (`gocam-shapes-no-self-causal-edge`; the evidence-code strength ordering; the
  `is_small_molecule_activator_of`/`inhibitor_of` RO:0012005/0012006 stubs — for
  which the shape-grounded RO:0012001 family is preferred). See guidelines §9.

## Known relevant sources NOT yet ingested

- **Noctua User Guide** (Google Doc `1a5YZBJrnJ9LKJxPVpXk62dJJGpHB2b9zH8-xr_Rm1Vs`,
  owner pgaudet1@gmail.com; reviewed 2025–2026 by Thomas / Gaudet / Masson /
  Aleksander) — the GO Consortium's umbrella curation guide and the *parent* doc
  that links out to the MF-guidelines Google Doc we already ingested
  (`186PR8Ml...`). Actively maintained; it is the current canonical statement of
  several rules for which our pack currently cites only older GO-wiki pages.
  **Not distilled into the knowledge pack yet** (tracked in
  [#58](https://github.com/geneontology/go-prototype-0000001/issues/58)).
  High-value tabs for ingestion:
  - **"GO-CAM annotation guidelines"** — one-activity-unit-per-gene-product
    (+ multifunctional-protein exception), what NOT to include (binding terms,
    reversible reactions, mechanism-in-MF-def), model naming convention,
    connecting pathways across models.
  - **VPE manual** (modeling parts only) — currency-chemical exclusion, ligand→
    receptor directionality, the three small-molecule use cases, unknown-enabler
    / unknown-MF conventions, complexes-as-enablers, BP nesting / activity-
    regulating processes, CC cell-type context "only if activity-specific",
    ISS/ISO/IC evidence + GO_REF defaults.
  - **Skip**: Landing Page, VPE/SAE UI mechanics, Copy Model, meetings/maintenance
    (curator-tool operation, not modeling rules).
  Ingest via the same export → distill → adversarially-verify → mirror-into-
  `guidelines.md` pipeline used for the rest of the corpus.

## Related but distinct: per-assertion provenance sources

The above is documentation that *feeds the agent*. Separately, each claim in a
built model is tagged with where it came from via the `SourceType` enum in
`provenance.py` — a different axis:

`literature`, `go_annotation`, `alliance`, `amigo`, `orthology`,
`pathway_resource`, `expert_review`, `instinct`, `figure`, `go_term_request`.
