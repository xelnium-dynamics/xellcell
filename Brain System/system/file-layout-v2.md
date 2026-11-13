---
title: File layout v2
type: system
summary: The live folder tree at ~/Desktop/Agent Brain - Obsidian sees only Brain System/, evidence and machine state sit beside it - and who may write where.
updated: 2026-11-08
---
# File layout v2

```
~/Desktop/Agent Brain/        the brain root (local git repo)
├─ AGENTS.md · CLAUDE.md      the protocol both agents follow (CLAUDE.md = @AGENTS.md + Claude adapter)
├─ ROADMAP.md · START-HERE.md short pointers for people
├─ Brain System/                     ← Obsidian opens ONLY this folder (clean knowledge)
│  ├─ 00-toc/                 generated table of contents + skills registry (never hand-edited)
│  ├─ self/                   identity, profile, career facts (scope-gated)
│  ├─ projects/<name>/        project notes, "<name> - history" (newest first), episodes/
│  ├─ domains/<subject>/      compiled knowledge pages
│  ├─ capabilities/           reusable methods, tool know-how, skill write-ups
│  ├─ history/                history index, legacy logs, histories without a project, episodes/
│  ├─ drawings/               Excalidraw drawings
│  ├─ problems/ · lessons/    pain memory · candidate and released lessons
│  ├─ _attachments/           images and files that notes embed
│  └─ system/                 this design, rules, templates, boot docs
├─ raw/                       evidence copies + manifests (append-only, never in Obsidian)
├─ sessions/<session-id>/     contract, checkpoints, retrieval, verdicts, summaries (working state)
├─ queue/                     candidate lessons waiting for consolidation
├─ index/                     brain.db full-text index (generated)
├─ judge/                     schemas, config, questions, gold sets
├─ gym/                       replay tasks, holdout, results.tsv
├─ state/                     undo list, move log, migration config/decisions, backups
├─ tools/                     scripts + tests
├─ reports/                   scans, audits, removal and migration records
└─ _to_delete/                superseded material waiting for the owner's decision (never deleted by agents)
```
Sensitive personal data (IDs, finances, health) lives **outside** the brain root (Level 2, [[layer-03-scope-gate]]).

## Who writes where
| Path | Writer | Rule |
|---|---|---|
| `raw/` | `snapshot.py` only | append-only, hash-verified |
| `sessions/<id>/` | that session (`brain_session.py`, `brain_route.py`, `brain_judge.py`) | its own folder only |
| `Brain System/projects/<p>/episodes/`, `Brain System/history/episodes/` | `brain_session.py close` | new files only |
| `queue/` | `brain_session.py close` | new files only |
| `Brain System/` (other notes) | Sleep job, or a build step with the owner's OK | lock + staging + release |
| `Brain System/self/` | only with the owner's approval | D-030 |
| `Brain System/00-toc/`, `index/` | `brain_index.py` | generated, never hand-edited |
| `judge/`, `gym/` holdout | build steps with the owner's OK | protected from the improver |
| `state/integration-manifest.md` | any step that changes something outside the brain | every entry has its undo |
| `tools/` | build steps | every script ships with tests |
