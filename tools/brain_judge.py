#!/usr/bin/env python3
"""
brain_judge.py — blind cross-vendor judgment of a session's deliverable (layer 8, Tier 0 + Tier 2).

    python3 -I brain_judge.py --session <id> [--artifacts file ...] [--vendor auto|codex|claude] [--dry-run]
    python3 -I brain_judge.py --session <id> [--artifacts file ...] --preflight     # no model call, no verdict file

- Tier 0: runs the optional "## Checks" lines of the contract (`- R1: cmd: <command>`), records exit codes.
- Tier 2: builds a sealed packet from FILES ONLY (contract + artifacts + Tier-0 results; never checkpoints or
  chat; the maker's own summaries go in under a heading that marks them as claims to verify) in an empty temp folder and asks the OTHER vendor's CLI, read-only, for a verdict per
  hard requirement (pass / fail / inconclusive / not_checked). Typed Tier-1 questions start once gold sets
  exist; until then every question escalates here (cold start, layer 8).
- Writes sessions/<id>/verdict-NN.json and appends sessions/<id>/judge.md.
v3 "Fable Art": a failed Tier-0 check ends the round at once (fail) without calling the other vendor, since a model
never overrides Tier 0 (--force-tier2 calls it anyway); a judge health check older than 14 days counts as unverified.
v6 "Clearwater" — the judge brief. The judge is told exactly:
  0 what it received  a manifest of every input: bytes, hash, and whether it is shown in full, as an excerpt (which
                      characters are cut) or not inlined at all (binary, image) and where the full original sits in the
                      sealed folder (./artifacts/NN-name). Nothing is cut silently any more.
  1 the goal          the frozen contract plus a requirement ledger: id, text, its check, its Tier-0 result.
  2 the errors        failed Tier-0 checks, error-looking command results from evidence.jsonl (with "clean rerun later:
                      yes/no"), hook warnings, and what the previous judge round found, to be re-checked one by one.
  3 what changed      files the session edited, and which of them were NOT submitted.
  4 the lenses        what usually goes wrong in this scope class (judge/lenses.json); for flaws, never for a verdict.
The judge's answer is then checked by code: every requirement of the contract must have a verdict (a missing one becomes
not_checked and a "pass" becomes inconclusive), a "pass" may not sit above a failing blocker, and quoted evidence that is
not in the packet is flagged. The maker gets a fix list back, so a failed round costs one read, not a re-derivation.
Exit: 0 pass · 1 fail · 2 inconclusive or judge unavailable.
Fake CLIs for tests: BRAIN_CODEX_BIN / BRAIN_CLAUDE_BIN. Models: judge/config.json.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

VERDICT_ITEM = {"type": "object", "additionalProperties": False,
                "required": ["requirement", "verdict", "evidence", "severity", "fix"],
                "properties": {"requirement": {"type": "string"},
                               "verdict": {"type": "string", "enum": ["pass", "fail", "inconclusive", "not_checked"]},
                               "evidence": {"type": "string"},
                               "severity": {"type": "string", "enum": ["blocker", "major", "minor", "none"]},
                               "fix": {"type": "string"}}}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["overall", "verdicts", "flaws", "inputs_missing", "unsupported_claims"],
          "properties": {"overall": {"type": "string", "enum": ["pass", "fail", "inconclusive"]},
                         "verdicts": {"type": "array", "items": VERDICT_ITEM},
                         "flaws": {"type": "array", "items": {"type": "string"}},
                         "inputs_missing": {"type": "array", "items": {"type": "string"}},
                         "unsupported_claims": {"type": "array", "items": {"type": "string"}}}}
INSTRUCTION = (
    "You are a blind judge. Judge ONLY from this packet and the files in ./artifacts/ (the sealed copies it lists). "
    "Work in this order.\n"
    "1. Read section 0 (what you received). If an input you need is cut, binary or absent, open its sealed copy "
    "(./artifacts/SEALED.txt lists the copies that really exist); if you "
    "still cannot see it, answer not_checked for that requirement and name the input in inputs_missing. Never guess.\n"
    "2. For EVERY hard requirement in the requirement ledger give one verdict: pass, fail, inconclusive (evidence "
    "insufficient) or not_checked (you cannot check it from what you received, e.g. visual quality without a render). "
    "Start `requirement` with its id (R1 ...). Quote the evidence exactly as it appears. A failed Tier-0 check is a fail.\n"
    "3. Section 2 lists errors and what the previous round found. Say for each previous finding whether it is fixed.\n"
    "4. The maker's summaries are claims. A claim that no artifact supports goes into unsupported_claims, word for word.\n"
    "5. For every verdict that is not pass, `fix` says the smallest concrete change that would make it pass (\"\" for pass).\n"
    "The lenses are hints for `flaws` only: never fail a requirement because of a lens. Never assume. "
    "Answer only with JSON matching the schema.")
MAX_FILE, MAX_PACKET = 40000, 120000
SEALED_ONLY = object()  # marker: an artifact the maker sends as a sealed copy without inlining it
UNREADABLE = object()   # marker: the file exists but could not be read
SEAL_FILE_MAX, SEAL_TOTAL_MAX = 25 * 1024 * 1024, 80 * 1024 * 1024
HEALTH_DAYS = int(os.environ.get("BRAIN_JUDGE_HEALTH_DAYS", "14"))
CLAIMS = ("task-summary.md", "brain-summary.md", "report.md")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".svg")
ERR_RX = re.compile(r"Traceback \(most recent|\b\w*(?:Error|Exception)\b\s*[:(]|\berror[:\s]|\bFAILED\b|\bFAIL\b|\bfatal:|"
                    r"command not found|No such file or directory|exit (?:code|status) [1-9]|npm ERR!|✗|Permission denied", re.I)
SOFT_ERR_RX = re.compile(r"No such file or directory|command not found|Traceback \(most recent|Permission denied|cannot access", re.I)
BRAIN_CMD_RX = re.compile(r"brain(?:_session|_fetch|_judge|_route|_learn|_map)?\.py\b")
EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "ApplyPatch")


def health_fresh(checked):
    """v3 (B6): "STRONG" from a check older than HEALTH_DAYS is no longer evidence (flaw H51)."""
    t = B.local_epoch(str(checked) + ":00" if len(str(checked)) == 16 else checked)
    return bool(t) and t > __import__("time").time() - HEALTH_DAYS * 86400


def tier0(contract, cwd):
    """Tier 0 = tools/tier0.py (cmd, exists, contains, links, html, json, image, vault checks)."""
    import tier0 as T0
    return T0.run(contract, cwd)


def _section(text, name):
    m = re.search(r"^## " + re.escape(name) + r"[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def requirements(contract):
    """[(id, text, check)] from the contract's hard requirements."""
    out = []
    for rid, text in re.findall(r"^[ \t]*-[ \t]*(R\d+)[ \t]*:(.*)$", _section(contract, "Hard requirements"), re.M):
        m = re.search(r"\s*[—–-]?\s*check\s*:\s*(.*)$", text, re.I)
        out.append((rid, (text[:m.start()] if m else text).strip(), (m.group(1).strip() if m else "")))
    return out


