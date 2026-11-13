---
title: CLAUDE template
type: template
summary: The slim Claude Code boot file - imports AGENTS.md and adds only Claude-specific facts. Installed as CLAUDE.md at cutover.
updated: 2026-11-08
---
<!-- Install: remove this frontmatter; keep the file under 15 lines. -->
@AGENTS.md
# Claude Code adapter
- Scout = `.claude/agents/scout.md` (Haiku, read-only). The built-in Explore agent runs on the main model; do not use it for bulk search.
- Scribe = `.claude/agents/scribe.md` (Haiku; writes only `sessions/<id>/`, enforced by hook).
- Your work is judged by Codex (`codex exec`, read-only sandbox), never by yourself.
- New skills hot-reload; `/reload-skills` forces a rescan. Do not export `CLAUDE_CODE_SUBAGENT_MODEL`.
