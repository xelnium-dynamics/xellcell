---
description: Route, inspect, and enforce required technical skills before execution (Command -> Agent -> Skill)
allowed-tools:
  - Bash
  - Read
  - Agent
---

# /hydro-skills — Skill Routing & Gap Resolution

## Execution Contract
1. Query the router for the exact user request and scope:
   `python3 -I "$BRAIN_ROOT/tools/brain_route.py" --query "<task words>" --scope <scope_class> --skills-only`
   (or inspect the current session's `sessions/<id>/retrieval-NN.md`).
2. Read the top returned `SKILL.md` files (plus their `## Gotchas`) BEFORE editing code or designs.
3. **Fail-closed check**: If a domain task returns 0 matching skills or misses an expected specialist skill (the skill your task obviously needs), invoke `brain-hunter` (for skill search) before proceeding.
