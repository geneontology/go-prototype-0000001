"""Build the vendored curator roster (`docs/assets/curators.json`) from the GO
`users.yaml` — the curators with noctua/go **allow-edit** authorization. The
viewer's self-identification picker reads this so a curator action can be
attributed to a real ORCID (#52 pt5).

Vendored per repo policy (no upstream dependency at page-serve time): re-run
this module to refresh the snapshot when users.yaml drifts.

    uv run python -m gocam_prototype.curators
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import yaml

USERS_YAML = "https://raw.githubusercontent.com/geneontology/go-site/master/metadata/users.yaml"


def _allow_edit(user: dict) -> bool:
    auth = (((user.get("authorizations") or {}).get("noctua") or {}).get("go") or {})
    return bool(auth.get("allow-edit"))


def build_curators(users: list[dict]) -> list[dict]:
    """Filter to allow-edit curators that have an ORCID (needed to attribute a
    LinkML ProvenanceInfo.contributor), as {nickname, orcid, github}."""
    out: list[dict] = []
    for u in users:
        if not _allow_edit(u):
            continue
        uri = u.get("uri") or ""
        if "orcid.org/" not in uri:  # no ORCID -> can't be a model contributor
            continue
        # Store the BARE ORCID (e.g. 0000-0002-1190-4481), not the full URL, to
        # match how ProvenanceInfo.contributor is written everywhere else in this
        # repo (demo.py, the curator-action issue template) — otherwise the same
        # curator keys as two distinct contributors.
        out.append({
            "nickname": u.get("nickname") or uri,
            "orcid": uri.rstrip("/").rsplit("/", 1)[-1],
            "github": (u.get("accounts") or {}).get("github"),
        })
    out.sort(key=lambda c: (c["nickname"] or "").lower())
    return out


def main(out_path: Path | None = None) -> Path:
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        users = yaml.safe_load(c.get(USERS_YAML).text)
    curators = build_curators(users)
    out_path = out_path or (Path(__file__).resolve().parents[2] / "docs" / "assets" / "curators.json")
    out_path.write_text(json.dumps(curators, indent=2) + "\n")
    return out_path


if __name__ == "__main__":
    path = main()
    print(f"wrote {path}")
