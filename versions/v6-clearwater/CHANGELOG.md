# Changelog — v6 "Clearwater" (2026-11-13)

New files
- `tools/brain_map.py` — project map (query, outline, slice, who, build, stats).
- `tools/brain.py` — one entry point; forwards to the existing tools.
- `judge/lenses.json` — per-scope lenses for the judge brief.
- `agents/brain-verifier.md` — claims-against-records subagent.
- `state/eval/prompt-skills-holdout.json`, `state/eval/prompt-skills-holdout-2.json` — blind routing sets.
- `tools/route_real.py` — the router on the owner's real requests and short messages (reported only; stores no message text).
- `tools/tests/test_v6_clearwater.py` — 40 tests; `TESTMAP.md` maps every behaviour to its test.
- `versions/v6-clearwater/` — this record.

Changed
- `tools/brain_judge.py` — judge brief (manifest, ledger, errors, previous round, changes, lenses), fair size budget with named cuts, sealed artifact copies, schema fields `fix` / `inputs_missing` / `unsupported_claims`, `review_verdict()` (+ `quoted()`), `--preflight`, `--export DIR`, `--record FILE --judge-name NAME`, `--sealed-only FILE…`, `prepare()`/`unseal()`/`seal_plan()` (the packet names only copies that exist), `PASS?` for a check that exits 0 on an error, `judge-brief-NN.md`, fix list in the result, duplicate artifacts counted once, judge CLI timeout/start failure reported instead of raised.
- `tools/judge_typed.py` — `status` counts uncalibrated escalations apart and raises `calibrate_threshold`.
- `tools/brain_hooks.py` — say-once hook state, machine-message skip, `$BRAIN` skill paths, logs excluded from note hints, linker hardened (`runs_new`, `fresh_session`), `brain.py new` recognised.
- `tools/hydro_skills.py` — thin-prompt evidence gate; `variants()` (v4's plural forms in one function; the -ing rule was withdrawn).
- `tools/brain_start.py` — shorter card around `BRAIN`, `resume_card()` for compact/resume.
- `tools/brain_session.py` — `capsule` command, refreshed by `checkpoint`.
- `tools/brain_fetch.py` — `--outline`, `--section`.
- `tools/brain_learn.py` — queue takes proposed lessons only, max 3 per session; ledger line for gotchas; a one-word skill name in prose no longer counts as "used".
- `tools/brain_dream.py` — whole-sentence reflections, recurring errors only, hook-error signatures, topical anchor for bridges, logs typed `log`, LaunchAgent without `--apply-links`, honest docstring for the synonym stage, real `started` time, alert printing tolerant of the new alert kind.
- `tools/brain_route.py` — notes of `type: log` are not returned.
- `tools/brain_sleep.py` — eight lesson boxes with ranking, cost line (`token_week()`).
- `tools/route_eval.py` — `--holdout`.
- `tools/tier0.py` — `BRAIN_TIER0_TIMEOUT` raises the 300 s limit of a `cmd` check (a timeout stays a fail).
- `agents/brain-scout.md`, `brain-worker.md`, `brain-scribe.md` — map, slice, capsule, stricter output rules.
- `AGENTS.md` — rewritten for v6 (5,755 chars); no longer says "live".
- `HANDOFF.md`, `START-HERE.md`, `ROADMAP.md`, `tools/tools-v2-readme.md` — v6 state.
- `.gitignore` — `index/maps/`, `state/map-savings.jsonl`, `state/hook-seen.json`.

Unchanged on purpose
- `tools/tests/test_*.py` of v2–v5: none edited; all 111 still pass.
- `tools/hydro_install.py`, `tools/gym.py`, `tools/harness2.py`, `tools/brain_index.py`, `tools/brain_mcp.py` (still 10 tools), the vault notes, the skill packs, the presentations.
