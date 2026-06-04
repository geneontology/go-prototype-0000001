# Curator prompt journal

A chronological record of the prompts **@kltm** has given the agent while
building this prototype — kept so the conversational back-and-forth that
shaped the work is visible on-disk and in git history, not only in the
GitHub issue trail.

How to read this:

- **Going forward (2026-06-03 onward):** entries are appended automatically
  by a `UserPromptSubmit` hook (`journal/append-prompt.py`). Each is the
  prompt **verbatim**, stamped with the UTC time it was submitted.
- **The backfill block below** was reconstructed from the live transcript
  of the session that produced issues #29–#38. It is faithful but
  hand-transcribed, so minor punctuation/wording may vary, and exact
  per-prompt clock times weren't recorded — entries are dated to the
  commit(s) they produced.
- **Before #29:** the v0 / v0.2 build (issues #1–#28) predates this
  journal. Those prompts weren't captured verbatim; the **issue tracker is
  this repo's primary work journal** for that period — start at #1.

Each `>` block is a prompt; the italic line under it notes what it led to.

---

## 2026-05-12 — landing-page polish block

### #29

> Great! Picking up again. On the landing page, the draft models are below the fold, Could we make them and the submission side-by-side in some pleasing way? Also, do the form inputs do anything? If not, could you make them (and the "Queue draft model" visibly inoperable and leave the "Open GitHub form" visible.

_→ Side-by-side landing layout; disabled the non-wired inputs + Queue button; kept "Open GitHub form". (commit 8bbb925)_

### #30

> Great! Okay, on my screen and on my laptop, the two boxes overlap. Not ideal. Left and right margin on those could be reduced as well. Also, for the "Draft models" display, does that update periodically if new model drafts are finished in GitHub?

_→ Fixed grid `min-width: 0` overlap; reduced outer padding. (Answered: no auto-update yet — set up the poller next.) (commit fa368f5)_

### #31

> I tiny JS poller would be nice; if it sees something, update the display. It can run very slow--this is a demo and I don't want to annoy GH's API.

_→ 10-min GitHub-contents poller + "new drafts" refresh banner. (commit 0690eb0)_

### #32

> This is looking nice. It seems that the same image is being used?

_→ Confirmed `demo` and `figure1` both came from the same figure. Surfaced the source figure: landing thumbnail + zoomable viewer lightbox. (commit 9af6fde)_

### #33

> Ah, now I understand. Please do 2.

_→ (Of the options offered) ran the agent on figure2 (C. elegans intestinal immunity) for a visually distinct second draft. (commit 5cd8783)_

### #35

> Okay, last last question. Would it be possible to show the evidence chips (just icon, no text) in the graph display?

_→ HTML overlay of evidence-type emoji chips on each node and causal edge. (commit b2168b0)_

---

## 2026-05-14 — agent-on-GHA debugging block

### #37

> Recently, somebody tried to upload an image, but nothing happened. Can you check what the issue is?

_→ Root-caused: `run-agent.yml` was unparseable YAML (block-scalar indent), so GitHub silently dropped every issue/dispatch event — the agent had never run on GHA. (commit dda17db)_

### #36 (retrigger)

> Please retrigger it--it is a test.

_→ Re-fired the workflow on the test issue by toggling the `run-agent-request` label; first real end-to-end agent run on GHA succeeded._

### #38

> There seems to be an issue; please check: https://github.com/geneontology/go-prototype-0000001/issues/36#issuecomment-4454069751

_→ Curator (pkalita-lbl) reported a 404 link. Root cause: comment URL used the uppercase timestamp but the on-disk slug is lowercased (GH Pages is case-sensitive)._

### #38 (fix)

> Please fix as needed and in place.

_→ Ported `_slugify` into the workflow so bash/Python agree; edited the broken issue comment in place. (commit 5d3e7fa)_

### feedback — agent disclosure

> Another note: Always, if you are writing a comment, as it appears as "me" (kltm), you must note that it is an agentic message.

_→ Amended the comment with an agent-disclosure trailer; saved as a memory and (next) lifted to global CLAUDE.md._

### CLAUDE.md

> Thank you. Anything to write back to CLAUDE.md at any level?

_→ Proposed two: agent-disclosure (global) and validate-workflow-YAML-locally (local)._

### CLAUDE.md (placement)

> The first: please global; the second: local, please.

_→ Appended agent-disclosure to `~/.claude/CLAUDE.md`; created project `CLAUDE.md` with the YAML-validation + slugify-parity notes. (commit 034f3e0)_

### sign-off

> Thank you! This is great; I'll give you more feedback as it comes in.

---

## 2026-06-03 — pickup + this journal

### orientation

> Okay, I want to pick up this prototype project again. What is the operating structure of this repo? Is this repo an independent project, or is it an iterating meta-project?

_→ Explained: independent, fresh repo (no template/parent); an iterating disposable prototype, issue-driven, journal-in-issues._

### provenance

> Okay, can you tell me how this was built up again? What is the originating meta-repo or instructions?

_→ No meta-repo; the originating spec is the curator "dream workflow" Google Doc. Walked the v0 → v0.2 → polish → curator-feedback (#39–#41) trail._

### this journal

> Okay, can you start keeping an on-filesystem and in-repo journal of the prompts-to-date, as well as prompts going forward? Looking back through my prompts, I can see the history.

_→ This file + the `UserPromptSubmit` hook (#42)._

---
