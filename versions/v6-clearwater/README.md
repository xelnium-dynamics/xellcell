# v6 "Clearwater" — the review of Hydro Brain v4/v5, and the surgery that followed

> **Public release note.** This is the build record as written during development. Paths and names were made generic for publication; the holdout prompt sets now sit in `versions/v6-clearwater/evidence/holdouts/`; the maintainers' own skill library, prompt set, sessions and private notes are not part of the public repository.


Date `2026-11-13` · reviewer and builder: Claude (Fable 5.2), session `20261113-174230-claude-2f97` (recorded in the live brain) · base: git `37b465c` (tag `v5-hydro-brain-2`) · **not live, not committed**: every change is in the working tree of `~/Desktop/HYDRO BRAIN`; nothing outside this folder was switched, installed or deleted.

## The verdict on Gemini's v4/v5, in one screen
Checked by running it, not by reading its handoff. Numbers are in `evidence/`.

| Claim in the v5 handoff | What the check showed | Verdict |
|---|---|---|
| 111/111 tests pass | 111/111 pass (68 s here) | **holds** |
| Skill routing: 88/88 recall, 2/30 false alarms | True on its own set. But 10 of the 30 "negative" test prompts are written word for word into the router's regex (`CONVERSATIONAL_NOISE_RX`). On 40 + 20 prompts it never saw: recall 32/40, **false alarms 11/20** | **inflated** — the set was taught, not learned |
| Unified scoring cures the skill-calling failures | The seven causes are really fixed (full-request tokens, families, re-route on contract change). Two hand-written special cases remain in the scorer (brand bonus, imagegen penalty) | **mostly holds** |
| Judge monitor found a `REQ-MET` rewrite alert (escalation 1.0) | The four calls escalated because nobody ran the calibration (39 gold labels wait). Tier 1 never disagreed with itself. The right action is "calibrate", not "rewrite the question" | **misdiagnosed** |
| Dreaming mines thinking into reflections | Output was 220-character cuts through the middle of sentences, single failed commands filed as insights, 100 raw hook-log lines; all of it indexed as retrievable knowledge | **noise in the memory** |
| Dreaming connects missing graph nodes | 79 "bridges", joined by shared words such as `entirely, whisky, wanna` and `live-dirty, low, adopted, high`; the idle LaunchAgent was set to write them into notes by itself (`--apply-links`) | **unsafe default** |
| Synonym autoresearch "ratchet" | The stage logs a baseline and always records `kept: false`. It proposes nothing | **a label, not a feature** |
| Instant learning after close | Works; but every bullet under Lessons/Gotchas/Fixes became its own queued lesson (8 files from one session), and the owner decides each by hand (19 decisions were waiting) | **floods the reviewer** |
| Judge: blind, cross-vendor, Tier 0 first | Sound design (v3). But the packet was cut at 120,000 characters with no word to the judge, a binary or image was "not shown" with no way to open it, round 2 never learned what round 1 found, and nothing checked the judge's own answer | **the judge did not know what it had** |
| Protocol says "live since 2026-11-13" | It is not live; the installer was never applied | **wrong** |
| Skill telemetry feeds the router | A shown skill counted as "used" when its name appeared anywhere in a summary; one-word skills (`ship`, `start`, `fix`, `commit`, `figma`) are ordinary words, so in the live sessions 11 of the 16 "used" labels rest on a one-word name (`ship` five times), while only two sessions hold a real read of a skill; those counts boost the skills in the router (`evidence/telemetry-used-labels.json`) | **polluted signal** |
| Token cost | The per-message hook re-sent the same reminder, skills and notes on every message, including machine notifications | **the largest avoidable cost** |

What Gemini built well and v6 keeps: the single scoring module, the contract-change re-route, the per-project learnings ledger with instant index upsert, idle/load/lock guards and incremental cursors in the dream job, the installer with backup and restore, the release records.

