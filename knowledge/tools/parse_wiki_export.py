#!/usr/bin/env python3
"""Parse a MediaWiki XML export into an index + per-page wikitext files.

The GO wiki sits behind a Cloudflare JS challenge that blocks WebFetch/curl,
so we work from a local MediaWiki export instead. This streams the export
(memory-safe via iterparse), writes a flat index of every page, and dumps the
latest revision of each non-redirect page as an individual `.wiki` file so
downstream tools/agents can read specific pages without re-parsing the XML.

Usage:
    parse_wiki_export.py EXPORT.xml --out OUTDIR [--namespaces 0,4,12,14] [--no-pages]

Outputs under OUTDIR:
    index.tsv                    title, ns, ns_name, text_bytes, redirect, last_ts, contributor
    pages/<ns_name>/<safe>.wiki  latest-revision wikitext (non-redirects only)
"""
import argparse
import csv
import os
import re
import sys
import xml.etree.ElementTree as ET


def localname(tag: str) -> str:
    """Strip the {namespace} prefix ElementTree puts on every tag."""
    return tag.rsplit("}", 1)[-1]


def safe_filename(title: str, maxlen: int = 120) -> str:
    s = title.replace("/", "__")
    s = re.sub(r"[^A-Za-z0-9._ -]", "_", s)
    s = s.strip().replace(" ", "_")
    return s[:maxlen] or "untitled"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--out", required=True)
    ap.add_argument("--namespaces", default=None,
                    help="comma-separated ns keys to write page files for (default: all)")
    ap.add_argument("--no-pages", action="store_true",
                    help="write index.tsv only; skip per-page files")
    args = ap.parse_args()

    want_ns = None
    if args.namespaces:
        want_ns = {int(x) for x in args.namespaces.split(",") if x.strip()}

    os.makedirs(args.out, exist_ok=True)
    pages_dir = os.path.join(args.out, "pages")

    ns_names: dict[int, str] = {}
    index_rows: list[tuple] = []
    ns_hist: dict = {}
    n_pages = 0
    n_redirects = 0
    in_namespaces = False

    for event, elem in ET.iterparse(args.export, events=("start", "end")):
        tag = localname(elem.tag)

        if event == "start":
            if tag == "namespaces":
                in_namespaces = True
            continue

        # end events
        if tag == "namespace" and in_namespaces:
            key = elem.get("key")
            if key is not None:
                ns_names[int(key)] = (elem.text or "").strip()
            elem.clear()
            continue
        if tag == "namespaces":
            in_namespaces = False
            elem.clear()
            continue
        if tag != "page":
            continue

        # ---- a whole <page> subtree is now available ----
        title, ns, redirect, text, last_ts, contributor = "", None, "", "", "", ""
        for child in elem:
            ctag = localname(child.tag)
            if ctag == "title":
                title = child.text or ""
            elif ctag == "ns":
                raw = (child.text or "").strip()
                ns = int(raw) if raw.lstrip("-").isdigit() else None
            elif ctag == "redirect":
                redirect = child.get("title") or "#REDIRECT"
            elif ctag == "revision":
                # exports order revisions oldest->newest; last seen == newest
                for rc in child:
                    rtag = localname(rc.tag)
                    if rtag == "text":
                        text = rc.text or ""
                    elif rtag == "timestamp":
                        last_ts = rc.text or ""
                    elif rtag == "contributor":
                        for cc in rc:
                            if localname(cc.tag) == "username":
                                contributor = cc.text or ""

        n_pages += 1
        ns_hist[ns] = ns_hist.get(ns, 0) + 1
        if redirect:
            n_redirects += 1
        ns_name = ns_names.get(ns, str(ns))
        index_rows.append((title, ns if ns is not None else "", ns_name,
                           len(text), redirect, last_ts, contributor))

        if (not args.no_pages and not redirect
                and (want_ns is None or ns in want_ns)):
            sub = os.path.join(pages_dir, (ns_name or "Main").replace(" ", "_") or "Main")
            os.makedirs(sub, exist_ok=True)
            with open(os.path.join(sub, safe_filename(title) + ".wiki"),
                      "w", encoding="utf-8") as fh:
                fh.write(f"= {title} =\n")
                fh.write(f"<!-- ns={ns} ({ns_name}); last edited {last_ts} by {contributor} -->\n\n")
                fh.write(text)

        elem.clear()

    with open(os.path.join(args.out, "index.tsv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow(["title", "ns", "ns_name", "text_bytes", "redirect_target", "last_ts", "contributor"])
        for row in sorted(index_rows, key=lambda r: (r[1] if isinstance(r[1], int) else 99, r[0].lower())):
            w.writerow(row)

    print(f"pages: {n_pages}  redirects: {n_redirects}  non-redirect: {n_pages - n_redirects}", file=sys.stderr)
    print("namespaces:", file=sys.stderr)
    for k in sorted(ns_hist, key=lambda x: (x is None, x if x is not None else 999)):
        print(f"  ns {k} ({ns_names.get(k, '?')}): {ns_hist[k]}", file=sys.stderr)


if __name__ == "__main__":
    main()
