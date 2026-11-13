#!/usr/bin/env python3
"""
brain_index.py — builds the brain's retrieval index and table-of-contents views (layer 4).

- index/brain.db: SQLite full-text index (standard library) over every vault note (title, summary,
  headings, tags, aliases, excerpt) and over every skill Claude Code or Codex can use.
- Brain System/00-toc/*.md: generated views (home, projects, domains, capabilities, self, history, system,
  skills registry by category). Never edit them by hand; they are rewritten only when content changes.

Usage: python3 -I brain_index.py [--check]      (--check: report fresh/stale, change nothing)
Skill locations: state/skill-roots.json if present (or $BRAIN_SKILL_ROOTS), else the defaults below.
"""
import glob, hashlib, json, os, re, sqlite3, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

TOC = os.path.join(B.VAULT, "00-toc")
DEFAULT_ROOTS = [
    # The brain's own skill library: never auto-loaded; agents find these through brain_route and read them on demand.
    {"path": os.path.join(B.ROOT, "skills"), "agent": "Claude + Codex (brain library, on demand)", "kind": "brain-library", "autoload": "no"},
    {"path": "~/.claude/skills", "agent": "Claude", "kind": "claude-personal", "autoload": "yes"},
    {"plugins_json": "~/.claude/plugins/installed_plugins.json", "agent": "Claude", "kind": "claude-plugin", "autoload": "if plugin enabled"},
    {"glob": "~/.claude/plugins/synced/*/*", "agent": "Claude", "kind": "claude-synced-plugin", "autoload": "yes (synced from claude.ai)"},
    {"path": "~/.codex/skills", "agent": "Codex", "kind": "codex-personal", "autoload": "yes"},
    {"path": "~/.agents/skills", "agent": "Codex", "kind": "agents-shared", "autoload": "unverified"},
    {"path": "~/.codex/skills-library", "agent": "Claude + Codex (on demand)", "kind": "library", "autoload": "no"},
    {"glob": "~/.codex/plugins/cache/*/*", "agent": "Codex", "kind": "codex-plugin", "autoload": "if plugin enabled"},  # v2.1 (O7): local Codex plugin skills beat drive copies
    {"glob": "~/.codex/ecc/*/skills", "agent": "Codex (ECC package)", "kind": "ecc-package", "autoload": "no (absent from Codex's runtime skills/list, 2026-11-08)"},
]
CATEGORIES = [  # first match wins; keywords are matched as whole words in name + description
    ("career-documents", r"\b(cv|resume|cover letter|job|jobs|application|hiring|interview|career)\b"),
    ("brand-identity", r"\b(brand|branding|logo|identity|typography|typeface|font|palette|packaging|guidelines)\b"),
    ("3d-video-audio", r"\b(3d|blender|render|video|motion graphics|remotion|manim|audio|music|song|comfyui|meshy|animation video|image generation|imagegen)\b"),
    ("web-ui-motion", r"\b(web|website|html|css|react|next\.?js|tailwind|ui|ux|frontend|landing|component|gsap|three\.?js|webgl|shader|glsl|motion|animation|figma|design system|svg)\b"),
    ("documents-office", r"\b(pdf|docx|pptx|xlsx|slides|presentation|spreadsheet|document|documents|word|excel|report)\b"),
    ("research-data", r"\b(research|search|scrape|scraping|crawl|data|analysis|analytics|sql|dashboard|chart|statistics|arxiv|paper|papers)\b"),
    ("engineering-code", r"\b(code|coding|debug|test|tests|testing|git|github|deploy|api|python|javascript|typescript|refactor|security|review|bug|backend|database)\b"),
    ("agents-automation", r"\b(agent|agents|claude|codex|skill|skills|plugin|orchestration|workflow|memory|hook|hooks|automation|prompt|mcp|harness|subagent)\b"),
    ("marketing-sales", r"\b(marketing|seo|ads|campaign|sales|crm|email|outreach|social|newsletter|lead|leads)\b"),
    ("business-finance", r"\b(finance|financial|trading|trade|crypto|market|business|pricing|invoice|accounting)\b"),
    ("science-bio", r"\b(bio|biology|chemistry|clinical|pubmed|cell|genomics|drug|protein)\b"),
]


