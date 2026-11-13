#!/usr/bin/env python3
"""
brain_hooks.py — the brain's Claude Code hooks, one dispatcher (layers 1, 3, 5, 7, 10, 13).

    python3 -I brain_hooks.py prompt   # UserPromptSubmit: skills + notes for this message, flow status
    python3 -I brain_hooks.py pre      # PreToolUse: contract gate, scope gate, ACTION-RISK, PRIVACY-LEAK
    python3 -I brain_hooks.py post     # PostToolUse: evidence log, links Claude session -> brain session
    python3 -I brain_hooks.py end      # SessionEnd: analyses the session (tokens, evidence, flow), marks unclosed

What it enforces (honest level: a hook, so a determined agent can still ask the owner to override):
- No file edits before a task contract exists (step 1). Writes to ~/.claude, temp and scratch folders are free.
- Reading Brain System/self needs a session whose scope class is cv_official or personal (layer 3).
- Irreversible shell actions (push, publish, send, delete, install) ask the owner (layer 7, ACTION-RISK).
- Web queries carrying e-mail addresses, phone numbers, long ID numbers or terms in state/privacy-terms.json
  are refused until redacted (layer 3, PRIVACY-LEAK).
Never crashes and never blocks on its own errors. BRAIN_OFF=1 turns every hook off (brain-off pilot arm).
"""
import hashlib, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

LINKS = os.path.join(B.STATE, "live-links.json")
AGENT = "codex" if "--agent" in sys.argv and sys.argv[sys.argv.index("--agent") + 1:][:1] == ["codex"] else "claude"
ANALYSIS = os.path.join(B.STATE, "analysis")
PRIVATE_SCOPES = ("cv_official", "personal")
GENERIC = set("""system systems session sessions agent agents work works working everything thing things need
want like help just whole functional functionality ready must mistake claude codex brain new now each start show tell
know good better best look find give take see time way part parts use used done sure right also really please make
made create let lets get got able there here what which when where why how who whom whose yes not okay fine thanks
wire wired layer layers paper information useless status explain changed change changes continue left fail failed
final order commit confirm understand purpose exist exists perfectly demand first refining plan analyzed analyse analyze""".split())
import hydro_skills as HS  # noqa: E402
from hydro_skills import STOP  # noqa: E402
STOP = STOP | set("nothing completely main into them before can you your yours it's i'm don't".split())
import tempfile as _tempfile
FREE_WRITE = tuple(os.path.expanduser(p) for p in os.environ.get("BRAIN_FREE_WRITE", "").split(os.pathsep) if p) or (
    os.path.expanduser("~/.claude") + os.sep, "/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/",
    os.path.realpath(_tempfile.gettempdir()) + os.sep, os.path.abspath(_tempfile.gettempdir()) + os.sep)
RISKY = [
    (r"\bgit\s+push\b", "pushes to a remote"),
    (r"\b(npm|pnpm|yarn)\s+publish\b|\bgh\s+release\s+create\b|\btwine\s+upload\b", "publishes a package or release"),
    (r"\bgh\s+(pr|issue)\s+(create|merge|close|comment)\b", "acts on GitHub in the owner's name"),
    (r"\b(sendmail|mailx?)\b|\bosascript\b.*\b(send|message)\b", "sends a message"),
    (r"\bcurl\b.*(\s-X\s*(POST|PUT|PATCH|DELETE)\b|\s--data\b|\s-d\s)", "writes to a web service"),
    (r"(^|[;&|({\n]\s*)(sudo\s+)?rm(\s|$)", "deletes files (never delete: move to the Trash or _to_delete)"),
    # v3 (A3): rm behind a shell keyword or xargs/-exec, find -delete, git clean
    (r"(^|\s)(then|do|else|xargs|-exec|-execdir|command|time)\s+(-\S+\s+)*rm(\s|$)|\bfind\b[^;&|\n]*\s-delete\b|\bgit\s+clean\b",
     "deletes files (never delete: move to the Trash or _to_delete)"),
    (r"\b(brew|port)\s+install\b|\bpip3?\s+install\b|\bnpm\s+(i|install)\s+(-g|--global)\b|\buv\s+tool\s+install\b", "installs software"),
    # Windows edition: PowerShell and cmd.exe forms of the same actions
    (r"(?i)\b(Remove-Item|ri)\b|(^|[;&|(\n]\s*)(del|erase|rd|rmdir)\s", "deletes files (never delete: move to the Recycle Bin or _to_delete)"),
    (r"(?i)\b(winget|choco|scoop)\s+install\b|\bInstall-(Module|Package)\b", "installs software"),
    (r"(?i)\b(reg\s+(add|delete)|Set-ItemProperty\s+-Path\s+['\"]?HK|schtasks\s+/create|Set-ExecutionPolicy)\b", "changes the system"),
    (r"\bsudo\b|\bdiskutil\s+erase|\blaunchctl\s+(load|bootstrap)\b|\bcrontab\b|\bdefaults\s+write\b", "changes the system"),
]
NET = re.compile(r"\b(curl|wget|http|https|ssh|scp|sftp|nc|ftp)\s|\bgh\s+(api|issue|pr|gist|release)\b|\bgit\s+push\b|"
                 r"\b(urllib\.request|requests\.(get|post|put)|http\.client|fetch\()")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?:\+|(?<![\w.-])0)[\d\s().-]{8,}\d")
LONG_ID = re.compile(r"\b[A-Z]{0,2}\d{10,}\b|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")


# ---------- shared ----------
def out(obj):
    print(json.dumps(obj, ensure_ascii=False))


def links():
    return B.load_json(LINKS, {})


def linked_session(claude_sid):
    """The brain session linked to this Claude session (meta dict) or None."""
    sid = links().get(claude_sid or "")
    if not sid:
        return None
    meta = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), None)
    return meta if isinstance(meta, dict) else None


