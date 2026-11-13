#!/usr/bin/env python3
"""
tier0.py — Tier-0 hard checks per requirement (layer 8, roadmap 4.1). No model involved; a model never overrides these.

    python3 -I tier0.py --session <id>          # runs the contract's "## Checks" lines, prints JSON, exit 1 if any fails
    python3 -I tier0.py --check "R1: exists: out/report.pdf" --cwd <dir>

Check lines (in the contract's "## Checks" section, one per line):
  - R1: cmd: <shell command>                 exit code 0 = pass
  - R2: exists: <path>                       file exists and is not empty
  - R3: contains: <path> :: <regex>          the file matches the regex
  - R4: links: <file.html|file.md>           every local href/src/markdown link resolves to an existing file
  - R5: html: <file.html> :: <selector>      element present; selector = tag | #id | .class | tag.class | tag#id
  - R6: json: <file.json> :: <dotted.key>    valid JSON and the key path exists (use "." for the whole file)
  - R7: image: <file> :: <W>x<H>             PNG/JPEG/GIF at least W x H pixels
  - R8: vault                                vault_scan + vault_audit report 0 errors
v2.1 "Ironclad" (Argon F2) — checks for the owner's real work, standard library only, no installs:
  - R9:  pdf_pages: <file.pdf> :: <N> | <=N    page count (page tree /Count, compressed object streams included;
                                               falls back to macOS mdls)
  - R10: stl_bbox: <file.stl> :: X,Y,Z[,tol]   bounding box in model units (mm), tolerance default 0.1
  - R11: stl_manifold: <file.stl>              watertight: every edge is shared by exactly two triangles
  - R12: brand_tokens: <file> :: <palette.json | #hex,#hex,...>   every hex colour in a CSS/SVG/HTML file is in the palette
  - R13: html_viewport: <file.html>            has a width=device-width viewport and no fixed width / min-width
                                               over 375 px (a heuristic for "no sideways scroll on a phone")
Relative paths resolve against the session's cwd.
"""
import argparse, json, os, re, struct, subprocess, sys
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

KINDS = "cmd|exists|contains|links|html|json|image|vault|pdf_pages|stl_bbox|stl_manifold|brand_tokens|html_viewport"
KINDS = "|".join(sorted(KINDS.split("|"), key=len, reverse=True))  # html_viewport before html
LINE = re.compile(r"^[ \t]*-[ \t]*(R[\w.-]*)[ \t]*:[ \t]*(" + KINDS + r")[ \t]*:?[ \t]*(.*)$", re.M)


def res(rid, kind, arg, ok, detail):
    return {"requirement": rid, "kind": kind, "check": arg, "pass": bool(ok), "exit": 0 if ok else 1, "command": f"{kind}: {arg}",
            "tail": str(detail)[-1500:]}


def path_of(p, cwd):
    p = os.path.expanduser(p.strip().strip('"'))
    return p if os.path.isabs(p) else os.path.join(cwd, p)


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els, self.refs = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.els.append((tag, a.get("id") or "", (a.get("class") or "").split()))
        for k in ("href", "src"):
            if a.get(k):
                self.refs.append(a[k])


def local_ref(r):
    return not re.match(r"^(https?:|mailto:|tel:|data:|javascript:|#|//)", r.strip())


def image_size(p):
    with open(p, "rb") as f:
        head = f.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", head[6:10])
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    return None
                if b[0] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    f.read(3)
                    h, w = struct.unpack(">HH", f.read(4))
                    return w, h
                ln = struct.unpack(">H", f.read(2))[0]
                f.seek(ln - 2, 1)
    return None


def pdf_page_count(p):
    """Largest /Count of a /Type /Pages dictionary, looking inside Flate streams too (object streams, PDF 1.5+)."""
    import zlib
    data = open(p, "rb").read()
    if not data.startswith(b"%PDF"):
        raise ValueError("not a PDF")
    chunks = [data]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            chunks.append(zlib.decompress(m.group(1)))
        except zlib.error:
            pass
    pat = re.compile(rb"/Type\s*/Pages\b[^>]*?/Count\s+(\d+)|/Count\s+(\d+)[^>]*?/Type\s*/Pages\b")
    counts = [int(g1 or g2) for ch in chunks for g1, g2 in pat.findall(ch)]
    if counts:
        return max(counts)
    out = subprocess.run(["mdls", "-raw", "-name", "kMDItemNumberOfPages", p], capture_output=True, text=True).stdout.strip()
    return int(out) if out.isdigit() else None


