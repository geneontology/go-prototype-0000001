#!/usr/bin/env python3
"""Consolidate the per-group extraction JSONs into one normalized digest.

Reads knowledge/sources/extracts/*.json (the per-group ruleset extractions),
plus the _flagged.json (rules that failed adversarial verification) and
_corrections.json (grounded-but-overstated rules with a corrected wording),
and produces:

  _consolidated.json  - every rule (group-tagged, flagged/corrected annotated)
                        + relations grouped by canonical RO/BFO CURIE
  _digest.md          - human/author-readable digest (relations matrix +
                        rules by category) used to write the final deliverables

Run:  python3 knowledge/tools/consolidate_extracts.py knowledge/sources/extracts
"""
import json
import os
import re
import sys

CURIE_RE = re.compile(r"\b(?:RO|BFO|GO|lego)[:_]\d{4,}", re.I)


def norm_curie(*vals):
    for v in vals:
        if not v:
            continue
        m = CURIE_RE.search(v)
        if m:
            return m.group(0).upper().replace("_", ":")
    return None


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "knowledge/sources/extracts"
    flagged = {}
    corrections = {}
    fp = os.path.join(base, "_flagged.json")
    if os.path.exists(fp):
        for f in json.load(open(fp)):
            flagged[(f["group"], f["rule_id"])] = f.get("issue", "")
    cp = os.path.join(base, "_corrections.json")
    if os.path.exists(cp):
        for c in json.load(open(cp)):
            corrections[(c["group"], c["rule_id"])] = c.get("corrected_statement", "")

    rules = []
    rel_by_key = {}
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".json") or fn.startswith("_"):
            continue
        data = json.load(open(os.path.join(base, fn)))
        group = data.get("source_group", fn[:-5])
        for r in data.get("rules", []):
            key = (group, r.get("id", ""))
            r["_group"] = group
            if key in flagged:
                r["_flagged"] = flagged[key]
            if key in corrections:
                r["_corrected"] = corrections[key]
            rules.append(r)
        for rel in data.get("relations", []):
            key = norm_curie(rel.get("curie"), rel.get("relation")) or \
                re.sub(r"[^a-z0-9]", "", (rel.get("relation") or "").lower())
            cur = rel_by_key.get(key)
            # keep the richest description (longest when_to_use)
            if cur is None or len(rel.get("when_to_use", "")) > len(cur.get("when_to_use", "")):
                rel["_group"] = group
                rel["_key"] = key
                rel_by_key[key] = rel

    consolidated = {
        "rules": rules,
        "relations": list(rel_by_key.values()),
        "counts": {
            "rules": len(rules),
            "relations": len(rel_by_key),
            "machine_checkable": sum(1 for r in rules if r.get("machine_checkable")),
            "flagged": sum(1 for r in rules if "_flagged" in r),
        },
    }
    json.dump(consolidated, open(os.path.join(base, "_consolidated.json"), "w"), indent=2)

    # ---- digest ----
    out = []
    out.append("# Consolidated GO curation ruleset — digest\n")
    out.append(f"- rules: {consolidated['counts']['rules']}  "
               f"(machine_checkable: {consolidated['counts']['machine_checkable']}, "
               f"flagged: {consolidated['counts']['flagged']})")
    out.append(f"- relations (deduped by CURIE): {consolidated['counts']['relations']}\n")

    out.append("## Relations matrix (canonical)\n")
    def relsort(r):
        c = r.get("_key", "")
        return (0, c) if c.startswith(("RO", "BFO")) else (1, c)
    for rel in sorted(consolidated["relations"], key=relsort):
        out.append(f"### {rel.get('relation','?')}  `{rel.get('curie') or rel.get('_key','')}`")
        out.append(f"- used_in: {rel.get('used_in','?')}  |  {rel.get('subject_type','?')} -> {rel.get('object_type','?')}")
        if rel.get("when_to_use"):
            out.append(f"- when: {rel['when_to_use']}")
        if rel.get("when_not_to_use"):
            out.append(f"- when NOT: {rel['when_not_to_use']}")
        if rel.get("example"):
            out.append(f"- e.g.: {rel['example']}")
        out.append(f"- src: {rel.get('source','')}  ({rel.get('_group','')})\n")

    out.append("## Rules by category\n")
    by_cat = {}
    for r in rules:
        by_cat.setdefault(r.get("category", "uncategorized"), []).append(r)
    for cat in sorted(by_cat):
        out.append(f"### {cat}  ({len(by_cat[cat])})")
        for r in by_cat[cat]:
            mark = " *" if r.get("machine_checkable") else ""
            flag = "  ⚠FLAGGED" if "_flagged" in r else ""
            out.append(f"- [{r['_group']}/{r.get('id','')}]{mark}{flag} {r.get('statement','')}")
            if r.get("_corrected"):
                out.append(f"    ↳ corrected: {r['_corrected']}")
            if r.get("_flagged"):
                out.append(f"    ↳ issue: {r['_flagged']}")
            if r.get("do"):
                out.append(f"    do: {' | '.join(r['do'][:2])}")
            if r.get("dont"):
                out.append(f"    dont: {' | '.join(r['dont'][:2])}")
            if r.get("examples"):
                out.append(f"    ex: {' | '.join(r['examples'][:1])}")
        out.append("")

    open(os.path.join(base, "_digest.md"), "w").write("\n".join(out))
    print(f"wrote {base}/_consolidated.json and _digest.md")
    print(f"rules={consolidated['counts']['rules']} relations={consolidated['counts']['relations']} "
          f"machine_checkable={consolidated['counts']['machine_checkable']} flagged={consolidated['counts']['flagged']}")
    print(f"digest size: {os.path.getsize(os.path.join(base, '_digest.md'))} bytes")


if __name__ == "__main__":
    main()