def scope_of(meta):
    try:
        c = open(os.path.join(B.SESSIONS, meta["id"], "contract.md"), encoding="utf-8").read()
        m = re.search(r"^scope_class:\s*(\w+)", c, re.M)
        if m:
            return m.group(1)
    except (OSError, KeyError):
        pass
    return (meta or {}).get("scope_class", "general")


def words(text):
    return HS.tokenize(text, limit=32, strip_noise=True)


def doc_tokens(text):
    return HS.doc_tokens(text)


def stem(w):
    return w


def hits(q, toks):
    return [w for w in q if HS.token_match(w, toks)]


def rank(q, docs, threshold, n):
    """docs: list of (name_text, body_text, payload). Rarity-weighted overlap (IDF), name words count double."""
    import math
    toks = [(doc_tokens(a), doc_tokens(a + " " + b), p) for a, b, p in docs]
    N = len(toks) or 1
    idf = {w: math.log(N / (1 + sum(1 for _, full, _ in toks if hits([w], full)))) for w in q}
    scored = []
    for name_t, full_t, p in toks:
        found = hits(q, full_t)
        if not found:
            continue
        score = sum(max(idf[w], 0) * (2 if hits([w], name_t) else 1) for w in found)
        if score >= threshold:
            scored.append((round(score, 2), p))
    scored.sort(key=lambda x: -x[0])
    return scored[:n]


DEFAULTS = {"skill_threshold": 8.0, "note_threshold": 9.0, "off_factor": 1.15, "rel_cut": 0.48, "len_norm": 9, "len_cap": 1.45}
_HOOK_DISK_CFG = {k: v for k, v in B.load_json(os.path.join(B.STATE, "harness-config.json"), {}).items() if k in DEFAULTS}
CFG = dict(DEFAULTS, **_HOOK_DISK_CFG)
_SKILL_ROWS_CACHE = None
# tuned on state/eval/prompt-skills.json; the Gym (tools/gym.py) may release a better config, sleep auto-reverts a bad one


