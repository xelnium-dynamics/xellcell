---
title: Layer 2 - Task contract
type: system
summary: The frozen record of what the owner asked - verbatim request, testable hard requirements, quoted constraints, explicit assumptions, permissions, scope class and lane.
updated: 2026-11-08
---
# Layer 2 — Task contract

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Freeze what was asked | The owner's request | `sessions/<id>/contract.md` (checkpoint 0) | Director | Ask one question | Judge sees original + current + diff |

## Fields (template: [[tpl-session-records]])
- **Request, verbatim.** Never paraphrased.
- **Deliverables** and **done-when**, split into *hard requirements* (each with its check method, e.g. "renders at 375 px without horizontal scroll: browser check") and *preferences* (scored, never allowed to hide a failed hard requirement).
- **Constraints, quoted** from the request (exact wording, sizes, languages). A constraint without a quote is an assumption.
- **Assumptions**, each marked confirmed / assumed / unknown. "Unknown" is a valid value; guessing is not.
- **Permissions and spend** from the hard rules (no paid API, no generation unless "generate", no installs).
- **Scope class** for [[layer-03-scope-gate]] and **lane** (fast / standard / deep, see [[brain-v2-map]]).
- **Novelty:** `reuse` (default) or `explore`. In `explore` mode retrieval keeps verification and technical cards but excludes earlier *creative-direction* cards, and the last approved directions for this client are listed as "do not repeat". This keeps the brain from making the owner's work more uniform.
- **Out of scope**, and the **contract version**.

## Rules
1. **One question at most**, and only when the answer changes the deliverable or the risk. Otherwise proceed and write the assumption down.
2. **Frozen.** A change creates version 2 with the reason and who asked. The judge always receives the original, the current version and the difference, so criteria cannot be quietly weakened.
3. **Reroute trigger.** If the goal, output, tools, constraints or scope change mid-session, retrieval runs again and the old route stays in the record.
4. **Lane can go up, never silently down.** Downgrading needs the owner.

## Typed checks on the contract ([[layer-08-jev-judgment]])
`REQ-TESTABLE` (is each hard requirement checkable? yes/no) · `CONSTRAINT-QUOTED` (does each constraint quote the request? supported/unsupported). A failed check sends the contract back before any work starts.