def _read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except OSError:
        pass
    return rows


def error_events(ev_rows, limit=8):
    """(open, resolved_count): error-looking shell results the hook recorded. A later run of the same command with a
    clean tail counts as resolved. The brain's own commands are left out: their arguments can carry the maker's notes."""
    shell = [r for r in ev_rows if r.get("tool") == "Bash" and not BRAIN_CMD_RX.search(str(r.get("command", "")))]
    key = lambda r: re.sub(r"\s+", " ", str(r.get("command", "")))[:80]
    bad = lambda r: bool(r.get("interrupted")) or bool(ERR_RX.search(str(r.get("stderr_tail") or "") + "\n" + str(r.get("stdout_tail") or "")))
    open_, resolved = [], 0
    for i, r in enumerate(shell):
        if not bad(r):
            continue
        if any(key(x) == key(r) and not bad(x) for x in shell[i + 1:]):
            resolved += 1
        else:
            open_.append(r)
    return open_[-limit:], resolved


def changed_files(ev_rows, sdir_):
    """{path: edits} for files the session edited (edit tools and Codex patches), without the session's own folder."""
    out = {}
    own = f"/sessions/{os.path.basename(sdir_.rstrip(os.sep))}/"  # the session's folder, also under another brain root
    skip = (os.path.realpath(sdir_) + os.sep, "/tmp/", "/private/tmp/",
            os.path.expanduser("~/.claude") + os.sep, os.path.expanduser("~/.codex") + os.sep)
    for r in ev_rows:
        if r.get("tool") not in EDIT_TOOLS:
            continue
        for f in ([r.get("file")] if r.get("file") else []) + list(r.get("files") or []):
            f = os.path.realpath(os.path.expanduser(str(f)))
            if f and not f.startswith(skip) and own not in f:
                out[f] = out.get(f, 0) + 1
    return out


def previous_round(d):
    """The last verdict file of this session, reduced to what the next judge must re-check."""
    vs = sorted(f for f in os.listdir(d) if f.startswith("verdict-") and f.endswith(".json"))
    if not vs:
        return None
    rec = B.load_json(os.path.join(d, vs[-1]), {}) or {}
    v = rec.get("verdict") or {}
    items = [f"Tier-0 check {r.get('requirement')} failed: `{str(r.get('command', ''))[:120]}` — {str(r.get('tail', '')).strip()[-200:]}"
             for r in rec.get("tier0") or [] if r.get("exit") not in (0, None)]
    for r in v.get("verdicts") or []:
        if r.get("verdict") != "pass":
            items.append(f"{str(r.get('requirement', ''))[:90]} → {r.get('verdict')} ({r.get('severity')}): "
                         f"{str(r.get('evidence', ''))[:260]}" + (f" | asked fix: {str(r.get('fix'))[:200]}" if r.get("fix") else ""))
    items += [f"flaw: {str(x)[:240]}" for x in (v.get("flaws") or [])[:8]]
    items += [f"unsupported claim: {str(x)[:200]}" for x in (v.get("unsupported_claims") or [])[:6]]
    return {"file": vs[-1], "round": len(vs), "items": items, "called": rec.get("tier2")}


def lenses(scope):
    data = B.load_json(os.path.join(B.JUDGE, "lenses.json"), {})
    return [str(x) for x in (data.get(scope) or data.get("general") or [])][:8]


