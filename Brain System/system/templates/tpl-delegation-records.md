---
title: Delegation record templates
type: template
summary: The father-to-son work order and the son-to-father menu of pointed options.
updated: 2026-11-08
---
# Delegation record templates

## Work order (director → scout)
```yaml
parent_step: "Building the airflow setup for a car body in Blender; I need the unit-check method and any export notes."
bring: "capability cards or passages about unit checks and Blender export"
shelves: [Brain System/capabilities, Brain System/domains/3d, Brain System/projects/story-building]
exclude: [Brain System/self, architectural layout, structural analysis]
budget: {tokens: 20000, minutes: 5}
return: menu            # 2-3 options, pointers only
```

## Menu (scout → director)
```yaml
options:
  - title: "Check model units before export"
    pointer: Brain System/capabilities/cap-units-check-before-export.md#L1-L40
    fits_because: "the car model moves Blender → simulation tool"
    risk: "card tested on fbx only; the brief may need stl"
    size_lines: 40
  - title: "Story building episode: export step"
    pointer: Brain System/projects/story-building/episodes/2026-10-20-story-building-model.md#L55-L80
    fits_because: "same export path"
    risk: "contains structural assumptions; read only the export section"
    size_lines: 26
not_found: ["airflow validation method"]
```
The director reads the pointed lines himself. The scout never paraphrases instructions or numbers.
