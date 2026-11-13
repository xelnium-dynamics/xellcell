---
title: Layer 9 - Recovery and stepping back
type: system
summary: Diagnose why a check failed before fixing, map each cause to its response, cap the fix loop at two rounds, then step back (in-task Harness² or the owner) and restore the last verified checkpoint on regression.
updated: 2026-11-08
---
# Layer 9 — Recovery and stepping back

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Fix the cause, not the symptom | Failed or inconclusive verdict | Diagnosis + chosen response | Director | Ask the owner with a concrete recovery path | Weakened test is flagged |

## Cause → response
| Finding | Response |
|---|---|
| Local execution error | Correct it, rerun the affected checks |
| Wrong or thin context | Retrieve more evidence ([[layer-04-retrieval-toc]]) |
| Wrong method | Compare one alternative method on the failing part |
| Invalid assumption | Revise the plan and everything built on it |
| A change caused a regression | Restore the last verified checkpoint |
| Verification too weak | Strengthen the check (Tier 0 if possible) |
| Goal changed | New contract version, reroute ([[layer-02-task-contract]]) |

## Rules
1. **Fix loop: at most 2 rounds**, each fixing only the listed flaws.
2. After 2 rounds: if the method is the problem and the lane is standard or deep, run one bounded in-task Harness² cycle ([[layer-12-improve]]); otherwise ask the owner with the diagnosis and a concrete next step.
3. **Changing tests or criteria is not a fix.** Any edit to tests, acceptance criteria or judge questions during a fix creates a visible contract version and is flagged to the judge and the owner.
4. Every failure, correction and restore is written to the checkpoint and later to the episode ([[layer-10-closeout]]).
