#!/usr/bin/env python3
"""
segment.py — split every note of a vault into blocks with exact line ranges. Read-only.

A block is the smallest unit that keeps its meaning: frontmatter, heading, paragraph,
one list item (with its continuation lines), table, code fence, quote/callout, rule.
Every non-blank line belongs to exactly one block; blank lines are counted as separators.
That is what lets the cleanup prove that EVERY line went somewhere (see coverage_check.py).

Block ids are content-based (path + normalized text + occurrence), so they stay the same
when unrelated lines are added elsewhere in the note.

Usage:
    python3 -I segment.py --vault "<vault or snapshot>" --out "<folder outside it>" [--with-text]
Outputs (in --out):
    blocks.jsonl         one record per block (no body text unless --with-text)
    segment_notes.jsonl  per note: total lines, blank lines, block lines, coverage_ok
    duplicates.csv       identical blocks (normalized) found in more than one place
Exit code 1 if any note's lines are not fully covered (a bug guard; expected 0).
"""
import argparse, csv, hashlib, json, os, re, sys
from collections import defaultdict

SKIP_DIRS = {".obsidian", ".trash", ".git", "node_modules", ".venv", "__pycache__", ".smart-env", ".makemd"}
RE_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
RE_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
RE_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
RE_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
RE_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
RE_DATE = re.compile(r"\b(?:19|20)\d\d-[01]\d-[0-3]\d\b")
RE_WIKI = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")


