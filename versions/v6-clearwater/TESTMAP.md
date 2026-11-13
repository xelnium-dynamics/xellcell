# Behaviour → regression test (v6 "Clearwater")

Every behaviour v6 adds or changes, and the test in `tools/tests/test_v6_clearwater.py` that fails without it. Old behaviour is covered by the 111 tests of v2–v5, none of which was edited.

| # | Behaviour | Test |
|---|---|---|
| 1 | Judge brief has sections 0 manifest, 1 goal + ledger, 2 errors, 3 changes, 4 lenses, 5 artifacts | `test_j1` |
| 2 | Manifest names every input: full, excerpt with the cut characters, binary/image with its sealed path, missing; a duplicate counts once | `test_j1` |
| 3 | A cut file shows head and tail; the packet stays inside its cap | `test_j1`, `test_j6` |
| 4 | Requirement ledger: id, text, check, Tier-0 state | `test_j1` |
| 5 | Error list from the evidence log; a clean rerun only counts; the brain's own commands (maker's notes) never appear | `test_j1`, `test_c2` |
| 6 | Edited-but-not-submitted files are named | `test_j1` |
| 7 | Sealed copies exist in the judge's folder; `SEALED.txt` lists them | `test_j2` |
| 8 | Result carries fix list, inputs_missing, unsupported_claims; the brief is saved as `judge-brief-NN.md`; the verdict records how each input was shown | `test_j2` |
| 9 | Round 2 is told what round 1 found (verdicts, asked fixes, flaws, unsupported claims) | `test_j2` |
| 10 | A requirement without a verdict → not_checked, pass → inconclusive | `test_j3` |
| 11 | Pass above a failed blocker/major → fail | `test_j3` |
| 12 | Pass next to any open row (inconclusive, not_checked, minor fail) → inconclusive | `test_j3` |
| 13 | A quote found neither in the packet nor in the artifacts is flagged; a quote from a sealed copy is accepted | `test_j3` |
| 14 | `--preflight`: no model call, no verdict file, failed checks and unchecked requirements listed | `test_j4` |
| 15 | Lenses exist for every scope class; the instruction forbids failing on a lens | `test_j5` |
| 16 | Many files with long paths: small ones whole, big ones cut, the end of the packet intact | `test_j6` |
| 17 | A file too large to seal is marked NOT SEALED; no sealed path is advertised for it | `test_j7` |
| 18 | A `cmd` check that exits 0 while printing an error is marked `PASS?` | `test_j8` |
| 19 | Typed status: uncalibrated escalation → `calibrate_threshold`; real disagreement → rewrite alert | `test_t1` (and v5's status test, unedited) |
| 20 | Map: query finds a symbol with its line range; `node_modules` skipped | `test_m1` |
| 21 | Map: slice prints only the symbol | `test_m1` |
| 22 | Map: HTML outline with inline script/style and real file line numbers; Python outline | `test_m1` |
| 23 | Map: who (definition + uses); methods carry their class | `test_m1` |
| 24 | Map: incremental rebuild; `self/` never outlined or walked; stats | `test_m2` |
| 25 | `brain_fetch.py --outline` / `--section` (and exit 4 for an unknown heading) | `test_m3` |
| 26 | Hook: flow line, skill and note said once per conversation; another conversation is told; `BRAIN_HOOK_VERBOSE=1` repeats | `test_h1` |
| 27 | Hook: machine messages and small talk get nothing | `test_h2` |
| 28 | Hook: the flow line returns when the state changes (session opened) and `brain.py new` links | `test_h3` |
| 29 | Linker: a script that only contains the words, or a real `new` showing an old id, does not re-link | `test_h4` |
| 30 | Router: one or two content words do not call a skill without evidence | `test_r1` |
| 31 | Router: short real tasks still find their skill | `test_r2` |
| 32 | Router: matching is by whole words (plurals yes; no `close`→`closed`, no `str`→`string`, no `rig`→`rigging`: the -ing rule is withdrawn) | `test_r3` |
| 33 | Holdout sets exist; no holdout prompt (either set, positives and negatives) appears in the router or hook code | `test_r4` |
| 34 | `route_eval.py --holdout` reports both sets and never gates | `test_r5` |
| 35 | Checkpoint rewrites the capsule (goal, requirements, done, files, open error) | `test_c1` |
| 36 | Start hook after a compaction prints the capsule, not the card; an ordinary start prints the card inside its cap, with `BRAIN`, map and preflight, for Codex too | `test_c1` |
| 37 | The judge never sees checkpoint text | `test_c2` |
| 38 | Learn: at most three queued lessons, proposed first; no gap-as-lesson; gotchas go to the ledger | `test_l1` |
| 39 | Dream: reflections are whole sentences; no clean sentence → nothing | `test_l2`, `test_l6` |
| 40 | Dream: a bridge needs a shared title/tag word; the map is `type: log` | `test_l3` |
| 41 | Dream: the idle agent's arguments hold no `--apply-links`; `type: log` notes are not retrieval answers | `test_l4` |
| 42 | Sleep: eight lesson boxes, structured first, the rest counted; cost line present | `test_l5` |
| 43 | Dream: a single failed command is not recorded, a repeated signature is, with its count; hook errors are one line per distinct error | `test_l6` |
| 44 | Sleep: the cost line reads session analyses and the map log | `test_l7` |
| 45 | `brain.py` forwards arguments and exit codes; unknown command → 2 | `test_e1` |
| 46 | Map: GLSL (uniforms, functions), CSS-only (rules, at-rules, nested rule not top-level), JSON (top-level keys); slice of a one-line definition shows its body | `test_m4` |
| 47 | Hook: skill paths under the brain are shortened to `$BRAIN/…` and the root is named once | `test_h5` |
| 48 | Hook: after the first line, silence, except a ten-word nudge on every fifteenth message | `test_h6` |
| 49 | Judge: quotes are paired in order (prose between two quotes is not a quote); each quote checked on its own | `test_j3` |
| 50 | Judge: a copy that fails is taken out of the packet and the manifest | `test_j9` |
| 51 | Judge: `--export` writes packet, schema and sealed copies; records no round; never overwrites | `test_j9` |
| 52 | Learn: a one-word skill name in ordinary prose is not a "used" skill; a multi-word name or a backticked one is | `test_l8` |
| 53 | `route_real.py`: skips private and open sessions, counts real skill reads, deduplicates short messages, leaves out machine/slash/meta/harness messages, stores no message text | `test_r6` |
| 54 | Judge: `--record FILE --judge-name NAME` records the answer of a judge run by hand, checks it like any other, and marks a same-vendor judge | `test_j10` |
| 55 | Judge: `--sealed-only` files are listed and sealed but not inlined, so the documents stay whole | `test_j11` |
| 56 | Tier 0: a `cmd` check that runs past its time limit fails; `BRAIN_TIER0_TIMEOUT` raises the limit | `test_j12` |

Not covered by a test (stated, not hidden): one thing — a real judging CLI opening a sealed image. The tests prove the image is in the judge's folder with the right name (`test_j2`) and that the packet points at it (`test_j1`); whether a given model CLI then looks at it cannot be tested without calling that model.
