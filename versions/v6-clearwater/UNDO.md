# Undo — v6 "Clearwater"

Nothing is committed and nothing outside this folder was touched, so undo is a git operation inside `~/Desktop/HYDRO BRAIN`.

Everything, back to v5 (`37b465c`):
```bash
cd "~/Desktop/HYDRO BRAIN"
git stash push --include-untracked -m "v6-clearwater"     # keeps v6 recoverable: git stash pop
```
One part only (examples):
```bash
git checkout -- tools/hydro_skills.py                      # router back to v5 (gate + variants off)
git checkout -- tools/brain_hooks.py                       # hooks back to v5 (or just: export BRAIN_HOOK_VERBOSE=1)
git checkout -- tools/brain_judge.py tools/judge_typed.py  # judge back to v5; then move judge/lenses.json to _to_delete/
git checkout -- tools/brain_dream.py tools/brain_learn.py tools/brain_sleep.py tools/brain_route.py
```
New files are untracked: move them to `_to_delete/` (never delete): `tools/brain_map.py`, `tools/brain.py`, `judge/lenses.json`, `agents/brain-verifier.md`, `state/eval/prompt-skills-holdout*.json`, `tools/tests/test_v6_clearwater.py`, `versions/v6-clearwater/`. If `brain.py` goes, `tools/brain_start.py` and `AGENTS.md` must go back too (they name it).

Runtime files v6 creates (safe to move away at any time): `index/maps/`, `state/map-savings.jsonl`, `state/hook-seen.json`, `sessions/<id>/capsule.md`, `sessions/<id>/judge-brief-NN.md`.

During this session one test artefact was moved, not deleted: `_to_delete/2026-11-13/test-capsule-b1c2.md`.