def sealed_names(artifacts):
    """A stable name for every artifact inside the judge's folder: ./artifacts/NN-basename."""
    return {p: f"artifacts/{i:02d}-{os.path.basename(p) or 'file'}" for i, p in enumerate(artifacts, 1)}


def seal_plan(artifacts):
    """The artifacts that get a sealed copy (size limits applied in order). packet() and seal() both use it, so the
    manifest never advertises a copy that is not there (found by judge round 2 of the v6 session)."""
    ok, total = [], 0
    for p in artifacts:
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        # v7 (Argon, round 4): unreadable counts as not sealable, so --dry-run and --preflight tell the truth too
        if os.path.isfile(p) and os.access(p, os.R_OK) and size <= SEAL_FILE_MAX and total + size <= SEAL_TOTAL_MAX:
            ok.append(p)
            total += size
    return ok


def _budgets(lengths, total):
    """Share `total` characters fairly: a short file is shown whole, long files split what is left."""
    out, left, order = {}, total, sorted(range(len(lengths)), key=lambda i: lengths[i])
    for n, i in enumerate(order):
        share = max(0, left) // (len(order) - n)
        out[i] = min(lengths[i], MAX_FILE, share)
        left -= out[i]
    return [out[i] for i in range(len(lengths))]


def _excerpt(text, budget):
    """(shown text, note) — head and tail of a file that does not fit, with the cut named."""
    if len(text) <= budget:
        return text, None
    head = int(budget * 0.7)
    tail = budget - head
    a, b = head, len(text) - tail
    return (text[:head] + f"\n…[CUT: characters {a + 1}–{b} of {len(text)} are not shown here]…\n" + (text[b:] if tail else ""),
            f"excerpt: {budget} of {len(text)} chars (characters {a + 1}–{b} cut)")


def packet(contract, artifacts, t0, d=None, scope="general", sealed_only=()):
    """The judge brief. Returns (text, manifest rows). `sealed_only`: artifacts listed and sealed, but not inlined."""
    sealed_only = set(sealed_only)
    sdir_ = d or (os.path.dirname(artifacts[-1]) if artifacts else "")
    names = sealed_names(artifacts)
    claims = [x for x in artifacts if os.path.basename(x) in CLAIMS and os.path.dirname(x) == sdir_]
    ordered = [x for x in artifacts if x not in claims] + claims
    ev_rows = _read_jsonl(os.path.join(sdir_, "evidence.jsonl")) if sdir_ else []
    reqs = requirements(contract)
    t0_by = {}
    for r in t0:
        t0_by.setdefault(str(r.get("requirement")), []).append(r)

    # ---- fixed sections first, so the artifact budget is what is really left ----
    goal = ["## 1 Goal — the contract (frozen, verbatim)", contract.strip(), "", "### Requirement ledger (one verdict per row)",
            "| id | requirement | its check | Tier 0 |", "|---|---|---|---|"]
    for rid, text, check in reqs:
        res = t0_by.get(rid) or []
        state = "; ".join(("FAIL" if r.get("exit") != 0 else "PASS?" if r.get("kind") == "cmd" and SOFT_ERR_RX.search(str(r.get("tail", ""))) else "PASS")
                          + f" ({r.get('kind', 'cmd')})" for r in res) or "no Tier-0 check: judge from the artifacts"
        goal.append(f"| {rid} | {text[:200].replace('|', '/')} | {check[:140].replace('|', '/') or '(none named)'} | {state} |")
    if not reqs:
        goal.append("| - | (the contract names no hard requirement in the R<n> form) | - | - |")

    errs = ["## 2 Errors and risk signals (machine records; evidence of what ran, not of correctness)", "### Tier-0 check results"]
    errs += [f"- {r['requirement']}: `{r['command']}` → exit {r['exit']}"
             + (" ⚠ exit 0, but the output looks like an error: this check proves nothing by itself, judge the requirement from the artifacts"
                if r.get("exit") == 0 and r.get("kind") == "cmd" and SOFT_ERR_RX.search(str(r.get("tail", ""))) else "")
             + f"\n```\n{r['tail']}\n```" for r in t0] or ["- none"]
    open_err, resolved = error_events(ev_rows)
    errs.append("### Command results that look like errors")
    for r in open_err:
        tail = (str(r.get("stderr_tail") or "").strip() or str(r.get("stdout_tail") or "").strip())[-240:]
        errs.append(f"- {r.get('t', '?')} `{re.sub(chr(10), ' ', str(r.get('command', '')))[:160]}`" + (" (interrupted)" if r.get("interrupted") else "")
                    + f" — no clean rerun recorded\n```\n{tail}\n```")
    if not open_err:
        errs.append("- none open" + ("" if ev_rows else " (this session has no evidence log, so absence proves nothing)"))
    if resolved:
        errs.append(f"- {resolved} other error result(s) were followed by a clean rerun of the same command")
    warns = sorted({str(r["warn"]) for r in ev_rows if r.get("warn")})
    if warns:
        errs += ["### Process warnings"] + [f"- {w[:200]}" for w in warns[:6]]
    prev = previous_round(sdir_) if sdir_ and os.path.isdir(sdir_) else None
    if prev:
        errs.append(f"### Previous judge round ({prev['file']}) found — re-check each one and say whether it is fixed")
        errs += [f"- {x}" for x in prev["items"][:14]] or ["- nothing recorded (the round gave no usable verdict)"]

    changed = changed_files(ev_rows, sdir_) if sdir_ else {}
    submitted = {os.path.realpath(x) for x in artifacts}
    chg = ["## 3 What the session changed"]
    if changed:
        not_sub = sorted(p for p in changed if p not in submitted)
        chg.append(f"- {len(changed)} file(s) edited; {len(changed) - len(not_sub)} of them submitted in this packet.")
        if not_sub:
            chg.append("- Edited but NOT submitted (you cannot see them; if a requirement depends on one, answer not_checked and name it in inputs_missing):")
            chg += [f"  - {p} ({changed[p]} edit(s))" for p in not_sub[:15]] + ([f"  - … and {len(not_sub) - 15} more"] if len(not_sub) > 15 else [])
    else:
        chg.append("- no edit records (no evidence log, or the work was done by shell commands only)")

    lens = ["## 4 Lenses for scope `" + scope + "` (hints for flaws only; never a reason to fail a requirement)"] + [f"- {x}" for x in lenses(scope)]

    close = ["## Session closeout files (existence and size, so the judge never has to guess)"]
    for f in CLAIMS:
        hit = [x for x in artifacts if os.path.basename(x) == f]
        close.append(f"- {f}: " + (f"present, {os.path.getsize(hit[0])} bytes (full text below)" if hit else "absent"))

    # ---- artifacts: read, budget, excerpt; every cut is named in the manifest ----
    loaded = []
    for path in ordered:
        if not os.path.isfile(path):
            loaded.append((path, None, None))
            continue
        try:
            data = open(path, "rb").read()
        except OSError:  # v7: exists but cannot be read: say so, never crash, never advertise a sealed copy
            loaded.append((path, None, UNREADABLE))
            continue
        if path in sealed_only:
            loaded.append((path, data, SEALED_ONLY))
            continue
        try:
            loaded.append((path, data, data.decode("utf-8")))
        except UnicodeDecodeError:
            loaded.append((path, data, None))
    fixed = len(INSTRUCTION) + sum(len(x) + 1 for x in goal + errs + chg + lens + close) + 1200 + 170 * len(ordered)
    text_idx = [i for i, (_, _, t) in enumerate(loaded) if t is not None and t is not SEALED_ONLY and t is not UNREADABLE]
    room = max(4000, MAX_PACKET - fixed)
    for _ in range(4):  # the overhead of headings and manifest rows is only known once rendered: render, measure, tighten
        text, manifest = _render(loaded, names, claims, text_idx, room, goal, errs, chg, lens, close, t0, ev_rows, prev)
        over = len(text) + len(INSTRUCTION) + 2 - MAX_PACKET
        if over <= 0:
            return text, manifest
        room = max(2000, room - over - 600)
    text = text[:MAX_PACKET - len(INSTRUCTION) - 200] + "\n…[PACKET CUT at the size cap: later artifacts above are incomplete; open the sealed copies]…"
    for m in manifest:  # cannot happen with ordinary inputs; if it does, every row says so instead of a silent cut
        m["shown"] += " (packet hit its size cap: verify against the sealed copy)"
    return text, manifest


