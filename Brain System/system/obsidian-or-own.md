---
title: Obsidian or our own system
type: decision
summary: Why the brain keeps plain Markdown files with Obsidian as the viewer, plus a generated index we own, instead of building a custom app or database.
updated: 2026-11-08
---
# Obsidian or our own system?

**Decision (D-018): both, split by job.** The brain is plain Markdown files + our own scripts and index. Obsidian is only the window the owner looks through.

| Job | Who does it | Why |
|---|---|---|
| Store knowledge | Plain `.md` files in `Brain System/` | Claude and Codex read them natively at zero cost; git can version them; no lock-in |
| Find knowledge (agents) | Our scripts: router, generated TOC views, SQLite full-text index | Agents never open Obsidian; they need exact, scriptable, testable retrieval |
| Look at knowledge (the owner) | Obsidian: graph, backlinks, search, Canvas, Excalidraw | The owner is visual; Obsidian already does this well, for free |
| Check structure | `vault_scan.py` v2 | Obsidian's own view hides ghost and ambiguous links; the scanner counts them |

## Why not a custom app or database
- Agents read files anyway; a database adds a layer agents must query through tools, and the owner could no longer just open a note.
- A semantic database usually needs embeddings: paid APIs break the NO-COST rule, local models need installs and upkeep.
- Every custom component is code to build, test and maintain. The goal is less management, not more.

## Why not Obsidian alone
- Obsidian resolves links by bare filename, so duplicate names silently create ambiguous links (227 duplicate filenames in the old vault).
- Automatic link updates on rename can rewrite files in bulk; that is why evidence (`raw/`) sits outside the Obsidian folder.
- Obsidian has no notion of scope, authority, freshness or line-level provenance. Those live in frontmatter and our scripts.

## Rules for living with Obsidian
Open only `Brain System/` · filenames unique across the vault (enforced by `coverage_check.py` and the scanner) · `00-toc/` and generated notes are never edited by hand · plugins that write files must be listed in the undo list · the scanner runs after every consolidation.
