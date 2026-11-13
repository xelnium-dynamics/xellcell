---
paths:
  - "tools/**/*.py"
---

# Python Tools Standards (XellCell)

- Use Python 3 stdlib first (`python3 -I` safe; zero third-party deps inside `tools/`).
- Write state/config/markdown files via `brainlib.atomic_write` + `brainlib.lock` when mutating shared state.
- Resolve paths from `brainlib.ROOT` (or `HYDRO_BRAIN_ROOT` / `AGENT_BRAIN_ROOT` env overrides), never hardcode `~/AgentBrain`.
- Run regression tests (`bash tools/test_all.sh`), evals (`python3 -I tools/route_eval.py`), and `python3 -I tools/tree_validate.py` after every tool change.