def _render(loaded, names, claims, text_idx, room, goal, errs, chg, lens, close, t0, ev_rows, prev):
    """One rendering of the brief with `room` characters shared between the text artifacts."""
    budget = dict(zip(text_idx, _budgets([len(loaded[i][2]) for i in text_idx], room)))
    sealable = set(seal_plan([p for p, data, _ in loaded if data is not None]))  # unreadable and missing files are never in it
    manifest, art, shown_claims_head = [], ["## 5 Artifacts"], False
    for i, (path, data, text) in enumerate(loaded):
        seal = names[path]
        if claims and path == claims[0] and not shown_claims_head:  # v3 (B7): the maker's own account is a claim to check, never evidence
            art += ["", "## The maker's own summaries (claims to verify against the artifacts above; not evidence)"]
            shown_claims_head = True
        kind = "maker claim" if path in claims else "artifact"
        if data is None and text is UNREADABLE:
            art.append(f"### {path}\n(unreadable: the file exists but could not be opened; answer not_checked for what depends on it)")
            manifest.append({"path": path, "kind": kind, "bytes": None, "shown": "UNREADABLE: the file exists but could not be opened", "sealed": None})
            continue
        if data is None:
            art.append(f"### {path}\n(missing)")
            manifest.append({"path": path, "kind": kind, "bytes": None, "shown": "MISSING: the maker named it, it does not exist", "sealed": None})
            continue
        if path not in sealable:  # too large for the sealed folder: say so; never point at a copy that is not there
            if text is SEALED_ONLY:
                text = None
            what = "image/PDF" if path.lower().endswith(IMAGE_EXT) else ("binary" if text is None else "text")
            note = f"NOT SEALED (over the {SEAL_FILE_MAX // 1048576} MB per file / {SEAL_TOTAL_MAX // 1048576} MB total limit)"
            body, cut = _excerpt(text, budget.get(i, MAX_FILE)) if text is not None else ("", None)
            art.append(f"### {path}  (sha256 {B.sha256_bytes(data)[:16]}…, {len(data)} bytes, {note})"
                       + ("\n```\n" + body + "\n```" if text is not None else f"\n({what} file; not shown and not sealed: answer not_checked for what depends on it)"))
            manifest.append({"path": path, "kind": kind, "bytes": len(data), "sealed": None,
                             "shown": (f"{cut}; {note}" if cut else f"full; {note}") if text is not None else f"not inlined ({what}); {note}"})
            continue
        head = f"### {path}  (sha256 {B.sha256_bytes(data)[:16]}…, {len(data)} bytes, sealed copy ./{seal})"
        if text is SEALED_ONLY and path in sealable:
            art.append(head + f"\n(sent as a sealed copy only, by the maker's choice, to keep the packet for the documents: open ./{seal})")
            manifest.append({"path": path, "kind": kind, "bytes": len(data), "shown": f"not inlined (sealed only); open ./{seal}", "sealed": seal})
            continue
        if text is None:
            what = "image/PDF" if path.lower().endswith(IMAGE_EXT) else "binary"
            art.append(head + f"\n({what} file; not shown — open ./{seal} to look at it; if you cannot, the judge must answer not_checked for properties it cannot see)")
            manifest.append({"path": path, "kind": kind, "bytes": len(data), "shown": f"not inlined ({what}); open ./{seal}", "sealed": seal})
            continue
        body, note = _excerpt(text, budget.get(i, MAX_FILE))
        art.append(head + "\n```\n" + body + ("\n…(truncated)" if note else "") + "\n```")
        manifest.append({"path": path, "kind": kind, "bytes": len(data), "sealed": seal,
                         "shown": "full" if not note else note + f"; full file: ./{seal}"})

    man = ["## 0 What you received (manifest — check it before judging)", "| # | input | kind | bytes | shown |", "|---|---|---|---|---|"]
    man += [f"| {n} | {m['path']} | {m['kind']} | {m['bytes'] if m['bytes'] is not None else '-'} | {m['shown']} |" for n, m in enumerate(manifest, 1)]
    if not manifest:
        man.append("| - | (no artifact was submitted: only the contract and the Tier-0 results) | - | - | - |")
    man += ["", f"Also in this packet: the frozen contract, {len(t0)} Tier-0 result(s), {len(ev_rows)} evidence-log record(s) reduced to "
            f"errors and edited files" + (f", the findings of judge round {prev['round']}" if prev else "") + ".",
            "NOT in this packet, by design: the chat, the maker's reasoning and checkpoints, and any file not listed above."]

    parts = ["# Judge packet", ""] + man + [""] + goal + [""] + errs + [""] + chg + [""] + lens + [""] + close + [""] + art
    return "\n".join(parts), manifest