def pick_skills(prompt, agent="claude", n=5, threshold=None, scope="general"):
    global _SKILL_ROWS_CACHE
    import sqlite3
    if not prompt or prompt.lstrip().startswith("/") or not os.path.exists(B.INDEX_DB):
        return []
    who = "Claude" if agent == "claude" else "Codex"
    try:
        st = os.stat(B.INDEX_DB)
        sig = (B.INDEX_DB, st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    if _SKILL_ROWS_CACHE and _SKILL_ROWS_CACHE[0] == sig and sig is not None:
        rows = _SKILL_ROWS_CACHE[1]
    else:
        con = sqlite3.connect(B.INDEX_DB)
        try:
            rows = con.execute("SELECT name, description, location, agent, kind, autoload FROM skills").fetchall()
        finally:
            con.close()
        if sig is not None:
            _SKILL_ROWS_CACHE = (sig, rows)
    cfg = HS.load_config()
    # Allow in-process CFG mutations (e.g., tests or gym loops) without bypassing HS.CFG_OVERRIDE
    for k, v in CFG.items():
        if k in cfg and k not in HS.CFG_OVERRIDE and v != _HOOK_DISK_CFG.get(k, DEFAULTS.get(k)):
            cfg[k] = v
    return HS.rank_skills(prompt, rows, who=who, scope=scope, n=n, threshold=threshold, cfg=cfg,
                          strict_agent=True, include_drives=False)


def pick_notes(prompt, scope, n=3, threshold=None):
    import sqlite3
    q = words(prompt)
    if len(q) < 2 or not os.path.exists(B.INDEX_DB):
        return []
    con = sqlite3.connect(B.INDEX_DB)
    rows = con.execute("SELECT title, path, collection, sub, summary, type FROM notes").fetchall()
    con.close()
    docs = [(title, summary or "", {"title": title, "path": path, "type": ntype}) for title, path, col, sub, summary, ntype in rows
            if col != "00-toc" and str(ntype or "").lower() != "log" and B.allowed(col, sub, scope)
            and (col != "lessons" or B.lesson_visible(path, scope))]
    out, episodes = [], 0
    for _, p in rank(q, docs, CFG["note_threshold"] if threshold is None else threshold, n * 3):
        if p["type"] == "episode":  # v3 (C2): past sessions are examples, not knowledge; one is enough in a hint
            episodes += 1
            if episodes > 1:
                continue
        out.append(p)
    return out[:n]


def shelf_hint(where):
    """v2.1: a skill from a shelved plugin is read from the brain; its TOOLS need the plugin switched on."""
    m = re.search(r"/skills/plugins/([^/]+)/", where or "")
    if not m:
        return ""
    return f" (plugin {m.group(1)} is shelved in the brain: read this SKILL.md now; if the task needs the plugin's own tools: python3 -I \"{os.path.join(B.TOOLS, 'plugin_shelf.py')}\" activate {m.group(1).replace('codex-', '')})"


SEEN = os.path.join(B.STATE, "hook-seen.json")
MACHINE_RX = re.compile(r"^\s*(?:<[a-z][\w-]*[ >]|\[SYSTEM\b|\[system\b|<!--)")
NUDGE_EVERY = 15
REMIND_AFTER = 8  # v7: a skill shown earlier that fits again is named again (one line, with its path) after this many messages


def seen_load(csid):
    return (B.load_json(SEEN, {}) or {}).get(csid or "", {}) if csid else {}


def seen_save(csid, rec):
    """What this conversation was already told (v6). Best effort: a lost write only repeats one reminder."""
    if not csid:
        return
    try:
        with B.lock("hook-seen", timeout_s=1):
            allrec = B.load_json(SEEN, {}) or {}
            allrec[csid] = dict(rec, t=time.time())
            if len(allrec) > 300:  # keep the newest conversations
                allrec = dict(sorted(allrec.items(), key=lambda kv: -kv[1].get("t", 0))[:200])
            B.atomic_write(SEEN, json.dumps(allrec, ensure_ascii=False))
    except (B.LockBusy, OSError):
        pass


def seen_forget(csid):
    """After a compaction the conversation no longer holds what the hooks said: tell it again (called by brain_start)."""
    seen_save(csid, {})


def cmd_prompt(data):
    """v6: say a thing once. The flow reminder, a skill and a note are injected the first time they apply to this
    conversation and again only when the state changes; a long session no longer pays for the same lines on every
    message. Machine-made messages (task notifications, system events) get nothing. BRAIN_HOOK_VERBOSE=1 = old behaviour."""
    prompt = str(data.get("prompt") or "")
    csid = data.get("session_id") or ""
    verbose = os.environ.get("BRAIN_HOOK_VERBOSE") == "1"
    machine = bool(MACHINE_RX.match(prompt))
    meta = linked_session(csid)
    seen = {} if verbose else dict(seen_load(csid))
    count = int(seen.get("n", 0)) + 1
    lines = []
    if meta and meta.get("status") != "closed":
        routed = any(f.startswith("retrieval-") and f.endswith(".md") for f in os.listdir(os.path.join(B.SESSIONS, meta["id"])))
        escalate = False
        try:
            import harness2
            escalate = bool(harness2.qualifies(meta["id"]))
        except Exception:
            pass
        state = f"open:{meta['id']}:{scope_of(meta)}:{routed}:{escalate}"
        if seen.get("flow") != state:
            lines.append(f"Agent Brain flow: brain session {meta['id']} is open for this conversation (scope {scope_of(meta)}). "
                         "Checkpoint after each milestone; judge (step 6) unless fast lane; close with both summaries (step 7)."
                         + ("" if routed else " Step 2 has not run yet: brain_session.py lint --session " + meta["id"] + " runs it once the contract is filled."))
            if escalate:
                lines.append("Agent Brain layer 9: two judge rounds failed. Do not start a third fix round: run one in-task Harness² cycle "
                             f"(python3 -I \"{os.path.join(B.TOOLS, 'harness2.py')}\" start --session {meta['id']} --subtask ... --check ...), "
                             "or ask the owner with the diagnosis.")
        elif count % NUDGE_EVERY == 0 and not machine:
            lines.append(f"Agent Brain: session {meta['id']} still open — checkpoint, judge, close.")
        seen["flow"] = state
    elif not prompt.lstrip().startswith("/") and not machine:
        state = "closed" if meta else "none"
        if seen.get("flow") != state:
            lines.append("Agent Brain flow: no brain session is open for this conversation. If this message asks for work that "
                         "changes files, start with step 1 (brain_session.py new ...); file edits are blocked until a contract exists.")
        seen["flow"] = state
    active_scope = scope_of(meta) if meta else "general"
    prompt_for_skills = prompt
    if not machine and not meta and re.search(r"\b(?:last session|bring up|continue|pick up where|v2|next round)\b", prompt, re.I):
        # Inherit recent open/closed session context in same cwd on continuation requests
        cwd = str(data.get("cwd") or "")
        try:
            for sid in sorted(os.listdir(B.SESSIONS), reverse=True)[:15]:
                om = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), {})
                if isinstance(om, dict) and cwd and om.get("cwd") == cwd:
                    active_scope = om.get("scope_class", "general")
                    prompt_for_skills = f"{prompt} {om.get('title', '')}".strip()
                    lines.append(f"Hydro Brain continuation: prior session `{sid}` (scope {active_scope}, {om.get('title', '')}).")
                    break
        except OSError:
            pass
    told_raw, told_n = seen.get("skills") or {}, set(seen.get("notes") or [])
    told_s = dict(told_raw) if isinstance(told_raw, dict) else {w: 0 for w in told_raw}  # where -> message number it was last named
    skills = pick_skills(prompt_for_skills, agent=AGENT, scope=active_scope) if prompt and not machine else []
    fresh = [s for s in skills if s["where"] not in told_s]
    # v7 (Argon, round 4): "said once" must not mean "never again". A skill shown earlier that fits THIS message is named
    # again with its path once REMIND_AFTER messages have passed: by then the first mention is far up the conversation.
    again = [s for s in skills if s["where"] in told_s and count - int(told_s[s["where"]]) >= REMIND_AFTER]
    root_t = B.ROOT.replace(os.path.expanduser("~"), "~")
    short = lambda w: "$BRAIN" + w[len(root_t):] if w.startswith(root_t + "/") else w
    if fresh:
        lines.append("Skills for this message, from the brain (none load at start). Before working, open the SKILL.md of each "
                     "one that fits and follow it; ignore those that do not fit:")
        if any(s["where"].startswith(root_t + "/") for s in fresh):
            lines[-1] += f" ($BRAIN = {root_t})"
        lines += [f"- {s['name']}: {s['description'][:100]} · {short(s['where'])}" + shelf_hint(s["where"]) for s in fresh]
        recent = [s["name"] for s in skills if s["where"] in told_s and s not in again]
        if recent:
            lines.append("(also still fitting, shown a few messages ago: " + ", ".join(recent) + ")")
    if again:
        lines.append("Skills shown earlier that fit this message again (open the SKILL.md if it is no longer in view"
                     + (f"; $BRAIN = {root_t}" if any(s["where"].startswith(root_t + "/") for s in again) else "") + "): "
                     + " · ".join(f"{s['name']} → {short(s['where'])}" for s in again))
    for s in fresh + again:
        told_s[s["where"]] = count
    notes = pick_notes(prompt, active_scope) if prompt and not machine else []
    fresh_n = [x for x in notes if x["path"] not in told_n]
    if fresh_n:
        lines.append("Brain notes that may apply (headers only; open one only if it fits, cite path:line):")
        lines += [f"- {x['title']} · {x['path']}" for x in fresh_n]
    if not verbose:
        seen.update({"n": count, "skills": dict(sorted(told_s.items(), key=lambda kv: kv[1])[-60:]),
                     "notes": sorted(told_n | {x["path"] for x in fresh_n})[-60:]})
        seen_save(csid, seen)
    if lines:
        out({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(lines)}})


