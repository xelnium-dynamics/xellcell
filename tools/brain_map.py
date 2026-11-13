#!/usr/bin/env python3
"""
brain_map.py — the project map: read the symbol you need, not the file it lives in (v6, layers 4 + 6).

    python3 -I brain_map.py query "<words>" [--root DIR] [--budget 900]    ranked pointers path:Lstart-Lend + neighbours
    python3 -I brain_map.py outline <file> [--budget 700]                  every symbol / heading / selector with its lines
    python3 -I brain_map.py slice <file> --symbol NAME | --lines A-B       exactly those lines, numbered
    python3 -I brain_map.py who NAME [--root DIR]                          where it is defined, who imports or mentions it
    python3 -I brain_map.py build [--root DIR] [--force]                   (re)build the map; query/who do it by themselves
    python3 -I brain_map.py stats [--root DIR]                             tree size in tokens, heaviest files, savings so far

Why: in a long session the expensive habit is opening a 3,000-line main.js to change one function, again after every
compaction. The map answers "where is it" in a few hundred tokens and `slice` returns only that function.
How it differs from a knowledge-graph builder that asks a model to read the code: this one is deterministic and free
(Python's ast for .py, line scanners for JS/TS/HTML/CSS/GLSL/Markdown/JSON), incremental (a file is re-read only when its
size or mtime changed), and every answer is a pointer into the original, never a summary of it, so nothing is paraphrased
and nothing can be invented. What it does not do: it draws no semantic conclusions and it does not follow dynamic calls.
The map lives in index/maps/ (rebuildable, never the source of truth). Works the same for Claude and Codex.
"""
import argparse, ast, hashlib, json, math, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

MAPS = os.path.join(B.ROOT, "index", "maps")
SAVINGS = os.path.join(B.STATE, "map-savings.jsonl")
SKIP_DIRS = {".git", "node_modules", "dist", "build", ".next", ".nuxt", ".cache", "__pycache__", ".venv", "venv", "env", ".idea",
             ".vscode", "_to_delete", ".obsidian", ".trash", "coverage", ".turbo", ".parcel-cache", "vendor", "Pods", ".gradle",
             "target", ".svelte-kit", "out", ".DS_Store", "raw"}
LANG = {".py": "py", ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js", ".html": "html", ".htm": "html",
        ".vue": "html", ".svelte": "html", ".css": "css", ".scss": "css", ".less": "css", ".md": "md", ".mdx": "md", ".json": "json",
        ".glsl": "glsl", ".vert": "glsl", ".frag": "glsl", ".wgsl": "glsl", ".sh": "text", ".toml": "text", ".yaml": "text",
        ".yml": "text", ".txt": "text", ".svg": "text", ".csv": "text"}
MAX_FILE, MAX_FILES = 2 * 1024 * 1024, 8000
JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "else", "do", "try", "typeof", "new", "await", "super",
               "constructor_", "with", "delete", "void", "yield", "case", "throw", "import", "export", "in", "of"}
SELF = os.path.realpath(os.path.join(B.VAULT, "self"))


def est(n_chars):
    return n_chars // 4 + 1


# ---------- parsers: each returns ([kind, name, start, end, parent], imports, doc) ----------
def parse_py(text):
    syms, imports, doc = [], [], ""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return parse_lines(text, r"^\s*(?:async\s+)?(def|class)\s+(\w+)", lambda m: (("fn" if m.group(1) == "def" else "class"), m.group(2)))
    doc = (ast.get_docstring(tree) or "").strip().splitlines()[0][:140] if ast.get_docstring(tree) else ""

    def walk(node, parent):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                syms.append(["method" if parent else "fn", n.name, n.lineno, getattr(n, "end_lineno", n.lineno), parent])
            elif isinstance(n, ast.ClassDef):
                syms.append(["class", n.name, n.lineno, getattr(n, "end_lineno", n.lineno), parent])
                walk(n, n.name)
            elif isinstance(n, ast.Assign) and not parent:
                for t in n.targets:
                    if isinstance(t, ast.Name) and t.id.isupper() and len(t.id) > 2:
                        syms.append(["const", t.id, n.lineno, getattr(n, "end_lineno", n.lineno), ""])
            elif isinstance(n, ast.Import):
                imports.extend(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom):
                imports.append(("." * n.level) + (n.module or ""))
    walk(tree, "")
    return syms, imports, doc


