---
title: Layer 7 - Execution
type: system
summary: Work in milestones, save a checkpoint after each, capture commands and results automatically, gate actions with real-world side effects, and cite fetched docs for version-sensitive facts.
updated: 2026-11-08
---
# Layer 7 — Execution

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Do the work with recoverable state | Ready plan | Artifacts + checkpoints + evidence log | Director + workers | Restore last verified checkpoint | Kill a session mid-task; another agent resumes |

## Mechanisms
1. **Milestones** come from the contract's hard requirements, foundations first: for a CV, facts before layout; for a website, critical interactions before polish; for engineering, assumptions and validation method before the visual.
2. **Checkpoint after each milestone** (`sessions/<id>/checkpoints/NN.md`, atomic write): decisions, files changed with hashes, evidence pointers, open questions. A crash loses at most one milestone.
3. **Evidence is captured by the harness, not reported by the agent.** A Claude PostToolUse hook appends each shell command, exit code and output hash to `sessions/<id>/evidence.jsonl`. A claim like "tests pass" is valid only if the log shows it.
4. **Actions with real-world effects** (send, publish, pay, delete, external API) are classified by the typed question `ACTION-RISK` (read-only / reversible / irreversible). Code then decides: allow, ask the owner, or block. Irreversible always asks. These actions are logged and never replayed by the Gym.
5. **Version-sensitive facts** (APIs, prices, flags, laws, deadlines) must cite a fetched source with its date. Memory alone is not a source.
6. **Hard rules apply in every step:** no paid API, no generation unless the owner says "generate", no installs without OK, deliverables to the owner's Desktop folders.
