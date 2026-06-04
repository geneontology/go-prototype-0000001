#!/usr/bin/env python3
"""UserPromptSubmit hook: append the submitted prompt to the prompt journal.

Reads the hook JSON payload on stdin, extracts the `prompt` field, and
appends a timestamped, block-quoted entry to journal/prompts.md next to
this script.

Design constraints:
- Prints NOTHING to stdout. For a UserPromptSubmit hook, stdout is injected
  into the model's context — staying silent keeps the journal invisible to
  the conversation.
- Defensive: any error (bad JSON, unwritable file, etc.) is swallowed and
  the script still exits 0, so a journal hiccup can never block a prompt.
- Appends only; it never commits. Captured prompts enter the public repo's
  git history only when someone deliberately commits journal/prompts.md,
  which leaves a review window between capture and publish.

Wire it (in .claude/settings.local.json, which is gitignored) as:
    "hooks": { "UserPromptSubmit": [ { "hooks": [ { "type": "command",
      "command": "python3 /ABS/PATH/journal/append-prompt.py" } ] } ] }
"""

import datetime
import json
import pathlib
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return
    # Skip bare slash-commands / local commands (e.g. /effort, /model).
    if prompt.startswith("/"):
        return

    journal = pathlib.Path(__file__).resolve().parent / "prompts.md"
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    quoted = "\n".join("> " + line for line in prompt.splitlines())
    entry = f"\n### {ts}\n\n{quoted}\n"

    try:
        with journal.open("a", encoding="utf-8") as fh:
            fh.write(entry)
    except Exception:
        return


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
