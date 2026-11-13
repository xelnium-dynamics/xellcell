---
title: Builder notes
type: rules
summary: How to change the brain itself - build standards, checks to run after every change, and the hard rules for builders.
updated: 2026-11-08
---
# Builder notes

These replace the v1 builder instructions (kept as evidence in `raw/brain-v1-kit-2026-11-06/root-files/CLAUDE.md`).

## How to change the brain
1. Find the next unchecked step in roadmap-v2 and restate its done-when in at most three lines.
2. Build it, then prove it with real checks (scripts, fixtures, the done-when). A step is not done on your word.
3. Record agreed design changes in decisions-v2 and a line in brain-v2-log.
4. After any change to `Brain System/`: run `tools/brain_index.py`, `tools/vault_scan.py` (0 ghosts, 0 ambiguous names, 0 bad fragments) and `tools/vault_audit.py` (0 errors).

## Build standards
- Scripts live in `tools/`, Python 3 standard library first; bash must run on macOS bash 3.2.
- Every script ships with a test (fixtures in `tools/tests/`) that you actually ran: `bash tools/test_all.sh`.
- Read-only tools must prove they changed nothing (hash before and after).
- Notes need YAML frontmatter and unique filenames; `[[wikilinks]]` may point only to notes that exist.
- Keep `AGENTS.md`, `CLAUDE.md` and every skill file short; detail belongs in `Brain System/system/`.

## Hard rules
- `raw/` is read-only evidence; only `tools/snapshot.py` adds to it (append-only).
- Never delete: move to `_to_delete/` or the Trash and tell the owner.
- No installs, paid calls, pushes or new internet skills without the owner's explicit OK.
- Every change outside the brain folder is recorded with its undo in `state/integration-manifest.md`.
- If the design is unclear or looks wrong, ask the owner instead of improvising.
