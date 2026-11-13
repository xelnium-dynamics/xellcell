---
title: Session record templates
type: template
summary: Templates for the task contract, a milestone checkpoint, the Task Summary, the Brain Summary and the episode.
updated: 2026-11-08
---
# Session record templates

## Task contract — `sessions/<id>/contract.md`
```yaml
---
session: 20261108-213000-claude-k3f9
contract_version: 1
lane: standard            # fast | standard | deep
scope_class: website      # cv_official | engineering | website | personal | research | system
novelty: reuse            # reuse | explore
---
```
- **Request (verbatim):** …
- **Deliverables:** …
- **Hard requirements** (each with its check): `R1` … — check: …
- **Preferences:** …
- **Constraints (quoted):** "…"
- **Assumptions:** A1 … — confirmed | assumed | unknown
- **Permissions and spend:** no paid API · no generation unless "generate" · no installs
- **Out of scope:** …
- **Changes:** v2 — what, why, asked by whom

## Checkpoint — `sessions/<id>/checkpoints/NN.md`
Milestone · decisions taken · files changed (path + sha256) · evidence pointers (lines in `evidence.jsonl`) · open questions · next step.

## Task Summary
| Field | Content |
|---|---|
| Delivered | files with paths |
| Verified | requirement → tier → evidence pointer |
| Not verified | requirement → why |
| Limits | … |
| Next step / handoff | … |
| Approval | pending · approved · rejected · approved with signed exception |

## Brain Summary
| Field | Content |
|---|---|
| Reused | card ids, lessons |
| Observed | new facts, failures (with conditions) |
| Proposed | candidate lessons → queue ids, or "none" |
| Tested / adopted / rejected | … |
| Retrieval log | useful · rejected (reason) · missing |
| Brain release | rel-… |

## Episode — `Brain System/projects/<p>/episodes/<date>-<short-title>.md`
```yaml
---
id: ep-20261108-claude-k3f9
title: "Landing page for client X: hero, nav, mobile checks"
project: client-x
agent: claude
lane: standard
approval: approved
brain_release: rel-20261108-1
cost: {context_in: 0, output: 0}   # filled by token_meter.py, never estimated
inputs: [{path: …, sha256: …}]
---
```
Sections: Task (verbatim) · What was done · Verdicts · Specific to this task · May transfer · Problems raised · Next step.