def skill_roots():
    p = os.environ.get("BRAIN_SKILL_ROOTS") or os.path.join(B.STATE, "skill-roots.json")
    return B.load_json(p, DEFAULT_ROOTS)


def find_skill_files(base):
    out = []
    for d, dirs, files in os.walk(base):
        dirs[:] = sorted(x for x in dirs if x not in (".trash", "node_modules", ".git", "__pycache__", "skills-figquery", ".in_use", "evals"))
        if "SKILL.md" in files:
            out.append(os.path.join(d, "SKILL.md"))
    # Prefer top-level brain skills before nested plugins/ paths
    return sorted(out, key=lambda p: (1 if os.sep + "plugins" + os.sep in p else 0, p))


NON_ENGLISH = re.compile(r"[\u3040-\u30FF\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\uAC00-\uD7AF\u1100-\u11FF\u0400-\u04FF\u0E00-\u0E7F\u0900-\u097F\u0590-\u05FF\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF\u011E\u011F\u015E\u015F\u0130\u0131]+")


def english_only(desc):
    """With "english_only_descriptions": true in state/vault-policy.json the registry shows descriptions in English only
    (other scripts removed; the skill file is untouched). Default: descriptions are shown as written."""
    if not B.language_policy().get("english_only_descriptions"):
        return desc
    cleaned = re.sub(r"\s+", " ", NON_ENGLISH.sub(" ", desc)).strip(" ,.;:-()")
    if NON_ENGLISH.search(desc) and len(re.sub(r"[^A-Za-z]", "", cleaned)) < 15:
        return "(description not in English; open the skill file)"
    return cleaned


def categorize(text):
    t = text.lower()
    for cat, rx in CATEGORIES:
        if re.search(rx, t):
            return cat
    return "other"


def claude_settings():
    """the owner's Claude Code user settings: which personal skills and plugins really load at start."""
    s = B.load_json(os.path.expanduser(os.environ.get("BRAIN_CLAUDE_SETTINGS", "~/.claude/settings.json")), {})
    return s.get("skillOverrides") or {}, s.get("enabledPlugins") or {}


def codex_disabled():
    """SKILL.md paths switched off in Codex's own config ([[skills.config]] path = ... enabled = false)."""
    p = os.path.expanduser(os.environ.get("BRAIN_CODEX_CONFIG", "~/.codex/config.toml"))
    try:
        text = open(p, encoding="utf-8").read()
    except OSError:
        return set()
    off = set()
    for block in re.split(r"^\[\[skills\.config\]\]\s*$", text, flags=re.M)[1:]:
        block = re.split(r"^\[", block, maxsplit=1, flags=re.M)[0]
        m = re.search(r'^path\s*=\s*"([^"]+)"', block, re.M)
        if m and re.search(r"^enabled\s*=\s*false", block, re.M):
            off.add(os.path.realpath(os.path.expanduser(m.group(1))))
    return off