def parse_verdict(raw):
    def find(o):
        if isinstance(o, dict):
            if o.get("overall") in ("pass", "fail", "inconclusive") and isinstance(o.get("verdicts"), list):
                return o
            for k in ("structured_output", "result", "response"):
                v = o.get(k)
                if isinstance(v, str):
                    try:
                        v = json.loads(v)
                    except ValueError:
                        v = None
                r = find(v) if v is not None else None
                if r:
                    return r
        return None
    try:
        return find(json.loads(raw))
    except ValueError:
        o = B.last_json(raw, lambda x: find(x) is not None)  # v2.1 (O14): last JSON object, not a greedy regex
        return find(o) if o else None
    return None


def quoted(text):
    """The quoted passages of an evidence string, 20-200 characters each. Quotes are paired in order (the text between
    a closing quote and the next opening quote is the judge's own prose, not a quote: round 3 of the v6 session was
    flagged for exactly that)."""
    # v7 (Argon, round 4): an escaped quote is not a delimiter, and a backticked span is taken out before the
    # double quotes are paired, so `{"a": "b"}` in backticks no longer turns the prose around it into a "quote".
    text = text.replace('\\"', "\x01").replace("\\`", "\x02")
    ticks = text.split("`")
    spans = ticks[1::2] if len(ticks) % 2 == 1 else ticks[1:-1:2]
    rest = " ".join(ticks[0::2]) if len(ticks) % 2 == 1 else text
    parts = rest.split('"')
    out = spans + (parts[1::2] if len(parts) % 2 == 1 else parts[1:-1:2]) + re.findall(r"“([^”]*)”", text)
    clean = (re.sub(r"\s+", " ", x.replace("\x01", '"').replace("\x02", "`")).strip() for x in out)
    return [q for q in clean if 20 <= len(q) <= 200]


