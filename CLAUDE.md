@AGENTS.md

# Claude Code adapter
- Scouts: for bulk search, use a Haiku subagent with a work order; the built-in Explore agent runs on the main model.
- Your work is judged by Codex (`brain_judge.py` picks the other vendor automatically), never by yourself.
- New skills hot-reload; `/reload-skills` forces a rescan. Do not export `CLAUDE_CODE_SUBAGENT_MODEL`.
