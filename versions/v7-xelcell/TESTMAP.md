# Behaviour → regression test (v7 "Xelcell")

v6's 56 behaviours and their tests: `versions/v6-clearwater/TESTMAP.md` (still valid; `test_j3` now expects the stricter quote rule). v7 adds, all in `tools/tests/test_v7_xelcell.py`:

| # | Behaviour | Test |
|---|---|---|
| 57 | Judge: backticked spans and escaped quotes are paired correctly | `test_q1` |
| 58 | Judge: a pass resting only on unfindable quotes becomes inconclusive; one found quote keeps the row | `test_q2` |
| 59 | Judge: an unreadable artifact is marked UNREADABLE, never advertised as sealed, never crashes dry-run or preflight | `test_q3` |
| 60 | Judge: the CLI timing out or not starting is an inconclusive round with the reason recorded | `test_q4` |
| 61 | `brain.py` puts the forwarded flag first | `test_q5` |
| 62 | Hook: a skill that fits again is named again with its path after 8 messages, in one line, then silence | `test_h7` |
| 63 | Hook: after a compaction the skill is offered in full again | `test_h8` |
| 64 | Close: one place queues lessons, one naming scheme, at most three | `test_c3` |
| 65 | Close: the old queue code runs only when `brain_learn.py` fails | `test_c4` |
| 66 | Map: braces inside a multi-line template literal are not code | `test_m5` |
| 67 | Map: memo / forwardRef / styled components; GLSL precision qualifiers | `test_m6` |
| 68 | `route_real.py` routes each request with its session's scope; the result holds no words | `test_r7` |
| 69 | `route_real.py --sheet` / `--labels`: the tick sheet and its scoring; the sheet is git-ignored | `test_r8` |
| 70 | Dream prints the calibrate alert | `test_d1` |
| 71 | Installer migrates the HYDRO BRAIN folder name, never its own root | `test_d2` |
| 72 | `brain_learn.py --rebuild-telemetry` recounts from records with the current rule and keeps the old file | `test_d3` |

Not covered by a test: a real judging CLI opening a sealed image (needs a live model call).
