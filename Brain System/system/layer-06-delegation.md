---
title: Layer 6 - Delegation (father and son)
type: system
summary: The director plans and decides; cheap helpers get a work order with purpose, shelves and budget, return a menu of pointers, and the director reads the chosen original. Adds a contract to the existing roles, not new agents.
updated: 2026-11-08
---
# Layer 6 — Delegation (father and son)

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Save the director's context and tokens | Work order | Menu of 2–3 pointed options | Director + son | Son returns "not found", never a guess | Planted-exception fixture survives the menu |

The owner's picture: the father knows the repair; the son fetches the screwdriver and the metal bar. The son must know **what the father is building**, so he brings the right options and lets the father choose.

## Roles (unchanged from v1, now under one contract)
| Role | Claude Code | Codex | Job |
|---|---|---|---|
| Director (father) | Opus 5.5 | GPT-6 Sol (Astra for the hardest) | Plans, decides, reads originals, does hard parts |
| Scout (son) | Haiku 5.5 | GPT-6 Luna | Finds and returns menus |
| Worker | Sonnet 5.5 | GPT-6 Sol | Routine edits |
| Hunter | Sonnet 5.5 | GPT-6 Sol | Skill search ([[layer-05-readiness-gap]]) |
| Scribe | Haiku 5.5 | GPT-6 Luna | Writes records from checkpoints, not memory |
| Judge | the other vendor | the other vendor | [[layer-08-jev-judgment]] |

## Work order (father → son) — template: [[tpl-delegation-records]]
What I am building and why (the parent step) · what to bring · which shelves are allowed (collections, paths) · what to skip · budget (tokens, time) · return format.

## Menu (son → father)
2–3 options. Each: title · **pointer** (file + line range, or card id) · why it fits *this* parent step · risk or mismatch · size (lines) · "not found" allowed. **No paraphrase of instructions or numbers**: the father reads the pointed original himself, so a cheap summary can never drop the one exception that matters.

## When to hire, when to wait
1. Hire a son when the search spans many files or shelves. One known file: read it directly. A deterministic lookup: run the script.
2. If the next step depends on the son, wait for his result. No repeated status checks, no duplicate search.
3. If independent useful work exists, the director may continue it; the dependency decides whether he pauses.

## Mechanism facts (so expectations are right)
- **Waiting costs no tokens either way.** The saving is that the son's reading never enters the father's context.
- A Claude Code subagent cannot stop mid-task to ask its parent; it reports once. "Ask the father" therefore means: menu → father picks → father reads, or sends the same son back (subagents can be continued).
- Each son has a fixed start-up cost. `token_meter.py` measures it, and the Gym removes any delegation that does not pay ([[layer-13-accounting]]).
- Every pick, rejection (with reason) and "not found" goes into the retrieval log ([[layer-04-retrieval-toc]]).

## Build notes
Claude: `.claude/agents/scout.md` (model haiku; tools Read, Grep, Glob only) and `scribe.md` (Write limited to `sessions/<id>/` by a PreToolUse hook, because tool permissions are not path-scoped per subagent). Codex: `.codex/agents/scout.toml` (model luna, read-only sandbox).
