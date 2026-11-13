---
paths:
  - "skills/**/SKILL.md"
---

# Skill Authoring Standards (XellCell)

- Keep YAML frontmatter clean: `name` (hyphenated), `description` (>= 20 chars, written as user/task **triggers** + keywords), and optional `when_to_use` (never exceed single-screen length).
- Include a concise `## Gotchas` section capturing verified failure modes and non-obvious traps.
- Move heavy tables, examples, and scripts out of `SKILL.md` into lazy `references/` or `scripts/` files (load on demand).
- Quarantine & audit external GitHub skills (`curl|sh`, `eval`, `exec`, secret access) before copying into `skills/`.
- Rebuild index after skill edits: `python3 -I tools/brain_index.py` and verify with `python3 -I tools/route_eval.py`.