def norm_text(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def loose_text(s):
    s = re.sub(r"^\s*([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?", "", s, flags=re.M)
    return re.sub(r"[\W_]+", " ", s.lower()).strip()


def split_lines(text):
    lines = text.split("\n")
    if text.endswith("\n"):
        lines = lines[:-1]
    return [l[:-1] if l.endswith("\r") else l for l in lines]


def segment(lines):
    """Return list of (kind, start, end, extra) with 1-based inclusive line numbers, and blank count."""
    blocks, blank, n, i = [], 0, len(lines), 0
    if n and lines[0].strip() == "---":
        for j in range(1, n):
            if lines[j].strip() in ("---", "..."):
                blocks.append(["frontmatter", 1, j + 1, {}])
                i = j + 1
                break
    cur = None  # open block that can take more lines: paragraph | list_item | table | quote

    def close():
        nonlocal cur
        if cur:
            blocks.append(cur)
        cur = None

    while i < n:
        line, ln = lines[i], i + 1
        s = line.strip()
        if not s:
            close(); blank += 1; i += 1; continue
        m = RE_FENCE.match(line)
        if m:
            close()
            mark = m.group(1)
            j = i + 1
            while j < n and not re.match(r"^\s{0,3}" + re.escape(mark[0]) + "{" + str(len(mark)) + r",}\s*$", lines[j]):
                j += 1
            end = min(j, n - 1)
            blocks.append(["code", ln, end + 1, {}])
            i = end + 1
            continue
        if cur and cur[0] == "paragraph" and cur[1] == cur[2] and RE_SETEXT.match(line) and not RE_LIST.match(line):
            cur[0], cur[2] = "heading", ln  # setext heading: "Title" + "===" / "---"
            close(); i += 1; continue
        hm = RE_HEADING.match(line)
        if hm:
            close(); blocks.append(["heading", ln, ln, {"level": len(hm.group(1)), "title": hm.group(2)}]); i += 1; continue
        if RE_RULE.match(line):
            close(); blocks.append(["rule", ln, ln, {}]); i += 1; continue
        if s.startswith("|"):
            if not (cur and cur[0] == "table"):
                close(); cur = ["table", ln, ln, {}]
            else:
                cur[2] = ln
            i += 1; continue
        if s.startswith(">"):
            if not (cur and cur[0] == "quote"):
                close(); cur = ["quote", ln, ln, {}]
            else:
                cur[2] = ln
            i += 1; continue
        lm = RE_LIST.match(line)
        if lm:
            close(); cur = ["list_item", ln, ln, {"indent": len(lm.group(1).expandtabs(4))}]; i += 1; continue
        if cur and cur[0] in ("paragraph", "list_item"):
            cur[2] = ln  # continuation (indented or lazy) line
        else:
            close(); cur = ["paragraph", ln, ln, {}]
        i += 1
    close()
    return blocks, blank


def walk(vault):
    for root, dirs, files in os.walk(vault, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not os.path.islink(os.path.join(root, d)))
        for f in sorted(files):
            p = os.path.join(root, f)
            if f.lower().endswith(".md") and not os.path.islink(p):
                yield p


def main():
    ap = argparse.ArgumentParser(description="Split notes into line-ranged blocks (read-only)")
    ap.add_argument("--vault", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-text", action="store_true", help="include block text in blocks.jsonl")
    a = ap.parse_args()
    vault = os.path.realpath(os.path.expanduser(a.vault))
    out = os.path.realpath(os.path.expanduser(a.out))
    if not os.path.isdir(vault):
        sys.exit(f"vault not found: {vault}")
    if out == vault or out.startswith(vault + os.sep):
        sys.exit("refusing: --out must be outside the vault (read-only)")
    os.makedirs(out, exist_ok=True)

    dup = defaultdict(list)
    totals = {"notes": 0, "blocks": 0, "lines": 0, "blank": 0, "uncovered_notes": 0, "unreadable": 0}
    with open(os.path.join(out, "blocks.jsonl"), "w", encoding="utf-8") as fb, \
         open(os.path.join(out, "segment_notes.jsonl"), "w", encoding="utf-8") as fn:
        for p in walk(vault):
            rel = os.path.relpath(p, vault).replace(os.sep, "/")
            try:
                with open(p, "rb") as fh:
                    raw = fh.read()
            except OSError as e:
                totals["unreadable"] += 1
                fn.write(json.dumps({"path": rel, "error": str(e)}, ensure_ascii=False) + "\n")
                continue
            text = raw.decode("utf-8", errors="replace")
            lines = split_lines(text)
            blocks, blank = segment(lines)
            heading_path, seen = [], defaultdict(int)
            covered = 0
            for kind, start, end, extra in blocks:
                body = "\n".join(lines[start - 1:end])
                parents = [h[1] for h in heading_path]
                if kind == "heading":
                    lvl = extra.get("level") or (1 if lines[end - 1].strip().startswith("=") else 2)
                    title = extra.get("title") or lines[start - 1].strip()
                    kept = [h for h in heading_path if h[0] < lvl]
                    parents = [h[1] for h in kept]
                    heading_path = kept + [(lvl, title)]
                nt = norm_text(body)
                seen[nt] += 1
                bid = "b" + hashlib.sha1(f"{rel}\0{nt}\0{seen[nt]}".encode("utf-8")).hexdigest()[:12]
                rec = {"block_id": bid, "path": rel, "line_start": start, "line_end": end, "kind": kind,
                       "heading_path": parents,
                       "chars": len(body), "text_sha256": hashlib.sha256(nt.encode("utf-8")).hexdigest(),
                       "dates": sorted(set(RE_DATE.findall(body))),
                       "wikilinks": [t.split("|", 1)[0] for t in RE_WIKI.findall(body)]}
                if "indent" in extra:
                    rec["indent"] = extra["indent"]
                if a.with_text:
                    rec["text"] = body
                fb.write(json.dumps(rec, ensure_ascii=False) + "\n")
                lt = loose_text(body)
                if kind not in ("heading", "rule", "frontmatter") and len(lt) >= 12:
                    dup[hashlib.sha256(lt.encode("utf-8")).hexdigest()].append((rel, start, end))
                covered += end - start + 1
            ok = covered + blank == len(lines)
            totals["notes"] += 1; totals["blocks"] += len(blocks); totals["lines"] += len(lines); totals["blank"] += blank
            totals["uncovered_notes"] += 0 if ok else 1
            fn.write(json.dumps({"path": rel, "lines": len(lines), "blank": blank, "block_lines": covered,
                                 "blocks": len(blocks), "coverage_ok": ok,
                                 "sha256": hashlib.sha256(raw).hexdigest()}, ensure_ascii=False) + "\n")
    groups = [v for v in dup.values() if len(v) > 1]
    with open(os.path.join(out, "duplicates.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["copies", "locations"])
        for g in sorted(groups, key=lambda g: -len(g)):
            w.writerow([len(g), " | ".join(f"{r}:{s}-{e}" for r, s, e in g[:20])])
    totals["duplicate_groups"] = len(groups)
    totals["duplicate_extra_copies"] = sum(len(g) - 1 for g in groups)
    print(json.dumps(totals))
    sys.exit(1 if totals["uncovered_notes"] else 0)


if __name__ == "__main__":
    main()