def stl_triangles(p):
    data = open(p, "rb").read()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            return [struct.unpack("<9f", data[84 + 50 * i + 12:84 + 50 * i + 48]) for i in range(n)]
    v = [tuple(float(x) for x in m) for m in re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)]
    return [v[i] + v[i + 1] + v[i + 2] for i in range(0, len(v) - 2, 3)]


def hex_colors(text):
    out = set()
    for h in re.findall(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", text):
        h = h.lower()
        out.add("#" + ("".join(c * 2 for c in h) if len(h) == 3 else h))
    return out


def run_one(rid, kind, arg, cwd):
    try:
        if kind == "cmd":
            # v6: 300 s by default; BRAIN_TIER0_TIMEOUT raises it for a slow suite on a busy machine (a timeout is a fail)
            p = B.shell_run(arg, cwd=cwd, capture_output=True, text=True, timeout=int(os.environ.get("BRAIN_TIER0_TIMEOUT", "300")))
            r = res(rid, kind, arg, p.returncode == 0, p.stdout + p.stderr)
            r["exit"] = p.returncode
            return r
        if kind == "vault":
            outs = []
            ok = True
            tmp = os.path.join(B.ROOT, "index", "tier0-vault")
            for tool in ("vault_scan.py", "vault_audit.py"):
                p = subprocess.run([sys.executable, "-I", os.path.join(B.TOOLS, tool), "--vault", B.VAULT, "--out", tmp + "-" + tool[:-3]],
                                   capture_output=True, text=True, timeout=600)
                last = (p.stdout.strip().splitlines() or [""])[-1]
                outs.append(last)
                ok = ok and p.returncode == 0 and ("errors=0" in last or '"errors": 0' in last)
            return res(rid, kind, "vault", ok, " | ".join(outs))
        target, _, extra = arg.partition("::")
        p = path_of(target, cwd)
        extra = extra.strip()
        if kind == "exists":
            return res(rid, kind, arg, os.path.isfile(p) and os.path.getsize(p) > 0, f"{p}: {os.path.getsize(p) if os.path.exists(p) else 'missing'} bytes")
        if not os.path.isfile(p):
            return res(rid, kind, arg, False, f"{p}: missing")
        if kind == "contains":
            text = open(p, encoding="utf-8", errors="replace").read()
            m = re.search(extra, text, re.M)
            return res(rid, kind, arg, m, f"match: {m.group(0)[:200]!r}" if m else "no match")
        if kind == "links":
            text = open(p, encoding="utf-8", errors="replace").read()
            refs = []
            if p.endswith((".html", ".htm")):
                e = Elements()
                e.feed(text)
                refs = e.refs
            refs += re.findall(r"\]\(([^)\s]+)\)", text)
            base = os.path.dirname(p)
            broken = [r for r in refs if local_ref(r) and not os.path.exists(os.path.join(base, r.split("#")[0].split("?")[0]))]
            return res(rid, kind, arg, not broken, f"{len(refs)} refs, broken: {broken[:20]}")
        if kind == "html":
            e = Elements()
            e.feed(open(p, encoding="utf-8", errors="replace").read())
            m = re.match(r"^([a-zA-Z][\w-]*)?(?:#([\w-]+))?(?:\.([\w-]+))?$", extra)
            if not m:
                return res(rid, kind, arg, False, f"unsupported selector {extra!r}")
            tag, eid, cls = m.groups()
            found = [x for x in e.els if (not tag or x[0] == tag.lower()) and (not eid or x[1] == eid) and (not cls or cls in x[2])]
            return res(rid, kind, arg, found, f"{len(found)} element(s) match {extra}")
        if kind == "json":
            d = json.load(open(p, encoding="utf-8"))
            if extra in ("", "."):
                return res(rid, kind, arg, True, "valid JSON")
            cur = d
            for k in extra.split("."):
                if isinstance(cur, list) and k.isdigit() and int(k) < len(cur):
                    cur = cur[int(k)]
                elif isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    return res(rid, kind, arg, False, f"key path {extra} missing at {k!r}")
            return res(rid, kind, arg, True, f"{extra} = {json.dumps(cur)[:200]}")
        if kind == "pdf_pages":
            n = pdf_page_count(p)
            want = extra.replace(" ", "")
            ok = n is not None and (n <= int(want[2:]) if want.startswith("<=") else n == int(want))
            return res(rid, kind, arg, ok, f"{n} page(s), need {want}")
        if kind in ("stl_bbox", "stl_manifold"):
            tris = stl_triangles(p)
            if not tris:
                return res(rid, kind, arg, False, "no triangles")
            if kind == "stl_bbox":
                xs, ys, zs = [t[i] for t in tris for i in (0, 3, 6)], [t[i] for t in tris for i in (1, 4, 7)], [t[i] for t in tris for i in (2, 5, 8)]
                size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
                want = [float(x) for x in extra.split(",")]
                tol = want[3] if len(want) > 3 else 0.1
                ok = all(abs(a - b) <= tol for a, b in zip(size, want[:3]))
                return res(rid, kind, arg, ok, f"bbox {tuple(round(x, 3) for x in size)}, need {tuple(want[:3])} ± {tol}")
            edges = {}
            key = lambda v: tuple(round(c, 4) for c in v)
            for t in tris:
                vs = [key(t[0:3]), key(t[3:6]), key(t[6:9])]
                for a, b in ((0, 1), (1, 2), (2, 0)):
                    e = tuple(sorted((vs[a], vs[b])))
                    edges[e] = edges.get(e, 0) + 1
            bad = sum(1 for c in edges.values() if c != 2)
            return res(rid, kind, arg, bad == 0, f"{len(tris)} triangles, {len(edges)} edges, {bad} edge(s) not shared by exactly 2")
        if kind == "brand_tokens":
            if extra.startswith("#"):
                palette = hex_colors(extra)
            else:
                pal = json.load(open(path_of(extra, cwd), encoding="utf-8"))
                vals = pal if isinstance(pal, list) else pal.get("colors", list(pal.values()) if isinstance(pal, dict) else [])
                palette = hex_colors(" ".join(str(v) for v in vals))
            used = hex_colors(open(p, encoding="utf-8", errors="replace").read())
            off = sorted(used - palette)
            return res(rid, kind, arg, not off, f"{len(used)} colour(s) used, off-palette: {off[:20]}")
        if kind == "html_viewport":
            text = open(p, encoding="utf-8", errors="replace").read()
            vp = re.search(r"<meta[^>]+name=[\"']viewport[\"'][^>]*width=device-width", text, re.I)
            wide = [int(w) for w in re.findall(r"(?<![\w-])(?:min-)?width\s*:\s*(\d+)px", text) if int(w) > 375]
            return res(rid, kind, arg, bool(vp) and not wide, f"viewport meta: {'yes' if vp else 'missing'}; fixed widths > 375px: {wide[:10]}")
        if kind == "image":
            size = image_size(p)
            w, h = (int(x) for x in extra.lower().split("x")) if extra else (1, 1)
            return res(rid, kind, arg, size and size[0] >= w and size[1] >= h, f"size {size}, need >= {w}x{h}")
    except Exception as ex:  # a broken check is a failed check, never a pass
        return res(rid, kind, arg, False, f"{type(ex).__name__}: {ex}")
    return res(rid, kind, arg, False, "unknown check")


def checks_section(contract):
    found = re.findall(r"^## Checks[^\n]*\n(.*?)(?=^## |\Z)", contract, re.S | re.M)  # every Checks section counts
    body = re.sub(r"<!--.*?-->", "", "\n".join(found), flags=re.S)
    return [(a, b, c.strip()) for a, b, c in LINE.findall(body)]


def run(contract, cwd):
    return [run_one(rid, kind, arg, cwd) for rid, kind, arg in checks_section(contract)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session")
    ap.add_argument("--check")
    ap.add_argument("--cwd", default=os.getcwd())
    a = ap.parse_args()
    if a.session:
        d = os.path.join(B.SESSIONS, a.session)
        contract = open(os.path.join(d, "contract.md"), encoding="utf-8").read()
        cwd = B.load_json(os.path.join(d, "meta.json"), {}).get("cwd") or B.ROOT
        out = run(contract, cwd)
    elif a.check:
        out = run("## Checks\n- " + a.check.strip().lstrip("- ") + "\n", a.cwd)
    else:
        ap.error("give --session or --check")
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0 if out and all(r["pass"] for r in out) else 1


if __name__ == "__main__":
    sys.exit(main())
