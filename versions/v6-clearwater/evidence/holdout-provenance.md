# Routing provenance — who wrote which prompts, and when, relative to the router changes

Times come from `evidence.jsonl` of session `20261113-174230-claude-2f97`, written by the live brain's PostToolUse hook as each shell command ran (not by the maker). The raw records are in `hook-log-extract.jsonl` (same folder).

| time (2026-11-13) | event |
|---|---|
| 2026-11-13 17:45:53 | HOLDOUT 1 written and first measured, on the untouched v5 router |
| 2026-11-13 17:55:16 | ROUTER edited: -ing variants + thin-prompt gate added |
| 2026-11-13 17:55:45 | ROUTER edited: gate set to two content words |
| 2026-11-13 18:10:45 | (linker incident) the maker restores the conversation's link to its own session |
| 2026-11-13 18:16:47 | ROUTER comment reworded (patch3.py; no logic) |
| 2026-11-13 18:17:29 | HOLDOUT 2 written, then measured |
| 2026-11-13 22:43:00 | REAL TRAFFIC first measured (v6 with -ing variants vs v5): 32 of 63 real requests changed |
| 2026-11-13 22:44:28 | ROUTER edited: -ing variants withdrawn (patch8.py); the gate is the only router change left |
| 2026-11-13 22:44:54 | FINAL measurement on the final router: tuned set, both holdouts, real traffic |

| file | sha256 |
|---|---|
| `tools/hydro_skills.py` at git `37b465c` (Gemini's v5 router) | `aee7aa9f6d4e632c2eed0d1f707e58e2cdea00beb35774cd32d09926501c2430` |
| `tools/hydro_skills.py` final v6 (the router every number in `measure-after.json`, `route-eval*.txt` and `real-traffic-v6.json` was produced with) | `3de37b58766ec24308b8fda2eeb7bf57961a7addd0d848752373116abbfc55ee` |
| `state/eval/prompt-skills-holdout.json` | `2f65f595e58844dd3f00432f2b6a6fef63a49dc4a72668cda05318ce6dfd77bd` |
| `state/eval/prompt-skills-holdout-2.json` | `c2ed4333363ca0598167e84f40a0715249d6688cac2e57685228dc4092a0150f` |

## What is blind and what is not (stated so the reader does not have to guess)
1. **the owner's real words (`real-traffic-*.json`, `tools/route_real.py`) — blind for every router author.** The 63 requests are the "Request (verbatim)" of closed, non-private sessions in the live brain; the 21 short messages are the owner's typed messages of at most four words from the local Claude Code transcripts. The owner wrote them before v6 existed; no agent chose or edited them; the only label used is a real `Read` of a SKILL.md in a session's evidence log. Result: the offered skill list is identical for 63 of 63 real requests (v6 changes nothing for real task requests); the two sessions with a real skill read have that skill offered by both routers; of 21 real short messages, 8 got a skill list under v5 and 2 under v6. One caveat: the maker saw one of the 63 requests earlier in the session (session `…b1c2`, used as the sample for the judge brief).
2. **Holdout 1 — blind for Gemini's router, not for v6's gate.** Written and measured before the first router edit (first row). The reviewer then shaped the gate with its results in view.
3. **Holdout 2 — written after the gate was fixed, by the same agent that wrote the gate.** Not independent in authorship; and the router was edited once more afterwards (the withdrawal of the -ing rule, decided on the owner's real requests, not on this set). It was re-run on the final router: unchanged result (17/20 · 2/20).
4. What does not exist: a labelled set of task prompts written by someone other than a router author. It can only come from the owner, or from use: every session that reads a SKILL.md adds one label to `route_real.py` by itself.
