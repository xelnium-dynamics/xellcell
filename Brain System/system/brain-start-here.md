---
title: Brain start here
type: guide
summary: The live Agent Brain - where it lives, how every Claude Code and Codex session enters it, how to browse it in Obsidian, and what is built versus still designed.
updated: 2026-11-08
---
# Agent Brain: start here

The brain is **live** since 2026-11-08 at `~/Desktop/Agent Brain`. Every Claude Code and Codex session, started in any folder, gets a readiness card from the brain and follows the same seven-step flow ([[brain-v2-map]]). Claude gets it from its start hook. Codex gets it from its start hook once the owner has trusted that hook in Codex; until then Codex's global instructions make it run the card command itself (both tested 2026-11-08, see [[layer-01-entry]]).

## For the owner
- **Browse in Obsidian:** open the folder `~/Desktop/Agent Brain/Brain System` as a vault. Start at [[toc-home]]. Only clean, sorted knowledge is in there; evidence and machine files sit beside it.
- **What the old vault became:** every real note was sorted into self / projects / domains / capabilities / history, line by line, with a source reference back to the untouched copy in `raw/obsidian-vault/2026-11-08/`. Junk, Hermes material and foreign-language filler stayed only in that evidence copy, each with a recorded reason (vault-cleanup-tonight).
- **Skills:** every skill Claude Code or Codex can use is listed by category in [[skills-registry]].

## For agents
1. The readiness card is injected at session start (Claude and Codex hooks). If it is missing: `python3 -I "~/Desktop/Agent Brain/tools/brain_start.py" --agent <claude|codex> --format text`.
2. Follow `AGENTS.md` at the brain root. Legacy notes (authority: legacy) never override it.
3. Search with `tools/brain_route.py`; never bulk-read `Brain System/` or `raw/`.

## Built and verified vs designed
| Live and tested | Designed, not built yet |
|---|---|
| Readiness card + SessionStart hooks (Claude, Codex), global pointers | Typed Tier-1 judge with calibrated thresholds (cold start escalates to Tier 2) |
| Session records: contract, checkpoints, closeout with two summaries | Sleep consolidation job and releases beyond the first |
| Router with scope gate + full-text index + table of contents + skills registry | In-task Harness² and the night shift (after the pilot) |
| Cross-vendor judge runner (Tier 0 + Tier 2) | Evidence-capture hook for every shell command |
| Old vault migrated: every line accounted for, 0 ghosts, 0 ambiguous names | The four-session pilot that proves the brain helps |

Everything else: [[brain-v2-index]] · build order: roadmap-v2 · decisions: decisions-v2.
