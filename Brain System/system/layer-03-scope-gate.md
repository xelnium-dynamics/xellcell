---
title: Layer 3 - Scope gate
type: system
summary: Memory is split by purpose (self, projects, domains, capabilities) and by authority; each task class may read only its permitted collections, with two enforcement levels.
updated: 2026-11-08
---
# Layer 3 — Scope gate

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Only permitted memory reaches the task | Contract scope class | Allowed collections for retrieval | Router script | Return nothing, ask | Engineering task returns 0 `self/` items |

## Collections (folders in `Brain System/`, see [[file-layout-v2]])
`self/` (identity, career facts, life, preferences) · `projects/<name>/` · `domains/<subject>/` · `capabilities/` (reusable methods and tools) · `problems/` · `lessons/`

## Every record carries three labels
| Label | Values |
|---|---|
| What it is | fact · decision · procedure · event · preference · reference |
| Where it applies | this task · project · domain · general |
| Who said it (authority) | The owner's decision · sourced fact · agent observation · agent proposal |

"the owner asked for this in project A" must never turn into "the agent recommends this everywhere". Widening a record's scope needs evidence ([[layer-11-memory]]).

## Identity
`self/identity.md` holds one person with aliases: **Alex = Al = Lex** (D-016). Agents treat them as one person.

## What each task class may read
| Task class | Allowed | Never, unless the owner adds it |
|---|---|---|
| CV / official document | `self/identity`, `self/career` (only the fields needed), document domain, capabilities | journals, other clients, engineering |
| Engineering / 3D / physics | `projects/<p>`, `domains/engineering`, capabilities | all of `self/` |
| Website / brand | `projects/<client>`, brand decisions of that client, `domains/web`, capabilities | `self/`, other clients |
| Personal decision | the relevant `self/` subset | other clients' work |

## Enforcement (honest levels)
- **Level 1 (default).** Knowledge reaches a session only through the router and `brain_fetch`, which filter by the contract's scope class. `self/` lives in a separate index table that non-personal searches cannot query. The boot card never contains personal data. This removes accidental reading, the normal case.
- **Level 2 (sensitive: passport and ID numbers, finances, health).** Stored outside the brain root, in a folder denied by Claude settings in every project except a dedicated personal workspace. Codex cannot block reads by path, so Level-2 data stays out of Codex sessions.
- Text already injected by the host app (global files, earlier chat) cannot be unread. That is why the boot diet in [[layer-01-entry]] matters.

## Rules
- Minimum necessary: even a personal task loads only the fields it needs.
- **No inferred personality.** A claim about the owner's character or taste is stored only from the owner's own words (authority = the owner's decision).
- Outgoing research queries pass the typed check `PRIVACY-LEAK` before leaving the machine; names, IDs and client details are removed.
