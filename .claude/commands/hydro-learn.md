---
description: Run immediate post-session learning and consolidation (tools/brain_learn.py)
allowed-tools:
  - Bash
  - Read
---

# /hydro-learn — Immediate Post-Session Improvement

1. Identify the session id (or pass `--latest`):
   `python3 -I "$BRAIN_ROOT/tools/brain_learn.py" --session <id>`
2. Review extracted insights in `Brain System/history/learnings/`, queued candidate lessons in `queue/`, and skill usage telemetry updates in `state/skill-telemetry.json`.
3. Rebuild search index incrementally (`python3 -I "$BRAIN_ROOT/tools/brain_index.py"`) so the next session immediately retrieves the new knowledge.
