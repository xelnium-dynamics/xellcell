#!/usr/bin/env python3
"""
scan_external.py — read-only catalog of the skills and Git repositories on an external drive (or any folder).

Writes one JSON catalog to state/external/<label>.json. brain_index.py turns it into searchable registry
entries and generated vault pages, so the brain keeps knowing what is on the drive while it is unplugged.
Nothing on the scanned drive is written, moved or executed.

Usage: python3 -I scan_external.py --root /Volumes/MyDrive --label MyDrive
       [--enrich <repository catalog.json>] [--out <file>]

Skills kept: one per name, which is the best copy (curated packages first, then upstream snapshots, then
local snapshots, then repository copies). Skipped, and counted by reason: test or fixture folders, backups,
archives, app bundles, no name, no English description, and names already installed on this Mac (brain_index
drops those).
"""
import argparse, hashlib, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
from brain_index import NON_ENGLISH, english_only  # noqa: E402

PRUNE = {"node_modules", ".venv", "venv", "site-packages", "__pycache__", ".Spotlight-V100", ".fseventsd", ".Trashes",
         ".DocumentRevisions-V100", ".TemporaryItems", ".cache", ".next", "dist-newstyle"}
SKIP_PARTS = {"test", "tests", "__tests__", "fixture", "fixtures", "testdata", "_backup", "backup", "backups", "_archive",
              "_archive_old_versions", "archive", "junks"}
LOCALE_DIR = re.compile(r"(^|/)(i18n|locales?|translations?|[a-z]{2}-[A-Z]{2}|zh|ja|ko|tr|ru)(/|$)")
HERMES_PATH = re.compile(r"(^|/|\s)(\.hermes|hermes-agent|runbookhermes|hermes_agent)(/|$)|/optional-skills/")
LATIN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+&()'-]{0,80}$")


def frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    out, key = {}, None
    for line in text[3:end].split("\n"):
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key = m.group(1)
            out[key] = m.group(2).strip().strip('"').strip("'")
        elif key == "description" and line.startswith((" ", "\t")):
            out[key] = (out[key] + " " + line.strip()).strip()
    if out.get("description", "").startswith((">", "|")):
        out["description"] = out["description"][1:].strip(" -")
    return out


