#!/usr/bin/env python3
"""
vault_scan.py (v2) — read-only structural scan of an Obsidian vault.

No LLM, no network, no writes inside the vault. Python 3.9+ stdlib only.

v2 fixes (Agent Brain FINAL VERSION, 2026-11-08):
  - an unreadable note is reported ("unreadable"), it no longer crashes the scan
  - an explicit path link ([[Folder/Note]]) resolves only to that path; a same-name note
    elsewhere is offered as "suggest", never silently accepted
  - #Heading and #^block fragments are checked against the target note ("bad_fragment")
  - broken markdown links count as ghosts too, with their link kind
  - angle-bracket links [x](<path with spaces.md>) are parsed; absolute paths are
    resolved inside the vault or reported as "outside_vault"

Usage:
    python3 -I vault_scan.py --vault "/path/to/Vault" --out "/path/outside/vault/scan-out" \
        [--ignore-prefix raw/]   # ghosts whose every source is under this prefix are counted apart

Outputs (in --out):
    notes.jsonl     one record per note: path, hash, size, frontmatter keys, title flags, link counts
    links.jsonl     one record per link: source, raw target, kind, resolution
    ghosts.csv      link targets that resolve to no file (the "phantom nodes" in Graph view), ranked
    report.md       summary metrics + top problem lists

Body text is never copied into outputs; only H1, heading count, word count and link targets.
"""
import argparse, csv, hashlib, json, os, re, sys, time
from collections import Counter, defaultdict
from urllib.parse import unquote

SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", ".venv", "__pycache__", ".smart-env", ".makemd"}
NOTE_EXT = {".md"}
MAX_BYTES = 5 * 1024 * 1024  # notes larger than this are indexed as metadata only

RE_FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.M | re.S)
RE_INLINE_CODE = re.compile(r"`[^`\n]*`")
RE_WIKI = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
RE_MDLINK = re.compile(r"(!?)\[([^\]\n]*)\]\((?:<([^>\n]+)>|([^)\s]+))(?:\s+\"[^\"]*\")?\)")
RE_BLOCK_ID = re.compile(r"(?:^|\s)\^([A-Za-z0-9\-]+)\s*$", re.M)
RE_BARE_URL = re.compile(r"(?<![\(\[<\"'])\bhttps?://[^\s)\]>]+")
RE_TAG = re.compile(r"(?:(?<=\s)|^)#([A-Za-z0-9_\-/]*[A-Za-z_\-/][A-Za-z0-9_\-/]*)")
RE_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.M)
RE_UNTITLED = re.compile(r"^(untitled|unbenannt|new note|note|bez nazwy)( ?\d+)?$", re.I)


def split_frontmatter(text):
    if not text.startswith("---"):
        return None, text
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def parse_frontmatter(fm):
    """Minimal YAML reader: top-level keys, plus list values for aliases/tags. Never raises."""
    keys, lists, current = [], defaultdict(list), None
    for line in fm.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        km = re.match(r"^([A-Za-z0-9_\-]+)\s*:\s*(.*)$", line)
        if km and not line.startswith((" ", "\t", "-")):
            current = km.group(1).lower()
            keys.append(current)
            val = km.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                lists[current] += [v.strip().strip("'\"") for v in val[1:-1].split(",") if v.strip()]
            elif val:
                lists[current].append(val.strip("'\""))
            continue
        lm = re.match(r"^\s*-\s+(.*)$", line)
        if lm and current:
            lists[current].append(lm.group(1).strip().strip("'\""))
    return keys, lists


def strip_code(body):
    return RE_INLINE_CODE.sub(" ", RE_FENCE.sub(" ", body))


def is_external(target):
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", target))  # http:, https:, obsidian:, file:, mailto:


def norm(s):
    return s.strip().replace("\\", "/").lower()


def head_key(s):
    """Heading match key: case-insensitive, whitespace-collapsed (Obsidian heading links)."""
    return re.sub(r"\s+", " ", s.strip()).lower()


def slug(s):
    """GitHub-style slug, accepted as an alternative heading spelling in markdown links."""
    return re.sub(r"[^\w\- ]", "", s.strip().lower()).replace(" ", "-")


def walk(vault):
    for root, dirs, files in os.walk(vault, followlinks=False):
        for d in dirs:
            if os.path.islink(os.path.join(root, d)):
                yield os.path.join(root, d), "symlink"
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(root, d)))
        for f in sorted(files):
            p = os.path.join(root, f)
            if os.path.islink(p):
                yield p, "symlink"
            else:
                yield p, "file"


