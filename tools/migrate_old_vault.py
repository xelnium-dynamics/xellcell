#!/usr/bin/env python3
"""
migrate_old_vault.py — builds the clean brain vault from the old Obsidian vault SNAPSHOT (raw/, read-only).

Re-runnable and non-destructive: it writes a fresh staging folder; nothing in raw/ or the live vault (Brain System/) is touched.

    python3 -I migrate_old_vault.py --snapshot raw/obsidian-vault/2026-11-08 \
        --config state/migration-config-2026-11-08.json --base-vault vault --out state/migration-staging/<run>

Outputs in --out: vault/ (copy of the base vault + migrated notes), segments/ (segment.py output),
plan.csv (every block: place | raw_only + target/reason, for coverage_check.py), link-log.csv, report.md.

Rules (config): folder rules + per-note overrides decide place / raw_only / split / blocks / verbatim.
Blocks with a disallowed script (Chinese, Japanese, Korean, Cyrillic, Turkish letters, ...) or matching a
drop rule stay only in raw/ (logged, an HTML comment marks the spot). Text is kept verbatim; only links change:
links to placed notes are rewritten to their new unique names, links to retired notes go to a redirect or
become plain text, ghost links are repaired only when exactly one note has that name. Nothing is guessed.
"""
import argparse, csv, hashlib, json, os, re, shutil, subprocess, sys
from collections import defaultdict
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import brainlib as B  # noqa: E402

RE_WIKI = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
RE_MD = re.compile(r"(!?)\[([^\]\n]*)\]\((?:<([^>\n]+)>|([^)\s]+))(\s+\"[^\"]*\")?\)")
RE_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
RE_INLINE = re.compile(r"(`[^`\n]*`)")
RE_DATE = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*\s*)?(20\d\d-\d\d-\d\d)")
SKIP = {".obsidian", ".trash", ".git", "__pycache__"}


def is_external(t):
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:", t))


def norm(s):
    return s.strip().replace("\\", "/").lower()


