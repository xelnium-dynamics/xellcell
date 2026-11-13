---
title: Layer 12 - Improve
type: system
summary: Harness² propose-probe-compose inside hard tasks (bounded) and in a night shift, with the final composed run, a Gym that includes failures and an unseen holdout, a protected evaluation, sample-size rules, versioned release and auto-revert.
updated: 2026-11-08
---
# Layer 12 — Improve

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Make the harness better, provably | Failures, retrieval logs, candidate lessons | Released improvements or rejections, one results line each | Director (in task) / night-shift job | Keep the current harness | Composed change beats baseline on holdout without regressions |

## A. Inside a hard task (restores Harness²'s core)
**Trigger:** the fix loop ran 2 rounds without success, the same failure repeats, or the method is in doubt, in the standard or deep lane only. **Budget:** at most 3 extra runs of the failing sub-task and a token cap set in the contract.
1. Freeze the current method and its result as the reference.
2. Propose two changes: one **general** (planning, tools, context, delegation) and one **domain** change.
3. Probe both on the same failing sub-task, isolated, with no real-world side effects.
4. Compare: Tier 0 checks, then `PAIR-BETTER` in both orders ([[layer-08-jev-judgment]]).
5. Compose only the changes an observation supports.
6. **Run and check the composed result once more** (Harness²'s ledger counts base + 2 candidates + final; v1 forgot the final run).
7. Keep it for this task; send a transferable lesson to the queue as a *candidate*. Shared procedures are never rewritten mid-session.

## B. Night shift (only when it pays)
Runs when a card failed twice, its score dropped, a new skill arrived, or enough candidates are queued.
- **Gym:** replay tasks from approved, rejected, failed and interrupted episodes, with **immutable input snapshots** and tool/model/brain versions recorded. Side effects are mocked.
- **Holdout:** at least 20% of Gym tasks are hidden from the improver.
- **Protected surface:** the improver cannot edit Gym tasks, holdout, judge questions, thresholds, gold sets, permissions or contract rules. Their hashes are checked before and after (Karpathy's fixed evaluation).
- Steps: baseline → propose (general + domain) → probe → blind judge → compose → **final composed run** → small cross-domain regression set.
- **Ratchet by sample size:** fewer than 3 tasks → candidate only, no promotion · 3–4 tasks → must win all, lose none · 5 or more → win at least 60%, lose none · equal quality and simpler → keep the simpler. Quality first, tokens second.
- Release as a git tag, monitor later tasks, auto-revert on a score drop. One line per experiment in `gym/results.tsv`.

## C. The brain inspects itself
| Observed | Proposal |
|---|---|
| Right source found only after several searches | add a tested search term, re-rank |
| Card retrieved but rejected | sharpen its do-not-use-when |
| Same raw document summarized repeatedly | write a maintained, source-linked page |
| Scout keeps missing details | change its work order or stop delegating that job |
| Judge catches the same defect repeatedly | move the check earlier |
| Same manual correction by the owner | test folding it into the procedure |
| Memory grows without helping retrieval | merge, retire |
| New CLI version breaks a procedure | invalidate, retest |
Format: observed problem → suspected cause → proposed change → comparison test → adopt or reject. The improver may never make itself "better" by weakening tests or widening its own permissions.
