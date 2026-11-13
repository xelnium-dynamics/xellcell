---
title: Layer 5 - Readiness and gap
type: system
summary: Six evidence-backed readiness questions with four outcomes, a gap diagnosis table, and a bounded skill hunt (local first, verified existence, quarantine, the owner's OK).
updated: 2026-11-08
---
# Layer 5 — Readiness and gap

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Prove the task can be done and checked | Contract + packet | One of 4 outcomes, with evidence | Director | "Cannot verify" stays visible | Missing-input fixture is caught |

## Six questions, each answered with evidence (a path, a check, a quote), never "I think so"
| Question | Evidence needed |
|---|---|
| Is the outcome clear? | Deliverable + hard requirements in the contract |
| Are the inputs here? | Actual files, measurements, facts, or a written assumption |
| Is there a method that applies? | A card that passed `APPLIES`, with known limits |
| Can the tools run here? | Tool present, version, environment checked |
| Am I allowed? | Permissions and spend rules |
| Can the result be verified? | A Tier-0 check, a reference, or a Tier-2 review route |

## Four outcomes
**Ready** → work · **Prototype first** → test the uncertain part small before committing · **Missing X** → get exactly X · **Cannot verify** → say so, keep it visible, decide with the owner. In the deep lane the readiness report goes to the owner before work starts.

## Diagnose the gap before hunting
| Gap | Response |
|---|---|
| Missing knowledge | Authoritative source, cited with date |
| Possibly outdated fact | Fetch the current source, record the date |
| Missing tool | Look for compatible tools (below) |
| Missing procedure | Find or build one, test it on the failing part |
| Missing personal fact | Authorized `self/` record, or ask the owner |
| Unclear goal | Ask the one consequential question |
| Failed method | Find out why before looking for a replacement |
Example: a CV with unknown employment dates needs **facts**, not another writing skill.

## Bounded skill hunt
1. **Local first:** `~/.claude/skills`, plugins, `~/.codex/skills-library` (including the 69 skills migrated from Hermes, listed in `MIGRATED-2026-11-08.md` there), the brain registry.
2. **Internet, only for tool or procedure gaps:** at most 3 candidates. Each repo or page is **fetched to prove it exists**; license, last update and permissions are read from the page, never from memory.
3. **Quarantine:** run the candidate only on the failing sub-task, in an empty temp folder with no access to the owner's files.
4. **the owner's OK** before any install (hard rule).
5. "Newest" never beats "verified appropriate". After 3 candidates: reduce scope with the owner, or build a small procedure from tools already present.
