#!/usr/bin/env python3
"""
harness2.py — in-task Harness² cycle with a hard budget (layer 12 A, roadmap 7.2; layer 9 rule 2).

Trigger: the fix loop ran 2 rounds without success (2 failing judge verdicts), the same failure repeats, or the
method is in doubt — standard or deep lane only. The prompt hook tells the agent when a session qualifies.

    harness2.py start   --session S --subtask "<the failing sub-task>" --check "<command that exits 0 when it works>"
                        [--scope path1 path2 ...] [--token-cap 200000]
    harness2.py adapt   --session S [--propose]   # builds the evidence folder + INV/DOM briefs; --propose asks the
                                                  # other vendor's CLI (your subscription) for the two patches
    harness2.py propose --session S --general "<INV change>" --domain "<DOM change>"
                        [--general-patch f.patch] [--domain-patch f.patch]
    harness2.py probe   --session S --arm reference|general|domain|composed [--output <file inside the workspace>] [--in-place]
    harness2.py compare --session S              # every arm against the reference (Tier 0) + PAIR-BETTER when outputs exist
    harness2.py compose --session S --keep general,domain
    harness2.py close   --session S              # ledger → checkpoint + candidate lesson in queue/

v2.1 "Ironclad" (Argon O2, F1, Google Harness² recursion.py):
- Isolation: each probe runs in its OWN fresh copy of the session's cwd (or of --scope paths only), with only that
  arm's patch applied (composed = the kept patches in order). Side effects of one arm never reach another, and the
  live folder is never touched. Copies live in the system temp folder (never deleted by the brain; macOS cleans them).
  --in-place keeps the old behaviour and is recorded as "not isolated".
- Patches: unified diffs (git diff style, a/ b/ prefixes, paths relative to the session's cwd), stored as
  sessions/S/harness2/arms/<arm>.patch.
- compare reports general, domain and composed each against the reference (win / loss / tie), never only one arm.
- Ledger counts R (probe rollouts) and P (proposals), and the tokens spent since start.
Budget: at most 3 extra runs (general, domain, composed final) after the reference, and the token cap, measured from
the linked transcript ("unmeasured" when none is linked); the final composed run is mandatory before close.
Ledger: sessions/<S>/harness2/ledger.json (every run: arm, workspace, exit, output tail, output hash).
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

MAX_EXTRA = 3
COPY_CAP = 300 * 1024 * 1024  # a probe copy larger than this needs --scope
SKIP = shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".venv", "_to_delete", ".DS_Store")
HARNESS_PARTS = ("prompt", "guardrails", "memory", "skills", "tool_guidance", "scripts", "subagents", "plugins")
EXPERIENCE_JSONL = os.path.join(B.STATE, "harness2-experience.jsonl")
EXPERIENCE_MD = os.path.join(B.VAULT, "lessons", "harness2-experience.md")


def hdir(sid):
    return os.path.join(B.SESSIONS, sid, "harness2")


def lp(sid):
    return os.path.join(hdir(sid), "ledger.json")


def load(sid):
    led = B.load_json(lp(sid), None)
    if not led:
        sys.exit("no Harness² cycle: run `harness2.py start` first")
    return led


def save(sid, led):
    os.makedirs(hdir(sid), exist_ok=True)
    B.atomic_write(lp(sid), json.dumps(led, indent=1, ensure_ascii=False))


def tokens_now(sid):
    """Tokens used so far by the conversation linked to this brain session (None if unknown)."""
    try:
        import pilot
        meta = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), {})
        csid, agent = meta.get("claude_session"), meta.get("agent", "claude")
        tr = pilot.transcript(csid, agent) if csid else None
        if not tr:
            return None
        m = pilot.meter(tr, agent)
        return m["fresh"] + m["cache_read"]
    except Exception:
        return None


def qualifies(sid):
    """Layer 9 rule 2: two failing judge rounds in a standard/deep session."""
    d = os.path.join(B.SESSIONS, sid)
    try:
        lane = next((l.split(":", 1)[1].split()[0] for l in open(os.path.join(d, "contract.md"), encoding="utf-8") if l.startswith("lane:")), "standard")
    except OSError:
        return False
    fails = 0
    for f in sorted(os.listdir(d)):
        if f.startswith("verdict-") and f.endswith(".json"):
            fails += (B.load_json(os.path.join(d, f), {}).get("verdict") or {}).get("overall") == "fail"
    return lane in ("standard", "deep") and fails >= 2 and not os.path.exists(lp(sid))


def tree_size(path):
    n = 0
    for d, dirs, files in os.walk(path):
        dirs[:] = [x for x in dirs if x not in (".git", "node_modules", "__pycache__", ".venv", "_to_delete")]
        for f in files:
            try:
                n += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return n


def workspace(led, arm, patches):
    """A fresh copy of the cwd (or of the scope paths) with the given patches applied. Returns (path, error)."""
    cwd, scope = led["cwd"], led.get("scope") or []
    srcs = [os.path.join(cwd, s) for s in scope] if scope else [cwd]
    if sum(tree_size(s) if os.path.isdir(s) else os.path.getsize(s) for s in srcs if os.path.exists(s)) > COPY_CAP:
        return None, f"the folder to copy is larger than {COPY_CAP // 2**20} MB: restart the cycle with --scope <the paths the check needs>"
    ws = tempfile.mkdtemp(prefix=f"brain-h2-{arm}-")
    if scope:
        for s in scope:
            src, dst = os.path.join(cwd, s), os.path.join(ws, s)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=SKIP, symlinks=True)
            elif os.path.exists(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
    else:
        shutil.copytree(cwd, ws, ignore=SKIP, symlinks=True, dirs_exist_ok=True)
    for p in patches:
        r = subprocess.run(["git", "apply", "--whitespace=nowarn", p], cwd=ws, capture_output=True, text=True)
        if r.returncode != 0:
            return ws, f"patch {os.path.basename(p)} does not apply: {r.stderr.strip()[-300:]}"
    return ws, None


def arm_patches(sid, led, arm):
    arms = os.path.join(hdir(sid), "arms")
    names = (led["composed"] or {}).get("keep", []) if arm == "composed" else ([arm] if arm in ("general", "domain") else [])
    return [os.path.join(arms, f"{n}.patch") for n in names if os.path.exists(os.path.join(arms, f"{n}.patch"))], names


def verdict_vs(ref, run):
    if not ref or not run:
        return None
    r, c = ref["exit"] == 0, run["exit"] == 0
    return "win" if c and not r else "loss" if r and not c else "tie"


INV_BRIEF = """You improve the INVARIANT procedure of an agent harness (Harness² INV dimension): the steps, helper scripts,
checks and hooks that would have made this sub-task succeed reliably. Prefer, in this order: a deterministic script
(tools/ or a skill's scripts/), a check the agent cannot skip, a narrow skill trigger, and only last more prose.
Read every file in this folder (contract, evidence, verdicts, ledger). Where runs diverged or the agent hand-rolled
a step, the harness left a decision to chance: fix that. Answer with ONE unified diff (git diff style, a/ b/
prefixes, paths relative to the task folder) inside a ```diff block, then one line: WHY: <reason>."""
DOM_BRIEF = """You improve the DOMAIN knowledge of an agent harness (Harness² DOM dimension): what a practitioner of this
task's field knows that the agent missed (units, standards, file formats, typical failure modes), written into the
skill or note the agent reads for this kind of task. Read every file in this folder. Answer with ONE unified diff
(git diff style, a/ b/ prefixes, paths relative to the task folder) inside a ```diff block, then one line: WHY: <reason>."""


def _experience_for(subtask, scope_list):
    """Query prior Harness² experience + safe non-self lesson notes for similar subtasks."""
    words = {w for w in re.findall(r"[a-z0-9]{3,}", (subtask or "").lower()) if w not in ("the", "and", "for", "with", "that", "this")}
    hits = []
    if os.path.isfile(EXPERIENCE_JSONL):
        with open(EXPERIENCE_JSONL, encoding="utf-8", errors="ignore") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                except ValueError:
                    continue
                text = (str(rec.get("subtask", "")) + " " + json.dumps(rec.get("proposals", {}))).lower()
                ov = sum(1 for w in words if w in text)
                if ov > 0 or not words:
                    hits.append((ov, rec))
    hits.sort(key=lambda x: -x[0])
    lines = ["# Experience Library (Harness² prior cycles)", ""]
    for _, rec in hits[:6]:
        lines.append(f"- `{rec.get('session')}` ({rec.get('result')}): subtask={str(rec.get('subtask', ''))[:90]} · "
                     f"parts={rec.get('parts') or {}} · proposals={rec.get('proposals') or {}}")
    lesson_hits = []
    ldir = os.path.join(B.VAULT, "lessons")
    if os.path.isdir(ldir):
        for fn in sorted(os.listdir(ldir)):
            if not fn.endswith(".md") or fn == "harness2-experience.md":
                continue
            p = os.path.join(ldir, fn)
            rel = f"Brain System/lessons/{fn}"
            if not B.lesson_visible(rel, "engineering"):
                continue
            with open(p, encoding="utf-8", errors="ignore") as fh:
                txt = fh.read()
            ov = sum(1 for w in words if w in txt.lower())
            if ov >= 2:
                lesson_hits.append((ov, rel, txt.splitlines()[0] if txt else fn))
    lesson_hits.sort(key=lambda x: -x[0])
    if lesson_hits:
        lines += ["", "## Matching released lessons"]
        for _, rel, hdr in lesson_hits[:5]:
            lines.append(f"- `{rel}` ({hdr[:80]})")
    if len(lines) == 2:
        lines.append("- No matching prior Harness² cycles recorded yet.")
    return "\n".join(lines) + "\n", len(hits[:6]) + len(lesson_hits[:5])


def _auto_hypotheses(d, led):
    """Deterministically turn verdict failures, retrieval gaps, and analysis logs into initial INV/DOM hypotheses."""
    hyps = []
    for fn in sorted(os.listdir(d)):
        if fn.startswith("verdict-") and fn.endswith(".json"):
            v = B.load_json(os.path.join(d, fn), {}) or {}
            for chk in v.get("checks", []) if isinstance(v.get("checks"), list) else []:
                if not chk.get("pass", True):
                    hyps.append(f"- [INV -> scripts/guardrails] `{fn}` failing check `{chk.get('command')}`: {str(chk.get('tail', ''))[:140]}")
            for d_item in v.get("defects", []) if isinstance(v.get("defects"), list) else []:
                hyps.append(f"- [DOM -> skills/memory] `{fn}` defect: {str(d_item)[:140]}")
    rlog = os.path.join(d, "retrieval-log.jsonl")
    if os.path.isfile(rlog):
        with open(rlog, encoding="utf-8", errors="ignore") as fh:
            for ln in fh:
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                kind = row.get("mark") or row.get("action")
                if kind == "missing":
                    hyps.append(f"- [DOM -> skills] Missing capability/note flagged during retrieval: {row.get('what') or row.get('reason')}")
                elif kind == "rejected":
                    hyps.append(f"- [DOM -> tool_guidance] Rejected note `{row.get('path')}`: {row.get('reason', '')}")
    an = B.load_json(os.path.join(d, "analysis.json"), {}) or {}
    for st in (an.get("flow") or {}).get("missing_steps", []):
        hyps.append(f"- [INV -> guardrails/prompt] Flow step skipped before failure: `{st}`")
    if not hyps:
        hyps.append(f"- [INV -> scripts] Encode deterministic pre-check for `{led.get('check')}` so failures fail fast.")
        hyps.append(f"- [DOM -> skills] Clarify domain edge cases for `{led.get('subtask')}` in the active skill/note.")
    body = "# Auto-Hypotheses Across Harness² 8 Editable Parts\n\nParts: `" + "`, `".join(HARNESS_PARTS) + "`\n\n" + "\n".join(hyps) + "\n"
    return body, len(hyps)


def _record_experience(sid, led, improved):
    rec = {
        "ts": B.now(),
        "session": sid,
        "subtask": led.get("subtask"),
        "check": led.get("check"),
        "scope": led.get("scope", []),
        "result": led.get("result"),
        "improved": improved,
        "proposals": led.get("proposals", {}),
        "parts": led.get("parts", {}),
        "composed": led.get("composed"),
        "budget": led.get("budget"),
    }
    os.makedirs(B.STATE, exist_ok=True)
    with open(EXPERIENCE_JSONL, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    os.makedirs(os.path.dirname(EXPERIENCE_MD), exist_ok=True)
    existing_lines = []
    if os.path.exists(EXPERIENCE_MD):
        with open(EXPERIENCE_MD, encoding="utf-8", errors="ignore") as fh:
            for ln in fh:
                if ln.startswith("- `"):
                    existing_lines.append(ln.rstrip("\n"))
    entry = (f"- `{B.today()}` · `{sid}` · **{'IMPROVED' if improved else 'NO-GAIN'}** · "
             f"subtask: `{str(led.get('subtask', ''))[:80]}` · parts: `{led.get('parts') or {}}` · "
             f"kept: `{(led.get('composed') or {}).get('keep', [])}`")
    entries = [e for e in existing_lines if f"`{sid}`" not in e]
    entries.insert(0, entry)
    entries = entries[:50]
    md = (
        "---\n"
        "title: Harness² Experience Library\n"
        "type: lesson\n"
        "status: candidate\n"
        "scope_class: engineering\n"
        f"sources:\n  - sessions/{sid}/\n"
        f"updated: {B.today()}\n"
        "---\n\n"
        "# Harness² Experience Library\n\n"
        "Outcomes of closed in-task Harness² cycles (grounded in session ledgers and Tier-0 probe runs).\n\n"
        "## Recent cycles\n\n"
        + "\n".join(entries)
        + "\n"
    )
    B.atomic_write(EXPERIENCE_MD, md)
    return B.rel(EXPERIENCE_JSONL)


def adapt(sid, led, propose):
    """F1: the evidence folder (Harness² context/), Experience Library hits, auto-hypotheses, two briefs,
    and on --propose the two patches from the other vendor."""
    ctx = os.path.join(hdir(sid), "context")
    os.makedirs(ctx, exist_ok=True)
    d = os.path.join(B.SESSIONS, sid)
    for f in sorted(os.listdir(d)):
        if (
            f in ("contract.md", "report.md", "task-summary.md", "brain-summary.md", "retrieval-log.jsonl", "learn.json", "analysis.json")
            or (f.startswith("verdict-") and f.endswith(".json"))
            or (f.startswith("retrieval-") and f.endswith(".md"))
        ):
            shutil.copy2(os.path.join(d, f), os.path.join(ctx, f))
    ev = os.path.join(d, "evidence.jsonl")
    if os.path.exists(ev):
        with open(ev, encoding="utf-8") as efh:
            tail = "".join(efh.readlines()[-80:])
        B.atomic_write(os.path.join(ctx, "evidence-tail.jsonl"), tail)
    exp_md, exp_hits = _experience_for(led.get("subtask", ""), led.get("scope", []))
    hyp_md, hyp_n = _auto_hypotheses(d, led)
    B.atomic_write(os.path.join(ctx, "EXPERIENCE.md"), exp_md)
    B.atomic_write(os.path.join(ctx, "AUTO-HYPOTHESES.md"), hyp_md)
    B.atomic_write(os.path.join(ctx, "ledger.json"), json.dumps(led, indent=1, ensure_ascii=False))
    B.atomic_write(os.path.join(ctx, "task.md"), f"# Sub-task\n{led['subtask']}\n\n# Check that must pass\n`{led['check']}`\n\n"
                   f"# Task folder\n{led['cwd']}\n\n# Editable Harness² parts\n{', '.join(HARNESS_PARTS)}\n")
    B.atomic_write(os.path.join(ctx, "BRIEF-INV.md"), INV_BRIEF + "\n")
    B.atomic_write(os.path.join(ctx, "BRIEF-DOM.md"), DOM_BRIEF + "\n")
    out = {
        "context": B.rel(ctx),
        "briefs": ["BRIEF-INV.md", "BRIEF-DOM.md"],
        "experience_hits": exp_hits,
        "hypotheses_count": hyp_n,
        "parts_catalog": list(HARNESS_PARTS),
        "proposed": {},
    }
    if not propose:
        out["next"] = "write the two patches yourself (or rerun with --propose), then: harness2.py propose --general-patch ... --domain-patch ..."
        return out
    meta = B.load_json(os.path.join(d, "meta.json"), {})
    vendor = "codex" if meta.get("agent", "claude") == "claude" else "claude"  # the improver is the other vendor
    arms = os.path.join(hdir(sid), "arms")
    os.makedirs(arms, exist_ok=True)
    for arm, brief in (("general", INV_BRIEF), ("domain", DOM_BRIEF)):
        text = brief + "\n\nThe folder is your working directory. Files: " + ", ".join(sorted(os.listdir(ctx)))
        raw = improver_call(vendor, text, ctx)
        m = re.search(r"```diff\n(.*?)```", raw or "", re.S)
        if m:
            B.atomic_write(os.path.join(arms, f"{arm}.patch"), m.group(1))
            why = re.search(r"WHY:\s*(.+)", raw or "")
            led.setdefault("proposals", {})[arm] = (why.group(1).strip() if why else f"{vendor} patch")[:300]
            out["proposed"][arm] = B.rel(os.path.join(arms, f"{arm}.patch"))
        else:
            out["proposed"][arm] = f"no diff returned by {vendor}"
    led["P"] = led.get("P", 0) + 2
    return out


def improver_call(vendor, text, cwd, timeout=900):
    env = dict(os.environ, BRAIN_OFF="1")
    if vendor == "codex":
        out_p = os.path.join(cwd, f".improver-{os.getpid()}.txt")
        cmd = [os.environ.get("BRAIN_CODEX_BIN", "codex"), "exec", "--sandbox", "read-only", "--ephemeral", "--skip-git-repo-check", "-o", out_p, "-"]
        p = subprocess.run(cmd, cwd=cwd, input=text, capture_output=True, text=True, timeout=timeout, env=env)
        if os.path.exists(out_p):
            with open(out_p, encoding="utf-8") as ofh:
                return ofh.read()
        return p.stdout
    cmd = [os.environ.get("BRAIN_CLAUDE_BIN", "claude"), "-p", text, "--allowedTools", "Read", "--permission-mode", "dontAsk"]
    return subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=env).stdout


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--session", required=True)
    s.add_argument("--subtask", required=True)
    s.add_argument("--check", required=True)
    s.add_argument("--scope", nargs="*", default=[])
    s.add_argument("--token-cap", type=int, default=200000)
    ad = sub.add_parser("adapt")
    ad.add_argument("--session", required=True)
    ad.add_argument("--propose", action="store_true")
    p = sub.add_parser("propose")
    p.add_argument("--session", required=True)
    p.add_argument("--general", required=True)
    p.add_argument("--domain", required=True)
    p.add_argument("--general-patch")
    p.add_argument("--domain-patch")
    p.add_argument("--inv-part", choices=HARNESS_PARTS, default="scripts")
    p.add_argument("--dom-part", choices=HARNESS_PARTS, default="skills")
    pr = sub.add_parser("probe")
    pr.add_argument("--session", required=True)
    pr.add_argument("--arm", required=True, choices=["reference", "general", "domain", "composed"])
    pr.add_argument("--output")
    pr.add_argument("--in-place", action="store_true")
    c = sub.add_parser("compare")
    c.add_argument("--session", required=True)
    co = sub.add_parser("compose")
    co.add_argument("--session", required=True)
    co.add_argument("--keep", required=True)
    cl = sub.add_parser("close")
    cl.add_argument("--session", required=True)
    q = sub.add_parser("qualifies")
    q.add_argument("--session", required=True)
    a = ap.parse_args()
    sid = a.session
    if a.cmd == "qualifies":
        print(json.dumps({"session": sid, "qualifies": qualifies(sid)}))
        return 0
    if a.cmd == "start":
        if os.path.exists(lp(sid)):
            sys.exit("a Harness² cycle already exists for this session (one per task)")
        cwd = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), {}).get("cwd") or B.ROOT
        led = {"session": sid, "subtask": a.subtask, "check": a.check, "cwd": cwd, "scope": a.scope, "token_cap": a.token_cap,
               "started": B.now(), "tokens_at_start": tokens_now(sid), "proposals": {}, "runs": [], "composed": None,
               "closed": False, "R": 0, "P": 0}
        save(sid, led)
        print(json.dumps({"started": lp(sid)}))
        return 0
    led = load(sid)
    led.setdefault("cwd", B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), {}).get("cwd") or B.ROOT)
    if led.get("closed"):
        sys.exit("cycle closed")
    if a.cmd == "adapt":
        r = adapt(sid, led, a.propose)
        save(sid, led)
        print(json.dumps(r, indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "propose":
        led["proposals"] = {"general": a.general, "domain": a.domain}
        led["parts"] = {"general": a.inv_part, "domain": a.dom_part}
        arms = os.path.join(hdir(sid), "arms")
        for arm, f in (("general", a.general_patch), ("domain", a.domain_patch)):
            if f:
                os.makedirs(arms, exist_ok=True)
                shutil.copyfile(os.path.expanduser(f), os.path.join(arms, f"{arm}.patch"))
        led["P"] = led.get("P", 0) + sum(1 for x in (a.general, a.domain) if x)
    elif a.cmd == "probe":
        extra = [r for r in led["runs"] if r["arm"] != "reference"]
        if a.arm != "reference" and len(extra) >= MAX_EXTRA:
            sys.exit(f"budget spent: {MAX_EXTRA} extra runs used")
        if a.arm in ("general", "domain") and not led["proposals"]:
            sys.exit("propose both changes first")
        if a.arm == "composed" and not led["composed"]:
            sys.exit("compose first")
        now_t, start_t = tokens_now(sid), led.get("tokens_at_start")
        if now_t is not None and start_t is not None and now_t - start_t > led["token_cap"]:
            sys.exit(f"token cap spent: {now_t - start_t} > {led['token_cap']} tokens since the cycle started")
        led["token_measure"] = "measured from the linked transcript" if now_t is not None and start_t is not None else "unmeasured (no linked transcript)"
        patches, names = arm_patches(sid, led, a.arm)
        if a.in_place:
            ws, err, iso = led["cwd"], None, "not isolated (--in-place)"
        else:
            missing = [n for n in names if not os.path.exists(os.path.join(hdir(sid), "arms", f"{n}.patch"))]
            if missing:
                sys.exit(f"no patch for {missing}: give --general-patch/--domain-patch to propose (or probe --in-place, recorded as not isolated)")
            ws, err = workspace(led, a.arm, patches)
            iso = "isolated copy"
        if err:
            led["runs"].append({"arm": a.arm, "at": B.now(), "exit": "patch_failed" if ws else "copy_refused", "tail": err, "workspace": ws})
            save(sid, led)
            sys.exit(err)
        r = subprocess.run(led["check"], shell=True, cwd=ws, capture_output=True, text=True, timeout=900)
        led["R"] = led.get("R", 0) + 1
        out_copy = out_hash = None
        if a.output:
            src = a.output if os.path.isabs(a.output) else os.path.join(ws, a.output)
            if os.path.exists(src):
                dst = os.path.join(hdir(sid), "probes", a.arm, os.path.basename(src))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                out_copy, out_hash = dst, B.sha256_file(dst)[:16]
        led["runs"].append({"arm": a.arm, "at": B.now(), "exit": r.returncode, "tail": (r.stdout + r.stderr)[-800:], "workspace": ws,
                            "isolation": iso, "patches": [os.path.basename(x) for x in patches], "output": out_copy, "output_sha": out_hash})
    elif a.cmd == "compare":
        rows = {}
        for r in led["runs"]:
            rows[r["arm"]] = r  # latest run of each arm
        ref = rows.get("reference")
        res = {arm: ("pass" if r["exit"] == 0 else "fail") for arm, r in rows.items()}
        vs = {arm: verdict_vs(ref, rows.get(arm)) for arm in ("general", "domain", "composed") if rows.get(arm)}
        pair = {}
        for arm in ("general", "domain", "composed"):
            cand = rows.get(arm)
            if ref and cand and ref.get("output") and cand.get("output") and os.path.exists(ref["output"]) and os.path.exists(cand["output"]):
                import judge_typed as J
                with open(ref["output"], encoding="utf-8", errors="replace") as rf:
                    out_a = rf.read()
                with open(cand["output"], encoding="utf-8", errors="replace") as cf:
                    out_b = cf.read()
                st = {"requirement_text": led["subtask"], "output_a": out_a, "output_b": out_b}
                pair[arm] = J.ask("PAIR-BETTER", st, subject=f"harness2:{sid}:{arm}")["label"]
        led["comparison"] = {"tier0": res, "vs_reference": vs, "pair_better_ref_vs_arm": pair or None, "at": B.now()}
        save(sid, led)
        print(json.dumps(led["comparison"], indent=1))
        return 0
    elif a.cmd == "compose":
        keep = [k.strip() for k in a.keep.split(",") if k.strip() in ("general", "domain")]
        support = {r["arm"] for r in led["runs"] if r["exit"] == 0}
        unsupported = [k for k in keep if k not in support]
        if unsupported:
            sys.exit(f"no observation supports {unsupported}: its probe did not pass")
        led["composed"] = {"keep": keep, "changes": {k: led["proposals"][k] for k in keep}}
    elif a.cmd == "close":
        final = [r for r in led["runs"] if r["arm"] == "composed"]
        if not final:
            sys.exit("the final composed run is mandatory (Harness² ledger: base + candidates + final)")
        led["closed"] = True
        improved = final[-1]["exit"] == 0
        led["result"] = "improved" if improved else "not improved: keep the reference method"
        now_t, start_t = tokens_now(sid), led.get("tokens_at_start")
        led["budget"] = {"R_rollouts": led.get("R", 0), "P_proposals": led.get("P", 0),
                         "tokens": (now_t - start_t) if now_t is not None and start_t is not None else "unmeasured"}
        note = f"Harness² on '{led['subtask']}': {led['result']}; kept {led['composed']['keep'] if led['composed'] else []}; budget {led['budget']}"
        subprocess.run([sys.executable, "-I", os.path.join(B.TOOLS, "brain_session.py"), "checkpoint", "--session", sid, "--note", note],
                       capture_output=True)
        if improved and led["composed"]:
            qpath = os.path.join(B.QUEUE, f"{sid}-harness2.md")
            B.atomic_write(qpath, f"---\ntitle: \"Harness² candidate from {sid}\"\ntype: lesson\nstatus: candidate\nsource: sessions/{sid}/\n"
                                  f"updated: {B.today()}\n---\nFor sub-task '{led['subtask']}' the composed change "
                                  f"{json.dumps(led['composed']['changes'], ensure_ascii=False)} turned a failing check into a pass "
                                  f"(ledger sessions/{sid}/harness2/ledger.json, patches in harness2/arms/). Candidate only; needs varied tasks before release.\n")
            led["queued"] = B.rel(qpath)
        led["experience"] = _record_experience(sid, led, improved)
        try:
            import brain_learn
            led["learned"] = brain_learn.learn_session(sid, refresh_index=True, force=True).get("status")
        except Exception as exc:
            led["learned"] = f"skipped ({exc})"
    save(sid, led)
    print(json.dumps({k: led.get(k) for k in ("subtask", "proposals", "parts", "composed", "result", "queued", "experience", "learned", "budget") if led.get(k) is not None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