def origin_url(repo):
    cfg = os.path.join(repo, ".git", "config")
    try:
        text = open(cfg, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""
    m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', text, re.S)
    return m.group(1) if m else ""


def slug_of(url):
    u = re.sub(r"^git@([^:]+):", r"https://\1/", url.strip())
    u = re.sub(r"\.git$", "", u.rstrip("/"))
    m = re.search(r"github\.com/([^/]+/[^/]+)$", u)
    return (m.group(1) if m else u).lower(), u


def last_commit(repo):
    """Date of the newest HEAD move, read from .git/logs/HEAD (no git command is run)."""
    try:
        with open(os.path.join(repo, ".git", "logs", "HEAD"), "rb") as fh:
            lines = fh.read().splitlines()
        m = re.search(rb"> (\d{9,11}) [+-]\d{4}", lines[-1]) if lines else None
        return time.strftime("%Y-%m-%d", time.localtime(int(m.group(1)))) if m else ""
    except OSError:
        return ""


def rank(rel):
    if rel.startswith("CODEX FOR CLAUDE/plugins/"):
        return 0
    if rel.startswith("CODEX FOR CLAUDE/library/upstream/"):
        return 1
    if rel.startswith("CODEX FOR CLAUDE/"):
        return 2
    return 3


FAMILY_MIN = 15


def fold_families(skills):
    """Collapse mass-generated skills (one template, many names, e.g. one per SaaS app) into one entry each."""
    groups = {}
    for s in skills:
        base = re.sub(r"[-_](automation|automations|skill|integration|api|mcp|helper)$", "", s["name"].lower())
        norm = s["description"]
        for v in sorted({base, base.replace("-", " "), base.replace("-", ""), base.replace("_", " ")}, key=len, reverse=True):
            if len(v) >= 2:
                norm = re.sub(re.escape(v), "{X}", norm, flags=re.I)
        pattern = s["name"].lower().replace(base, "{X}", 1)
        groups.setdefault((norm, pattern), []).append(s)
    kept, families, fam_items = [], [], []
    for (norm, pattern), items in groups.items():
        if len(items) < FAMILY_MIN or "{X}" not in norm:
            kept.extend(items)
            continue
        fam_items.append((norm, pattern, items))
    for norm, pattern, items in fam_items:  # fold close variants of the same template too
        chunk = re.split(r"[.:;]", max((c.strip() for c in norm.split("{X}")), key=len))[0].strip()
        rx = re.compile("^" + re.escape(pattern).replace(re.escape("{X}"), ".+") + "$", re.I)
        variants = [s for s in kept if len(chunk) >= 12 and chunk in s["description"] and rx.match(s["name"])]
        kept = [s for s in kept if s not in variants]
        items.extend(variants)
    for norm, pattern, items in fam_items:
        items.sort(key=lambda r: r["name"].lower())
        srcs = sorted({re.sub(r" of .*$", "", i["source"]) for i in items})
        fam = {"name": f"{pattern} ({len(items)} templated skills)", "members": len(items),
               "description": f"{len(items)} generated skills of one pattern: \"{norm[:160]}\". Examples: "
                              + ", ".join(i["name"] for i in items[:5]) + ".",
               "location": items[0]["location"], "source": srcs[0] if len(srcs) == 1 else "several sources",
               "sha256": "", "copies": sum(i["copies"] for i in items), "family": True}
        kept.append(fam)
        families.append({"pattern": pattern, "members": len(items), "template": norm[:200], "examples": [i["name"] for i in items[:10]]})
    return kept, families


def scan(root, label, enrich=None):
    root = os.path.abspath(root)
    skills_raw, repos, excluded = [], [], {}
    repo_dirs = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in PRUNE and not x.endswith(".app"))
        if ".git" in dirs or ".git" in files:
            repo_dirs.append(d)
            if ".git" in dirs:
                dirs.remove(".git")
        if "SKILL.md" in files:
            skills_raw.append(os.path.join(d, "SKILL.md"))
    repo_set = sorted(repo_dirs, key=len, reverse=True)

    def repo_of(path):
        for r in repo_set:
            if path.startswith(r + os.sep):
                return r
        return None

    catalog_aliases = {}
    cfc = os.path.join(root, "CODEX FOR CLAUDE", "catalog.json")
    if os.path.exists(cfc):
        for e in B.load_json(cfc, []):
            if e.get("aliases"):
                catalog_aliases[os.path.join(root, "CODEX FOR CLAUDE", e["path"])] = e["aliases"][0]

    best = {}
    for p in skills_raw:
        rel = os.path.relpath(p, root)
        parts = {x.lower() for x in rel.split(os.sep)[:-1]}
        reason = None
        if parts & SKIP_PARTS:
            reason = "test, fixture, backup or archive folder"
        try:
            data = open(p, "rb").read()
        except OSError:
            excluded["unreadable"] = excluded.get("unreadable", 0) + 1
            continue
        meta = frontmatter(data.decode("utf-8", "replace"))
        name = (meta.get("name") or "").strip()
        desc = english_only(re.sub(r"\s+", " ", meta.get("description", "")).strip())
        if not reason and not name:
            reason = "no name in frontmatter"
        elif not reason and not LATIN_NAME.match(name):
            reason = "name not in English letters"
        elif not reason and (not desc or desc.startswith("(description not in English")):
            reason = "no English description"
        elif not reason and re.match(r"(?i)^(moved to|deprecated|this skill (has )?(moved|been moved)|superseded by)\b", desc):
            reason = "moved or deprecated stub"
        if not reason:
            body = data.decode("utf-8", "replace")[:4000]
            letters = sum(ch.isalpha() for ch in body) or 1
            if sum(len(m) for m in NON_ENGLISH.findall(body)) / letters > 0.05:
                reason = "skill text not in English"
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        origin_path = (catalog_aliases.get(p, "") + " " + rel).lower()
        if (HERMES_PATH.search(origin_path) or "hermes" in name.lower()
                or re.search(r"\bhermes\b(?! engine)", desc, re.I)):
            excluded["belongs to the removed Hermes agent"] = excluded.get("belongs to the removed Hermes agent", 0) + 1
            continue
        repo = repo_of(p)
        if rel.startswith("CODEX FOR CLAUDE/library/upstream/"):
            owner_repo = rel.split(os.sep)[3].replace("--", "/", 1)
            source = f"{owner_repo} (snapshot in CODEX FOR CLAUDE)"
        elif rel.startswith("CODEX FOR CLAUDE/library/local/"):
            alias = catalog_aliases.get(p, "")
            short = ""
            if alias:
                a = alias.replace(root + os.sep, "").replace(os.path.expanduser("~") + os.sep, "~/")
                bits = [b for b in a.split("/") if b not in ("skills", "SKILL.md", "source", ".claude", ".agents")]
                short = "/".join(bits[-3:-1]) if len(bits) > 2 else "/".join(bits[:-1])
            source = "CODEX FOR CLAUDE local snapshot" + (f" of {short}" if short else "")
        elif rel.startswith("CODEX FOR CLAUDE/plugins/"):
            source = f"CODEX FOR CLAUDE plugin {rel.split(os.sep)[2]}"
        elif repo:
            url = origin_url(repo)
            source = slug_of(url)[0] if url else os.path.relpath(repo, root)
        else:
            source = os.path.dirname(os.path.dirname(rel)) or "(drive top level)"
        row = {"name": name, "description": desc[:400], "location": p, "source": source,
               "sha256": hashlib.sha256(data).hexdigest(), "copies": 1,
               "_rank": (rank(rel), 1 if LOCALE_DIR.search(rel.replace(os.sep, "/")) else 0, len(rel), rel)}
        key = name.lower()
        if key in best:
            keep = min(best[key], row, key=lambda r: r["_rank"])
            keep["copies"] = best[key]["copies"] + 1
            best[key] = keep
        else:
            best[key] = row
    skills = [{k: v for k, v in r.items() if k != "_rank"} for r in best.values()]
    skills, families = fold_families(skills)
    skills.sort(key=lambda r: r["name"].lower())

    notes_by_slug = {}
    if enrich and os.path.exists(enrich):
        for e in B.load_json(enrich, []):
            if e.get("remote"):
                notes_by_slug[slug_of(e["remote"])[0]] = e
    seen = {}
    for r in sorted(repo_dirs):
        url = origin_url(r)
        slug, web = slug_of(url) if url else ("", "")
        rel = os.path.relpath(r, root)
        n_sk = sum(1 for s in skills_raw if s.startswith(r + os.sep))
        e = notes_by_slug.get(slug, {})
        row = {"path": r, "area": "/".join(rel.split(os.sep)[:2]), "remote": web, "slug": slug or rel,
               "last_commit": last_commit(r), "skill_files": n_sk,
               "description": (e.get("description") or "").strip(), "use": (e.get("use") or "").strip(), "copies": 1}
        k = slug or rel
        if k in seen:
            seen[k]["copies"] += 1
            if row["last_commit"] > seen[k]["last_commit"]:
                row["copies"] = seen[k]["copies"]
                seen[k] = row
        else:
            seen[k] = row
    upstream = os.path.join(root, "CODEX FOR CLAUDE", "library", "upstream")
    if os.path.isdir(upstream):
        for d in sorted(os.listdir(upstream)):
            if "--" not in d:
                continue
            slug = d.replace("--", "/", 1).lower()
            if slug not in seen:
                seen[slug] = {"path": os.path.join(upstream, d), "area": "CODEX FOR CLAUDE/library", "remote": f"https://github.com/{d.replace('--', '/', 1)}",
                              "slug": slug, "last_commit": "", "skill_files": sum(1 for s in skills_raw if s.startswith(os.path.join(upstream, d) + os.sep)),
                              "description": "Source snapshot kept by the CODEX FOR CLAUDE harness.", "use": "", "copies": 1}
    repos = sorted(seen.values(), key=lambda x: (x["area"].lower(), x["slug"]))
    return {"label": label, "root": root, "scanned": B.now(), "tool": "tools/scan_external.py",
            "counts": {"skill_files": len(skills_raw), "skills_kept": len(skills), "templated_families": len(families),
                       "templated_skills_folded": sum(f["members"] for f in families), "repos_found": len(repo_dirs), "repos_unique": len(repos)},
            "families": families,
            "excluded": excluded, "skills": skills, "repos": repos}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--root", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--enrich")
    ap.add_argument("--out")
    a = ap.parse_args()
    if not os.path.isdir(a.root):
        sys.exit(f"not a folder: {a.root}")
    root = os.path.realpath(a.root)
    out = a.out or os.path.join(B.STATE, "external", f"{a.label}.json")
    if os.path.realpath(out).startswith(root + os.sep):
        sys.exit("refusing to write inside the scanned folder")
    cat = scan(a.root, a.label, a.enrich)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    B.atomic_write(out, json.dumps(cat, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({"out": B.rel(out) if out.startswith(B.ROOT) else out, **cat["counts"], "excluded": cat["excluded"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
