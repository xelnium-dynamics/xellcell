---
paths:
  - "Brain System/**/*.md"
---

# Vault Notes Standards (XellCell)

- Every note needs YAML frontmatter (`title`, `type`, `scope`, `summary`, `updated` as `YYYY-MM-DD`).
- Write vault notes in one language per note; if you want a language rule enforced, set it in `state/vault-policy.json`.
- Never write directly into `raw/`; only cite existing `raw/...#La-Lb` line ranges.
- After editing notes in `Brain System/`, rebuild `python3 -I tools/brain_index.py` and run `tools/vault_scan.py` + `tools/vault_audit.py` to keep 0 errors and 0 ghosts.
