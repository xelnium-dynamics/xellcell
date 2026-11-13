---
title: Tools v2
type: guide
summary: Every live brain script, how to run it, what it proves, and its test status (2026-11-08).
updated: 2026-11-08
---
# Tools v2

Python 3 standard library only, run with `python3 -I`. No paid calls, except the judge, which calls a model CLI and is used only at step 6 of the flow. Read-only tools refuse to write inside the folder they read. `brainlib.py` holds the shared paths and helpers. You can override the paths with `BRAIN_ROOT`, `BRAIN_VAULT` or `BRAIN_INDEX_DB`.

## Session flow (the 7 steps in `AGENTS.md`)
| Script | What it does |
|---|---|
| `brain_start.py` | Prints the readiness card: release, index freshness, judge health, folder → project, open sessions, the flow, the rules. It is the SessionStart hook for Claude and Codex, and never fails. |
| `brain_session.py` | `new` writes a session folder with `contract.md` and `meta.json`. `checkpoint` adds a note. `close` refuses empty summaries, then writes the episode, queues a proposed lesson and rebuilds the index, so the episode appears linked in Obsidian at once. `status` lists open sessions. |
| `brain_route.py` | Full-text search over notes and skills with the scope gate. It rebuilds a stale index first and writes `retrieval-NN.md` into the session. |
| `brain_judge.py` | Tier 0 runs the contract's `cmd:` checks. Then the other vendor judges blind (contract + artifacts + Tier-0 results). Writes `verdict-NN.json`. Exit 0 pass, 1 fail, 2 inconclusive. |
| `judge_smoke.sh` | Proves which judge CLIs really work (good canary, bad canary, write test). Writes `judge-health.json`, which the card and the judge read. |

## Vault upkeep (after any change to `Brain System/`)
| Script | What it does |
|---|---|
| `brain_index.py` | Builds `index/brain.db` (notes + skills) and the TOC notes in `Brain System/00-toc/`. `--check` only reports fresh or stale. |
| `vault_scan.py` | Structural scan: ghosts (all link kinds), ambiguous names, missing headings and blocks, outside-vault links, orphans, duplicates. |
| `scan_external.py` | Read-only catalog of an external drive's skills and Git repositories into `state/external/<label>.json`. Skips tests, backups, translations, non-English text, moved stubs and anything from the removed Hermes agent. Folds mass-generated skill families into one entry. `brain_index.py` then lists the skills that are not installed, and the repositories, on generated `drive-<label>` pages and in search. |
| `vault_audit.py` | Content audit: frontmatter, empty notes, disallowed scripts, garbled text, Hermes stubs, language-default rules, raw-source references, old-vault instructions. |

## Evidence and migration
| Script | What it does |
|---|---|
| `snapshot.py` | Copy-only, never-overwrite snapshot into `raw/` with a SHA-256 manifest. `verify` re-hashes. |
| `segment.py` | Cuts every note into line-ranged blocks with stable ids and proves every line is covered. |
| `coverage_check.py` | Proves a placement plan gives every block exactly one fate and covers 100% of lines. |
| `migrate_old_vault.py` | The line-by-line migration of the old vault (plan, link rewrite, redirects, raw references). |
| `token_meter.py` | Measures real token use from Claude Code and Codex logs. |

## Run
```bash
bash tools/test_all.sh
python3 -I tools/brain_start.py --agent claude --format text
python3 -I tools/brain_session.py new --agent claude --cwd "$PWD" --title "<title>" [--lane fast|standard|deep] [--scope <class>]
python3 -I tools/brain_session.py checkpoint --session <id> --note "<text>"
python3 -I tools/brain_session.py close --session <id> [--approval approved]
python3 -I tools/brain_route.py --session <id>   # or --query "<words>" --scope <class>
python3 -I tools/brain_judge.py --session <id> --artifacts <files> [--dry-run]
python3 -I tools/brain_index.py [--check]
python3 -I tools/scan_external.py --root /Volumes/<DRIVE> --label <DRIVE> [--enrich <repository catalog.json>]
python3 -I tools/vault_scan.py --vault "Brain System" --out <folder outside it>
python3 -I tools/vault_audit.py --vault "Brain System" --out <folder outside it>
python3 -I tools/snapshot.py copy --src <folder> --dest raw/<name> --manifest raw/manifests/<name>.json
python3 -I tools/snapshot.py verify --manifest <manifest.json> [--src <folder>]
python3 -I tools/segment.py --vault <vault> --out <folder outside it> [--with-text]
python3 -I tools/coverage_check.py --blocks <blocks.jsonl> --plan <plan.csv>
python3 -I tools/token_meter.py claude ~/.claude/projects/<project>
```

