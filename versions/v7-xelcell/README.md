# v7 "Xelcell" — v6 after Argon's judge round, every note fixed

> **Public release note.** This is the build record as written during development. Paths and names were made generic for publication; the holdout prompt sets now sit in `versions/v6-clearwater/evidence/holdouts/`; the maintainers' own skill library, prompt set, sessions and private notes are not part of the public repository.


Date `2026-11-14` · folder `~/xellcell` (a copy of `~/Desktop/HYDRO BRAIN` as Argon judged it, plus the fixes below) · base git `37b465c` (v5) · **LIVE since 2026-11-14 (folder renamed xellcell; see HANDOFF.md), committed and tagged `v7-xellcell`** · maker: Claude, session `20261113-174230-claude-2f97` in the live brain.

## Where v7 comes from
- v4, v5: built by Gemini. v6 "Clearwater": the review of that build and the surgery (`versions/v6-clearwater/README.md`).
- Judge rounds on v6: three by Codex (fail, inconclusive, fail), then round 4 by Argon, run by hand from the export package: **pass on all seven requirements**, with eleven notes: five on earlier findings (three fixed, two partly) and six new flaws (three major, three minor). Argon's answer: `evidence/argon-verdict-round4.txt`; as recorded and checked by the brain: `evidence/verdict-04.json`.
- v7 fixes those notes. Nothing else was changed.

## Argon's notes and what was done
| # | Note | Done in v7 | Test |
|---|---|---|---|
| 1 | Quote check: a fabricated quote on a pass only warned | A pass whose quotes are all unfindable becomes inconclusive, and the round with it | `test_q2` |
| 2 | Quote pairing broke on backticked JSON and escaped quotes | Backticked spans are taken out first; escaped quotes are not delimiters | `test_q1` |
| 3 | Unreadable files could appear as sealed in `--dry-run` / `--preflight` | Marked UNREADABLE in the manifest, never advertised, no crash | `test_q3` |
| 4 | The judge's temp folder (packet + sealed copies) is never removed | Left as it is on purpose: "never delete" is the owner's rule, and the folder sits in the system temp area that macOS clears by itself. Said here so it is a decision, not an oversight | — |
| 5 | MAJOR `route_real.py` ignored the session's scope | Each request is routed with its session's scope; scope general is kept beside it | `test_r7` |
| 6 | MAJOR "said once" silenced a needed skill for the rest of a long session | A skill shown earlier that fits again is named again with its path after 8 messages; a compaction makes the hooks say everything once more | `test_h7`, `test_h8` |
| 7 | MAJOR real prompts are almost unlabelled | The labels are the owner's to give. `route_real.py --sheet` writes the tick sheet, `--labels` scores the router against it. Until he ticks, recall on real requests is known for two sessions | `test_r8` |
| 8 | `close` queued the proposed lesson before `brain_learn.py` did | One place queues (`brain_learn.py`); the v3 code is the fallback when it fails | `test_c3`, `test_c4` |
| 9 | Map: braces inside multi-line template literals; memo / forwardRef; GLSL precision | Template literals are blanked before counting; wrapped components are symbols; `highp float f()` is found. Indented `const x = {…}` inside functions stays unmapped by design (it would list every local variable) | `test_m5`, `test_m6` |
| 10 | Polluted v5 telemetry and old dream text still on disk | Set aside in `_to_delete/2026-11-13/v5-polluted-state/`; telemetry rebuilt from the 53 session records: 11 skills with a real use, none of them a one-word name (`evidence/telemetry-rebuilt.json`) | `test_d3` |
| 11 | `brain.py` flag order; three behaviours without a test | Forwarded flags go first; tests for the judge CLI timing out or missing, dream's calibrate alert, the re-offer after a compaction | `test_q5`, `test_q4`, `test_d1`, `test_h8` |
Also: the installer now migrates configs that name the HYDRO BRAIN folder (`test_d2`), and the tree check knows the folder name XELCELL.

## Measured on the final v7 code (`evidence/`)
| Measure | v5 | v7 |
|---|---|---|
| Tests | 111 pass | 167 pass: 111 old (none edited), 40 from v6, 16 new (`evidence/tests.txt`) |
| The owner's 63 real requests, each routed with its session's scope: offered skills | — | identical to v5 for 63 of 63 |
| The owner's 21 real short messages that get a skill list | 8 | 2 |
| Hook text over the 14-message test session | 18,281 chars | 5,662 chars (v6: 5,192; the difference is the new reminders) |
| Readiness card | 3,828 chars | 3,589 chars |
| Reviewer-written holdouts: recall · false alarms | 32/40 · 11/20 and 17/20 · 3/20 | 32/40 · 3/20 and 17/20 · 2/20 |
| Tuned set | 88/88 · 2/30 | 88/88 · 1/30 |

## Still true (not fixed by code)
- Live check on 2026-11-14: the running Claude Code conversation's hooks wrote into the new brain right after the switch, and one real Codex turn ran its SessionStart, UserPromptSubmit and end hooks on v7 (its conversation id is in `state/hook-seen.json` and `state/analysis/2026-11.jsonl`).
- Recall of the router on real task requests needs the owner's ticks (note 7): the sheet is ready at `reports/route-labels.md` (local, git-ignored); after ticking, run `python3 -I tools/route_real.py --labels reports/route-labels.md`. On reviewer-written prompts it is 80–85%, as in v5.
- A real judging CLI opening a sealed image was not exercised.
- "Zero hallucination" is not something code can promise; v7 checks claims against records in three places and now refuses a pass built on unfindable quotes.
- The presentations still describe v5.

Before going live: the seven steps in `HANDOFF.md`.

## Router verdict from the owner's own labels (2026-11-14, interview of 18 real requests + 21 real short messages)
Counts: `evidence/owner-labels-2026-11-14.json` (no message text). The owner answered in six click rounds; requests 10 and 19 of the interview were left unanswered and are not counted. The interview showed four of each request's offered skills; a fifth, unshown one counts as "not right", so precision below is a lower bound.

| Measure on the owner's real words | Result |
|---|---|
| Requests where a right skill was offered | 13 of 18 (72%) |
| ... first offered skill was right / right skill in the top 3 | 9 of 18 / 10 of 18 |
| Offered skills that fit (lower bound) | 26 of 89 (29%) |
| Requests where nothing offered fits | 5 of 18: three brain-maintenance jobs (the library holds no brain-engineering skills; whatever is offered is noise), two three.js bug fixes (card rotation, paper grain + cassette) where the right three.js skill was not offered |
| Short messages that are talk: got a skill list anyway | 1 of 18 ("reply OK" → slack-reply-drafting) |
| Short messages that are tasks: got nothing | 2 of 3 ("update the handoff", "provide a Handoff.md"; the library has no handoff skill) |
| Skill named as missing | SparkJS / a suggestion to move a Blender web game to three.js |

**Verdict: PASS for live use**, strongest on 3D, three.js and brand work. Weak spots: brain-maintenance requests and handoff commands, and roughly two of every three offered lines are noise.
**Fixed from these labels:** the word "tokens" (AI usage in the owner's messages) no longer pulls in design-token skills unless a design word is next to it (`test_d5`). It was noise in 3 of the 18 requests and in a holdout false alarm (holdout 1 false alarms 3 → 2). No other tuning was done on 18 labels; tuning on the same labels would also stop them measuring anything.
**Next, by evidence:** stop offering anything when the best match is weak (the five "nothing fits" cases); a handoff/docs skill route; a SparkJS skill if the owner wants it; more labels over time (`route_real.py --sheet` again in a few weeks).
