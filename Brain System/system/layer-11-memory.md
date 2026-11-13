---
title: Layer 11 - Memory
type: system
summary: Short-term to long-term memory in four states, promotion rules per kind of memory, hybrid consolidation by one writer with releases, provenance that never inflates confidence, dependency-based freshness, and retraction.
updated: 2026-11-08
---
# Layer 11 — Memory (short-term → long-term)

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Keep what helps, earn every generalization | Queue items from closeouts | Released records + a release id | Sleep job (one writer) | Release not published; queue kept | A lesson from session A is used correctly in session B |

## Four states
| State | Contents | Lives in | Who reads it |
|---|---|---|---|
| Working | plan, decisions, attempts, checkpoints | `sessions/<id>/` | this session, an authorized handoff |
| Episode | what really happened, incl. failures and corrections | `Brain System/projects/<p>/episodes/` | future retrieval, clearly labeled |
| Candidate | proposed fact, procedure or brain change + evidence | `queue/` then `Brain System/lessons/` (status candidate) | experimental use only |
| Released | tested, scoped, versioned | cards, pages, lessons (status released) | normal routing |

## Promotion rules (not one rule for everything)
| Kind | Rule |
|---|---|
| The owner's explicit project decision | project memory at once (authority = the owner) |
| Sourced fact | needs source + date + freshness policy |
| Failed attempt | recorded at once as an observation ("failed under these conditions", never "never use X") |
| Procedure / workflow change | needs a comparison ([[layer-12-improve]]): 2 approved runs only make a *candidate*; *released* needs varied tasks, no rescue by the owner, and stated limits |
| Claim about the owner's personality or taste | only from the owner's own words; never inferred |
Widening scope (project → domain → general) needs evidence from more than one project: typed check `SCOPE-COVER`. Creative choices stay project-scoped; verification methods may widen.

## Consolidation (hybrid timing)
| Trigger | Work |
|---|---|
| Each milestone | checkpoint (in-session) |
| Delivery or interruption | finalize episode, queue lessons |
| Queue has enough related items | consolidate those records |
| Daily, if the queue is not empty | dedupe, rebuild links and TOC views, verify `raw/` hashes |
| Weekly, when justified | review patterns, retire weak rules, run [[layer-12-improve]] |
One writer per run, holding a lock with expiry; work is staged, checked, then published as one release ([[layer-00-integrity]]). Consolidation never delays a handoff or the saving of an important fact.

## What needs the owner (so he is not the brain's administrator)
| No approval needed (standing permission) | The owner approves |
|---|---|
| Dedupe, link and TOC rebuilds, hash checks, retiring records that never helped | Releasing a procedure or workflow change |
| Recording episodes, failures, observations | Anything written to `self/` |
| Candidate lessons (experimental use) | New shelf-code words, scope widening to "general" |
The owner sees one weekly digest of what changed and an exception queue, not every housekeeping event.

## Provenance and freshness
- Every claim cites `raw/` or an episode (path + lines). Synthesis is labeled as synthesis.
- **Summaries never raise confidence.** A script rejects a claim whose only support is another synthesis page (no self-citation loops).
- Each card lists `depends_on` (sources, tools, versions). When one changes, the card is flagged *needs revalidation* and its route-cache entries are dropped.

## Forgetting correctly
Retract (wrong) · supersede (replaced) · retire (no longer useful). Retrieval stops using them; history stays. Hard removal of personal data, even from `raw/`, is an action only the owner can authorize; it is recorded as an exception to never-delete. Low-value derived records that never help retrieval are merged or retired.
