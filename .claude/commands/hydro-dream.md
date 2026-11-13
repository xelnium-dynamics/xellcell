---
description: Run or inspect Hydro Brain 2's lightweight dreaming self-improvement layer (tools/brain_dream.py)
allowed-tools:
  - Bash
  - Read
---

# /hydro-dream — Background Dreaming Self-Improvement

1. Check dreaming status, macOS idle guard, and last summary:
   `python3 -I "$BRAIN_ROOT/tools/brain_dream.py" --status`
2. Run a gentle on-demand cycle (transcript thinking/reasoning mining, unlearned sessions, missing-node graph map, wiki lint, skill-gap refresh):
   `python3 -I "$BRAIN_ROOT/tools/brain_dream.py" --once`
3. Optionally weave verified missing-node links into eligible non-private notes (auto-rolled back on any `vault_scan` / `vault_audit` error):
   `python3 -I "$BRAIN_ROOT/tools/brain_dream.py" --once --apply-links`
4. Optional background Mac LaunchAgent (`com.hydrobrain.dream`, runs only when idle & CPU load is low):
   `python3 -I "$BRAIN_ROOT/tools/brain_dream.py" --install-launchd`