def review_verdict(verdict, contract, brief, corpus=""):
    """v6: the judge's own answer is checked by code. Returns (verdict, warnings). Nothing here can turn a fail into a pass.
    `corpus` = the full text of the artifacts: a quote the judge read in a sealed copy (beyond the excerpt) is real evidence."""
    warnings = []
    if not verdict:
        return verdict, warnings
    rows = [r for r in verdict.get("verdicts") or [] if isinstance(r, dict)]
    seen = {m.group(1) for r in rows for m in [re.search(r"\b(R\d+)\b", str(r.get("requirement", "")))] if m}
    missing = [rid for rid, _, _ in requirements(contract) if rid not in seen]
    for rid in missing:
        rows.append({"requirement": rid, "verdict": "not_checked", "severity": "major", "fix": "judge this requirement",
                     "evidence": "(added by brain_judge.py: the judge returned no verdict for this requirement)"})
    if missing:
        warnings.append("no verdict for: " + ", ".join(missing))
        if verdict.get("overall") == "pass":
            verdict["overall"] = "inconclusive"
            warnings.append("overall pass → inconclusive: a requirement without a verdict is not a pass")
    if verdict.get("overall") == "pass" and any(r.get("verdict") == "fail" and r.get("severity") in ("blocker", "major") for r in rows):
        verdict["overall"] = "fail"
        warnings.append("overall pass → fail: the judge's own verdicts hold a failed blocker/major requirement")
    flat = re.sub(r"\s+", " ", brief + "\n" + (corpus or ""))
    for r in rows:
        if r.get("verdict") != "pass":
            continue
        quotes = quoted(str(r.get("evidence", "")))
        lost = [q for q in quotes if q not in flat]
        if lost:  # every quote is checked on its own: one real quote does not cover an invented one (judge round 3)
            warnings.append(f"{str(r.get('requirement', ''))[:20]}: {len(lost)} of {len(quotes)} quote(s) found neither in the packet nor "
                            f"in the artifacts (check it): {lost[0][:80]!r}")
        if lost and len(lost) == len(quotes):  # v7 (Argon, round 4): a pass that rests only on quotes nobody can find is not a pass
            r["verdict"] = "inconclusive"
            r["evidence"] = str(r.get("evidence", "")) + " [brain_judge.py: none of the quoted evidence is in the packet or the artifacts]"
    open_rows = [str(r.get("requirement", ""))[:24] for r in rows if r.get("verdict") != "pass"]
    if verdict.get("overall") == "pass" and open_rows:  # found by judge round 2 of the v6 session
        verdict["overall"] = "inconclusive"
        warnings.append("overall pass → inconclusive: not every requirement passed (" + ", ".join(open_rows[:6]) + ")")
    verdict["verdicts"] = rows
    return verdict, warnings


def seal(tmp, artifacts):
    """Copy the artifacts into the judge's folder so it can open what the packet could not show (long files, images)."""
    names, copied = sealed_names(artifacts), []
    os.makedirs(os.path.join(tmp, "artifacts"), exist_ok=True)
    for p in seal_plan(artifacts):
        try:
            shutil.copyfile(p, os.path.join(tmp, names[p]))
            copied.append(names[p])
        except OSError:
            continue
    with open(os.path.join(tmp, "artifacts", "SEALED.txt"), "w", encoding="utf-8") as fh:  # what is really in this folder
        fh.write("\n".join(copied) + "\n")
    return len(copied)


def unseal(text, manifest, failed, names):
    """A copy that was planned but could not be made: the packet and the manifest stop pointing at it (judge round 3)."""
    for p in failed:
        text = text.replace(f"./{names[p]}", "[NOT SEALED: the copy failed]")
        for m in manifest:
            if m["path"] == p:
                m["sealed"] = None
                m["shown"] = m["shown"].replace(f"./{names[p]}", "[NOT SEALED: the copy failed]") + " (NOT SEALED: the copy failed)"
    return text, manifest


def prepare(artifacts, text, manifest):
    """The judge's folder, sealed BEFORE the packet is final, so the packet only names copies that exist."""
    tmp = tempfile.mkdtemp(prefix="brain-judge-")
    seal(tmp, list(artifacts))
    names = sealed_names(list(artifacts))
    try:
        have = set(open(os.path.join(tmp, "artifacts", "SEALED.txt"), encoding="utf-8").read().split("\n"))
    except OSError:
        have = set()
    failed = [p for p in seal_plan(list(artifacts)) if names[p] not in have]
    if failed:
        text, manifest = unseal(text, manifest, failed, names)
    return tmp, text, manifest


def call(vendor, text, cfg, timeout, artifacts=(), tmp=None):
    if tmp is None:
        tmp = tempfile.mkdtemp(prefix="brain-judge-")
        seal(tmp, list(artifacts))
    try:
        schema_p = os.path.join(tmp, "schema.json")
        with open(schema_p, "w") as fh:
            json.dump(SCHEMA, fh)
        pk = os.path.join(tmp, "packet.md")
        with open(pk, "w", encoding="utf-8") as fh:
            fh.write(INSTRUCTION + "\n\n" + text)
        if vendor == "codex":
            exe = os.environ.get("BRAIN_CODEX_BIN", "codex")
            out_p = os.path.join(tmp, "out.json")
            cmd = [exe, "exec", "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check",
                   "--output-schema", schema_p, "-o", out_p]
            if cfg.get("codex_model"):
                cmd += ["--model", cfg["codex_model"]]
            cmd += ["-"]
            with open(pk, encoding="utf-8") as fin:
                p = subprocess.run(cmd, cwd=tmp, stdin=fin, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, BRAIN_OFF="1"))
            raw = open(out_p, encoding="utf-8").read() if os.path.exists(out_p) else p.stdout
        else:
            exe = os.environ.get("BRAIN_CLAUDE_BIN", "claude")
            cmd = [exe, "-p", open(pk, encoding="utf-8").read(), "--model", cfg.get("claude_model", "sonnet"),
                   "--allowedTools", "Read", "--permission-mode", "dontAsk", "--output-format", "json",
                   "--json-schema", json.dumps(SCHEMA)]
            p = subprocess.run(cmd, cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=dict(os.environ, BRAIN_OFF="1"))
            raw = p.stdout
        return parse_verdict(raw), (raw[-2000:] if raw else p.stderr[-2000:])
    except subprocess.TimeoutExpired:
        return None, f"judge timed out after {timeout}s"
    except OSError as e:
        return None, f"judge CLI could not start: {e}"
    finally:
        pass  # never delete: the temp folder (packet + schema + sealed copies) is left for macOS's own temp cleanup


