---
description: Run full Tier 0, routing eval, and harness validation verification gate
allowed-tools:
  - Bash
  - Read
---

# /hydro-verify — Deterministic Verification Gate

Run all objective verification checks before closing or shipping work:
1. If inside a session: run `python3 -I "$BRAIN_ROOT/tools/brain_session.py" lint --session <id>` and `python3 -I "$BRAIN_ROOT/tools/tier0.py" --session <id>`.
2. Run harness checks in `HYDRO BRAIN`:
   - `python3 -I tools/tree_validate.py`
   - `python3 -I tools/route_eval.py`
   - `bash tools/test_all.sh`
3. Report only directly observed pass/fail numbers; never extrapolate unrun checks.