class Migrator:
    def __init__(self, snap, cfg, base_vault, out, decisions=None):
        self.snap, self.cfg, self.out = snap, cfg, out
        self.dec = decisions or {}
        for rel, why in self.dec.get("note_raw_only", {}).items():
            red = {"redirect_to_old": "02 GitHub Library/Repo Index.md"} if "Repo Index (UI)" in rel else {"redirect": "toc-domains"}
            self.cfg["overrides"][rel] = dict({"action": "raw_only", "reason": why}, **red)
        for line, bucket in self.dec.get("entry_overrides", {}).items():
            for sc in self.cfg.get("split", {}).values():
                sc["entry_overrides"][line] = bucket
        self.vault = os.path.join(out, "vault")
        self.src_root = cfg["snapshot_rel"]
        self.plan, self.linklog, self.report = [], [], defaultdict(int)
        self.anchors = None
        self.scripts = {k: re.compile(v) for k, v in cfg.get("disallowed_scripts", {}).items()}
        shutil.copytree(base_vault, self.vault, ignore=shutil.ignore_patterns(".obsidian", ".DS_Store"))
        self.load_snapshot()
        self.blocks = self.segment()
        self.section_drop = {}
        for rel, bl in self.blocks.items():
            cur = None
            for b in bl:
                if b["kind"] == "heading":
                    lvl = len(b["text"]) - len(b["text"].lstrip("#"))
                    if cur and lvl <= cur[1]:
                        cur = None
                    if b["block_id"] in self.dec.get("drop_sections", {}):
                        cur = (self.dec["drop_sections"][b["block_id"]], lvl)
                if cur:
                    self.section_drop[b["block_id"]] = cur[0]

    # ---------- inputs ----------
    def load_snapshot(self):
        self.notes, self.attachments = [], []
        for d, dirs, files in os.walk(self.snap):
            dirs[:] = sorted(x for x in dirs if x not in SKIP)
            for f in sorted(files):
                if f == ".DS_Store":
                    continue
                rel = os.path.relpath(os.path.join(d, f), self.snap).replace(os.sep, "/")
                (self.notes if f.endswith(".md") else self.attachments).append(rel)
        self.by_path, self.by_base, self.alias = {}, defaultdict(list), defaultdict(list)
        for rel in self.notes + self.attachments:
            self.by_path[norm(rel)] = rel
            base = rel.rsplit("/", 1)[-1]
            self.by_base[norm(base)].append(rel)
            if rel.endswith(".md"):
                self.by_path[norm(rel[:-3])] = rel
                self.by_base[norm(base[:-3])].append(rel)
        self.text = {}
        for rel in self.notes:
            with open(os.path.join(self.snap, rel), encoding="utf-8", errors="replace") as fh:
                self.text[rel] = fh.read()
            fm, _ = B.split_frontmatter(self.text[rel])
            if fm is not None:
                for al in B.parse_frontmatter(fm).get("aliases", []) or []:
                    if isinstance(al, str):
                        self.alias[norm(al)].append(rel)

    def segment(self):
        segdir = os.path.join(self.out, "segments")
        p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "segment.py"), "--vault", self.snap, "--out", segdir, "--with-text"],
                           capture_output=True, text=True)
        if p.returncode != 0:
            sys.exit("segment.py failed: " + p.stdout + p.stderr)
        blocks = defaultdict(list)
        with open(os.path.join(segdir, "blocks.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                b = json.loads(line)
                blocks[b["path"]].append(b)
        for v in blocks.values():
            v.sort(key=lambda b: b["line_start"])
        return blocks

    # ---------- decisions ----------
    def decide(self, rel):
        o = self.cfg["overrides"].get(rel)
        if o:
            return dict(o)
        best = None
        for r in self.cfg["folder_rules"]:
            if rel.startswith(r["prefix"]) and (best is None or len(r["prefix"]) > len(best["prefix"])):
                best = r
        if best:
            return dict(best)
        if rel.startswith("06 Brain & Knowledge/"):
            return dict(self.cfg["default_06"])
        return {"action": "raw_only", "reason": "not classified by any rule (review)"}

    def plan_names(self):
        used = set()
        for p in B.iter_notes(self.vault):
            used.add(os.path.splitext(os.path.basename(p))[0].lower())
        used |= {"toc-home", "toc-projects", "toc-domains", "toc-capabilities", "toc-self", "toc-history", "toc-system",
                 "toc-drawings", "toc-problems", "toc-lessons", "skills-registry", "history-index", "identity"}
        self.used = used
        self.spec, self.newstem, self.newrel = {}, {}, {}
        for rel in self.notes:
            s = self.decide(rel)
            self.spec[rel] = s
            if s["action"] not in ("place", "verbatim"):
                continue
            old_stem = rel.rsplit("/", 1)[-1][:-3]
            stem = s.get("name") or (s.get("name_prefix", "") + old_stem)
            stem = self.unique(stem, s["collection"])
            self.newstem[rel] = stem
            self.newrel[rel] = f"{s['collection']}/{stem}.md"
            if stem != old_stem:
                self.report["renamed"] += 1
                self.linklog.append({"source": rel, "target": old_stem, "outcome": "renamed", "new": stem, "reason": "name clash or prefix"})

    @staticmethod
    def safe(stem):
        """Obsidian/macOS-safe filename: no : / \\ ? * < > | " # ^ [ ]"""
        s = re.sub(r'[\\/:*?"<>|#^\[\]]', " - ", stem)
        return re.sub(r"\s+", " ", s).replace(" - - ", " - ").strip(" -") or "untitled"

    def unique(self, stem, collection):
        stem = self.safe(stem)
        cand, n = stem, 2
        if cand.lower() in self.used:
            cand = f"{stem} ({collection.rsplit('/', 1)[-1]})"
        while cand.lower() in self.used:
            cand = f"{stem} ({n})"
            n += 1
        self.used.add(cand.lower())
        return cand

    # ---------- links ----------
    def resolve(self, target, src):
        t = unquote(target.split("#", 1)[0]).strip().rstrip("\\")
        if not t:
            return "self", None
        if os.path.isabs(t):
            return "unresolved", None
        nt = norm(t)
        if nt in self.by_path:
            return "resolved", self.by_path[nt]
        rp = norm(os.path.normpath(os.path.join(os.path.dirname(src), t)).replace(os.sep, "/"))
        if rp in self.by_path:
            return "resolved", self.by_path[rp]
        base = nt.rsplit("/", 1)[-1]
        cands = self.by_base.get(base, [])
        if "/" in nt:
            cands = [c for c in cands if norm(c).endswith("/" + nt) or norm(c).endswith("/" + nt + ".md") or norm(c) in (nt, nt + ".md")]
        if len(cands) == 1:
            return "resolved", cands[0]
        if len(cands) > 1:
            return "ambiguous", cands
        if nt in self.alias and len(self.alias[nt]) == 1:
            return "resolved", self.alias[nt][0]
        return "unresolved", None

    def redirect_for(self, dest):
        s = self.spec.get(dest, {})
        if s.get("redirect"):
            return s["redirect"]
        if s.get("redirect_to_old"):
            return self.newstem.get(s["redirect_to_old"])
        stem = dest.rsplit("/", 1)[-1][:-3].lower() if dest.endswith(".md") else None
        return self.cfg.get("name_redirects", {}).get(stem)

    def outcome(self, target, src):
        status, dest = self.resolve(target, src)
        name = norm(unquote(target.split("#", 1)[0])).rsplit("/", 1)[-1]
        name = name[:-3] if name.endswith(".md") else name
        if status == "self":
            return ("self",)
        if status == "ambiguous":
            r = self.cfg.get("name_redirects", {}).get(name)
            if r:
                return ("note", r, False, "redirect (ambiguous name)")
            placed = {self.newstem[c] for c in dest if c in self.newstem}
            if len(placed) == 1:
                return ("note", placed.pop(), True, "ambiguous; only one candidate was kept")
            return ("unlink", "ambiguous target")
        if status == "unresolved":
            r = self.cfg.get("name_redirects", {}).get(name)
            if r:
                return ("note", r, False, "redirect (name)")
            cands = self.by_base.get(norm(name), []) + self.by_base.get(norm(name) + ".md", [])
            cands = sorted(set(cands))
            if len(cands) == 1:
                status, dest = "resolved", cands[0]
                why = "repaired broken path to the only note with this name"
            else:
                return ("unlink", "ghost link (no such note)")
        else:
            why = None
        if not dest.endswith(".md"):
            return ("attach", self.copy_attachment(dest), why or "attachment")
        if dest in self.newstem:
            return ("note", self.newstem[dest], True, why or "moved")
        r = self.redirect_for(dest)
        if r:
            return ("note", r, False, f"redirect ({self.spec.get(dest, {}).get('action', '?')} target)")
        return ("unlink", "target kept only in raw: " + self.spec.get(dest, {}).get("reason", "retired"))

    def copy_attachment(self, rel):
        if not hasattr(self, "att"):
            self.att = {}
        if rel in self.att:
            return self.att[rel]
        name = rel.rsplit("/", 1)[-1]
        stem, ext = os.path.splitext(name)
        dst_dir = os.path.join(self.vault, "_attachments")
        os.makedirs(dst_dir, exist_ok=True)
        cand, n = name, 2
        while os.path.exists(os.path.join(dst_dir, cand)) or cand.lower() in self.used:
            cand = f"{stem} ({n}){ext}"
            n += 1
        shutil.copy2(os.path.join(self.snap, rel), os.path.join(dst_dir, cand))
        self.used.add(cand.lower())
        self.att[rel] = cand
        self.report["attachments copied"] += 1
        return cand

    def anchor_ok(self, frag):
        if self.anchors is None:
            return True
        frag = unquote(frag).strip()
        if frag.startswith("^"):
            return True
        key = re.sub(r"\s+", " ", frag).lower()
        slug = re.sub(r"[^\w\- ]", "", frag.lower()).replace(" ", "-")
        return key in self.anchors or slug in self.anchors

    def rewrite_part(self, s, src):
        def wiki(m):
            bang, inner = m.group(1), m.group(2)
            esc = "\\|" in inner
            parts = re.split(r"\\?\|", inner, maxsplit=1)
            target, alias = parts[0], (parts[1] if len(parts) > 1 else None)
            o = self.outcome(target, src)
            frag = target.split("#", 1)[1] if "#" in target else ""
            shown = alias if alias is not None else unquote(target.split("#", 1)[0]).rsplit("/", 1)[-1] or target
            pipe = "\\|" if esc else "|"
            if o[0] == "self":
                if target.startswith("#") and not self.anchor_ok(target[1:]):
                    self.log(src, target, "unlinked", "", "dead in-page anchor")
                    return alias if alias is not None else target[1:]
                return m.group(0)
            if o[0] == "unlink":
                self.log(src, target, "unlinked", "", o[1])
                return alias if alias is not None else unquote(target).replace("#", " › ")
            if o[0] == "attach":
                self.log(src, target, "attachment", o[1], o[2])
                return f"{bang}[[{o[1]}{pipe}{alias}]]" if alias is not None else f"{bang}[[{o[1]}]]"
            stem, keep_frag, why = o[1], o[2], o[3]
            link = f"{stem}#{frag}" if (keep_frag and frag) else stem
            if why != "moved" or link != target:
                self.log(src, target, "rewritten", link, why)
            if alias is None and shown == stem and not frag:
                return f"{bang}[[{link}]]"
            return f"{bang}[[{link}{pipe}{shown if alias is None else alias}]]"

        def md(m):
            bang, label, angle, plain, title = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            target = angle or plain
            if target.startswith("#"):
                if not self.anchor_ok(target[1:]):
                    self.log(src, target, "unlinked", "", "dead in-page anchor")
                    return label
                return m.group(0)
            if is_external(target):
                return m.group(0)
            o = self.outcome(target, src)
            if o[0] == "self":
                return m.group(0)
            if o[0] == "unlink":
                self.log(src, target, "unlinked", "", o[1])
                return label
            if o[0] == "attach":
                self.log(src, target, "attachment", o[1], o[2])
                return f"![[{o[1]}]]" if bang else f"[[{o[1]}|{label}]]"
            self.log(src, target, "rewritten", o[1], o[3])
            return f"[[{o[1]}|{label}]]" if label else f"[[{o[1]}]]"

        s = RE_WIKI.sub(wiki, s)
        return RE_MD.sub(md, s)

    def rewrite(self, text, src, anchors=None):
        self.anchors = anchors
        out, fence = [], None
        for line in text.split("\n"):
            m = RE_FENCE.match(line)
            if fence:
                out.append(line)
                if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                    fence = None
                continue
            if m:
                fence = m.group(1)
                out.append(line)
                continue
            parts = RE_INLINE.split(line)
            out.append("".join(p if i % 2 else self.rewrite_part(p, src) for i, p in enumerate(parts)))
        return "\n".join(out)

    def log(self, src, target, outcome, new, reason):
        self.report[f"links {outcome}"] += 1
        self.linklog.append({"source": src, "target": target, "outcome": outcome, "new": new, "reason": reason})

    # ---------- block filters ----------
    def drop_reason(self, rel, b):
        if b["block_id"] in self.dec.get("drop_block_ids", {}):
            return self.dec["drop_block_ids"][b["block_id"]]
        if b["block_id"] in self.section_drop:
            return self.section_drop[b["block_id"]]
        for name, rx in self.scripts.items():
            if rx.search(b["text"]):
                return f"text in {name}; kept only in the evidence copy (disallowed by the migration config)"
        for d in self.cfg.get("drop_blocks", []):
            if d["path"] == rel and d["contains"] in b["text"]:
                return d["reason"]
        return None

    def add_plan(self, b, action, target="", reason=""):
        self.plan.append({"block_id": b["block_id"], "action": action, "target": target, "reason": reason})
        self.report[f"blocks {action}"] += 1

    # ---------- writers ----------
    @staticmethod
    def yaml(d):
        out = ["---"]
        for k, v in d.items():
            if v is None or v == [] or v == "":
                continue
            if k == "legacy_frontmatter":
                out.append("legacy_frontmatter: |")
                out += ["  " + ln for ln in v.split("\n")]
            else:
                out.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
        out.append("---")
        return "\n".join(out)

    @staticmethod
    def summary_of(lines):
        for ln in lines:
            s = ln.strip()
            if not s or s.startswith(("#", "```", "~~~", "|", "<!--", "---")) or re.fullmatch(r"[-*_=\s]+", s):
                continue
            s = re.sub(r"^>\s*(\[![^\]]+\][+-]?\s*)?", "", s)
            s = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
            s = re.sub(r"[*_`]+", "", s).strip()
            s = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", s)
            if len(s.split()) >= 3:
                return s[:160]
        return ""

    def write_note(self, rel_target, text):
        p = os.path.join(self.vault, rel_target)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "x", encoding="utf-8") as fh:
            fh.write(text)

    def project_of(self, collection):
        return collection.split("/", 1)[1].split("/")[0] if collection.startswith("projects/") else None

    def place_note(self, rel):
        s, text = self.spec[rel], self.text[rel]
        lines = text.split("\n")
        if text.endswith("\n"):
            lines = lines[:-1]
        blocks = self.blocks.get(rel, [])
        drop = {}
        for b in blocks:
            r = self.drop_reason(rel, b)
            if r and b["kind"] != "frontmatter":
                drop[b["line_start"]] = (b, r)
        fm, _ = B.split_frontmatter(text)
        fm_lines = (fm.count("\n") + 3) if fm is not None else 0
        old = B.parse_frontmatter(fm) if fm is not None else {}
        body = []
        i = fm_lines
        while i < len(lines):
            if (i + 1) in drop:
                b, r = drop[i + 1]
                body.append(f"<!-- L{b['line_start']}-L{b['line_end']} kept only in raw/ (reason: reports/migration-2026-11-08/plan.csv) -->")
                i = b["line_end"]
                continue
            body.append(lines[i])
            i += 1
        heads = set()
        for ln in body:
            hm = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", ln)
            if hm:
                t = hm.group(1)
                heads.add(re.sub(r"\s+", " ", t).lower())
                heads.add(re.sub(r"[^\w\- ]", "", t.lower()).replace(" ", "-"))
        body_text = self.rewrite("\n".join(body), rel, anchors=heads)
        h1 = next((ln[2:].strip() for ln in lines[fm_lines:] if ln.startswith("# ")), None)
        old_stem = rel.rsplit("/", 1)[-1][:-3]
        stem = self.newstem[rel]
        aliases = [a for a in (old.get("aliases") or []) if isinstance(a, str)]
        if stem != old_stem and old_stem not in aliases:
            aliases.append(old_stem)
        tags = old.get("tags") if isinstance(old.get("tags"), list) else ([old["tags"]] if isinstance(old.get("tags"), str) and old.get("tags") else [])
        coll = s["collection"]
        top = coll.split("/")[0]
        meta = {"title": s.get("name") or h1 or stem, "type": s.get("type", {"projects": "project-note", "domains": "knowledge", "self": "profile",
                                                          "capabilities": "capability", "system": "rules", "history": "log"}.get(top, "note")),
                "collection": coll, "project": self.project_of(coll),
                "scope": {"self": "self", "projects": "project", "domains": "domain", "history": "project"}.get(top, "general"),
                "authority": "legacy", "summary": self.summary_of(body), "sources": [f"{self.src_root}/{rel}#L1-L{len(lines)}"],
                "aliases": aliases, "tags": tags, "migrated": self.cfg["migrated"], "updated": self.cfg["migrated"],
                "legacy_frontmatter": fm}
        note = self.yaml(meta) + "\n" + body_text.rstrip("\n") + (
            f"\n\n---\n*Migrated {self.cfg['migrated']} from* `{self.src_root}/{rel}` *(lines 1–{len(lines)}; text verbatim, links updated)*\n")
        self.write_note(self.newrel[rel], note)
        for b in blocks:
            if b["line_start"] in drop:
                self.add_plan(b, "raw_only", reason=drop[b["line_start"]][1])
            else:
                self.add_plan(b, "place", self.newrel[rel])
        self.report["notes placed"] += 1

    def verbatim(self, rel):
        dst = os.path.join(self.vault, self.newrel[rel])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(self.snap, rel), dst)
        for b in self.blocks.get(rel, []):
            self.add_plan(b, "place", self.newrel[rel])
        self.report["notes copied verbatim"] += 1

    def raw_only(self, rel):
        r = self.spec[rel].get("reason", "retired")
        for b in self.blocks.get(rel, []):
            self.add_plan(b, "raw_only", reason=r)
        self.report["notes kept only in raw"] += 1

    def split(self, rel):
        sc = self.cfg["split"][rel]
        rules = [(name, re.compile(rx, re.I)) for name, rx in sc["rules"]]
        names = self.cfg["projects"]
        buckets = defaultdict(list)
        for b in self.blocks.get(rel, []):
            r = self.drop_reason(rel, b)
            m = RE_DATE.match(b["text"])
            if r:
                self.add_plan(b, "raw_only", reason=r)
                continue
            if not m:
                self.add_plan(b, "raw_only", reason=sc["structural_reason"])
                continue
            bucket = sc["entry_overrides"].get(str(b["line_start"]))
            if not bucket:
                t = b["text"].lower()
                ti = self.entry_title(b["text"]).lower()
                bucket = self.first_mention(rules, ti) or self.first_mention(rules, t) or "general"
            if bucket == "HERMES":
                self.add_plan(b, "raw_only", reason=sc["hermes_reason"])
                continue
            buckets[bucket].append((m.group(1), b))
        self.history_notes = []
        for bucket, items in sorted(buckets.items()):
            disp = names.get(bucket, bucket)
            in_history = bucket in sc["history_buckets"]
            coll = "history" if in_history else f"projects/{bucket}"
            stem = self.unique(f"{disp} - history", coll)
            target = f"{coll}/{stem}.md"
            items.sort(key=lambda x: x[0], reverse=True)
            entries = []
            for _, b in items:
                txt = self.rewrite(b["text"].rstrip(), rel)
                entries.append(f"{txt} [L{b['line_start']}–{b['line_end']}]")
                self.add_plan(b, "place", target)
            meta = {"title": f"{disp} — history", "type": "history", "collection": coll,
                    "project": None if in_history else bucket, "scope": "project", "authority": "legacy",
                    "summary": f"{len(items)} dated entries from the old Current State page, newest first",
                    "sources": [f"{self.src_root}/{rel}"], "migrated": self.cfg["migrated"], "updated": self.cfg["migrated"]}
            body = [f"# {disp} — history", "",
                    f"Dated entries moved from the old Current State page, newest first. Source: `{self.src_root}/{rel}`; the line numbers are in brackets.", ""]
            self.write_note(target, self.yaml(meta) + "\n" + "\n".join(body + entries) + "\n")
            self.history_notes.append((stem, coll, len(items)))
            self.report["history notes"] += 1

    @staticmethod
    def first_mention(rules, text):
        """The project named first in the text wins; rule order only breaks exact ties."""
        best = None
        for order, (name, rx) in enumerate(rules):
            m = rx.search(text) if text else None
            if m and (best is None or (m.start(), order) < best[0]):
                best = ((m.start(), order), name)
        return best[1] if best else None

    @staticmethod
    def entry_title(text):
        """The subject of a dated entry: its first bold text, else the text after the agent name."""
        m = re.search(r"\*\*(.+?)\*\*", text)
        if m:
            return m.group(1)
        m = re.match(r"^\s*(?:[-*+]\s+)?20\d\d-\d\d-\d\d[^(\n]*(?:\(([^)]*)\))?\s*[\u2014:-]*\s*(.*)", text)
        if not m:
            return ""
        paren, rest = (m.group(1) or "").strip(), m.group(2) or ""
        if "\u2014" in paren:
            return paren.split("\u2014", 1)[1]
        if paren.lower() in ("claude", "codex", "hermes", "claude code", "xelnium-agent"):
            return re.split(r"[:.]", rest, maxsplit=1)[0][:120]
        return paren or rest[:120]

    def blocks_action(self, rel):
        bc = self.cfg["blocks"][rel]
        targets = defaultdict(list)
        for b in self.blocks.get(rel, []):
            r = self.drop_reason(rel, b)
            sel = None if r else next((s for s in bc["selectors"] if s["contains"] in b["text"]), None)
            if sel:
                targets[(sel["target"], sel["section"])].append(b)
                self.add_plan(b, "place", sel["target"])
            else:
                self.add_plan(b, "raw_only", reason=r or bc["reason"])
        self.extra_sections = targets

    # ---------- new notes ----------
    def new_notes(self):
        src = f"{self.src_root}/CLAUDE.md"
        made = defaultdict(list)
        for (target, section), blocks in getattr(self, "extra_sections", {}).items():
            made[target].append((section, blocks))
        ident = "self/identity.md"
        if ident not in made:
            made[ident] = []
        for target, sections in sorted(made.items()):
            stem = target.rsplit("/", 1)[-1][:-3]
            if target == ident:
                meta = {"title": "Identity", "type": "identity", "collection": "self", "scope": "self",
                        "authority": "owner-decision", "summary": "One person, three names: The owner, Al and Lex (D-016)",
                        "aliases": ["the owner", "Al", "Lex"], "updated": self.cfg["migrated"]}
                body = ["# Identity", "", "## Names (the owner, 2026-11-08)",
                        "the owner, Al and Lex are the same person. The owner confirmed this on 2026-11-08 (decision D-016). Treat them as one person.", ""]
            else:
                coll = target.rsplit("/", 1)[0]
                meta = {"title": stem, "type": "note", "collection": coll, "project": self.project_of(coll),
                        "scope": "project" if coll.startswith("projects") else "general", "authority": "legacy",
                        "summary": f"Taken from the old vault's rules: {', '.join(s for s, _ in sections)}",
                        "sources": [src], "updated": self.cfg["migrated"]}
                body = [f"# {stem}", ""]
            for section, blocks in sections:
                body += [f"## {section}", ""]
                body += [self.rewrite(b["text"].rstrip(), "CLAUDE.md") + f" [L{b['line_start']}–{b['line_end']}]" for b in blocks]
                body += ["", f"Source: `{src}` (legacy, not re-verified)", ""]
            self.write_note(target, self.yaml(meta) + "\n" + "\n".join(body).rstrip() + "\n")
            self.report["new notes"] += 1
        ecc = os.path.expanduser("~/.codex/ecc/local-2.1.0-2026-10-01")
        meta = {"title": "ECC library (Codex package)", "type": "capability", "collection": "capabilities", "scope": "general",
                "authority": "sourced-fact", "summary": "Where the ECC skill and agent library lives and how to use it, instead of the vault copy",
                "sources": [f"{self.src_root}/03 Agent Ops/ECC - Codex Library/"], "updated": self.cfg["migrated"]}
        body = ["# ECC library (Codex package)", "",
                f"- **Where:** `{ecc.replace(os.path.expanduser('~'), '~')}` (installed for Codex; present on 2026-11-08: {'yes' if os.path.isdir(ecc) else 'no'}).",
                "- **What:** the ECC package: skills, agents, rules and docs (READMEs also in other languages).",
                "- **Why it is not in this vault:** the old vault held a copy (2,512 notes). On 2026-11-08, 2,489 of its Markdown files were byte-identical to the installed package, so the copy was kept only as evidence in raw/ and the package is the single source.",
                "- **Use:** search the brain with `tools/brain_route.py`; ECC skills under the package's `skills/` folder are listed in [[skills-registry]].", ""]
        self.write_note("capabilities/ECC library (Codex package).md", self.yaml(meta) + "\n" + "\n".join(body))
        hist = sorted(getattr(self, "history_notes", []), key=lambda x: (x[1], x[0].lower()))
        meta = {"title": "History index", "type": "toc", "collection": "history", "scope": "general", "authority": "generated",
                "summary": "Every history note made from the old Current State page, with entry counts",
                "sources": [f"{self.src_root}/04 Projects/Current State.md"], "updated": self.cfg["migrated"]}
        body = ["# History index", "", "The old Current State page was split by project. Each line below is one history note (newest entries first).", "",
                "| History | Entries |", "|---|---|"] + [f"| [[{stem}]] | {n} |" for stem, coll, n in hist]
        self.write_note("history/history-index.md", self.yaml(meta) + "\n" + "\n".join(body) + "\n")

    # ---------- run ----------
    def run(self):
        self.plan_names()
        for rel in self.notes:
            a = self.spec[rel]["action"]
            if a == "place":
                self.place_note(rel)
            elif a == "verbatim":
                self.verbatim(rel)
            elif a == "split":
                self.split(rel)
            elif a == "blocks":
                self.blocks_action(rel)
            else:
                self.raw_only(rel)
        self.new_notes()
        with open(os.path.join(self.out, "plan.csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["block_id", "action", "target", "reason"])
            w.writeheader()
            w.writerows(self.plan)
        with open(os.path.join(self.out, "link-log.csv"), "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["source", "target", "outcome", "new", "reason"])
            w.writeheader()
            w.writerows(self.linklog)
        rep = ["# Migration report", "", f"Snapshot: `{self.src_root}` · notes in snapshot: {len(self.notes)} · attachments: {len(self.attachments)}", "",
               "| Measure | Count |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(self.report.items())]
        with open(os.path.join(self.out, "report.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(rep) + "\n")
        return dict(self.report)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--base-vault", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--decisions")
    a = ap.parse_args()
    if os.path.exists(a.out):
        sys.exit(f"refusing: {a.out} exists (each run writes a fresh folder)")
    os.makedirs(a.out)
    cfg = json.load(open(a.config, encoding="utf-8"))
    dec = json.load(open(a.decisions, encoding="utf-8")) if a.decisions else None
    print(json.dumps(Migrator(os.path.realpath(a.snapshot), cfg, os.path.realpath(a.base_vault), os.path.realpath(a.out), dec).run(), indent=1))


if __name__ == "__main__":
    main()