def collect_skills():
    rows, seen = [], set()
    overrides, enabled = claude_settings()
    codex_off = codex_disabled()
    try:  # v2.1: Codex plugin switches from ~/.codex/config.toml (plugin_shelf.py)
        import plugin_shelf
        codex_plugins = {e["name"]: e["on"] for e in plugin_shelf.codex_entries()}
    except Exception:
        codex_plugins = {}
    in_brain = set()  # (name, plugin) already in the brain library; the brain copy is the home, other copies are skipped
    brain_plugins = os.path.join(B.ROOT, "skills", "plugins") + os.sep
    for r in skill_roots():
        bases = []
        if "path" in r:
            bases = [(os.path.expanduser(r["path"]), "")]
        elif "glob" in r:
            bases = [(b, os.path.basename(b.rstrip("/")).split("~")[0]) for b in sorted(glob.glob(os.path.expanduser(r["glob"]))) if "/.trash/" not in b]
        elif "plugins_json" in r:
            data = B.load_json(os.path.expanduser(r["plugins_json"]), {})
            for name, installs in sorted((data.get("plugins") or {}).items()):
                for inst in installs or []:
                    if inst.get("installPath"):
                        bases.append((inst["installPath"], name.split("@")[0]))
        for base, plugin in bases:
            if not os.path.isdir(base):
                continue
            for f in find_skill_files(base):
                if r["kind"] == "brain-library" and f.startswith(brain_plugins):
                    plugin = f[len(brain_plugins):].split(os.sep)[0]
                elif r["kind"] == "brain-library":
                    plugin = ""
                try:
                    note = B.read_note(f)
                except OSError:
                    continue
                name = str(note["meta"].get("name") or os.path.basename(os.path.dirname(f))).strip()
                desc = note["meta"].get("description") or ""
                if isinstance(desc, list):
                    desc = " ".join(desc)
                wtu = note["meta"].get("when_to_use") or ""
                if isinstance(wtu, list):
                    wtu = " ".join(str(x) for x in wtu)
                d_str, w_str = str(desc).strip(), str(wtu).strip()
                parts = [p for p in (d_str, w_str if (w_str and w_str not in d_str) else "") if p]
                desc = english_only(re.sub(r"\s+", " ", " ".join(parts)).strip())[:600]
                key = (name.lower(), r["kind"], plugin)
                if key in seen:
                    continue
                if r["kind"] == "brain-library":
                    in_brain.add((name.lower(), plugin))
                    in_brain.add((name.lower(), ""))
                elif r["kind"] in ("claude-personal", "codex-personal", "library") and (name.lower(), "") in in_brain:
                    continue
                elif r["kind"].startswith("claude-") and (name.lower(), plugin) in in_brain:
                    continue
                seen.add(key)
                autoload = r["autoload"]
                if r["kind"] == "claude-personal":
                    state = overrides.get(name, overrides.get(os.path.basename(os.path.dirname(f)), "on"))  # keyed by name or folder
                    autoload = "yes" if state in ("on", "name-only") else f"no ({state})"
                elif r["kind"] in ("codex-personal", "agents-shared", "ecc-package") and os.path.realpath(f) in codex_off:
                    autoload = "no (switched off in ~/.codex/config.toml)"
                elif r["kind"] == "codex-plugin":
                    autoload = ("yes" if codex_plugins[plugin] else "no (plugin off: plugin_shelf.py activate " + plugin + ")") \
                        if plugin in codex_plugins else "unverified (not in ~/.codex/config.toml)"
                elif r["kind"] == "claude-plugin":
                    on = any(v for k, v in enabled.items() if k.split("@")[0] == plugin)
                    autoload = "yes" if on else "no (plugin off)"
                rows.append({"name": name, "description": desc, "category": categorize(name + " " + desc),
                             "location": f, "agent": r["agent"], "kind": r["kind"], "plugin": plugin,
                             "autoload": autoload})
    return sorted(rows, key=lambda x: (x["category"], x["name"].lower(), x["kind"]))


def note_rows():
    rows = []
    for p in B.iter_notes():
        if os.sep + "00-toc" + os.sep in p:
            continue
        n = B.read_note(p)
        col, sub = B.collection_of(p)
        m = n["meta"]
        summary = m.get("summary") if isinstance(m.get("summary"), str) else ""
        tags = m.get("tags") if isinstance(m.get("tags"), list) else ([m["tags"]] if isinstance(m.get("tags"), str) and m.get("tags") else [])
        aliases = m.get("aliases") if isinstance(m.get("aliases"), list) else []
        body = re.sub(r"```.*?```", " ", n["body"], flags=re.S)
        excerpt = re.sub(r"\s+", " ", body)[:1500]
        rows.append({"path": B.rel(p), "stem": os.path.splitext(os.path.basename(p))[0], "title": n["title"],
                     "collection": col, "sub": sub, "scope": str(m.get("scope", "")), "type": str(m.get("type", "")),
                     "summary": summary, "headings": " | ".join(n["headings"][:40]), "tags": " ".join(tags),
                     "aliases": " ".join(aliases), "excerpt": excerpt})
    return rows


