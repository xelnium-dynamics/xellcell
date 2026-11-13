---
title: Layer 8 - JEV judgment
type: system
summary: A JEV-style judgment layer - hard checks first, then fast typed micro-judgments with calibrated thresholds, escalation to an independent cross-vendor reasoning judge only when unsure, and the owner only for taste and exceptions.
updated: 2026-11-08
---
# Layer 8 — JEV judgment

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Decide each requirement with evidence, at the lowest cost that keeps accuracy | Frozen contract (original + current + diff), artifact manifest, captured evidence, renders | Per requirement: pass / fail / inconclusive / not checked + confidence + deciding tier + evidence pointer + severity | Scripts + judges | "Inconclusive" is never counted as pass | Planted-defect set per question type |

## What "JEV style" means here
JEV (TypeSafe AI, Sept 2026) is a decision-only model: it answers a **typed question** (yes/no, pick one of a set, or a score) about a given **state**, returns a probability for every label and writes no prose. Its published pattern is a cascade: **accept when confident, escalate when unsure** to a stronger reasoning judge, with thresholds set from about 100 local labels. Sources: the arXiv paper "JEV-as-a-Judge: Accept When Confident, Escalate When Unsure" (2609.26550) and LangChain's LangSmith announcement (21 Sep 2026). Their numbers are reported by the authors and by LangChain, not independently verified, and the paper did not test agentic tasks.
**We adopt the method, not the vendor.** JEV itself is a paid hosted API (about $0.042 per million input tokens, per the paper), so under the NO-COST rule it is an optional plug-in for the Tier-1 slot, used only after the owner releases spend.

## Four tiers
| Tier | Who | Decides | Never decides |
|---|---|---|---|
| 0 Hard checks | Code: tests, schema, link scanner, renders + DOM/pixel checks, units, hashes | Everything a script can check | — (no model overrides a hard check) |
| 1 Fast typed judge | Small model through the CLI with a JSON schema (Haiku / Luna), or JEV if released | Narrow typed questions at volume | Derived verdicts, polished-but-maybe-wrong work, reference-free prose, visual taste |
| 2 Strong reasoning judge | The **other vendor**, blind, read-only, in an empty temp folder; does **not** see Tier 1's answer | Escalations + the kinds Tier 1 is weak at + all hard requirements in the deep lane | Taste and scope |
| 3 the owner | The owner | Taste, brand fit, scope, signed exceptions | Technical pass (a technical failure stays a failure unless the owner signs an exception, which is recorded) |

Routing rule from the JEV paper: fast judges trail on **derived verdicts** (math, code, logic: engineering calculations count), on **style-adversarial** items (a wrong answer written more elaborately), and on **reference-free prose**. Those go straight to Tier 0 or Tier 2.

## Typed question catalog (`judge/questions/`); schemas: `templates/judge-question.schema.json`, `templates/judge-verdict.schema.json`
Each question: id · state fields (exactly what evidence goes in; no grading instructions inside the state) · output type · labels · threshold τ · escalation rule.
Starter set: `REQ-MET` (yes/no) · `CLAIM-SUPPORT` (supported/overstated/unsupported) · `APPLIES` (yes/no/unsure) · `PIPELINE-FIT` (yes/no) · `PRIVACY-LEAK` (yes/no) · `ACTION-RISK` (read_only/reversible/irreversible) · `SCOPE-COVER` (yes/no/insufficient) · `PAIR-BETTER` (A/B/tie, run in both orders) · `DUP-SAME` (same fact? yes/no) · `PLACE` (which collection, one of a set) · `REQ-TESTABLE` · `CONSTRAINT-QUOTED`.

## Confidence and calibration
- Without JEV, a model's self-reported confidence is not trustworthy. **Default confidence = agreement**: the question is asked twice (Claude and Codex small models, or two runs with the order swapped); both must give the same label.
- **Thresholds per question type** from a local gold set: The owner's past approvals and rejections, planted-defect canaries, fixed cases. Rule (from the paper): choose the most permissive threshold whose one-sided 95% lower bound on accuracy loss versus Tier 2 stays within 2 points; if none qualifies, escalate everything.
- **Cold start:** a question type with fewer than 30 labels always escalates. The layer starts expensive and gets cheaper as labels accumulate. That is honest, not a flaw.
- Thresholds live in `judge/thresholds.json`, bound to model + CLI version + date, and expire after 30 days or on any version change.
- **Judge health v2** replaces v1's "STRONG" (a 3-fruit test): connected · follows the schema · calibrated per question type (date, model, version, permissions).

## Anti-gaming
The maker cannot edit questions, thresholds, gold sets, or the contract without a visible version. A script builds the packet from the artifact manifest; the maker's chat and reasoning are never sent. Pairwise questions run in both orders. If one question type escalates more than half the time, the question is badly written and gets rewritten.

## Where else the typed questions run
Router applicability ([[layer-04-retrieval-toc]]) · privacy check on outgoing queries ([[layer-03-scope-gate]]) · action risk gate ([[layer-07-execution]]) · claim check of summaries ([[layer-10-closeout]]) · lesson scope ([[layer-11-memory]]) · the vault cleanup audit (vault-cleanup-tonight).
