---
title: Layer 13 - Accounting
type: system
summary: Tokens and the owner's effort are measured from the CLIs' own logs by token_meter.py (built and tested), never estimated, with the 2026-11-08 baseline and the one success metric.
updated: 2026-11-08
---
# Layer 13 — Accounting

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Prove the brain helps overall | CLI logs, episodes | Cost per verified useful delivery | `token_meter.py` + script | No savings claim is made | Brain-off vs brain-on pilot |

## Sources (verified 2026-11-08)
- Claude Code: `~/.claude/projects/<project>/<session>.jsonl`, `usage` on each assistant message (deduplicated by message id).
- Codex: `~/.codex/sessions/**/rollout-*.jsonl`, `token_count` events with a running total.
- `tools/token_meter.py` reads both. Zero model tokens. Tested (`tools/tools-v2-readme.md`).

## Baseline measured on 2026-11-08
| Measure | Value |
|---|---|
| First turn of this Claude session (boot context, before reading any file) | 100,898 tokens |
| This Claude session so far | 67 turns, 16.2 M context tokens read (98% cache reads), 163 K output |
| All Codex sessions on this Mac | 26 sessions, 98.7 M total tokens |

## The one success metric
**Cost per verified useful delivery** = all tokens of the task (director, scouts, judges, retries) + a fair share of maintenance (ingest, consolidation, night shift), divided by approved deliveries, shown next to **the owner's corrections per delivery** and his review time. More notes, links or loops are not progress by themselves.

## Rules
- No token or speed claim without these numbers.
- Subscription plans bill by limits, not per token; Codex logs also record rate-limit use, a second signal.
- The never-worse gate: a feature stays only if brain-on is not worse than brain-off on matched tasks (roadmap-v2 phase 6).
