---
title: Source coverage v2
type: system
summary: Each mechanism of Harness², Karpathy's LLM Wiki and autoresearch, Agent Skills, Background Dreaming and JEV, where it lives, and its honest level - mentioned, specified, built or verified.
updated: 2026-11-13
---
# Source coverage v2 (updated for Hydro Brain 2 / v5)

Levels: **mentioned** (named only) · **specified** (a layer page says exactly how) · **built** (code exists and its tests pass) · **verified** (shown working on real tasks).

## Google Harness²
| Mechanism | In v5 (Hydro Brain 2) | Level |
|---|---|---|
| Improve the harness, never the weights | D-001 + `harness2.py` + `gym.py` | **built** |
| Task-level propose → probe → compose on the current task | `tools/harness2.py` (`adapt` + `propose` + `probe` + `compose` + `close`) | **built** |
| Reference run of the current harness | `harness2.py probe --arm reference` | **built** |
| Two proposals: invariant (general) + domain | `harness2.py adapt` (`AUTO-HYPOTHESES.md`, `BRIEF-INV.md`, `BRIEF-DOM.md`) | **built** |
| Probes under matched settings | Isolated workspace copy probes + `MAX_EXTRA=3` + token cap | **built** |
| Composer merges only observation-backed changes | `harness2.py compose` requires Tier-0 pass | **built** |
| Final execution of the composed harness (base + 2 candidates + final) | Mandatory `composed` run enforced by `close` | **built** |
| Improvement library: harness + EXPERIENCE (situation, lesson, evidence) | `state/harness2-experience.jsonl` + `Brain System/lessons/harness2-experience.md` | **built** |
| Next task starts from the base; the library only informs | `EXPERIENCE.md` fed into `adapt()`, never auto-mutates shared rules | **built** |
| Eight editable parts (prompt, guardrails, memory, skills, tool guidance, scripts, subagents, plugins) | Tracked explicitly in `harness2.py` (`HARNESS_PARTS`, `--inv-part`, `--dom-part`) | **built** |
| Works without ground truth | Tier 0 + `PAIR-BETTER` across `general`, `domain`, and `composed` | **built** |

## Karpathy LLM Wiki
| Mechanism | In v5 (Hydro Brain 2) | Level |
|---|---|---|
| Raw sources immutable | `raw/` + `snapshot.py` + pre-tool gate | **built** |
| Wiki maintained by the LLM + idle background dreaming | `Brain System/` + `brain_learn.py` + `brain_sleep.py` + `brain_dream.py` | **built** |
| Schema (CLAUDE.md / AGENTS.md) | `AGENTS.md`, `CLAUDE.md`, `.claude/rules/` | **built** |
| Ingest (summary, entity, concept pages, index, log) | `brain_learn.py` + `brain_dream.py` + `brain_index.py` | **built** |
| Query: index first, cited answer; good answers filed back | `brain_route.py` + `brain_fetch.py` + `brain_learn.py` | **built** |
| Lint: contradictions, orphans, missing pages, ghosts, self-citation loops | `vault_scan.py` + `vault_audit.py` + `brain_dream.py` | **built** |
| index.md + append-only log.md | `brain-v2-index`, `brain-v2-log`, `dream-journal.md`, `00-toc/` | **built** |
| Search tool past ~100 sources | SQLite FTS5 (`index/brain.db`) + `hydro_skills.py` inverted index | **built** |

## Karpathy autoresearch
| Mechanism | In v5 (Hydro Brain 2) | Level |
|---|---|---|
| Fixed, protected evaluation | `PROTECTED` SHA-256 surface in `tools/gym.py` | **built** |
| One change per experiment, fixed budget | `gym.py` grid + `harness2.py` budget + `brain_dream.py` micro-caps | **built** |
| Keep if better, reset if not | `gym.py` ratchet (`HS.CFG_OVERRIDE`) + git tags + `sleep` auto-revert | **built** |
| `results.tsv` log, crash status | `gym/results.tsv` + `state/dream-experiments.jsonl` | **built** |
| Simpler and equal = keep | `_complexity()` tie-break in `gym.py` ratchet | **built** |
| "Never stop" | Bounded by budget caps + idle/load guard in `brain_dream.py` | **built** |
| Human edits the instructions, not the code | The owner edits `AGENTS.md`, contracts, and approves `queue/` lessons | **built** |

## Agent Skills / Voyager
| Mechanism | In v5 (Hydro Brain 2) | Level |
|---|---|---|
| Skill library, name + description first, body on demand | `hydro_skills.py` (1,311+ skills, families, synonyms, telemetry boost) | **built** |
| Hot-load mid-session | Claude `brain_route`/`brain_fetch`/`brain_find_skills`; Codex scripts | **built** |
| Verify before keeping | Quarantine + `state/quarantine-ledger.json` + the owner's OK | **built** |
| Automatic curriculum | `dream-skill-gaps.md` + `inspect()` suggest; the owner chooses | **built** |

## JEV (TypeSafe AI)
| Mechanism | In v5 (Hydro Brain 2) | Level |
|---|---|---|
| Typed questions over a declared state, no prose | 12 question specs in `judge/questions/` | **built** |
| Probability per label | Agreement-based Tier 1 confidence; JEV plug-in after spend release | **built** |
| Accept when confident, escalate when unsure | Tier 1 → Tier 2 blind cross-vendor in `judge_typed.py` | **built** |
| Thresholds from ~30 local labels, lower-bound rule + escalation alert | `judge_typed.py calibrate` + `judge_typed.py status` (>50% rewrite alert) | **built** |
| Known weak spots routed away | `route_direct_to_tier2_when` in question configs | **built** |
| Pairwise both orders | `PAIR-BETTER` both orders | **built** |