def build_db(notes, skills):
    os.makedirs(os.path.dirname(B.INDEX_DB), exist_ok=True)
    tmp = B.INDEX_DB + ".tmp"
    if os.path.exists(tmp):
        os.unlink(tmp)
    con = sqlite3.connect(tmp)
    con.execute("CREATE VIRTUAL TABLE notes USING fts5(title, summary, headings, tags, aliases, excerpt, "
                "path UNINDEXED, stem UNINDEXED, collection UNINDEXED, sub UNINDEXED, scope UNINDEXED, type UNINDEXED, "
                "tokenize='unicode61 remove_diacritics 2')")
    con.execute("CREATE VIRTUAL TABLE skills USING fts5(name, description, category, location UNINDEXED, agent UNINDEXED, "
                "kind UNINDEXED, plugin UNINDEXED, autoload UNINDEXED, tokenize='unicode61 remove_diacritics 2')")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    con.executemany("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(n["title"], n["summary"], n["headings"], n["tags"], n["aliases"], n["excerpt"], n["path"], n["stem"],
                      n["collection"], n["sub"], n["scope"], n["type"]) for n in notes])
    con.executemany("INSERT INTO skills VALUES (?,?,?,?,?,?,?,?)",
                    [(s["name"], s["description"], s["category"], s["location"], s["agent"], s["kind"], s["plugin"],
                      s["autoload"]) for s in skills])
    con.executemany("INSERT INTO meta VALUES (?,?)", [("built", B.now()), ("notes", str(len(notes))), ("skills", str(len(skills)))])
    con.commit()
    con.close()
    os.replace(tmp, B.INDEX_DB)


def fm(title, summary):
    return f"---\ntitle: \"{title}\"\ntype: toc\ngenerated: true\nsummary: \"{summary}\"\nupdated: {B.today()}\n---\n"


def link(n):
    t = n["title"].replace("|", "-").replace("]", ")").replace("[", "(")
    return f"[[{n['stem']}]]" if t == n["stem"] else f"[[{n['stem']}|{t}]]"


def grouped(notes, collection):
    g = {}
    for n in notes:
        if n["collection"] == collection:
            g.setdefault(n["sub"] or "(top level)", []).append(n)
    return {k: sorted(v, key=lambda x: (0 if x["stem"].endswith("- history") else 1, x["title"].lower())) for k, v in sorted(g.items())}