def fix_list(verdict, t0):
    """What the maker has to do next, in one place: failed checks first, then the judge's non-pass verdicts."""
    out = [{"requirement": r["requirement"], "verdict": "fail (Tier 0)", "fix": f"make `{str(r['command'])[:120]}` pass: {str(r['tail']).strip()[-160:]}"}
           for r in t0 if r.get("exit") not in (0, None)]
    for r in (verdict or {}).get("verdicts") or []:
        if r.get("verdict") != "pass":
            out.append({"requirement": str(r.get("requirement", ""))[:80], "verdict": r.get("verdict"),
                        "fix": str(r.get("fix") or r.get("evidence") or "")[:300]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--artifacts", nargs="*", default=[])
    ap.add_argument("--sealed-only", nargs="*", default=[], metavar="FILE",
                    help="v6: artifacts that go to the judge as sealed copies only (listed in the manifest, not inlined), so long "
                         "code files do not push the documents out of the packet")
    ap.add_argument("--vendor", default="auto", choices=["auto", "codex", "claude"])
    ap.add_argument("--dry-run", action="store_true", help="build and print the packet only")
    ap.add_argument("--preflight", action="store_true", help="Tier 0 + what the judge would receive, as JSON; no model call, no verdict file")
    ap.add_argument("--export", metavar="DIR", help="v6: write a self-contained judge package (REQUEST.md with the instruction, schema and "
                    "packet; artifacts/ with the sealed copies) for a judge that is run by hand, e.g. another model; no model call")
    ap.add_argument("--record", metavar="FILE", help="v6: record the answer of a judge that was run by hand on an --export package "
                    "(a file holding its JSON verdict); Tier 0 runs again and the answer is checked like any other")
    ap.add_argument("--judge-name", default="external", help="with --record: who judged (e.g. argon)")
    ap.add_argument("--force-tier2", action="store_true", help="call the other vendor even though a Tier-0 check failed")
    a = ap.parse_args()
    d = os.path.join(B.SESSIONS, a.session)
    meta = B.load_json(os.path.join(d, "meta.json"), None)
    if not meta:
        sys.exit(f"unknown session {a.session}")
    contract = open(os.path.join(d, "contract.md"), encoding="utf-8").read()
    cfg = B.load_json(os.path.join(B.JUDGE, "config.json"), {})
    maker = meta.get("agent", "claude")
    vendor = a.vendor if a.vendor != "auto" else ("codex" if maker == "claude" else "claude")
    jh = B.load_json(os.path.join(B.TOOLS, "judge-health.json"), {})
    health = {j.get("cli"): j.get("status") for j in jh.get("judges", [])}
    strength = ("weak" if vendor == maker else "unverified" if health.get(vendor) != "STRONG" else
                "strong" if health_fresh(jh.get("checked")) else "unverified (health check stale)")
    artifacts = []
    sealed_only = {os.path.realpath(os.path.expanduser(x)) for x in a.sealed_only}
    for x in list(a.artifacts) + list(a.sealed_only):  # the same file named twice is one input
        rp = os.path.realpath(os.path.expanduser(x))
        if rp not in artifacts:
            artifacts.append(rp)
    # v2.1 (O14): the session's own report and both summaries always go in, whole, after the declared artifacts
    for f in ("report.md", "task-summary.md", "brain-summary.md"):
        fp = os.path.realpath(os.path.join(d, f))
        if os.path.exists(fp) and fp not in artifacts:
            artifacts.append(fp)
    t0 = tier0(contract, meta.get("cwd") or B.ROOT)
    import brain_session as S
    problems = S.lint(contract)
    t0.insert(0, {"requirement": "CONTRACT", "kind": "lint", "check": "REQ-TESTABLE + CONSTRAINT-QUOTED", "pass": not problems,
                  "exit": 0 if not problems else 1, "command": "brain_session.py lint", "tail": "; ".join(problems) or "ok"})
    sm = re.search(r"^scope_class:\s*(\w+)", contract, re.M)
    scope = sm.group(1) if sm else (meta.get("scope_class") or "general")
    text, manifest = packet(contract, artifacts, t0, d=os.path.realpath(d), scope=scope, sealed_only=sealed_only)
    if a.dry_run:
        print(text)
        return 0
    t0_failed = any(isinstance(r["exit"], int) and r["exit"] != 0 or r["exit"] == "timeout" for r in t0)
    cut = [m["path"] for m in manifest if m["shown"] != "full" and "(sealed only)" not in m["shown"]]
    if a.export:  # the same packet and sealed folder a CLI judge would get, as files someone can hand to any judge
        out_dir = os.path.realpath(os.path.expanduser(a.export))
        tmp, text, manifest = prepare(artifacts, text, manifest)
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, "artifacts")
        if os.path.exists(dst):
            sys.exit(f"{dst} already exists: choose an empty folder (nothing is overwritten or deleted)")
        shutil.copytree(os.path.join(tmp, "artifacts"), dst)
        B.atomic_write(os.path.join(out_dir, "schema.json"), json.dumps(SCHEMA, indent=1) + "\n")
        B.atomic_write(os.path.join(out_dir, "packet.md"), INSTRUCTION + "\n\n" + text + "\n")
        print(json.dumps({"exported": out_dir, "files": ["packet.md", "schema.json", "artifacts/"], "packet_chars": len(text),
                          "sealed": len(os.listdir(dst)) - 1, "not_shown_in_full": cut, "tier0_failed": [r["requirement"] for r in t0 if r["exit"] != 0]}, indent=1))
        return 0
    if a.preflight:  # v6: the cheap round before the expensive one — what would fail or go unseen, for zero tokens
        reqs = requirements(contract)
        checked = {str(r.get("requirement")) for r in t0}
        open_err, _ = error_events(_read_jsonl(os.path.join(d, "evidence.jsonl")))
        changed = changed_files(_read_jsonl(os.path.join(d, "evidence.jsonl")), os.path.realpath(d))
        out = {"ready": not t0_failed and bool([m for m in manifest if m["kind"] == "artifact" and m["bytes"]]),
               "tier0_failed": [r["requirement"] for r in t0 if r["exit"] != 0],
               "requirements_without_tier0_check": [rid for rid, _, _ in reqs if rid not in checked],
               "artifacts": len([m for m in manifest if m["kind"] == "artifact"]),
               "not_shown_in_full": cut, "missing_files": [m["path"] for m in manifest if m["bytes"] is None],
               "edited_but_not_submitted": sorted(p for p in changed if p not in set(artifacts))[:20],
               "open_error_results": len(open_err), "packet_chars": len(text), "fix_list": fix_list(None, t0)}
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0 if out["ready"] else 1
    if a.record:  # a judge someone ran by hand; never the maker's own vendor grading itself unnoticed
        try:
            raw = open(os.path.expanduser(a.record), encoding="utf-8").read()
        except OSError as e:
            sys.exit(f"cannot read {a.record}: {e}")
        verdict, tail = parse_verdict(raw), raw[-2000:]
        vendor = re.sub(r"[^\w.-]+", "-", a.judge_name.strip().lower()) or "external"
        strength = "by hand (not health-checked)" + (" — SAME VENDOR AS THE MAKER" if vendor == maker else "")
    elif t0_failed and not a.force_tier2:  # v3 (B5): no model call for a round Tier 0 already decided
        verdict, tail = None, "Tier 2 skipped: a Tier-0 check failed (fix it first; --force-tier2 calls the judge anyway)"
    else:
        tmp, text, manifest = prepare(artifacts, text, manifest)
        verdict, tail = call(vendor, text, cfg, int(cfg.get("timeout_s", 900)), artifacts, tmp=tmp)
    corpus = []
    for p in artifacts:  # full text of the artifacts, for the quote check (the judge may quote from a sealed copy)
        try:
            if os.path.getsize(p) <= 5 * 1024 * 1024:
                corpus.append(open(p, encoding="utf-8", errors="strict").read())
        except (OSError, UnicodeDecodeError):
            continue
    verdict, warnings = review_verdict(verdict, contract, text, "\n".join(corpus))
    n = len([f for f in os.listdir(d) if f.startswith("verdict-")]) + 1
    brief_file = f"judge-brief-{n:02d}.md"
    try:  # the exact text the judge received, kept with the verdict (the owner and the next round can read it)
        B.atomic_write(os.path.join(d, brief_file), text + "\n", exclusive=True)
    except OSError:
        brief_file = None
    rec = {"session": a.session, "judge_vendor": vendor, "maker": maker, "judge_strength": strength, "tier0": t0,
           "tier2": "recorded by hand" if a.record else "skipped" if t0_failed and not a.force_tier2 else "called",
           "verdict": verdict, "raw_tail": None if verdict else tail, "at": B.now(),
           "brief": {"file": brief_file, "chars": len(text), "inputs": manifest}, "judge_warnings": warnings}
    B.atomic_write(os.path.join(d, f"verdict-{n:02d}.json"), json.dumps(rec, indent=1, ensure_ascii=False) + "\n", exclusive=True)
    overall = verdict["overall"] if verdict else "inconclusive"
    if t0_failed:
        overall = "fail"  # a failed hard check is never overridden by a model (Tier 0 rule)
    with open(os.path.join(d, "judge.md"), "a", encoding="utf-8") as fh:
        fh.write(f"- {B.now()} round {n}: {overall} (judge {vendor}, {strength}; tier0 {len(t0)} checks)\n")
    print(json.dumps({"overall": overall, "judge": vendor, "strength": strength, "tier2": rec["tier2"],
                      "failed_checks": [r["requirement"] for r in t0 if r["exit"] != 0],
                      "fix_list": fix_list(verdict, t0), "inputs_missing": (verdict or {}).get("inputs_missing") or [],
                      "unsupported_claims": (verdict or {}).get("unsupported_claims") or [],
                      "not_shown_in_full": cut, "judge_warnings": warnings,
                      "verdict_file": f"sessions/{a.session}/verdict-{n:02d}.json"}, ensure_ascii=False))
    return {"pass": 0, "fail": 1}.get(overall, 2)


if __name__ == "__main__":
    sys.exit(main())