# ---------- pre ----------
def deny(reason):
    out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}})


def ask(reason):
    out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask", "permissionDecisionReason": reason}})


def privacy_terms():
    return [t for t in B.load_json(os.path.join(B.STATE, "privacy-terms.json"), []) if isinstance(t, str) and len(t) >= 3]


def privacy_leak(text):
    found = []
    if EMAIL.search(text):
        found.append("an e-mail address")
    if any(len(re.sub(r"\D", "", m)) >= 9 for m in PHONE.findall(text)):
        found.append("a phone number")
    if LONG_ID.search(text):
        found.append("an ID or account number")
    low = text.lower()
    found += [f"the private term '{t}'" for t in privacy_terms() if t.lower() in low]
    return found


def strip_heredocs(cmd):
    """Text written through a heredoc is content, not a path being read."""
    return re.sub(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\b", "<<heredoc", cmd or "", flags=re.S)


SELF_DIR = os.path.realpath(os.path.join(B.VAULT, "self"))


def _norm(text):
    t = re.sub(r"['\"]\s*\+\s*['\"]", "", text)        # 'Brain System/' + 'self/x'  ->  Brain System/self/x
    t = t.replace("\\ ", " ")
    t = t.replace("\\", "/")                            # Windows edition: Brain System\\self\\x -> Brain System/self/x
    t = re.sub(r"/(\./)+", "/", t)                        # Brain System/./self
    t = re.sub(r"/{2,}", "/", t)
    return t


def _shell_tokens(text):
    import shlex
    try:
        lx = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
        lx.whitespace_split = True
        toks = list(lx)
    except ValueError:
        toks = re.findall(r"[^\s;&|()]+", text)
    out = []
    for t in toks:  # quoted strings inside a token (python -c "open('x')") are paths too
        out.append(t)
        out += re.findall(r"['\"]([^'\"]{2,})['\"]", t)
    return out


def _resolve(tok, bases):
    import glob as G
    tok = os.path.expanduser(tok)
    found = []
    for base in bases:
        full = tok if os.path.isabs(tok) else os.path.join(base, tok)
        if any(c in tok for c in "*?["):  # a glob may name self/ even when the file it ends in does not exist
            parts = full.split(os.sep)
            try:
                hits = [h for i in range(2, len(parts) + 1) if any(c in parts[i - 1] for c in "*?[") for h in G.glob(os.sep.join(parts[:i]))]
            except (re.error, ValueError, OSError):  # v3 (A1): x[z-a], a[::-1] are not globs; never crash the gate
                hits = [full]
        else:
            hits = [full]
        found += [os.path.realpath(h) for h in hits]
    return found


def _segments(toks):
    """Split shell tokens into simple commands at ; & | ( ) (shlex keeps those as their own tokens)."""
    segs, cur = [], []
    for t in toks:
        if t and set(t) <= set(";&|()"):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(t)
    return segs + ([cur] if cur else [])


RECURSIVE_VERBS = {"rg", "ag", "ack", "tree", "find", "rsync", "zip", "ditto"}


def _recursive(seg):
    """Is this simple command a reader that walks folders? Only the command word and its flags count, never quoted text."""
    while seg and (seg[0] in ("sudo", "env", "command", "nice", "time") or re.fullmatch(r"\w+=\S*", seg[0])):
        seg = seg[1:]
    if not seg:
        return False
    v, flags = os.path.basename(seg[0]), [x for x in seg[1:] if x.startswith("-")]
    if v in RECURSIVE_VERBS:
        return True
    if v in ("grep", "egrep", "fgrep"):
        return any(re.fullmatch(r"-\w*[rR]\w*", f) or f == "--recursive" for f in flags)
    if v in ("cp", "scp"):
        return any(re.fullmatch(r"-\w*[rR]\w*", f) for f in flags)
    if v == "tar":
        return any("c" in f for f in flags + seg[1:2])
    return False


def touches_self(text, cwd=None):
    """Layer 3 scope gate (v2.1, O4): literal text, normalised text (./, //, 'a' + 'b'), and every path-like token
    resolved with realpath against the cwd and any `cd` target (globs expanded, symlinks followed). A recursive
    reader (grep -r, rg, find, ...) aimed at a folder that contains self/ counts too, unless it excludes self (N4)."""
    t = _norm(strip_heredocs(text or ""))
    if re.search(r"Brain System/self(/|\b)", t):
        return True
    cwd = cwd or os.getcwd()
    toks = _shell_tokens(t)
    segs = _segments([x for x in toks])
    bases = [cwd]
    for seg in segs:
        if seg[0] == "cd" and len(seg) > 1:
            bases.append(os.path.join(bases[-1], os.path.expanduser(seg[1])))
    for tok in toks:
        if "self" not in tok and not any(c in tok for c in "*?["):
            continue
        for r in _resolve(tok, bases):
            if r == SELF_DIR or r.startswith(SELF_DIR + os.sep):
                return True
    excluded = re.search(r"exclude-dir[= ]['\"]?self\b|!\*\*/self/|-not\s+-path\s+['\"]?\*/?self|--glob\s+['\"]?!", t)
    if not excluded:
        for seg in segs:
            if not _recursive(seg):
                continue
            paths = [x for x in seg[1:] if not x.startswith("-") and ("/" in x or x in (".", "..") or os.path.isdir(os.path.join(bases[-1], x)))]
            for tok in paths or ["."]:
                for r in _resolve(tok, bases[-1:]):
                    if SELF_DIR.startswith(r.rstrip(os.sep) + os.sep):
                        return True
    return False


def contract_filled(meta):
    try:
        c = open(os.path.join(B.SESSIONS, meta["id"], "contract.md"), encoding="utf-8").read()
    except (OSError, KeyError):
        return False
    return "<paste the owner's request exactly>" not in c and "- R1: … — check: …" not in c  # v2.1: request AND a real R1


def unquoted(cmd):
    """Blank out the inside of quoted strings, except a quoted word right after > or >> (a quoted redirect target)."""
    out, i, n = [], 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c in "'\"":
            j = cmd.find(c, i + 1)
            j = n if j < 0 else j
            before = "".join(out).rstrip()
            if before.endswith(">") and not before.endswith(("->", "=>")):
                out.append(cmd[i:j + 1])          # keep: it is the target of a redirect
            else:
                out.append(c + " " * max(0, j - i - 1) + (c if j < n else ""))
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


WRITE_VERBS = [  # v2.1 (O4): commands that change files although no redirect is visible; target = cwd when unknown
    r"\bsed\s+(-[a-zA-Z]*\s+)*-i", r"\bperl\s+(-\w+\s+)*-\w*i", r"\bdd\b[^;&|]*\bof=", r"\btar\s+(-?\w*x\w*)\b", r"\bunzip\b",
    r"\bpatch\b", r"\bcurl\b[^;&|]*\s(-o|-O|--output|--remote-name)\b", r"\bwget\b(?![^;&|]*-O\s*-)", r"\bgit\s+(checkout\s+--|restore\b|reset\s+--hard\b|apply\b|am\b|clean\b|stash\s+pop\b)",
    r"(^|[;&|(]\s*)(install|ln|touch|truncate|rsync|ditto|rmdir|trash)\s", r"\bnode\s+-e\b[^;&|]*writeFile", r"\bruby\s+-e\b[^;&|]*File\.write",
    r"(?i)\b(Set-Content|Add-Content|Out-File|New-Item|Copy-Item|Move-Item|Rename-Item|Expand-Archive)\b",  # Windows edition: PowerShell writes
]
PY_WRITE = re.compile(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wax]b?\+?['\"]|\.write_(text|bytes)\(|shutil\.(copy\w*|move|rmtree)|os\.(remove|unlink|rename|replace|rmdir|makedirs|mkdir)\(")


def inline_code_writes(cmd, cwd):
    """python -c / python - <<EOF that opens a file for writing (or moves/removes files)."""
    out = []
    if re.search(r"\bpython3?\b[^;&|]*\s-c\b|\bpython3?\b[^;&|]*\s-\s*<<", cmd):
        for m in PY_WRITE.finditer(cmd):
            out.append(os.path.abspath(os.path.join(cwd, os.path.expanduser(m.group(1)))) if m.group(1) else os.path.abspath(cwd))
    return out


def shell_write_targets(cmd, cwd):
    """Paths a shell command writes: > / >> redirects, tee, cp, mv, the WRITE_VERBS above, inline Python writes
    (best effort; a seatbelt, not a proof)."""
    extra = inline_code_writes(cmd, cwd)
    if any(re.search(p, unquoted(cmd)) for p in WRITE_VERBS):
        extra.append(os.path.abspath(cwd) + os.sep + ".")
    cmd = unquoted(cmd)  # text inside quotes (commit messages, echo text, "a -> b") is never a redirect
    found = re.findall(r"(?<![0-9&<=-])>>?\s*([^\s;&|<>]+)", cmd)
    found += re.findall(r"\btee\s+(?:-a\s+)?([^\s;&|<>]+)", cmd)
    for m in re.finditer(r"(?:^|[;&|]\s*)(?:cp|mv)\s+(?:-\w+\s+)*(.+?)(?=$|[;&|])", cmd):
        parts = m.group(1).split()
        if len(parts) >= 2:
            found.append(parts[-1])
    out = []
    for f in found:
        f = f.strip("\"'")
        if not f or f.startswith(("/dev/", "&")) or "$" in f:
            continue
        out.append(os.path.abspath(os.path.join(cwd, os.path.expanduser(f))))
    return out + extra


SHELL_TOOLS = ("Bash", "shell", "exec_command", "local_shell")
EDIT_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "ApplyPatch")
PY_DELETE = re.compile(r"shutil\.rmtree\(|os\.(remove|unlink|rmdir|removedirs)\(|\.unlink\(")
RAW_DIR = os.path.realpath(os.path.join(B.ROOT, "raw")) + os.sep
SESSIONS_DIR = os.path.realpath(B.SESSIONS) + os.sep


def log_error(where, e):
    """A hook never blocks the owner's work because of its own bug; it leaves a trace the card and the digest show (v3, A5)."""
    try:
        os.makedirs(ANALYSIS, exist_ok=True)
        with open(os.path.join(ANALYSIS, "hook-errors.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{B.now()} {where} {type(e).__name__}: {e}\n")
    except OSError:
        pass


def _command(ti):
    c = ti.get("command") or ti.get("cmd") or ""
    return " ".join(c) if isinstance(c, list) else str(c)


def write_paths(c):
    """Every path this tool call writes, as far as a hook can see (edit tools exactly, shell best effort). Cached."""
    if "writes" not in c:
        tool, ti, cwd = c["tool"], c["ti"], c["cwd"]
        if tool in ("apply_patch", "ApplyPatch"):  # Codex: paths come from the patch text
            found = re.findall(r"\*\*\* (?:Add|Update|Delete) File: ([^\\\n]+)", json.dumps(ti))
            c["writes"] = [os.path.abspath(os.path.join(cwd, os.path.expanduser(x.strip()))) for x in found] or [""]
        elif tool in EDIT_TOOLS:
            c["writes"] = [os.path.abspath(os.path.expanduser(str(ti.get("file_path") or ti.get("notebook_path") or "")))]
        elif tool in SHELL_TOOLS:
            cmd = _command(ti)
            targets = shell_write_targets(strip_heredocs(cmd), cwd)
            c["writes"] = targets + [x for x in inline_code_writes(cmd, cwd) if x not in targets]  # heredoc Python
        else:
            c["writes"] = []
    return c["writes"]


def gate_scope(c):
    """Layer 3: Brain System/self is readable only in a cv_official or personal session."""
    tool, ti = c["tool"], c["ti"]
    probe = " ; ".join((" ".join(v) if isinstance(v, list) else str(v)) for v in (ti.get(k) for k in ("file_path", "path", "pattern", "command", "cmd", "notebook_path")) if v)
    hits_self = touches_self(probe, c["cwd"])
    if not hits_self and tool in ("Grep", "Glob"):  # v2.1 (N4): a search tool rooted above self/ reads it too
        root = os.path.realpath(os.path.expanduser(str(ti.get("path") or c["cwd"])))
        excl = str(ti.get("glob") or "") + str(ti.get("pattern") if tool == "Glob" else "")
        hits_self = SELF_DIR.startswith(root.rstrip(os.sep) + os.sep) and "self" not in excl and (
            tool == "Grep" or "**" in str(ti.get("pattern") or ""))
    if hits_self and (not c["open"] or scope_of(c["open"]) not in PRIVATE_SCOPES):
        deny("Agent Brain scope gate: Brain System/self is readable only in a session whose contract scope_class is "
             "cv_official or personal. Open or reclassify the contract first, or work without personal records. A search over a "
             "folder that contains self/ counts too: search a narrower folder (Brain System/projects …) or exclude it "
             "(grep --exclude-dir=self, rg -g '!**/self/**').")
        return True


def gate_contract(c):
    """Layer 2/7: a filled contract before any file change (edit tools, and shell writes: redirects, tee, cp, mv, ...)."""
    tool, open_meta = c["tool"], c["open"]
    if c["filled"] or tool not in EDIT_TOOLS + SHELL_TOOLS:
        return
    free = FREE_WRITE + ((os.path.join(B.SESSIONS, open_meta["id"]) + os.sep,) if open_meta else ())  # v2.1 (N1): own folder
    outside = [x for x in write_paths(c) if not x.startswith(free)]
    if not outside:
        return
    new = f"python3 -I \"{os.path.join(B.TOOLS, 'brain_session.py')}\" new --agent {AGENT} --cwd \"$PWD\" --title \"<short title>\""
    if tool in EDIT_TOOLS:
        why = ("its contract.md is still the empty template: fill the verbatim request and hard requirements first" if open_meta else
               "the linked brain session is closed; open a new one for new work" if c["meta"] else "no brain session is open for this conversation")
        deny(f"Agent Brain step 1: {why}. Run: {new} and fill its contract.md (verbatim request, hard requirements with checks). Then retry this edit.")
    else:
        deny(f"Agent Brain step 1: this command writes files ({', '.join(write_paths(c)[:3])}) but no filled brain contract is open. "
             f"Run: {new}, fill contract.md, then retry.")
    return True


def gate_protected(c):
    """v3 (A4): two rules that were only on paper. raw/ is read-only evidence (only tools/snapshot.py adds to it),
    and another session's folder is a record, not a workspace."""
    own = os.path.realpath(os.path.join(B.SESSIONS, c["open"]["id"])) + os.sep if c["open"] else None
    for p in write_paths(c):
        r = os.path.realpath(p) + os.sep if p else ""
        if r.startswith(RAW_DIR):
            deny("Agent Brain raw/ gate: raw/ is read-only evidence. Only tools/snapshot.py adds to it (append-only). "
                 "Write somewhere else, or take a snapshot.")
            return True
        if r.startswith(SESSIONS_DIR) and r != SESSIONS_DIR and not (own and r.startswith(own)):
            ask("Agent Brain record gate: this writes into another session's folder, which is a record of past work. The owner decides.")
            return True


def gate_risk(c):
    """Layer 7, ACTION-RISK: irreversible shell actions ask the owner."""
    if c["tool"] not in SHELL_TOOLS:
        return
    raw = _command(c["ti"])
    cmd = strip_heredocs(raw)
    for pat, what in RISKY:
        if re.search(pat, cmd):
            ask(f"Agent Brain ACTION-RISK: this command {what} (irreversible or outside the machine). The owner decides.")
            return True
    if re.search(r"\bpython3?\b", raw) and PY_DELETE.search(raw):  # v3 (A3): the heredoc body counts here
        ask("Agent Brain ACTION-RISK: this command deletes files from inline Python (never delete: move to the Trash or _to_delete). The owner decides.")
        return True


def gate_privacy(c):
    """Layer 3, PRIVACY-LEAK: network shell commands (the payload may sit in a heredoc) and outgoing web queries."""
    tool, ti = c["tool"], c["ti"]
    if tool in SHELL_TOOLS:
        cmd = _command(ti)
        if NET.search(unquoted(strip_heredocs(cmd))):  # the command word decides; the payload is screened in full
            leak = privacy_leak(cmd)
            if leak:
                deny("Agent Brain PRIVACY-LEAK: this network command carries " + ", ".join(leak) + ". Remove it, or ask the owner.")
                return True
    if tool in ("WebSearch", "WebFetch") or tool.startswith("mcp__") and any(k in ti for k in ("query", "url", "q")):
        leak = privacy_leak(" ".join(str(ti.get(k) or "") for k in ("query", "url", "q", "prompt")))
        if leak:
            deny("Agent Brain PRIVACY-LEAK: the outgoing query contains " + ", ".join(leak) + ". Remove it and search again.")
            return True


GATES = (gate_scope, gate_contract, gate_protected, gate_risk, gate_privacy)


def cmd_pre(data):
    """v3 (A2): every gate runs on its own. A gate that crashes is logged and skipped; the others still decide."""
    meta = linked_session(data.get("session_id"))
    open_meta = meta if meta and meta.get("status") != "closed" else None
    c = {"tool": data.get("tool_name") or "", "ti": data.get("tool_input") or {}, "cwd": data.get("cwd") or os.getcwd(),
         "meta": meta, "open": open_meta, "filled": bool(open_meta) and contract_filled(open_meta)}
    for gate in GATES:
        try:
            if gate(c):
                return
        except Exception as e:
            log_error(f"['pre'] {gate.__name__}", e)


# ---------- post ----------
def h(text):
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]


def cmd_post(data):
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    resp = data.get("tool_response", data.get("tool_output"))
    stdout = resp.get("stdout", "") if isinstance(resp, dict) else str(resp or "")
    stderr = resp.get("stderr", "") if isinstance(resp, dict) else ""
    csid = data.get("session_id") or ""
    if tool in ("shell", "exec_command", "local_shell"):
        tool = "Bash"
        c = ti.get("command") or ti.get("cmd") or ""
        ti = dict(ti, command=" ".join(c) if isinstance(c, list) else str(c))
    if tool == "Bash" and runs_new(str(ti.get("command", ""))):
        # v3 (A8): the id is also found when the output was piped or reformatted. v6: but only when the command really
        # runs `new` (not when a script merely contains those words) and the id is one this command created just now:
        # a past session's id in the output used to re-link the conversation to a closed session and lock all edits.
        m = re.search(r'"session":\s*"([\w-]+)"', stdout) or re.search(r"\b(\d{8}-\d{6}-[a-z]+-[0-9a-f]{4})\b", stdout)
        if m and not fresh_session(m.group(1)):
            m = None
        if m and os.path.isdir(os.path.join(B.SESSIONS, m.group(1))):
            with B.lock("links", timeout_s=5):  # v2.1 (O12): read-modify-write under a lock, never drops a key
                l = links()
                l[csid] = m.group(1)
                B.atomic_write(LINKS, json.dumps(l, indent=1))
            mp = os.path.join(B.SESSIONS, m.group(1), "meta.json")
            meta = B.load_json(mp, {})
            meta["claude_session"] = csid
            B.atomic_write(mp, json.dumps(meta, indent=1, ensure_ascii=False))
    meta = linked_session(csid)
    if not meta or meta.get("status") == "closed" or tool not in ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "apply_patch", "ApplyPatch", "Read", "Agent", "Task"):
        return  # v3: a closed session's evidence is a finished record; later work in the same conversation is not appended
    ev_path = os.path.join(B.SESSIONS, meta["id"], "evidence.jsonl")
    rec = {"t": B.now(), "tool": tool}
    if tool in ("Agent", "Task"):  # v2.1 (F7): subagent contracts checked in code (warn-only)
        rec.update(subagent_check(ti, resp))
    elif tool == "Read":
        rec["file"] = os.path.realpath(str(ti.get("file_path") or ""))
    if tool in ("Edit", "MultiEdit", "Write"):
        warn = unread_scout_target(ev_path, os.path.realpath(str(ti.get("file_path") or "")))
        if warn:
            rec["warn"] = warn
    if tool == "Bash":
        rec.update({"command": str(ti.get("command", ""))[:2000], "interrupted": bool(resp.get("interrupted")) if isinstance(resp, dict) else None,
                    "stdout_sha": h(stdout), "stderr_sha": h(stderr), "stdout_tail": stdout[-300:], "stderr_tail": stderr[-300:]})
    elif tool in ("apply_patch", "ApplyPatch"):
        rec["files"] = re.findall(r"\*\*\* (?:Add|Update|Delete) File: ([^\\\n]+)", json.dumps(ti))
        rec["patch_sha"] = h(json.dumps(ti))
    elif tool not in ("Agent", "Task", "Read"):
        p = str(ti.get("file_path") or ti.get("notebook_path") or "")
        rec["file"] = p
        try:
            rec["file_sha"] = B.sha256_file(p)[:16]
        except OSError:
            rec["file_sha"] = None
    with open(ev_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


NEW_CMD = re.compile(r"brain(?:_session)?\.py[\"']?\s+new(?:\s|$)")


def runs_new(cmd):
    """Does this shell command invoke `brain_session.py new` / `brain.py new` itself? Heredoc bodies do not count."""
    return bool(NEW_CMD.search(strip_heredocs(cmd)))


def fresh_session(sid, max_age_s=180):
    """A session `new` created within the last minutes (its meta.json is that young)."""
    try:
        return time.time() - os.path.getmtime(os.path.join(B.SESSIONS, sid, "meta.json")) <= max_age_s
    except OSError:
        return False


POINTER = re.compile(r"pointer:\s*(\S+?)#L(\d+)-L(\d+)")


def subagent_check(ti, resp):
    """layer 6: a scout returns 1-3 pointers in <= 1,200 chars of YAML; anything else is logged as a warning."""
    kind = str(ti.get("subagent_type") or "")
    text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False) if resp is not None else ""
    out = {"subagent": kind}
    if kind == "brain-scout":
        ptrs = POINTER.findall(text)
        out["pointers"] = [p[0] for p in ptrs]
        problems = []
        if not ptrs and "not_found" not in text:
            problems.append("no pointer and no not_found")
        if len(ptrs) > 3:
            problems.append(f"{len(ptrs)} pointers > 3")
        body = text[text.find("options:"):] if "options:" in text else text
        if len(body) > 1200 + 400:  # 400 chars of slack for the not_found / searched lists
            problems.append(f"reply {len(body)} chars > 1,200 (prose instead of a menu?)")
        if problems:
            out["warn"] = "scout_output: " + "; ".join(problems)
    return out