def parse_lines(text, pattern, to_sym):
    rx, syms = re.compile(pattern), []
    for i, line in enumerate(text.splitlines(), 1):
        m = rx.match(line)
        if m:
            kind, name = to_sym(m)
            syms.append([kind, name, i, i, ""])
    return syms, [], ""


def _strip_js(line):
    """Drop string contents and // comments so braces inside them are not counted (approximate, on purpose)."""
    line = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", "''", line)
    return re.sub(r"//.*$", "", line)


JS_DEF = [
    (re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+([\w$]+)"), "fn"),
    (re.compile(r"^(\s*)(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([\w$]+)"), "class"),
    (re.compile(r"^(\s*)(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*(?::[^=]+)?=>"), "fn"),
    (re.compile(r"^(\s*)(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*=\s*(?:async\s+)?function\b"), "fn"),
    (re.compile(r"^(\s*)(?:export\s+)?(?:declare\s+)?(?:interface|enum)\s+([\w$]+)"), "type"),
    (re.compile(r"^(\s*)(?:export\s+)?(?:declare\s+)?type\s+([\w$]+)\s*(?:<[^>]*>)?\s*="), "type"),
    (re.compile(r"^(\s*)(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*(?:React\.)?(?:memo|forwardRef|lazy|observer|styled[.(][\w.]*)\s*[(`]"), "fn"),
    (re.compile(r"^()(?:export\s+)?(?:const|let|var)\s+([\w$]+)\s*(?::[^=]+)?=\s*(?:new\s+[\w$.]+\s*\(|[\[{])"), "const"),
]
JS_METHOD = re.compile(r"^(\s+)(?:(?:static|async|get|set|public|private|protected|readonly|override)\s+)*([\w$#]+)\s*\([^)]*\)\s*(?::[^{]+)?\{")
JS_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+)['"]([^'"]+)['"]""")


def _blank_templates(text):
    """v7 (Argon, round 4): a multi-line template literal (an inline GLSL shader in a three.js file) keeps its line count
    but loses its content, so the braces inside it are not counted as code."""
    return re.sub(r"`(?:\\.|[^`\\])*`", lambda m: "`" + "\n" * m.group(0).count("\n") + "`", text, flags=re.S)


def parse_js(text, offset=0):
    text = _blank_templates(text)
    lines = text.splitlines()
    clean = [_strip_js(l) for l in lines]
    syms, imports, classes = [], [], []  # classes: (indent, name, end)

    def end_of(i, indent):
        opens = clean[i].count("{") - clean[i].count("}")
        if opens <= 0:
            return i
        for j in range(i + 1, min(len(lines), i + 4000)):
            opens += clean[j].count("{") - clean[j].count("}")
            if opens <= 0:
                return j
        return i

    for i, line in enumerate(clean):
        for m in JS_IMPORT.finditer(line):
            imports.append(m.group(1))
        hit = None
        for rx, kind in JS_DEF:
            m = rx.match(line)
            if m:
                hit = (kind, m.group(2), len(m.group(1)))
                break
        classes = [c for c in classes if c[2] >= i]
        if not hit:
            m = JS_METHOD.match(line)
            if m and classes and m.group(2) not in JS_KEYWORDS and len(m.group(1)) > classes[-1][0]:
                hit = ("method", m.group(2), len(m.group(1)))
        if not hit:
            continue
        kind, name, indent = hit
        end = end_of(i, indent)
        parent = classes[-1][1] if classes and kind == "method" else ""
        syms.append([kind, name, i + 1 + offset, end + 1 + offset, parent])
        if kind == "class":
            classes.append((indent, name, end))
    head = next((l.strip().lstrip("/*# ").strip() for l in lines[:6] if l.strip().startswith(("//", "/*", "*"))), "")
    return syms, imports, head[:140]


def parse_css(text, offset=0):
    syms, depth = [], 0
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = re.sub(r"/\*.*?\*/", "", raw)
        if depth == 0:
            m = re.match(r"^\s*([^{}/][^{}]*?)\s*\{", line)
            if m:
                name = re.sub(r"\s+", " ", m.group(1))[:70]
                opens, end = line.count("{") - line.count("}"), i
                j = i
                while opens > 0 and j + 1 < len(lines) and j < i + 3000:
                    j += 1
                    opens += lines[j].count("{") - lines[j].count("}")
                end = j
                syms.append(["at-rule" if name.startswith("@") else "css", name, i + 1 + offset, end + 1 + offset, ""])
        depth = max(0, depth + line.count("{") - line.count("}"))
    return syms, [], ""


def parse_html(text):
    syms, imports = [], []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        for m in re.finditer(r"<([a-zA-Z][\w-]*)\b[^>]*?\bid=[\"']([^\"']+)[\"']", line):
            syms.append(["el", f"{m.group(1).lower()}#{m.group(2)}", i + 1, i + 1, ""])
        for m in re.finditer(r"<(?:script|link|img|source)\b[^>]*?\b(?:src|href)=[\"']([^\"'#?]+)", line):
            if not re.match(r"^(https?:|data:|//)", m.group(1)):
                imports.append(m.group(1))
    for tag, parser in (("script", parse_js), ("style", parse_css)):
        for m in re.finditer(rf"<{tag}\b([^>]*)>(.*?)</{tag}>", text, re.S | re.I):
            if tag == "script" and re.search(r"\bsrc=", m.group(1)):
                continue
            start = text.count("\n", 0, m.start(2))
            end = start + m.group(2).count("\n")
            syms.append(["block", f"<{tag}>", start + 1, end + 1, ""])
            s2, i2 = parser(m.group(2), offset=start)[:2]
            syms += s2
            imports += i2
    title = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
    syms.sort(key=lambda s: s[2])
    return syms, imports, (re.sub(r"\s+", " ", title.group(1)).strip()[:140] if title else "")


def parse_md(text):
    syms, lines, fence = [], text.splitlines(), False
    heads = []
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if m:
            heads.append((len(m.group(1)), m.group(2), i + 1))
    for n, (lvl, name, start) in enumerate(heads):
        end = next((h[2] - 1 for h in heads[n + 1:] if h[0] <= lvl), len(lines))
        syms.append([f"h{lvl}", name[:90], start, end, ""])
    fm, _ = B.split_frontmatter(text)
    doc = str(B.parse_frontmatter(fm).get("summary") or "")[:140] if fm else ""
    return syms, re.findall(r"\[\[([^\]|#^]+)", text)[:40], doc


def parse_glsl(text):
    syms = []
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*(?:uniform|varying|attribute|in|out)\s+(?:(?:highp|mediump|lowp)\s+)?\w+\s+(\w+)", line)
        if m:
            syms.append(["uniform", m.group(1), i, i, ""])
        m = re.match(r"^\s*(?:(?:highp|mediump|lowp)\s+)?(?:\w+)\s+(\w+)\s*\([^;]*\)\s*\{?\s*$", line)
        if m and m.group(1) not in ("if", "for", "while", "switch"):
            syms.append(["fn", m.group(1), i, i, ""])
    return syms, [], ""


def parse_json(text):
    syms = []
    if len(text) < 400000:
        for i, line in enumerate(text.splitlines(), 1):
            m = re.match(r'^\s{0,2}"([^"]{1,60})"\s*:', line)
            if m:
                syms.append(["key", m.group(1), i, i, ""])
    return syms[:200], [], ""


PARSERS = {"py": parse_py, "js": parse_js, "html": parse_html, "css": parse_css, "md": parse_md, "glsl": parse_glsl, "json": parse_json}


def parse_file(path):
    lang = LANG.get(os.path.splitext(path)[1].lower())
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return None
    n_lines = text.count("\n") + 1
    if lang in ("js", "css") and n_lines < 8 and len(text) > 20000:
        return {"lang": lang, "lines": n_lines, "chars": len(text), "symbols": [], "imports": [], "doc": "(minified: not mapped)"}
    try:
        syms, imports, doc = PARSERS[lang](text) if lang in PARSERS else ([], [], "")
    except Exception as e:  # a parser bug must never stop the map; the file is still listed
        syms, imports, doc = [], [], f"(not parsed: {type(e).__name__})"
    return {"lang": lang or "text", "lines": n_lines, "chars": len(text), "symbols": syms[:1500], "imports": sorted(set(imports))[:60], "doc": doc}


# ---------- the map ----------
def map_path(root):
    return os.path.join(MAPS, f"{B.slugify(os.path.basename(root) or 'root', 32)}-{hashlib.sha1(root.encode()).hexdigest()[:10]}.json")


def walk(root):
    n = 0
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith(".") and os.path.realpath(os.path.join(d, x)) != SELF)
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() not in LANG or f.endswith((".min.js", ".min.css", ".lock")) or f.startswith("."):
                continue
            p = os.path.join(d, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size > MAX_FILE or st.st_size == 0:
                continue
            yield os.path.relpath(p, root).replace(os.sep, "/"), st
            n += 1
            if n >= MAX_FILES:
                return


def build(root, force=False):
    """Incremental: only files whose size or mtime changed are read again. Returns (map, stats)."""
    root = os.path.realpath(os.path.expanduser(root))
    if root == SELF or root.startswith(SELF + os.sep):
        sys.exit("brain_map: Brain System/self is never mapped (layer 3)")
    mp = map_path(root)
    old = {} if force else (B.load_json(mp, {}) or {})
    old_files = old.get("files", {}) if old.get("root") == root and old.get("v") == 1 else {}
    files, parsed = {}, 0
    for rel, st in walk(root):
        prev = old_files.get(rel)
        if prev and prev.get("m") == st.st_mtime_ns and prev.get("s") == st.st_size:
            files[rel] = prev
            continue
        e = parse_file(os.path.join(root, rel))
        if e is None:
            continue
        e.update({"m": st.st_mtime_ns, "s": st.st_size})
        files[rel] = e
        parsed += 1
    m = {"v": 1, "root": root, "built": B.now(), "files": files}
    if parsed or set(files) != set(old_files) or not os.path.exists(mp):
        os.makedirs(MAPS, exist_ok=True)
        B.atomic_write(mp, json.dumps(m, ensure_ascii=False, separators=(",", ":")))
    return m, {"files": len(files), "parsed_now": parsed, "symbols": sum(len(f["symbols"]) for f in files.values()), "map": B.rel(mp)}


def words(text):
    """camelCase, snake_case and kebab-case split into lower-case words."""
    out = []
    for w in re.findall(r"[A-Za-z0-9$#]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)):
        w = w.lower()
        if len(w) >= 2:
            out.append(w)
    return out


def _match(q, toks):
    return q in toks or (len(q) >= 4 and any(t.startswith(q) or (len(t) >= 4 and q.startswith(t)) for t in toks))


def query(m, text, limit=14):
    q = [w for w in dict.fromkeys(words(text)) if w not in ("the", "and", "for", "with", "that", "this", "from", "into", "where", "what", "how", "does", "is", "in", "of", "to", "it")]
    if not q:
        return [], q
    rows = []
    for rel, f in m["files"].items():
        ptoks = set(words(rel))
        dtoks = set(words(f.get("doc", "")))
        rows.append((rel, f, None, ptoks, set(), dtoks))
        for s in f["symbols"]:
            rows.append((rel, f, s, ptoks, set(words(s[1])) | {s[1].lower()}, set(words(s[4] or ""))))
    N = len(rows) or 1
    df = {w: sum(1 for r in rows if _match(w, r[4]) or (r[2] is None and _match(w, r[3]))) for w in q}
    idf = {w: math.log((N + 1) / (1 + df[w])) + 0.3 for w in q}
    joined = "".join(q)
    scored = []
    for rel, f, s, ptoks, ntoks, extra in rows:
        score, hit = 0.0, 0
        for w in q:
            if s is not None and _match(w, ntoks):
                score, hit = score + 3 * idf[w], hit + 1
            elif _match(w, ptoks):
                score, hit = score + (1.2 if s is not None else 2.0) * idf[w], hit + 1
            elif _match(w, extra):
                score, hit = score + 0.8 * idf[w], hit + 1
        if s is not None and s[1].lower().replace("_", "") == joined:
            score += 8
        if s is not None and not any(_match(w, ntoks) for w in q):
            continue  # a symbol is listed for its own name, never only because of the file it sits in
        if hit and score > 0:
            scored.append((score * (1 + 0.15 * (hit - 1)), rel, f, s))
    scored.sort(key=lambda x: (-x[0], x[1], (x[3] or [0, 0, 0])[2]))
    return scored[:limit], q


def text_hits(m, q, limit=6):
    """Literal hits for the rarest query words, tied to the symbol that encloses the line."""
    out = []
    for w in sorted((x for x in q if len(x) >= 4), key=len, reverse=True)[:2]:
        rx = re.compile(re.escape(w), re.I)
        for rel, f in m["files"].items():
            if f["chars"] > 600000 or len(out) >= limit:
                continue
            try:
                lines = open(os.path.join(m["root"], rel), encoding="utf-8", errors="replace").read().splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    inside = [s for s in f["symbols"] if s[2] <= i <= s[3] and s[0] not in ("block",)]
                    best = min(inside, key=lambda s: s[3] - s[2]) if inside else None
                    out.append((rel, i, line.strip()[:110], best))
                    break
    return out[:limit]


def neighbours(m, rel):
    f = m["files"].get(rel) or {}
    stem = os.path.splitext(os.path.basename(rel))[0]
    by = sorted(r for r, x in m["files"].items() if r != rel and any(os.path.splitext(os.path.basename(i))[0] == stem or i.endswith(stem) for i in x.get("imports", [])))
    return f.get("imports", [])[:8], by[:8]


def note_saving(root, answer_chars, whole_chars, what):
    try:
        os.makedirs(B.STATE, exist_ok=True)
        with open(SAVINGS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": B.now(), "root": root, "cmd": what, "answer_tokens": est(answer_chars), "whole_file_tokens": est(whole_chars)}) + "\n")
    except OSError:
        pass


def clip(lines, budget):
    out, used = [], 0
    for n, line in enumerate(lines):
        used += est(len(line)) + 1
        if used > budget:
            out.append(f"… {len(lines) - n} more line(s): raise --budget or narrow the words")
            break
        out.append(line)
    return out


def sym_line(rel, s):
    return f"{rel}:L{s[2]}-L{s[3]}  {s[0]} {s[1]}" + (f"  (in {s[4]})" if s[4] else "") + f"  ~{est((s[3] - s[2] + 1) * 38)} tok"


def cmd_query(a):
    m, st = build(a.root)
    hits, q = query(m, a.words)
    lines = [f"# map query {a.words!r} — root {m['root']} ({st['files']} files, {st['symbols']} symbols" + (f", {st['parsed_now']} re-read" if st["parsed_now"] else "") + ")"]
    whole = 0
    seen_files = []
    for score, rel, f, s in hits:
        if rel not in seen_files:
            seen_files.append(rel)
            whole += f["chars"]
        lines.append(sym_line(rel, s) if s else f"{rel}  file, {f['lines']} lines ~{est(f['chars'])} tok" + (f" — {f['doc']}" if f.get("doc") else ""))
    th = text_hits(m, q) if len([h for h in hits if h[3]]) < 4 else []
    if th:
        lines.append("text hits:")
        lines += [f"{rel}:L{i}  {txt}" + (f"  (in {s[0]} {s[1]} L{s[2]}-L{s[3]})" if s else "") for rel, i, txt, s in th]
    for rel in seen_files[:2]:
        imp, by = neighbours(m, rel)
        if imp or by:
            lines.append(f"neighbours of {rel}: imports [{', '.join(imp) or '-'}] · used by [{', '.join(by) or '-'}]")
    if len(lines) == 1:
        lines.append("no match. Try other words, `outline <file>`, or a plain search.")
    else:
        lines.append(f"read only what you need: brain_map.py slice <file> --symbol <name>   (the matched files whole would be ~{est(whole)} tok)")
    out = "\n".join(clip(lines, a.budget))
    note_saving(m["root"], len(out), whole, "query")
    print(out)
    return 0


def cmd_outline(a):
    p = os.path.realpath(os.path.expanduser(a.file))
    if p == SELF or p.startswith(SELF + os.sep):
        sys.exit("brain_map: Brain System/self is read through brain_fetch.py in a private-scope session only")
    f = parse_file(p)
    if f is None:
        sys.exit(f"cannot read {a.file}")
    lines = [f"# outline {p} — {f['lines']} lines, ~{est(f['chars'])} tok" + (f" — {f['doc']}" if f.get("doc") else "")]
    for s in f["symbols"]:
        depth = 1 if s[4] else (int(s[0][1]) - 1 if re.fullmatch(r"h[1-6]", s[0]) else 0)
        lines.append(f"{'  ' * depth}L{s[2]}-L{s[3]}  {s[0]} {s[1]}")
    if f["imports"]:
        lines.append("imports: " + ", ".join(f["imports"][:20]))
    if not f["symbols"]:
        lines.append("(no symbols found: read it with --lines A-B)")
    out = "\n".join(clip(lines, a.budget))
    note_saving(os.path.dirname(p), len(out), f["chars"], "outline")
    print(out)
    return 0


def cmd_slice(a):
    p = os.path.realpath(os.path.expanduser(a.file))
    if p == SELF or p.startswith(SELF + os.sep):
        sys.exit("brain_map: Brain System/self is read through brain_fetch.py in a private-scope session only")
    try:
        lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        sys.exit(f"cannot read {a.file}")
    if a.symbol:
        f = parse_file(p) or {"symbols": []}
        want = a.symbol.lower()
        cands = [s for s in f["symbols"] if s[1].lower() == want] or [s for s in f["symbols"] if want in s[1].lower()]
        if not cands:
            sys.exit(f"no symbol like {a.symbol!r} in {a.file}; run: brain_map.py outline \"{a.file}\"")
        if len(cands) > 1 and cands[0][1].lower() != want:
            print("several symbols match; showing the first. Others: " + ", ".join(f"{s[1]} L{s[2]}-L{s[3]}" for s in cands[1:6]))
        s = cands[0]
        start, end = s[2], s[3]
        if start == end:  # a one-line definition found by a line scanner: show some body
            end = min(len(lines), start + a.context)
    else:
        x, _, y = (a.lines or "1").partition("-")
        start, end = max(1, int(x)), min(len(lines), int(y or x))
    start = max(1, start - (2 if a.symbol else 0))
    body = [f"{i:>5}  {lines[i - 1]}" for i in range(start, min(len(lines), end) + 1)]
    print(f"# {p}:L{start}-L{end} of {len(lines)}")
    print("\n".join(body))
    note_saving(os.path.dirname(p), sum(len(x) for x in body), sum(len(x) + 1 for x in lines), "slice")
    return 0


def cmd_who(a):
    m, _ = build(a.root)
    name = a.name
    rx = re.compile(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])")
    defs = [(rel, s) for rel, f in m["files"].items() for s in f["symbols"] if s[1] == name]
    lines = [f"# who {name!r} — root {m['root']}"] + [f"defined: {sym_line(rel, s)}" for rel, s in defs[:6]]
    uses = []
    for rel, f in m["files"].items():
        if f["chars"] > 600000:
            continue
        try:
            text = open(os.path.join(m["root"], rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        hits = [text.count("\n", 0, x.start()) + 1 for x in rx.finditer(text)]
        hits = [h for h in hits if not any(rel == dr and ds[2] == h for dr, ds in defs)]
        if hits:
            uses.append((rel, hits))
    uses.sort(key=lambda x: -len(x[1]))
    lines += [f"used: {rel}  {len(h)}x at L{', L'.join(str(x) for x in h[:8])}" + (" …" if len(h) > 8 else "") for rel, h in uses[:20]]
    if not defs and not uses:
        lines.append("not found (the map follows names, not dynamic calls)")
    print("\n".join(clip(lines, a.budget)))
    return 0


def cmd_stats(a):
    m, st = build(a.root)
    total = sum(f["chars"] for f in m["files"].values())
    heavy = sorted(m["files"].items(), key=lambda kv: -kv[1]["chars"])[:8]
    saved = [json.loads(l) for l in open(SAVINGS, encoding="utf-8")] if os.path.exists(SAVINGS) else []
    mine = [r for r in saved if r.get("root", "").startswith(m["root"])]
    out = {"root": m["root"], **st, "tree_tokens": est(total), "map_file_bytes": os.path.getsize(map_path(m["root"])),
           "heaviest": [{"file": r, "tokens": est(f["chars"]), "symbols": len(f["symbols"])} for r, f in heavy],
           "calls_recorded": len(mine), "answer_tokens": sum(r["answer_tokens"] for r in mine),
           "whole_file_tokens_instead": sum(r["whole_file_tokens"] for r in mine),
           "note": "whole_file_tokens_instead is an upper bound: what opening every matched file in full would have cost"}
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Project map: pointers instead of whole files.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("query", "who", "build", "stats"):
        p = sub.add_parser(name)
        if name == "query":
            p.add_argument("words")
        if name == "who":
            p.add_argument("name")
        p.add_argument("--root", default=os.getcwd())
        p.add_argument("--budget", type=int, default=900, help="answer cap in tokens")
        p.add_argument("--force", action="store_true")
    o = sub.add_parser("outline")
    o.add_argument("file")
    o.add_argument("--budget", type=int, default=700)
    s = sub.add_parser("slice")
    s.add_argument("file")
    s.add_argument("--symbol")
    s.add_argument("--lines")
    s.add_argument("--context", type=int, default=30, help="lines to show after a one-line definition")
    a = ap.parse_args()
    if a.cmd == "build":
        _, st = build(a.root, force=a.force)
        print(json.dumps(st))
        return 0
    return {"query": cmd_query, "outline": cmd_outline, "slice": cmd_slice, "who": cmd_who, "stats": cmd_stats}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
