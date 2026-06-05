#!/usr/bin/env python3
"""Validate every ontology CURIE used in the knowledge deliverables.

Scans the given files for CURIEs (GO:, RO:, BFO:, CHEBI:, ECO:, CL:, UBERON:,
NCBITaxon:, PR:, SO:), looks each up in EBI OLS4, and reports:
  - OBSOLETE terms (with replaced_by/consider if OLS provides it)
  - terms that could not be resolved (possible typo / wrong ID)
  - the current canonical label (so callers can spot label drift)

Writes a TSV report and prints the problems. Read-only; no edits.

Run:  python3 knowledge/tools/validate_curies.py knowledge/go-curation-rules.yaml knowledge/go-curation-guidelines.md
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request

CURIE_RE = re.compile(r"\b(GO|RO|BFO|CHEBI|ECO|CL|UBERON|NCBITaxon|PR|SO):\d{4,}\b")
OLS = "https://www.ebi.ac.uk/ols4/api/terms?obo_id="


def lookup(curie):
    url = OLS + urllib.parse.quote(curie)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.load(r)
    except Exception as e:
        return {"curie": curie, "status": "lookup-error", "detail": str(e)[:80]}
    terms = (data.get("_embedded") or {}).get("terms") or []
    if not terms:
        return {"curie": curie, "status": "not-found"}
    # prefer a defining-ontology hit
    t = next((x for x in terms if x.get("is_defining_ontology")), terms[0])
    repl = t.get("term_replaced_by") or []
    ann = t.get("annotation") or {}
    if not repl:
        repl = ann.get("term replaced by") or ann.get("replaced_by") or []
    consider = ann.get("consider") or ann.get("consider using") or []
    return {
        "curie": curie,
        "status": "obsolete" if t.get("is_obsolete") else "ok",
        "label": t.get("label") or "",
        "ontology": t.get("ontology_name") or "",
        "replaced_by": ", ".join(repl) if isinstance(repl, list) else str(repl),
        "consider": ", ".join(consider) if isinstance(consider, list) else str(consider),
    }


def main():
    files = sys.argv[1:]
    text = ""
    for f in files:
        text += open(f, encoding="utf-8").read() + "\n"
    curies = sorted(set(m.group(0) for m in CURIE_RE.finditer(text)))
    print(f"found {len(curies)} unique CURIEs across {len(files)} file(s)", file=sys.stderr)

    rows = []
    for c in curies:
        rows.append(lookup(c))
        time.sleep(0.15)

    with open("knowledge/sources/extracts/_curie_validation.tsv", "w") as fh:
        fh.write("curie\tstatus\tlabel\tontology\treplaced_by\tconsider\n")
        for r in rows:
            fh.write("\t".join([r.get("curie", ""), r.get("status", ""), r.get("label", ""),
                                r.get("ontology", ""), r.get("replaced_by", ""), r.get("consider", "")]) + "\n")

    obsolete = [r for r in rows if r["status"] == "obsolete"]
    missing = [r for r in rows if r["status"] in ("not-found", "lookup-error")]
    ok = [r for r in rows if r["status"] == "ok"]
    print(f"\nOK: {len(ok)}   OBSOLETE: {len(obsolete)}   UNRESOLVED: {len(missing)}\n")
    if obsolete:
        print("=== OBSOLETE (must replace) ===")
        for r in obsolete:
            print(f"  {r['curie']}  '{r['label']}'  -> replaced_by: {r['replaced_by'] or '(none)'}  consider: {r['consider'] or '(none)'}")
    if missing:
        print("\n=== UNRESOLVED (verify ID) ===")
        for r in missing:
            print(f"  {r['curie']}  [{r['status']}]  {r.get('detail','')}")
    print("\nfull report: knowledge/sources/extracts/_curie_validation.tsv")


if __name__ == "__main__":
    main()
