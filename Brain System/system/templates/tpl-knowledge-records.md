---
title: Knowledge record templates
type: template
summary: Templates for the capability card, problem, lesson, identity record and project state.
updated: 2026-11-08
---
# Knowledge record templates

## Capability card — `Brain System/capabilities/<stable-id>.md`
```yaml
---
id: cap-units-check-before-export
title: Check model units before export between modeling and analysis tools
kind: instruction          # instruction | executable | integration
status: tested             # proposed | tested | released | outdated | retired
use_when: ["geometry moves between two tools", "physical simulation follows"]
do_not_use_when: ["2D layout only", "units fixed by a single tool end to end"]
requires: {inputs: [model file], tools: [modeling-tool], permissions: []}
produces: "unit report + corrected scale"
compatible_with: {formats: [fbx, obj, stl], versions: {modeling-tool: "4.x"}}
verification: "re-import and measure a known dimension"
evidence: [ep-20261020-claude-a1b2]
limits: ["does not check material properties"]
origin: {source: "own episode", revision: null, last_success: 2026-10-20}
depends_on: [{path: raw/…, sha256: …}]
last_verified: 2026-10-20
shelf: [3D.VAL.MODEL, ENG.VAL.SIMRES]
domains: [3d, engineering]
---
```
Body: steps · checks · known problems (ids) · examples (episode ids).

## Problem — `Brain System/problems/p-NNN.md`
```yaml
---
id: p-NNN
date: 2026-11-08
kind: flaw                 # flaw | rejection | slop | token-waste | safety
conditions: "when …"       # the situation, so it does not become a blanket ban
scope: project             # task | project | domain | general
status: open               # open | guarded | retired
episode: ep-…
---
```
What happened · cause (mechanism) · **guard** (a check, a card step, a rule; "be careful" does not count).

## Lesson — `Brain System/lessons/<id>.md`
```yaml
---
id: les-…
status: candidate          # candidate | released | retired
scope: project
evidence: [results.tsv rows, episode ids]
covers: ["task types the evidence actually includes"]
approved_by_mark: null     # date, required for release
---
```
Situation · lesson (the harness change) · evidence (baseline vs candidate, wins, losses, cost) · when NOT to apply.

## Identity — `Brain System/self/identity.md`
Canonical person with aliases **Alex = Al = Lex**. Only facts the owner stated or documents prove, each with its source.

## Project state — `Brain System/projects/<p>/state.md`
Current status (one paragraph) · open decisions · latest episodes (generated list) · client decisions (authority = the owner or client, with date).