## Tests
`bash tools/test_all.sh` runs 18 tests: 9 in `tests/test_tools.py` (scan, snapshot, segment, coverage, token meter) and 9 in `tests/test_live_tools.py` (card shape and never-fail, session lifecycle with immediate TOC linking, index + TOC + routing with the scope gate, judge packet and Tier 0 with a fake judge CLI, migration end to end, audit, scan of escaped table pipes, external drive catalog).

## Wired layers (2026-11-08, D-042)
| Tool | Layer | What it does | Runs |
|---|---|---|---|
| `brain_hooks.py prompt/pre/post/end` | 1,3,5,7,10,13 | per-message skills + notes, flow status; contract gate on edits; self/ scope gate; ACTION-RISK ask; PRIVACY-LEAK; evidence.jsonl; session analysis | Claude hooks (Codex after trust) |
| `brain_fetch.py` | 3,4 | scope-gated note reading + retrieval log (used / rejected / missing) | agent, step 2 |
| `tier0.py` | 8 | hard checks per requirement: cmd, exists, contains, links, html, json, image, vault | brain_judge, or by hand |
| `judge_typed.py ask/calibrate/canaries/health/gold` | 8 | typed questions, Tier 1 (Haiku ×2) → Tier 2 (other vendor), thresholds, judge health v2 | agent, sleep |
| `route_eval.py` | 4 | labeled retrieval sets; exit 0 only if every gate passes | sleep, gym, by hand |
| `entry_matrix.py` | 1 | live start-up cases for Claude and Codex | by hand |
| `pilot.py off/report/off-decide` | 13 | brain-off arm + cost per approved delivery | The owner |
| `brain_sleep.py` | 11, 12 C | daily: raw verify, analyse sessions, queue → candidate lessons, checks, release tag, digest | started by the card |
| `lesson_decide.py` | 11 | The owner approves / rejects a candidate lesson | The owner |
| `harness2.py` | 9, 12 A | budgeted in-task improvement cycle with a mandatory final run | agent after 2 failed judge rounds |
| `gym.py` | 12 B | weekly: tune state/harness-config.json, holdout + ratchet + protected surface | sleep job |
| `brain_mcp.py` | 1 | the brain as an MCP server for Claude Chat / Cowork | Claude desktop app (after the owner registers it) |
| `agents/brain-{scout,hunter,scribe,worker}.md` | 6, 10 | subagents with work orders and menus | Agent tool |