def unread_scout_target(ev_path, target):
    """layer 6: the director must read the original a scout pointed to before editing it."""
    if not os.path.exists(ev_path) or not target:
        return None
    pointed, read = set(), set()
    for line in open(ev_path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        pointed.update(os.path.realpath(p) for p in r.get("pointers") or [])
        if r.get("tool") == "Read" and r.get("file"):
            read.add(r["file"])
    return "scout_unread_original: edited a file a scout pointed to without reading it first" if target in pointed and target not in read else None


# ---------- end ----------
def analyse(csid, transcript, cwd, reason="", meta=None):
    import token_meter
    tokens = {}
    meta = meta or linked_session(csid)
    if transcript and os.path.exists(transcript):
        # v3 (C4): one conversation often holds several brain sessions; each gets only the tokens spent between its
        # own start and close, never the whole transcript again
        since, until = token_meter.window(meta) if meta else (None, None)
        agent = "codex" if AGENT == "codex" else ((meta or {}).get("agent") or "claude")  # the sleep job analyses Codex sessions too
        rows = (token_meter.codex if agent == "codex" else token_meter.claude)([transcript], since=since, until=until)
        if rows:
            r = rows[0]
            tokens = {k: r[k] for k in ("turns", "context_in", "cache_read", "output", "reasoning_output", "total", "sidechain_turns", "boot_context") if k in r}
            tokens["window"] = "session" if since else "whole transcript"
    rec = {"claude_session": csid, "cwd": cwd, "ended": B.now(), "reason": reason, "tokens": tokens, "brain_session": None}
    if meta:
        d = os.path.join(B.SESSIONS, meta["id"])
        contract = open(os.path.join(d, "contract.md"), encoding="utf-8").read() if os.path.exists(os.path.join(d, "contract.md")) else ""
        ev = open(os.path.join(d, "evidence.jsonl"), encoding="utf-8").read().splitlines() if os.path.exists(os.path.join(d, "evidence.jsonl")) else []
        verdicts = sorted(f for f in os.listdir(d) if f.startswith("verdict-") and f.endswith(".json"))
        last = B.load_json(os.path.join(d, verdicts[-1]), {}) if verdicts else {}
        flow = {
            "contract_filled": bool(contract) and "<paste the owner's request exactly>" not in contract,
            "retrieval_runs": len([f for f in os.listdir(d) if f.startswith("retrieval-") and f.endswith(".md")]),  # v3: not the fetch log
            "checkpoints": len(os.listdir(os.path.join(d, "checkpoints"))) if os.path.isdir(os.path.join(d, "checkpoints")) else 0,
            "evidence_lines": len(ev),
            "judge_rounds": len(verdicts),
            "last_verdict": (last.get("verdict") or {}).get("overall"),
            "closed": meta.get("status") == "closed",
        }
        lane = re.search(r"^lane:\s*(\w+)", contract, re.M)
        flow["lane"] = lane.group(1) if lane else meta.get("lane")
        # v3 (B3): the fast lane has no checkpoint step, so a fast session never "skipped" it
        missing = [k for k, ok in (("contract", flow["contract_filled"]), ("checkpoint", flow["checkpoints"] > 0 or flow["lane"] == "fast"),
                                   ("judge", flow["judge_rounds"] > 0 or flow["lane"] == "fast"), ("close", flow["closed"])) if not ok]
        flow["missing_steps"] = missing
        rec["brain_session"] = meta["id"]
        rec["flow"] = flow
        B.atomic_write(os.path.join(d, "analysis.json"), json.dumps(rec, indent=1, ensure_ascii=False))
        if not flow["closed"]:
            meta["unclosed"] = True
            B.atomic_write(os.path.join(d, "meta.json"), json.dumps(meta, indent=1, ensure_ascii=False))
    os.makedirs(ANALYSIS, exist_ok=True)
    with open(os.path.join(ANALYSIS, time.strftime("%Y-%m") + ".jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def cmd_end(data):
    rec = analyse(data.get("session_id") or "", data.get("transcript_path"), data.get("cwd"), data.get("reason", ""))
    try:  # v4 Hydro: immediately distil lessons/telemetry on close or substantive session end
        flow = (rec.get("flow") or {}) if isinstance(rec, dict) else {}
        bsid = rec.get("brain_session") if isinstance(rec, dict) else None
        if bsid and (flow.get("closed") or flow.get("evidence_lines", 0) >= 2):
            import brain_learn
            brain_learn.learn_session(bsid, refresh_index=True)
    except Exception:
        pass
    try:  # v2.1 (O1): the daily sleep job starts when a session ENDS, never while one is starting to work
        import brain_start
        brain_start.start_sleep_if_due()
    except Exception:
        pass


def main():
    if len(sys.argv) < 2 or os.environ.get("BRAIN_OFF") == "1":
        return 0
    try:
        data = json.load(sys.stdin)
        {"prompt": cmd_prompt, "pre": cmd_pre, "post": cmd_post, "end": cmd_end}[sys.argv[1]](data)
    except Exception as e:  # never block the owner's work because of a hook bug; leave a trace instead
        log_error(str(sys.argv[1:]), e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
