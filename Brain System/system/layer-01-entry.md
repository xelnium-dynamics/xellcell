---
title: Layer 1 - Entry
type: system
summary: How every Claude Code and Codex session, started from any folder, enters the same brain with a small readiness card instead of a flood of context.
updated: 2026-11-08
---
# Layer 1 — Entry

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Same brain from any folder, small boot | Session start, current folder | Readiness card (≤ 60 lines) | `brain_start.py` + agent adapter | Agent says "brain offline", works natively, logs it | Start from 3 outside folders in both agents |

## The problems this fixes (all verified on 2026-11-08)
- Claude Code loads a project CLAUDE.md only from the folder it starts in, and v1's boot file used folder-relative paths. A CV session started in another folder never saw the brain.
- The old global `~/.claude/CLAUDE.md` ordered every session to read the old vault (including a 320 KB Current State) and write back to it: two brains competing.
- Boot weight: this session's first turn already carried **100,898 tokens** before any file was read ([[layer-13-accounting]]).

## Mechanism
1. **One global pointer** (≤ 8 lines, absolute paths) in `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`. It replaces the old Xelnium banner at cutover. Template: [[global-pointer.template]].
2. **The readiness card is injected, not remembered.** Both agents run `python3 -I "<brain>/tools/brain_start.py" --agent <claude|codex>` as a SessionStart hook (`~/.claude/settings.json`, `~/.codex/hooks.json`); it reads the session's folder from the hook input and its output enters the session. If the hook does not run, the global pointer tells the agent to run the same command with `--format text` first.
   - Verified 2026-11-08: Claude Code fresh sessions started in `~/Desktop/Success` received the card with `project: job-search` (transcripts in `~/.claude/projects/-Users-you-Desktop-Success/`), and the desktop app received it on session start in this folder.
   - Codex 0.166 runs a hook only after the owner trusts it once (stored as `trusted_hash` in `~/.codex/config.toml`). Until then Codex lists it as "1 hook needs review" at startup and skips it. Agents must not write that trust themselves or pass `--dangerously-bypass-hook-trust`. The fallback works: a fresh Codex session in `~/Desktop/Success` ran the card command itself, as its global instructions say, and reported `project: job-search` (`reports/live-check-2026-11-08/codex-fallback-evidence.txt`).
3. **The card contains:** brain release id · index fresh or stale · open handoffs and unclosed sessions for this folder's project · judge health age · today's hard rules · the 7-line protocol pointer. **It contains no personal data and no knowledge content.** Knowledge arrives only through retrieval ([[layer-04-retrieval-toc]]).
4. **Boot diet.** The global file keeps only the pointer + hard rules. Skills: at most 25 always-on per project, the rest listed in the registry and loaded by card. The cap is applied **per project** (project settings), never machine-wide, and recorded in the undo list ([[layer-00-integrity]]). Measured with `/context` and `token_meter.py` before and after.

## Agent adapters (facts, with verification state)
| | Claude Code | Codex |
|---|---|---|
| Boot file | CLAUDE.md (`@AGENTS.md` + adapter lines) | AGENTS.md (32 KiB cap) |
| Start hook | SessionStart hook: verified | SessionStart hook: installed, runs after the owner trusts it once (startup "Trust all and continue" or `/hooks`); AGENTS.md pointer is the fallback |
| Subagents | `.claude/agents/*.md`, `model:` field | `.codex/agents/*.toml` |
| New skill mid-session | hot reload | run as script until verified |
| Judges the other | `claude -p --json-schema`, read-only | `codex exec --output-schema`, read-only sandbox |
| Token log | `~/.claude/projects/*/*.jsonl` | `~/.codex/sessions/**/rollout-*.jsonl` |
| Runtime note | native binary | Node script; Node now at `~/.local/node` (moved out of Hermes on 2026-11-08) |

Boot templates: [[AGENTS.template]] · [[CLAUDE.template]]
