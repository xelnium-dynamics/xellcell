---
title: Layer 4 - Retrieval (table of contents)
type: system
summary: One canonical card per reusable capability, generated table-of-contents views, a six-step reading ladder that rejects before it reads, a measured token budget, and a retrieval log that improves the next search.
updated: 2026-11-08
---
# Layer 4 — Retrieval (table of contents)

| Job | Input | Output | Owner | If it fails | Test |
|---|---|---|---|---|---|
| Right pieces in, wrong pieces rejected unread | Contract facets + allowed collections | Context packet + retrieval log | Router script + scout | "No match": plan from first principles | Labeled set: ≥ 9 of 10 correct in top 5 |

## Canonical cards, many views
- **One file per reusable thing.** A project stays an intact history; its reusable methods become separate **capability cards** that cite the project as evidence. Template: [[tpl-knowledge-records]].
- **Card header** (read before the body): stable id · descriptive title ("Check model units before export", not "Amazing 3D skill") · purpose · **use when** · **do not use when** · requires (inputs, tools, permissions) · produces · compatible with (formats, versions) · verification · evidence · limits · status (proposed / tested / released / outdated / retired) · last verified · depends on · shelf codes.
- **Generated views** (by `brain_index.py`, never hand-edited) in `Brain System/00-toc/`: by outcome · by capability · by domain · by tool · by project · by problem · by shelf code. Plus `index/brain.db`, a SQLite full-text index (Python standard library, no paid embeddings) over titles, use-when, do-not-use-when and synonyms.

## Shelf codes (v1 recall codes, demoted to labels)
`DOMAIN.ACTION.OUTPUT` stays as a navigation shelf, not the key. A task gets several codes. Vocabulary added so the owner's real tasks fit:
DOMAIN `PER` personal life · `ENG` engineering and physics analysis · `CAR` career and official documents · `FIN` finance research (paper only). ACTION `ANL` analyse/calculate · `VAL` validate · `ORG` organize/clean. OUTPUT `CV` · `LETTER` · `FORM` · `PART` (mechanical part) · `SIMRES` (simulation result).

## The reading ladder (reject before reading)
1. Contract → facets (outcome, domain, tools, constraints, risk).
2. Facets → TOC branches (only allowed collections).
3. Read **card headers only** (≤ 15 cards).
4. **Applicability check** per card: use-when, do-not-use-when and requires against the contract; typed question `APPLIES` (yes / no / unsure).
5. Open the bodies of the selected cards only.
6. For consequential decisions, open the cited source passage (path + line range), never a summary of it.

For a chain of capabilities, the output of step k must meet the input of step k+1 (format, units, assumptions): typed check `PIPELINE-FIT`.

## Building → car in a wind tunnel (the owner's example)
| From the building project | For the car task |
|---|---|
| Blender geometry operations | candidate, check against new geometry needs |
| Units check procedure | reuse the method, re-verify the values |
| Export workflow | reuse only if the receiving tool and format match |
| Architectural layout, structural analysis | excluded by do-not-use-when |
| Airflow method and validation | not in brain → named as a gap ([[layer-05-readiness-gap]]) |

## Budget, cache, log
- **Token budget** (default 2,500 tokens for the packet) with protected space for constraints, exclusions and unknowns; a bounded expansion is allowed when a missing detail matters, and is logged. Replaces v1's "40 lines".
- **Route cache** keyed by the facet signature; it stores card ids + their content hashes + tool versions and is invalid the moment any of them changes.
- **Retrieval log** per session: *selected and useful* · *considered and rejected (reason)* · *needed and missing*. It feeds [[layer-12-improve]] (better terms, sharper exclusions, direct cards for methods found repeatedly inside project histories).
- "No match" is a valid answer. A match is never forced because two tasks share a word like "3D".
- **Explore mode** (contract field *novelty*): creative-direction cards are excluded and the client's recent directions are returned as "do not repeat"; verification cards are still used.
