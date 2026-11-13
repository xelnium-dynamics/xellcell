#!/usr/bin/env python3
"""
vault_audit.py — line-by-line quality audit of the brain vault (read-only, no model).

    python3 -I vault_audit.py --vault <vault> --out <report folder outside the vault> [--root <brain root>]

Checks every line of every note:
  ERROR   frontmatter missing · empty note · text in a disallowed script (Chinese, Japanese, Korean,
          ...) · garbled characters · Hermes skill-stub boilerplate · a forbidden rule · a source reference
          that does not exist in raw/ or whose line range is outside the file · an instruction to read or write
          the old vault
  WARN    text in a warned script outside project/history records · very long line or base64-like blob outside code
Which scripts and rules count is the owner's choice: state/vault-policy.json (brainlib.language_policy). Without that
file every language is allowed and no rule is forbidden.
  INFO    every remaining mention of Hermes (kept only as history or provenance), counted per note
Exit code 1 if any ERROR.
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import brainlib as B  # noqa: E402

GARBLED = re.compile(r"Ã[\u0080-¿]|â€|�")
STUB = re.compile(r"\[!info\]\s*Hermes skill", re.I)
OLD_VAULT = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?(?:\*\*[^*]+\*\*\s*[\u2014:-]\s*)?(?:read|update|write|save|sync|append)\b[^\n]{0,80}(?:Obsidian Xelnium|Current State|HUB)", re.I)
HERMES = re.compile(r"\bhermes\b", re.I)
BLOB = re.compile(r"[A-Za-z0-9+/=]{220,}")
RECORD_COLLECTIONS = ("projects", "history")


SYNTHESIS_TYPES = {"lesson", "learning", "experience"}
PRIMARY_SOURCE_HINTS = ("raw/", "sessions/", "tools/", "skills/", "references/", "http://", "https://", "transcript", "verdict", "evidence", ".claude/", ".codex/", "analysis.json", "hook-errors.log")
SECONDARY_ONLY_HINTS = ("Brain System/lessons/", "Brain System/history/learnings/", "lessons/", "learnings/", "[[")


def _check_self_citation(rel, meta, body, warns):
    """Karpathy LLM Wiki layer-11 provenance guard: synthesis notes must cite primary evidence, not only other syntheses."""
    ntype = str(meta.get("type") or "").strip().lower()
    is_synth = ntype in SYNTHESIS_TYPES or rel.startswith(("lessons/", "history/learnings/"))
    if not is_synth:
        return False
    declared = []
    for key in ("sources", "source"):
        val = meta.get(key)
        if isinstance(val, list):
            declared.extend(str(x).strip() for x in val if str(x).strip())
        elif isinstance(val, str) and val.strip():
            declared.append(val.strip())
    if not declared:
        return False
    joined = "\n".join(declared) + "\n" + body
    has_primary = any(h in joined for h in PRIMARY_SOURCE_HINTS)
    has_secondary_declared = any(any(sh in s for sh in SECONDARY_ONLY_HINTS) for s in declared)
    if has_secondary_declared and not has_primary:
        warns.append((rel, 0, "self-citation loop: cites only synthesis notes without primary evidence", "; ".join(declared)[:100]))
        return True
    return False


def audit(vault, root):
    errors, warns, info = [], [], {}
    policy = B.language_policy(root)
    SCRIPTS = {k: re.compile(v) for k, v in (policy.get("disallowed_scripts") or {}).items()}
    WARN_SCRIPTS = {k: re.compile(v) for k, v in (policy.get("warn_scripts") or {}).items()}
    RULES = [re.compile(r, re.I) for r in (policy.get("forbidden_rules") or [])]
    notes = list(B.iter_notes(vault))
    for p in notes:
        rel = os.path.relpath(p, vault).replace(os.sep, "/")
        with open(p, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        fm, body = B.split_frontmatter(text)
        meta = B.parse_frontmatter(fm) if fm is not None else {}
        if fm is None:
            errors.append((rel, 0, "frontmatter missing", ""))
        lines_nb = [ln for ln in body.split("\n") if ln.strip() and not ln.lstrip().startswith(("---", "*Migrated", "<!--"))]
        h1s = [ln for ln in lines_nb if re.match(r"^#\s", ln)]
        content = [ln for ln in lines_nb if ln not in h1s[:1]]
        if not content and not rel.startswith("drawings/"):
            errors.append((rel, 0, "empty note", ""))
        top = rel.split("/")[0]
        in_code, offset = False, (text[:len(text) - len(body)].count("\n"))
        for i, line in enumerate(body.split("\n"), start=offset + 1):
            if re.match(r"^\s{0,3}(```|~~~)", line):
                in_code = not in_code
            for name, rx in SCRIPTS.items():
                if rx.search(line):
                    errors.append((rel, i, f"text in {name}", line.strip()[:100]))
            if GARBLED.search(line):
                errors.append((rel, i, "garbled characters", line.strip()[:100]))
            if STUB.search(line):
                errors.append((rel, i, "Hermes skill-stub boilerplate", line.strip()[:100]))
            for rx in RULES:
                if rx.search(line):
                    errors.append((rel, i, "forbidden rule (state/vault-policy.json)", line.strip()[:100]))
            if OLD_VAULT.search(line) and meta.get("authority") == "legacy" and meta.get("type") not in ("history", "log"):
                errors.append((rel, i, "instruction to use the old vault", line.strip()[:100]))
            for name, rx in WARN_SCRIPTS.items():
                if rx.search(line) and top not in RECORD_COLLECTIONS:
                    warns.append((rel, i, f"{name} outside a project/history record", line.strip()[:100]))
            if not in_code and not rel.startswith("drawings/") and (len(line) > 4000 or BLOB.search(line)):
                warns.append((rel, i, "very long line or blob outside code", line.strip()[:60]))
            if HERMES.search(line):
                info[rel] = info.get(rel, 0) + 1
        for src in meta.get("sources", []) if isinstance(meta.get("sources"), list) else []:
            m = re.match(r"^(raw/[^#]+?)(?:#L(\d+)-L(\d+))?$", src)
            if not m:
                continue
            path = os.path.join(root, m.group(1))
            if not os.path.exists(path):
                errors.append((rel, 0, "source missing in raw/", src))
            elif m.group(2) and os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as sfh:
                    n = sum(1 for _ in sfh)
                if int(m.group(3)) > n + 1:
                    errors.append((rel, 0, f"source line range beyond file ({n} lines)", src))
        _check_self_citation(rel, meta, body, warns)
    return notes, errors, warns, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--root", default=B.ROOT)
    a = ap.parse_args()
    vault, out = os.path.realpath(a.vault), os.path.realpath(a.out)
    if out == vault or out.startswith(vault + os.sep):
        sys.exit("refusing: --out must be outside the vault")
    os.makedirs(out, exist_ok=True)
    notes, errors, warns, info = audit(vault, os.path.realpath(a.root))
    self_cites = sum(1 for _, _, why, _ in warns if "self-citation loop" in why)
    rep = ["# Vault audit", "", f"Vault: `{vault}` · notes: {len(notes)} · errors: {len(errors)} · warnings: {len(warns)} · "
           f"self-citation warnings: {self_cites} · notes that still mention Hermes (history/provenance): {len(info)}", ""]
    for title, rows in (("Errors", errors), ("Warnings", warns)):
        rep += [f"## {title} ({len(rows)})", ""] + [f"- `{r}`:{n} — {why} — {txt}" for r, n, why, txt in rows[:300]] + [""]
    rep += ["## Hermes mentions kept (count per note)", ""] + [f"- `{r}`: {c}" for r, c in sorted(info.items())]
    with open(os.path.join(out, "audit.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(rep) + "\n")
    print(json.dumps({"notes": len(notes), "errors": len(errors), "warnings": len(warns),
                      "self_citation_warnings": self_cites, "hermes_mention_notes": len(info)}))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
