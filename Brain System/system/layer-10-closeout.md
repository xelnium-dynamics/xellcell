---
title: Layer 10 - Closeout
type: system
summary: Every delivery or interruption ends with a Task Summary and a Brain Summary built from checkpoints and evidence, an episode with an honest approval state, a retrieval log, problems with structural guards, and candidate lessons only when one exists.
updated: 2026-11-08
---
# Layer 10 — Closeout

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Leave evidence the next session can use | Checkpoints, evidence log, verdicts, the owner's decision | Task Summary, Brain Summary, episode, retrieval log, problems, queue items | Scribe (from records) + director | Session marked "unclosed"; next start surfaces it | A fresh session continues without asking the owner |

## Triggers
Delivery · interruption · session end. In Claude a Stop/SessionEnd hook runs the closeout or marks the session *unclosed*; the next readiness card shows unclosed sessions ([[layer-01-entry]]).

## Two summaries (templates: [[tpl-session-records]])
| Task Summary | Brain Summary |
|---|---|
| What was delivered (files) | Knowledge and cards reused |
| What was actually verified, by which tier | New observations captured |
| What was NOT verified | Candidate improvements proposed |
| Remaining limits and next step | Changes tested and adopted, or rejected |
| Approval state | Active brain release id |
"No reusable improvement; existing procedures worked" is a valid Brain Summary. Lessons are never invented to satisfy a ritual.

## Rules
1. **Built from records, not recollection.** The scribe writes from checkpoints and the evidence log. Each sentence of the Task Summary passes `CLAIM-SUPPORT`; unsupported sentences are removed or marked unverified.
2. **Approval states:** pending · approved · rejected · approved with a signed exception. Pending is a visible state, not a missing record.
3. **Episodes can be reopened** when a problem shows up later; every lesson that used the episode as evidence is flagged for review.
4. **Titles describe content:** "Six-storey building model: geometry, analysis setup, export, verification", not "Task done". Each episode separates *specific to this task* from *may transfer*.
5. **Problems need a structural guard** (a check, a card step, a rule); "be careful" is not a guard. Template: [[tpl-knowledge-records]].
6. Retrieval log and candidate lessons go to the queue for [[layer-11-memory]].