## What v6 changes (details: `DESIGN.md`, list: `CHANGELOG.md`, undo: `UNDO.md`)
1. **Judge brief** — the judge is told what it received (every input: full, cut where, binary → sealed copy), the goal (requirement ledger with Tier-0 state), the errors (failed checks, error results from the evidence log, the previous round's findings), what changed and what was not submitted, and scope lenses. Its answer is checked by code and returns as a fix list. `preflight` does the free part first.
2. **Token layer** — `brain_map.py` (read the symbol, not the file), hooks that say a thing once, a compaction capsule instead of the whole card, section reads for notes, one entry point `brain.py`.
3. **Memory quality** — at most three queued lessons per session, whole-sentence reflections, recurring errors only, bridges need a shared title/tag word, dream output is a log and never a retrieval answer, the idle agent never edits notes, the digest shows the eight strongest lessons and the week's token cost.
4. **Routing honesty** — one router change only: a thin-prompt evidence gate. `route_real.py` measures the router on the owner's own requests and short messages; two reviewer-written holdout sets are reported and never gate. (A verb/-ing matching rule was built and withdrawn the same day: it changed the offer on 32 of 63 real requests and nobody could say for better or worse.)
5. **Subagents** — `brain-verifier` (claims against records before the judge); scout, worker and scribe use the map and the capsule; Codex gets the same abilities through the tools.
6. **A hook bug that locks sessions** — the session linker re-linked a conversation to a closed session when a command merely printed a past session id. It happened to this session on the live brain; fixed here.

## Measured (before = v5 at `37b465c`, after = this tree)
| Measure | v5 | v6 |
|---|---|---|
| Tests | 111 pass | 151 pass (111 old, none edited, + 40 new; map in `TESTMAP.md`) |
| Hook text over a 14-message session (tasks, follow-ups, small talk, 2 machine events) | 18,281 chars | 5,192 chars (−72%) |
| Readiness card | 3,828 chars | 3,608 chars, now also carrying map, preflight, capsule, section reads |
| After a compaction | the whole card again | the capsule (≤ 2,400 chars) + 2 lines |
| **the owner's 63 real requests** (closed non-private sessions): offered skill list | — | identical to v5 for 63 of 63 |
| **the owner's 21 real short messages** (≤ 4 words, from transcripts) that get a skill list | 8 | 2 |
| Sessions with a real SKILL.md read: that skill offered | 2 of 2 | 2 of 2 |
| Holdout 1 (reviewer-written; seen while shaping the gate): recall · false alarms | 32/40 · 11/20 | 32/40 · 3/20 |
| Holdout 2 (reviewer-written after the gate): recall · false alarms | 17/20 · 3/20 | 17/20 · 2/20 |
| Tuned set: recall · false alarms | 88/88 · 2/30 | 88/88 · 1/30 |
| Map answer vs opening the matched files | — | 6 calls: 1,353 tokens answered, 218,885 tokens of files not opened (upper bound) |
| Queued lessons from one rich session | up to 8 | at most 3 |

Read the routing rows plainly: v6 did not make the router smarter. For real task requests it offers exactly what v5 offered; on prompts written by the reviewer it finds the right skill about 80–85% of the time, before and after. What changed is that small talk no longer pulls in skill lists, and that the measurement now includes the owner's own words (`evidence/holdout-provenance.md` says what is blind and what is not).

## What v6 does not do
- "Zero hallucination" is not something code can promise. What is built: claims are checked against records (verifier, preflight, close-time claim check), the judge must quote and its quotes are checked against the packet, a requirement without a verdict cannot pass, pointers replace summaries. That lowers the rate; it does not make it zero.
- The map follows names, not meaning: no dynamic calls, no semantic grouping. It is cheaper than a model-built graph and cannot invent; it is not as rich.
- The judge brief ran three real cross-vendor rounds on this very session (below). The image path (judge opens `./artifacts/NN-render.png`) depends on the judging CLI's file access and was not exercised with a real image.
- There is no labelled set of task prompts written by someone other than a router author. Recall on real requests is therefore known only for the two sessions that recorded a skill read. The set grows by itself with use (`route_real.py`).
- The presentations (`presentation/*.html`) still describe v5.
- v5's skill telemetry (`state/skill-telemetry.json`) still holds the false "used" counts; v6 stops adding to them but did not rewrite the file (HANDOFF, step 6).
- Not live: `hydro_install.py --apply` is the owner's step. Read "Before going live" in `HANDOFF.md` first.

## The judge rounds on this work (records: session `20261113-174230-claude-2f97`, `verdict-01..03.json`, `judge-brief-01..03.md`)
The v6 judge code judged v6 itself, with Codex as the blind judge. That is also the first real use of the brief.
| Round | Result | What it found | What was done |
|---|---|---|---|
| 1 | fail at Tier 0, no model call | One old test failed because the maker's `BRAIN_ROOT` override leaked into the test command. And every input was flagged "not shown in full": the new size budget under-counted its own headings on an 18-file packet | Check command unsets the variable (contract v3). Budget now renders, measures and tightens (`test_j6`) |
| 2 | inconclusive: R1, R3, R4, R5, R6 pass; R2, R7 inconclusive | Seven flaws in the new code: "pass" could stand next to an unchecked row; quotes were checked only against the excerpt; the manifest advertised sealed copies that size limits would skip; only one holdout was guarded; one assertion could never fail; a check that exits 0 on an error looked like proof; no test for the recurring-error rule | All fixed with tests (`test_j3`, `j7`, `j8`, `r3`, `r4`, `r5`, `l6`, `l7`) |
| 3 | fail: R2 fail, R7 inconclusive, five pass | R2: the test map itself listed three untested behaviours. R7: the same agent wrote the gate and both holdouts, so blindness was not established. Also: a failed copy was still swallowed; one real quote hid an invented one; five claims in the maker's summary had no record (one was wrong: a relevant skill had been offered and not opened) | Tests for all three (`test_m4`, `h5`, `h6`) and for the copy failure and quote pairing (`test_j9`, `j3`); `route_real.py` measures on the owner's own words (`test_r6`), which led to withdrawing the -ing rule; records added for the linker incident (`evidence/linker-repro.txt`), the first test run (`evidence/first-test-run-fixes-patch3.py`), the 12 sessions (`evidence/live-gap.txt`); the summary corrected |
A fourth round has not been run by the maker: The owner hands the package (`brain_judge.py --export`) to Argon.
