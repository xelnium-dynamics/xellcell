# Changelog — v7 "Xelcell" (2026-11-14), relative to v6 "Clearwater"

- `tools/brain_judge.py` — `quoted()` handles backticked spans and escaped quotes; a pass whose quotes are all unfindable becomes inconclusive; `seal_plan()` requires a readable file; unreadable artifacts are marked UNREADABLE instead of crashing the packet.
- `tools/brain_hooks.py` — `REMIND_AFTER = 8`: a skill shown earlier that fits again is named again with its path; hook memory stores the message number per skill.
- `tools/brain_session.py` — `close` lets `brain_learn.py` queue lessons; the v3 queue code runs only when `brain_learn.py` fails.
- `tools/brain_learn.py` — `--rebuild-telemetry`.
- `tools/brain_map.py` — multi-line template literals are blanked before brace counting; `memo` / `forwardRef` / `lazy` / `styled` components; GLSL precision qualifiers.
- `tools/route_real.py` — requests routed with their session's scope (`offered_general` kept); `--sheet`, `--labels`.
- `tools/brain.py` — forwarded flags first.
- `tools/hydro_install.py` — also rewrites configs that name `~/Desktop/HYDRO BRAIN`.
- `tools/tree_validate.py` — knows the folder name XELCELL.
- `tools/brain_start.py` — card label v7.
- `tools/tests/test_v7_xelcell.py` — new; `tools/tests/test_v6_clearwater.py` — one expectation of `test_j3` follows the stricter quote rule.
- `.gitignore` — `reports/route-labels*.md`.
- State: `state/skill-telemetry.json` rebuilt from records; the v5 file, its log and v5's `dream-reflections.md` / `dream-map.md` moved to `_to_delete/2026-11-13/v5-polluted-state/`; index and TOC rebuilt.
- Docs: `AGENTS.md`, `HANDOFF.md`, `START-HERE.md`, `ROADMAP.md`, `agents/*.md`, `.claude/commands`, `tools/tools-v2-readme.md` point at `~/xellcell`.