def main():
    ap = argparse.ArgumentParser(description="Read-only Obsidian vault structure scan")
    ap.add_argument("--vault", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=40, help="rows per list in report.md")
    ap.add_argument("--ignore-prefix", action="append", default=[],
                    help="ghosts whose sources all start with this vault-relative prefix are counted apart")
    a = ap.parse_args()

    vault = os.path.realpath(os.path.expanduser(a.vault))
    out = os.path.realpath(os.path.expanduser(a.out))
    if not os.path.isdir(vault):
        sys.exit(f"vault not found: {vault}")
    if out == vault or out.startswith(vault + os.sep):
        sys.exit("refusing: --out must be outside the vault (scan is read-only)")
    os.makedirs(out, exist_ok=True)

    t0 = time.time()
    notes, attachments, errors, symlinks = {}, {}, [], []
    for p, kind in walk(vault):
        rel = os.path.relpath(p, vault).replace(os.sep, "/")
        if kind == "symlink":
            symlinks.append(rel)
            continue
        if os.path.basename(p) == ".DS_Store":  # macOS Finder metadata, not an attachment
            continue
        ext = os.path.splitext(p)[1].lower()
        try:
            st = os.stat(p)
        except OSError as e:
            errors.append((rel, str(e)))
            continue
        if ext in NOTE_EXT:
            notes[rel] = {"path": rel, "bytes": st.st_size, "mtime": int(st.st_mtime)}
        else:
            attachments[rel] = {"path": rel, "bytes": st.st_size, "ext": ext}

    # name indexes for Obsidian-style resolution (basename, case-insensitive; or path suffix)
    by_base = defaultdict(list)
    by_path = {}
    for rel in list(notes) + list(attachments):
        by_path[norm(rel)] = rel
        stem = rel.rsplit("/", 1)[-1]
        by_base[norm(stem)].append(rel)
        if stem.lower().endswith(".md"):
            by_base[norm(stem[:-3])].append(rel)
            by_path[norm(rel[:-3])] = rel

    alias_index = defaultdict(list)
    bodies = {}
    anchors = {}  # rel -> {"h": heading keys, "s": heading slugs, "b": block ids}
    for rel, n in notes.items():
        # complete record first, so an unreadable note can never crash later steps (v2 fix 57)
        n.update({"sha256": None, "has_frontmatter": False, "fm_keys": [], "aliases": [], "h1": None,
                  "headings": 0, "words": 0, "tags": [], "flags": []})
        p = os.path.join(vault, rel)
        h = hashlib.sha256()
        try:
            with open(p, "rb") as fh:
                raw = b""
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
                    if len(raw) < MAX_BYTES:
                        raw += chunk
        except OSError as e:
            errors.append((rel, str(e)))
            n["read_error"] = True
            n["flags"] = ["unreadable"]
            continue
        n["sha256"] = h.hexdigest()
        n["truncated_read"] = n["bytes"] > MAX_BYTES
        text = raw[:MAX_BYTES].decode("utf-8", errors="replace")
        fm, body = split_frontmatter(text)
        keys, lists = parse_frontmatter(fm) if fm is not None else ([], {})
        n["has_frontmatter"] = fm is not None
        n["fm_keys"] = keys
        n["aliases"] = list(lists.get("aliases", [])) + list(lists.get("alias", []))
        for al in n["aliases"]:
            alias_index[norm(al)].append(rel)
        clean = strip_code(body)
        heads = RE_HEADING.findall(clean)
        n["h1"] = next((t for lvl, t in heads if lvl == "#"), None)
        n["headings"] = len(heads)
        anchors[rel] = {"h": {head_key(t) for _, t in heads}, "s": {slug(t) for _, t in heads},
                        "b": set(RE_BLOCK_ID.findall(clean))}
        n["words"] = len(re.findall(r"\w+", clean))
        tags = set(t.lower() for t in lists.get("tags", []) + lists.get("tag", []))
        tags |= set(t.lower() for t in RE_TAG.findall(clean))
        n["tags"] = sorted(tags)
        stem = rel.rsplit("/", 1)[-1][:-3]
        flags = []
        if RE_UNTITLED.match(stem.strip()):
            flags.append("untitled_or_generic")
        if re.fullmatch(r"[\d\s\-_.]+", stem) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", stem):
            flags.append("numeric_title")
        if len(stem.strip()) <= 2:
            flags.append("very_short_title")
        if n["words"] == 0:
            flags.append("empty")
        elif n["words"] < 20:
            flags.append("stub")
        if not n["has_frontmatter"]:
            flags.append("no_frontmatter")
        if n["h1"] and norm(n["h1"]) != norm(stem):
            flags.append("h1_differs_from_filename")
        n["flags"] = flags
        bodies[rel] = clean

    suggestions = {}  # (src, target) -> same-name notes offered for a broken explicit path

    def resolve_file(target, src):
        t = unquote(target.split("#", 1)[0]).strip()
        if not t:
            return "self", src  # [[#Heading]] link within the same note
        if os.path.isabs(t):
            real = os.path.normpath(t)
            if real == vault or real.startswith(vault + os.sep):
                t = os.path.relpath(real, vault).replace(os.sep, "/")
            else:
                return "outside_vault", None
        nt = norm(t)
        if nt in by_path:
            return "resolved", by_path[nt]
        # relative path from source folder (markdown-style links)
        src_dir = os.path.dirname(src)
        rp = norm(os.path.normpath(os.path.join(src_dir, t)).replace(os.sep, "/"))
        if rp in by_path:
            return "resolved", by_path[rp]
        base = nt.rsplit("/", 1)[-1]
        cands = by_base.get(base, [])
        if "/" in nt:
            # an explicit path must match that path; never fall back to a same-name note (v2 fix 58)
            exact = [c for c in cands if norm(c).endswith("/" + nt) or norm(c).endswith("/" + nt + ".md")
                     or norm(c) in (nt, nt + ".md")]
            if not exact and cands:
                suggestions[(src, target)] = cands
            cands = exact
        if len(cands) == 1:
            return "resolved", cands[0]
        if len(cands) > 1:
            return "ambiguous", cands
        if nt in alias_index:
            return "alias_only", alias_index[nt]
        return "unresolved", None

    def resolve(target, src):
        """File resolution plus fragment check (v2 fix 59)."""
        status, dest = resolve_file(target, src)
        if status not in ("resolved", "self") or "#" not in target:
            return status, dest
        if not str(dest).lower().endswith(".md"):
            return status, dest  # fragments on attachments (e.g. PDF #page) are not checked
        frag = unquote(target.split("#", 1)[1]).strip()
        if dest not in anchors:
            return "fragment_unchecked", dest  # target unreadable
        if frag.startswith("^"):
            ok = frag[1:] in anchors[dest]["b"]
        else:
            last = frag.split("#")[-1]  # [[Note#H1#H2]] -> check the deepest heading
            ok = head_key(last) in anchors[dest]["h"] or slug(last) in anchors[dest]["s"]
        return ("resolved" if status == "resolved" else "self") if ok else "bad_fragment", dest

    links = []
    indeg, outdeg = Counter(), Counter()
    ghosts = defaultdict(lambda: {"refs": 0, "sources": set(), "kinds": Counter()})
    ext_hosts = Counter()

    def add_link(rel, target, kind, cnt):
        status, dest = resolve(target, rel)
        rec = {"source": rel, "target": target, "kind": kind, "status": status, "dest": dest}
        if (rel, target) in suggestions and status == "unresolved":
            rec["suggest"] = suggestions[(rel, target)]
        links.append(rec)
        cnt[status] += 1
        if status in ("resolved", "bad_fragment", "fragment_unchecked") and dest in notes and dest != rel:
            outdeg[rel] += 1
            indeg[dest] += 1
        if status == "unresolved":  # every link kind counts as a ghost (v2 fix 60)
            g = ghosts[norm(unquote(target.split("#", 1)[0]))]
            g["refs"] += 1
            g["sources"].add(rel)
            g["kinds"][kind] += 1
            g["display"] = unquote(target.split("#", 1)[0]).strip()

    for rel, clean in bodies.items():
        n = notes[rel]
        cnt = Counter()
        for bang, inner in RE_WIKI.findall(clean):
            add_link(rel, inner.split("|", 1)[0].rstrip("\\"), "embed" if bang else "wikilink", cnt)  # "\\|" = table escape
        for bang, label, angle, plain in RE_MDLINK.findall(clean):
            target = angle or plain
            if is_external(target):
                ext_hosts[re.sub(r"^[a-z]+://", "", target.lower()).split("/", 1)[0]] += 1
                links.append({"source": rel, "target": target, "kind": "external", "status": "external",
                              "dest": None})
                cnt["external"] += 1
                continue
            add_link(rel, target, "mdlink", cnt)
        bare = RE_BARE_URL.findall(RE_MDLINK.sub(" ", clean))
        for u in bare:
            ext_hosts[re.sub(r"^[a-z]+://", "", u.lower()).split("/", 1)[0]] += 1
            links.append({"source": rel, "target": u, "kind": "bare_url", "status": "external", "dest": None})
        cnt["bare_url"] += len(bare)
        n["links"] = dict(cnt)

    for rel, n in notes.items():
        n["in"] = indeg[rel]
        n["out"] = outdeg[rel]
        if n["in"] == 0 and n["out"] == 0:
            n["flags"].append("orphan")
        elif n["in"] == 0:
            n["flags"].append("no_backlinks")

    referenced_att = {l["dest"] for l in links if l["status"] == "resolved" and l["dest"] in attachments}
    dup_hash = defaultdict(list)
    for rel, n in notes.items():
        if n.get("sha256") and n.get("words", 0) > 0:
            dup_hash[n["sha256"]].append(rel)
    dup_hash = {k: v for k, v in dup_hash.items() if len(v) > 1}
    dup_names = {k: v for k, v in by_base.items() if len(v) > 1 and not k.endswith(".md")
                 and all(x.endswith(".md") for x in v)}

    # ---- write outputs ----
    with open(os.path.join(out, "notes.jsonl"), "w", encoding="utf-8") as f:
        for rel in sorted(notes):
            f.write(json.dumps(notes[rel], ensure_ascii=False) + "\n")
    with open(os.path.join(out, "links.jsonl"), "w", encoding="utf-8") as f:
        for l in links:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    ghost_rows = sorted(ghosts.values(), key=lambda g: (-g["refs"], g["display"].lower()))
    ignored = tuple(p.rstrip("/") + "/" for p in a.ignore_prefix)
    for g in ghost_rows:
        g["ignored"] = bool(ignored) and all(s.startswith(ignored) for s in g["sources"])
    with open(os.path.join(out, "ghosts.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["target", "references", "source_notes", "kinds", "ignored_prefix", "example_sources"])
        for g in ghost_rows:
            src = sorted(g["sources"])
            w.writerow([g["display"], g["refs"], len(src), " ".join(f"{k}:{v}" for k, v in sorted(g["kinds"].items())),
                        "yes" if g["ignored"] else "no", " | ".join(src[:5])])
    ghosts_counted = sum(1 for g in ghost_rows if not g["ignored"])

    N = len(notes)
    flag_counts = Counter(fl for n in notes.values() for fl in n.get("flags", []))
    status_counts = Counter(l["status"] for l in links)
    ambiguous_links = status_counts.get("ambiguous", 0)
    pct = lambda x: f"{(100.0 * x / N):.1f}%" if N else "n/a"
    fm_keys = Counter(k for n in notes.values() for k in n.get("fm_keys", []))
    top = a.top
    R = []
    R.append(f"# Vault scan report\n\nVault: `{vault}`  \nScanned: {time.strftime('%Y-%m-%d %H:%M')}  "
             f"Duration: {time.time()-t0:.1f}s  \nRead-only scan; no LLM; body text not copied.\n")
    R.append("## Totals\n")
    R.append(f"| Metric | Value |\n|---|---|\n| Notes (.md) | {N} |\n| Attachments | {len(attachments)} |\n"
             f"| Unreferenced attachments | {len(set(attachments) - referenced_att)} |\n"
             f"| Symlinks skipped | {len(symlinks)} |\n| Read errors | {len(errors)} |\n"
             f"| Notes with frontmatter | {N - flag_counts['no_frontmatter']} ({pct(N - flag_counts['no_frontmatter'])}) |\n"
             f"| Orphans (no links in or out) | {flag_counts['orphan']} ({pct(flag_counts['orphan'])}) |\n"
             f"| No backlinks | {flag_counts['no_backlinks']} ({pct(flag_counts['no_backlinks'])}) |\n"
             f"| Empty notes | {flag_counts['empty']} |\n| Stubs (<20 words) | {flag_counts['stub']} |\n"
             f"| Untitled-or-generic / numeric / ≤2-char titles | {flag_counts['untitled_or_generic']} / {flag_counts['numeric_title']} / {flag_counts['very_short_title']} |\n"
             f"| H1 differs from filename | {flag_counts['h1_differs_from_filename']} |\n"
             f"| Unreadable notes | {flag_counts['unreadable']} |\n"
             f"| Ghost targets (links to non-existent notes, all link kinds) | {len(ghosts)} |\n"
             f"| Ghost targets outside ignored prefixes {list(a.ignore_prefix) or ''} | {ghosts_counted} |\n"
             f"| Links to a missing heading/block (bad_fragment) | {status_counts.get('bad_fragment', 0)} |\n"
             f"| Links pointing outside the vault | {status_counts.get('outside_vault', 0)} |\n"
             f"| Duplicate filenames (same name, different folders) | {len(dup_names)} |\n"
             f"| Exact duplicate contents | {len(dup_hash)} groups |\n")
    R.append("\n## Link resolution\n\n| Status | Count |\n|---|---|\n" +
             "".join(f"| {k} | {v} |\n" for k, v in status_counts.most_common()))
    R.append("\n`unresolved` = phantom node in Graph view. `ambiguous` = several notes share the name. "
             "`alias_only` = target matches an alias but no filename (Obsidian does not resolve this). "
             "`bad_fragment` = the note exists but the #heading or #^block does not. "
             "`fragment_unchecked` = target note was unreadable.\n")
    R.append(f"\n## Ghost targets (top {top})\n\n| Target | Refs | From notes | Kinds | Ignored prefix |\n|---|---|---|---|---|\n" +
             "".join(f"| {g['display']} | {g['refs']} | {len(g['sources'])} | "
                     f"{' '.join(f'{k}:{v}' for k, v in sorted(g['kinds'].items()))} | {'yes' if g['ignored'] else 'no'} |\n"
                     for g in ghost_rows[:top]))
    sugg = [l for l in links if l.get("suggest")]
    if sugg:
        R.append(f"\n## Broken explicit paths with a same-name note elsewhere ({len(sugg)})\n\n" +
                 "".join(f"- {l['source']}: `{l['target']}` -> maybe {', '.join(l['suggest'][:3])}\n" for l in sugg[:top]))
    hubs = sorted(notes.values(), key=lambda n: -n["in"])[:top]
    R.append(f"\n## Hubs by backlinks (top {top})\n\n| Note | In | Out | Words | Frontmatter |\n|---|---|---|---|---|\n" +
             "".join(f"| {n['path']} | {n['in']} | {n['out']} | {n.get('words',0)} | {'yes' if n.get('has_frontmatter') else 'no'} |\n"
                     for n in hubs if n["in"] > 0))
    bad = [n for n in notes.values() if {"untitled_or_generic", "numeric_title", "very_short_title"} & set(n.get("flags", []))]
    R.append(f"\n## Bad titles ({len(bad)})\n\n" + "".join(f"- {n['path']} ({n.get('words',0)} words)\n" for n in bad[:top]))
    R.append(f"\n## Duplicate filenames ({len(dup_names)})\n\n" +
             "".join(f"- `{k}`: " + ", ".join(v) + "\n" for k, v in list(sorted(dup_names.items()))[:top]))
    R.append(f"\n## Exact duplicate contents ({len(dup_hash)} groups)\n\n" +
             "".join("- " + ", ".join(v) + "\n" for v in list(dup_hash.values())[:top]))
    R.append(f"\n## Frontmatter keys in use\n\n" + "".join(f"- {k}: {v}\n" for k, v in fm_keys.most_common(top)))
    R.append(f"\n## External link hosts (top {top})\n\n" + "".join(f"- {h}: {c}\n" for h, c in ext_hosts.most_common(top)))
    folders = Counter(rel.split("/", 1)[0] if "/" in rel else "(root)" for rel in notes)
    R.append("\n## Notes per top-level folder\n\n" + "".join(f"- {k}: {v}\n" for k, v in folders.most_common()))
    if errors:
        R.append("\n## Read errors\n\n" + "".join(f"- {r}: {e}\n" for r, e in errors[:top]))
    with open(os.path.join(out, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(R))
    print(f"notes={N} attachments={len(attachments)} links={len(links)} ghosts={len(ghosts)} "
          f"ghosts_counted={ghosts_counted} bad_fragments={status_counts.get('bad_fragment', 0)} "
          f"ambiguous_links={ambiguous_links} dup_names={len(dup_names)} "
          f"orphans={flag_counts['orphan']} errors={len(errors)} -> {out}")


if __name__ == "__main__":
    main()