def write_tocs(notes, skills, drives=()):
    os.makedirs(TOC, exist_ok=True)
    out = {}
    count = lambda c: sum(1 for n in notes if n["collection"] == c)
    names = [("projects", "toc-projects", "Projects", "Every project and its notes, history first."),
             ("domains", "toc-domains", "Domains", "Compiled knowledge by subject."),
             ("capabilities", "toc-capabilities", "Capabilities", "Reusable methods, tool know-how and skill write-ups."),
             ("self", "toc-self", "Self", "the owner's identity, profile and career facts (scope-gated: only personal, CV and official tasks)."),
             ("history", "toc-history", "History", "Legacy logs and episodes without a project."),
             ("system", "toc-system", "System", "The brain's own design, rules and templates."),
             ("drawings", "toc-drawings", "Drawings", "Excalidraw drawings."),
             ("problems", "toc-problems", "Problems", "Pain memory: failures with structural guards."),
             ("lessons", "toc-lessons", "Lessons", "Candidate and released lessons."),
             ("inbox", "toc-inbox", "Inbox", "New notes made in Obsidian land here until they are sorted into a collection.")]
    home = [fm("Brain home", "Start here: every collection of the brain and how many notes it holds."), "# Brain home", "",
            "Generated by `tools/brain_index.py`. Agents search with `tools/brain_route.py`; people browse from here.", "",
            "| Collection | Notes | View |", "|---|---|---|"]
    for col, stem, title, summary in names:
        home.append(f"| {title} | {count(col)} | [[{stem}]] |")
        body = [fm(title, summary), f"# {title}", "", summary, ""]
        g = grouped(notes, col)
        if not g:
            body.append("_Empty so far._")
        for sub, items in g.items():
            if sub != "(top level)":
                body += [f"## {sub}", ""]
            body += [f"- {link(n)}" + (f" — {n['summary'][:110]}" if n["summary"] else "") for n in items] + [""]
        out[stem] = "\n".join(body).rstrip() + "\n"
    cats = {}
    for s in skills:
        cats.setdefault(s["category"], []).append(s)
    home += ["", f"## Skills: {len(skills)} entries in {len(cats)} categories → [[skills-registry]]", ""]
    reg = [fm("Skills registry", "Every skill Claude Code or Codex can use, by category, with where it lives and whether it loads at start."),
           "# Skills registry", "", "Generated from the skill folders on this Mac. Search: `brain_route.py --query \"<words>\"`.", "",
           "| Category | Skills | View |", "|---|---|---|"]
    for cat, items in sorted(cats.items()):
        stem = f"skills-{cat}"
        reg.append(f"| {cat} | {len(items)} | [[{stem}]] |")
        rows = [fm(f"Skills: {cat}", f"{len(items)} skills in category {cat}."), f"# Skills: {cat}", "",
                "| Skill | For | Loads at start | What it does | Where |", "|---|---|---|---|---|"]
        for s in items:
            d = s["description"].replace("|", "/")[:120]
            where = s["location"].replace(os.path.expanduser("~"), "~").replace("|", "/")
            rows.append(f"| {s['name'].replace('|', '/')} | {s['agent']}{' · ' + s['plugin'] if s['plugin'] else ''} | {s['autoload']} | {d} | `{where}` |")
        out[stem] = "\n".join(rows) + "\n"
    kinds = {}
    for s in skills:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    reg += ["", "## By location", "", "| Location kind | Skills |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sorted(kinds.items())]
    if drives:
        reg += ["", "## On external drives (not installed)", "", "| Drive | Skills | View |", "|---|---|---|"]
        reg += [f"| {d['label']} | {len(d['skills'])} | [[{d['slug']}]] |" for d in drives]
        home += ["## External drives", "", "| Drive | Skills not installed | Repositories | View |", "|---|---|---|---|"]
        home += [f"| {d['label']} | {len(d['skills'])} | {len(d['repos'])} | [[{d['slug']}]] |" for d in drives]
        home.append("")
        for d in drives:
            out.update(drive_pages(d, notes, set(cats)))
    out["skills-registry"] = "\n".join(reg) + "\n"
    out["toc-home"] = "\n".join(home) + "\n"
    changed = 0
    undated = lambda t: re.sub(r"^updated: \d{4}-\d{2}-\d{2}$", "updated:", t, count=1, flags=re.M)
    for stem, text in out.items():
        path = os.path.join(TOC, stem + ".md")
        try:  # v3 (C5): only the date differs -> the page is not rewritten (no daily churn in git and Obsidian)
            with open(path, encoding="utf-8") as fh:
                if undated(fh.read()) == undated(text):
                    continue
        except OSError:
            pass
        changed += B.write_if_changed(path, text)
    stale_dir = os.path.join(B.ROOT, "_to_delete", "stale-toc")
    for f in os.listdir(TOC):  # views for categories that no longer exist leave the vault (generated files only)
        if (f.endswith(".md") and f[:-3] not in out) or f.endswith(".md.stale"):
            os.makedirs(stale_dir, exist_ok=True)
            os.replace(os.path.join(TOC, f), os.path.join(stale_dir, f"{B.today()}-{f.lstrip('.').replace('.md.stale', '.md')}"))
    return changed, len(out)


def collect_drives(installed):
    """External drive catalogs written by scan_external.py (state/external/*.json). Skills already installed
    on this Mac are left out; the rest stay searchable while the drive is unplugged."""
    have = {s["name"].lower() for s in installed}
    have |= {n[4:] for n in have if n.startswith("ecc-")}  # the ECC package prefixes its skill names
    have |= {n.split(":", 1)[1] for n in have if ":" in n}  # v2.1 (O7): "ckm:banner-design" == "banner-design"
    shas = set()
    for s in installed:
        try:
            with open(s["location"], "rb") as fh:
                shas.add(hashlib.sha256(fh.read()).hexdigest())
        except OSError:
            pass
    drives = []
    folder = os.path.join(B.STATE, "external")
    for f in sorted(glob.glob(os.path.join(folder, "*.json"))):
        cat = B.load_json(f, {})
        label = cat.get("label") or os.path.splitext(os.path.basename(f))[0]
        rows = []
        for s in cat.get("skills", []):
            if s["name"].lower() in have or s["name"].lower().split(":", 1)[-1] in have or s.get("sha256") in shas:
                continue
            desc = english_only(s.get("description", ""))
            rows.append({"name": s["name"], "description": desc, "category": categorize(s["name"] + " " + desc),
                         "location": s["location"], "agent": "Claude + Codex (not installed)", "kind": f"drive-{label}",
                         "plugin": "", "autoload": f"no: on drive {label}", "source": s.get("source", "")})
        drives.append({"label": label, "slug": "drive-" + re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-"),
                       "root": cat.get("root", ""), "scanned": cat.get("scanned", ""), "mounted": os.path.isdir(cat.get("root", "")),
                       "skills": sorted(rows, key=lambda x: (x["category"], x["name"].lower())), "repos": cat.get("repos", []),
                       "excluded": cat.get("excluded", {}), "counts": cat.get("counts", {}), "installed_overlap": len(cat.get("skills", [])) - len(rows)})
    return drives


def drive_pages(d, notes, installed_cats=()):
    """Generated pages for one external drive: overview, skills by category, repositories."""
    out, slug, label = {}, d["slug"], d["label"]
    stems = {n["stem"].lower(): n["stem"] for n in notes}
    texts = {}
    for n in notes:  # full text of hand-written notes, to link repositories they mention by owner/repo
        try:
            texts[n["stem"]] = (n["title"] + " " + n["aliases"] + " " + open(os.path.join(B.ROOT, n["path"]), encoding="utf-8").read()).lower()
        except OSError:
            texts[n["stem"]] = (n["title"] + " " + n["aliases"]).lower()
    repo_index = ""
    if "repo index" in stems:
        try:
            repo_index = open(os.path.join(B.VAULT, "domains", "github-library", "Repo Index.md"), encoding="utf-8").read().lower()
        except OSError:
            repo_index = ""
    cats = {}
    for s in d["skills"]:
        cats.setdefault(s["category"], []).append(s)
    harness = stems.get("codex for claude harness")
    ov = [fm(f"External drive {label}", f"What the {label} drive holds: {len(d['skills'])} skills not installed on this Mac and {len(d['repos'])} repositories."),
          f"# External drive {label}", "",
          f"Catalog made by `tools/scan_external.py` on {d['scanned']} from `{d['root']}` (read only; the drive was not changed). "
          f"Drive mounted now: {'yes' if d['mounted'] else 'no'}.", "",
          "Skills listed here are **not installed**. To use one: mount the drive, read its `SKILL.md`, and copy it into "
          "`~/.codex/skills-library/` only with the owner's OK. Agents find them with `brain_route.py` (they show `no: on drive`).", ""]
    if harness:
        ov += [f"The drive's largest collection is the [[{harness}]] (three plugin packages and a curated skill library).", ""]
    ov += ["| Skills by category | Count | View |", "|---|---|---|"]
    for cat, items in sorted(cats.items()):
        stem = f"{slug}-skills-{cat}"
        ov.append(f"| {cat} | {len(items)} | [[{stem}]] |")
        rows = [fm(f"{label} skills: {cat}", f"{len(items)} skills in category {cat} on drive {label}, not installed."),
                f"# {label} skills: {cat}", "", f"Back to [[{slug}]]" + (f" · installed skills of this kind: [[skills-{cat}]]" if cat in installed_cats else ""), "",
                "| Skill | What it does | Source | File on the drive |", "|---|---|---|---|"]
        for s in items:
            where = s["location"].replace(d["root"], "").lstrip("/").replace("|", "/")
            rows.append(f"| {s['name'].replace('|', '/')} | {s['description'].replace('|', '/')[:120]} | {s['source'].replace('|', '/')[:60]} | `{where}` |")
        out[stem] = "\n".join(rows) + "\n"
    ex = d.get("excluded", {})
    ov += ["", f"## Repositories: {len(d['repos'])} → [[{slug}-repos]]", "",
           "## Left out of this catalog", "", f"- Skill names already installed on this Mac: {d['installed_overlap']} (see [[skills-registry]])"]
    ov += [f"- {k}: {v} files" for k, v in sorted(ex.items())]
    out[slug] = "\n".join(ov) + "\n"
    rp = [fm(f"{label} repositories", f"Git repositories and source snapshots on drive {label}."), f"# {label} repositories", "",
          f"Back to [[{slug}]]. `In brain` links a repository the brain already knew (from [[Repo Index]]) or a note of the same name.", ""]
    areas = {}
    for r in d["repos"]:
        areas.setdefault(r["area"], []).append(r)
    for area, items in sorted(areas.items()):
        rp += [f"## {area}", "", "| Repository | Last commit | Skill files | In brain | What it is | Folder |", "|---|---|---|---|---|---|"]
        for r in items:
            name = r["slug"].split("/")[-1]
            known = []
            if r["remote"] and r["slug"] in repo_index:
                known.append("[[Repo Index]]")
            if name.lower() in stems and stems[name.lower()] != "Repo Index":
                known.append(f"[[{stems[name.lower()]}]]")
            if harness and r["area"].startswith("CODEX FOR CLAUDE"):
                known.append(f"[[{harness}]]")
            if "/" in r["slug"]:
                hits = sorted(s for s, tx in texts.items() if s != "Repo Index" and r["slug"] in tx and f"[[{s}]]" not in known)
                known += [f"[[{s}]]" for s in hits[:3]]
            title = f"[{r['slug']}]({r['remote']})" if r["remote"].startswith("http") else r["slug"].replace("|", "/")
            what = (r.get("description") or "").replace("|", "/")[:110]
            rp.append(f"| {title} | {r['last_commit'] or '-'} | {r['skill_files']} | {' '.join(known) or 'new'} | {what} | `{r['path'].replace(d['root'], '').lstrip('/')}` |")
        rp.append("")
    out[f"{slug}-repos"] = "\n".join(rp).rstrip() + "\n"
    return out


def build(toc=True, timeout_s=60):
    """Rebuild index/brain.db (and, unless toc=False, the 00-toc views) under state/index.lock (v2.1, O1).
    Read-time rebuilds (brain_route) pass toc=False so a lookup never rewrites tracked vault files (O11)."""
    with B.lock("index", timeout_s=timeout_s):
        notes = note_rows()
        skills = collect_skills()
        drives = collect_drives(skills)
        changed, total = write_tocs(notes, skills, drives) if toc else (0, 0)
        build_db(notes, skills + [s for d in drives for s in d["skills"]])
    return {"notes": len(notes), "skills": len(skills), "drive_skills": sum(len(d["skills"]) for d in drives),
            "toc_files": total, "toc_changed": changed, "toc": "rebuilt" if toc else "skipped (read-time rebuild)"}


def main():
    if "-h" in sys.argv or "--help" in sys.argv:
        print("usage: brain_index.py [--check]\n  no option: rebuild index/brain.db and Brain System/00-toc/\n  --check: report whether the index is fresh or stale")
        return 0
    if "--check" in sys.argv:
        fresh = os.path.exists(B.INDEX_DB) and os.path.getmtime(B.INDEX_DB) >= B.vault_max_mtime()
        print(json.dumps({"index": "fresh" if fresh else "stale"}))
        return 0
    print(json.dumps(build()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
