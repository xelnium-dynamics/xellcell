---
title: Global pointer template
type: template
summary: The few lines that go into ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md, so every session in any folder enters the same brain.
updated: 2026-11-08
---
# Global pointer (install at cutover, phase 1.6 / 2.2)

## For `~/.claude/CLAUDE.md` (added at the top)
```
# Agent Brain (global pointer)
Shared brain: {{BRAIN_ROOT}}. Your entry is the readiness card injected by the SessionStart hook.
If it is missing, run: python3 -I {{BRAIN_ROOT}}/tools/brain_start.py --agent claude --cwd "$PWD"
Then follow {{BRAIN_ROOT}}/AGENTS.md. Use absolute paths.
Hard rules: no paid API or spend without the owner's release · never delete: Trash or _to_delete, and tell the owner.
```

## For `~/.codex/AGENTS.md` (added at the top; the existing Codex rules stay)
```
# Agent Brain (global pointer)
Shared brain: {{BRAIN_ROOT}}. First run: python3 -I {{BRAIN_ROOT}}/tools/brain_start.py --agent codex --cwd "$PWD"
Read only its output, then follow {{BRAIN_ROOT}}/AGENTS.md. Use absolute paths.
```

## Notes
- The rest of `~/.claude/CLAUDE.md` is not part of the brain. Whether it stays is a boot-diet decision for the owner, measured with `token_meter.py`.
- Each line added or removed goes into `state/integration-manifest.md` with its undo ([[layer-00-integrity]]).
