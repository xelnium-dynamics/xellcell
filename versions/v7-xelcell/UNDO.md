# Undo — v7 "Xelcell"

XELCELL is a separate folder. Nothing outside it was changed by v7; `~/Desktop/HYDRO BRAIN` still holds v6 exactly as Argon judged it, and the live brain is `~/AgentBrain`.

- Drop v7 altogether: move `~/xellcell` to the Trash. v6 is intact in `~/Desktop/HYDRO BRAIN`.
- Back to v5 inside this folder: `git stash push --include-untracked -m v7-xelcell` (recover with `git stash pop`).
- One part only: `git checkout -- tools/<file>.py` gives v5's file; v6's file is in `~/Desktop/HYDRO BRAIN/tools/`.
- State set aside by v7 (restore by moving back): `_to_delete/2026-11-13/v5-polluted-state/` (`skill-telemetry.json`, `skill-telemetry.jsonl`, `dream-reflections.md`, `dream-map.md`).