## v2.1 "Ironclad" (2026-11-09) — from Argon's review, approved by the owner
Folder with plan, changelog, undo and evidence: `versions/v2.1-ironclad/`.
- Shared state: `brainlib.lock()` (fcntl, state/*.lock) around the index build, live-links and commits; `brainlib.git_commit_paths()`
  commits only its own paths through a private git index (never sweeps in staged work). The sleep job starts at session END.
- Gates (`tools/brain_hooks.py`): self/ resolved with realpath (./, globs, `cd`, 'a' + 'b', recursive readers, Grep/Glob above
  self/); writes found in sed -i, perl -pi, dd, tar -x, curl -o, git checkout --, python -c …; PRIVACY-LEAK on network shell
  commands; a session may always write its own folder; a contract needs the request AND a real R1.
- Judges: The owner's labels in `judge/gold/owner/` (append-only) merged into `judge/gold/<qid>.jsonl`; `brain_session.py decide
  [--failed R2]` → REQ-MET, `tools/lesson_decide.py` → SCOPE-COVER; `judge_typed.py calibrate --tier2-vendor`; the blind
  packet always carries report + both summaries; JSON parsed with `brainlib.last_json`.
- Numbers: gym/results.tsv v2 header (v1 rows in gym/results-v1-archive.tsv); 123 eval tasks (8 real failures);
  `tools/pilot.py` counts closed sessions only and splits fresh tokens from cache reads.
- Harness²: `tools/harness2.py` probes each arm in its own copy (`start --scope`, patches via `propose --general-patch`);
  `compare` judges every arm; `adapt [--propose]` builds the Harness² context + INV/DOM briefs; ledger counts R, P, tokens.
- New: `tools/tree_validate.py` (always-on cap, compile, references, agents, hooks); Tier 0 `pdf_pages`, `stl_bbox`,
  `stl_manifold`, `brand_tokens`, `html_viewport`; `gym.py --suite work-tasks` (state/eval/work-tasks.json, 8 tasks, 4 domains).
- Routing: `brain_route.py --novelty explore`, `--budget` (constraints reserved), `state/synonyms.json`, exact-name and
  installed-first skill ranking, read-time rebuilds touch the database only (`BRAIN_ROUTE_READONLY=1` skips them).
- Flow: one-command fast lane (`new --lane fast --request …`, `close --summary`); close checks the files the Verified row
  cites (`--force-claims` records an override); `lint` syncs lane/scope into meta.json; `brain_session.py handoff`
  rewrites the auto table in HANDOFF.md; the card shows live judge readiness, the latest sessions of all agents, unclosed ones.
- Sleep: lessons need a sessions/ or raw/ source; `depends_on` staleness; checkbox digest + `brain_sleep.py --apply-digest`.
- Tests: 53 (`bash tools/test_all.sh`); `tools/tests/test_v21.py` holds one test per fix (20 of its 21 fail on v2.0 code).

## v6 "Clearwater" additions (2026-11-13)
| Script | What it does |
|---|---|
| `brain.py` | One entry point: `new`, `lint`, `checkpoint`, `capsule`, `close`, `fetch`, `route`, `map`, `preflight`, `judge`, `learn`, `verify`, `plugins`. Forwards arguments and exit codes to the tools below; the long names keep working. |
| `brain_map.py` | Project map. `query "<words>"` returns pointers `path:Lstart-Lend`; `outline <file>`; `slice <file> --symbol <name>` prints only that range; `who <name>`; `stats`. Deterministic, incremental, never maps `Brain System/self`. |
| `brain_judge.py` | Now builds the judge brief (manifest, requirement ledger, errors, previous round, changes, lenses from `judge/lenses.json`), seals copies of the artifacts for the judge, checks the judge's answer, returns a fix list. `--preflight` = the free part only. |
| `brain_session.py capsule` | The session in one screen, from its records; rewritten by every checkpoint; printed by `brain_start.py` after a compaction. |
| `brain_fetch.py --outline / --section` | Headings with line ranges, or one section of a note. |
| `route_eval.py --holdout` | Reports the blind sets `state/eval/prompt-skills-holdout*.json`. Never a gate; never tune against them. |
| `route_real.py` | The router on the owner's own words: offered skills for every closed non-private session's verbatim request, hit rate for sessions with a real SKILL.md read, share of his short typed messages that get a skill list. Stores no message text. Reported, never a gate. |
| `brain_judge.py --export DIR` / `--record FILE` | The judge packet, schema and sealed copies as files, for a judge that is run by hand; then its answer recorded and checked like any other round. |
Tests: `tools/tests/test_v6_clearwater.py` (40); map in `versions/v6-clearwater/TESTMAP.md`.

## v7 "Xelcell" additions (2026-11-14)
| Script | What it does |
|---|---|
| `route_real.py --sheet FILE` / `--labels FILE` | A local tick sheet with the owner's own requests and short messages (git-ignored), and the router scored against his ticks. Requests are routed with their session's scope. |
| `brain_learn.py --rebuild-telemetry` | Recounts `state/skill-telemetry.json` from all session records with the current "used" rule; the old file is kept beside it. |
Tests: `tools/tests/test_v7_xelcell.py`; map in `versions/v7-xelcell/TESTMAP.md`.
