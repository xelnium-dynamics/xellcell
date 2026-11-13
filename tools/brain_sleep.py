#!/usr/bin/env python3
"""
brain_sleep.py — the memory sleep job (layer 11, roadmap 7.1): one writer, staged, checked, released.

    python3 -I brain_sleep.py [--if-due] [--dry-run] [--no-gym]

    python3 -I brain_sleep.py --apply-digest [reports/digest-YYYY-Www.md]   apply the owner's ticked boxes in one pass

Runs by itself: the SessionEnd hook starts it in the background when the last run is older than 20 hours (v2.1:
no longer at SessionStart, so it never writes while a session is starting to work).
Standing permission (layer 11) covers everything it does; the owner only sees the digest and the exception queue.
Steps
 1  lock (state/sleep.lock, 30-minute expiry; an expired lock is taken over and the takeover is logged)
 2  raw/ evidence: every manifest in raw/manifests re-hashed (snapshot.py verify); a mismatch stops all writing
 3  sessions: every session without analysis.json is analysed; open sessions older than 24 h are marked unclosed
 4  queue → Brain System/lessons/ as status: candidate (dedupe by normalised text; queue files are kept)
 5  self-inspection (layer 12 C) from sessions/*/retrieval-log.jsonl and analysis: missing knowledge, rejected cards,
    skipped flow steps → proposals in the digest
 6  rebuild index, vault_scan, vault_audit; any error → this run's vault writes move to _to_delete and no release
 7  evals: route_eval.py; if it fails right after a Gym release, the previous harness config is restored (auto-revert)
 8  Gym night shift weekly (gym.py), unless --no-gym
 9  release: commit only the paths this run wrote (private git index + repo lock), tag rel-YYYYMMDD-n
 10 digest: reports/digest-YYYY-Www.md (changes, exception queue with checkboxes, proposals)
v3 "Fable Art": the release also commits the records of closed sessions (their folders, episodes, the queue, the
digests), so the working tree is clean between releases; the digest lists closed sessions that still wait for the owner's
verdict as checkboxes, sessions closed without a judge or on a failed verdict, and hook errors of the last 7 days;
skipped-step proposals look at the last 14 days and know that the fast lane has no checkpoint.
v2.1 "Ironclad": a queued lesson without an existing sessions/<id>/ or raw/ source is not written (no self-citation,
layer 11); structured lessons (cue / lesson / evidence / confidence) keep their fields; notes whose depends_on
target changed after their last_verified date are listed for the owner.
"""
import argparse, datetime, glob, json, os, re, shutil, socket, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

LOCK = os.path.join(B.STATE, "sleep.lock")
LAST = os.path.join(B.STATE, "sleep-last.json")
DONE = os.path.join(B.STATE, "sleep-consolidated.json")
LOGF = os.path.join(B.STATE, "sleep.log")
LESSONS = os.path.join(B.VAULT, "lessons")


def log(msg):
    with open(LOGF, "a", encoding="utf-8") as fh:
        fh.write(f"{B.now()} {msg}\n")


def acquire():
    now = time.time()
    if os.path.exists(LOCK):
        lk = B.load_json(LOCK, {})
        if lk.get("expiry", 0) > now:
            return False
        log(f"takeover of expired lock {lk}")
    B.atomic_write(LOCK, json.dumps({"owner": "brain_sleep", "pid": os.getpid(), "host": socket.gethostname(),
                                     "start": B.now(), "expiry": now + 1800}))
    return True


def release_lock():
    if os.path.exists(LOCK):
        os.replace(LOCK, LOCK + ".last")


def run(args, timeout=900):
    p = subprocess.run([sys.executable, "-I"] + args, capture_output=True, text=True, timeout=timeout, cwd=B.ROOT)
    return p.returncode, p.stdout, p.stderr


def verify_raw():
    bad = []
    for m in sorted(glob.glob(os.path.join(B.ROOT, "raw", "manifests", "*.json"))):
        rc, so, se = run([os.path.join(B.TOOLS, "snapshot.py"), "verify", "--manifest", m])
        if rc != 0:
            bad.append({"manifest": B.rel(m), "rc": rc, "out": (so + se)[-300:]})
    return bad


def sessions_pass():
    import brain_hooks as H
    import pilot
    analysed, unclosed = [], []
    now = time.time()
    for sid in sorted(os.listdir(B.SESSIONS)) if os.path.isdir(B.SESSIONS) else []:
        d = os.path.join(B.SESSIONS, sid)
        meta = B.load_json(os.path.join(d, "meta.json"), None)
        if not meta:
            continue
        age = now - os.path.getmtime(os.path.join(d, "meta.json"))
        if not os.path.exists(os.path.join(d, "analysis.json")) and age > 7200:
            csid = meta.get("claude_session")
            H.analyse(csid or "", pilot.transcript(csid) if csid else None, meta.get("cwd"), "sleep", meta=meta)
            analysed.append(sid)
        meta = B.load_json(os.path.join(d, "meta.json"), {})
        if meta.get("status") != "closed" and age > 86400:
            if not meta.get("unclosed"):
                meta["unclosed"] = True
                B.atomic_write(os.path.join(d, "meta.json"), json.dumps(meta, indent=1, ensure_ascii=False))
            unclosed.append({"session": sid, "title": meta.get("title")})
    return analysed, unclosed


def norm(text):
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def consolidate(dry):
    done = B.load_json(DONE, [])
    existing = {}
    os.makedirs(LESSONS, exist_ok=True)
    for p in glob.glob(os.path.join(LESSONS, "*.md")):
        existing[norm(B.read_note(p)["body"])] = p
    written, dupes, uncited = [], [], []
    for q in sorted(glob.glob(os.path.join(B.QUEUE, "*.md"))):
        name = os.path.basename(q)
        if name in done:
            continue
        note = B.read_note(q)
        body = note["body"].strip()
        key = norm(body)
        if not key:
            done.append(name)
            continue
        if key in existing:
            dupes.append({"queue": name, "same_as": B.rel(existing[key])})
            done.append(name)
            continue
        src = str(note["meta"].get("source", ""))
        if not cited(src):  # v2.1 (O9): a lesson must rest on a session or raw/ evidence, never on brain notes alone
            uncited.append({"queue": name, "source": src or "(none)"})
            done.append(name)
            continue
        sid = src.strip("/").split("/")[-1] if src else ""
        meta = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), {}) if sid else {}
        title = f"{B.today()} lesson - " + (meta.get("title") or name[:-3])[:60]
        path = os.path.join(LESSONS, B.slugify(title, 80) + ".md")
        text = (f"---\ntitle: \"{title}\"\ntype: lesson\nstatus: candidate\nauthority: agent proposal\n"
                f"scope_class: {meta.get('scope_class') or 'general'}\n"
                f"applies_to: project:{meta.get('project') or 'unknown'}\nsource: {src}\nqueued: queue/{name}\nupdated: {B.today()}\n---\n"
                f"# {title}\n\n{body}\n\nEvidence: [{src}]. Candidate only: used experimentally; releasing it as a procedure needs the owner (layer 11).\n")
        if not dry:
            B.atomic_write(path, text)
        written.append(B.rel(path))
        existing[key] = path
        done.append(name)
    if not dry:
        B.atomic_write(DONE, json.dumps(done, indent=1))
    return written, dupes, uncited


def cited(src):
    src = (src or "").strip()
    return bool(src) and src.startswith(("sessions/", "raw/")) and os.path.exists(os.path.join(B.ROOT, src.rstrip("/")))


def stale_depends():
    """Layer 11 (v2.1, O9): a note with depends_on + last_verified is stale when a dependency changed after that day."""
    stems = {os.path.splitext(os.path.basename(p))[0].lower(): p for p in B.iter_notes()}
    out = []
    for p in B.iter_notes():
        meta = B.read_note(p)["meta"]
        deps, lv = meta.get("depends_on"), str(meta.get("last_verified") or "")
        if not deps or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", lv):
            continue
        cutoff = time.mktime(time.strptime(lv, "%Y-%m-%d")) + 86400
        for dep in deps if isinstance(deps, list) else [deps]:
            d = re.sub(r"^\[\[|\]\]$|\|.*$", "", str(dep)).strip()
            cand = [os.path.join(B.ROOT, d), os.path.join(B.VAULT, d), stems.get(d.lower(), "")]
            f = next((c for c in cand if c and os.path.exists(c)), None)
            if f and os.path.getmtime(f) > cutoff:
                out.append({"note": B.rel(p), "depends_on": d, "last_verified": lv})
    return out


def inspect():
    """Layer 12 C: what the brain's own logs say should improve."""
    missing, rejected, skipped = {}, {}, {}
    for f in glob.glob(os.path.join(B.SESSIONS, "*", "retrieval-log.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                kind = r.get("mark") or r.get("action")
                what = r.get("what") or r.get("reason")
                if kind == "missing" and what:
                    missing[what] = missing.get(what, 0) + 1
                if kind == "rejected" and r.get("path"):
                    rejected.setdefault(r["path"], []).append(r.get("reason", ""))
    cut = time.time() - 14 * 86400
    for f in glob.glob(os.path.join(B.SESSIONS, "*", "analysis.json")):
        a = B.load_json(f, {})
        if (B.local_epoch(a.get("ended")) or 0) < cut:
            continue  # v3 (B3): a proposal is about now, not a running total since the first day
        flow = a.get("flow") or {}
        for step in flow.get("missing_steps", []):
            if step == "checkpoint" and flow.get("lane") == "fast":
                continue  # the fast lane has no checkpoint step
            skipped[step] = skipped.get(step, 0) + 1
    props = [f"Needed and missing ({n}x): \"{w}\" → write a capability card or name the gap" for w, n in sorted(missing.items(), key=lambda x: -x[1])]
    props += [f"Card rejected {len(r)}x: {p} → sharpen its do-not-use-when ({'; '.join(x for x in r if x)[:120]})" for p, r in rejected.items() if len(r) >= 2]
    props += [f"Flow step skipped in {n} session(s): {s} → check why the card/hook did not lead there" for s, n in sorted(skipped.items(), key=lambda x: -x[1])]
    return props


def checks():
    out = os.path.join(B.ROOT, "index", "sleep-checks")
    rc1, so1, _ = run([os.path.join(B.TOOLS, "brain_index.py")])
    rc2, so2, _ = run([os.path.join(B.TOOLS, "vault_scan.py"), "--vault", B.VAULT, "--out", out + "-scan"])
    rc3, so3, _ = run([os.path.join(B.TOOLS, "vault_audit.py"), "--vault", B.VAULT, "--out", out + "-audit"])
    scan, audit = (so2.strip().splitlines() or [""])[-1], (so3.strip().splitlines() or [""])[-1]
    ok = rc1 == 0 and rc2 == 0 and rc3 == 0 and "errors=0" in scan and '"errors": 0' in audit
    return ok, {"index": (so1.strip().splitlines() or [""])[-1], "scan": scan, "audit": audit}


def evals_and_revert():
    rc, so, _ = run([os.path.join(B.TOOLS, "route_eval.py")])
    reverted = False
    cfg, prev = os.path.join(B.STATE, "harness-config.json"), os.path.join(B.STATE, "harness-config.prev.json")
    if rc != 0 and os.path.exists(prev) and os.path.exists(cfg) and os.path.getmtime(cfg) > time.time() - 8 * 86400:
        shutil.copy2(cfg, cfg + f".reverted-{B.today()}")
        shutil.copy2(prev, cfg)
        reverted = True
        rc, so, _ = run([os.path.join(B.TOOLS, "route_eval.py")])
    return rc == 0, so.strip().splitlines()[:2], reverted


def git_release(paths, note):
    if not paths:
        return None
    # v2.1 (O1): a private index + compare-and-swap, under state/repo.lock: never sweeps in what a live
    # session or the owner has staged, never collides with .git/index.lock
    try:
        commit = B.git_commit_paths([B.rel(p) if os.path.isabs(p) else p for p in paths], f"Sleep release: {note}")
    except B.LockBusy:
        log("repo lock busy: release skipped, retried next run")
        return None
    if not commit:
        return None
    tag = B.next_release_tag()
    subprocess.run(["git", "-C", B.ROOT, "tag", tag, commit], capture_output=True, text=True)
    return tag


def judge_health_age():
    jh = B.load_json(os.path.join(B.JUDGE, "health-v2.json"), {}) or {}
    return jh.get("checked", "never (run judge_typed.py health)")


def first_line(p):
    """The lesson's first line of text (headings skipped), for the digest."""
    for line in B.read_note(p)["body"].splitlines():
        if line.strip() and not line.startswith("#"):
            return line.strip()[:140]
    return ""


def digest(rec):
    week = datetime.date.today().isocalendar()
    path = os.path.join(B.ROOT, "reports", f"digest-{week[0]}-W{week[1]:02d}.md")
    cands = [p for p in glob.glob(os.path.join(LESSONS, "*.md")) if "status: candidate" in open(p, encoding="utf-8").read()]
    lines = [f"# Brain digest — week {week[0]}-W{week[1]:02d} (updated {B.now()})", "",
             "## What changed (this run)", f"- release: {rec.get('release') or 'none (nothing to release)'}",
             f"- sessions analysed: {len(rec['analysed'])}; lessons written: {len(rec['lessons'])}; duplicates skipped: {len(rec['dupes'])}",
             f"- checks: {rec['checks']}", f"- route eval: {'pass' if rec['eval_ok'] else 'FAIL'}{' (harness config auto-reverted)' if rec['reverted'] else ''}",
             f"- gym: {rec.get('gym') or 'not due'}", f"- cost: {token_week()}", "", "## Exception queue (needs the owner)"]
    ex = []
    if rec["raw_bad"]:
        ex.append(f"raw/ evidence changed or missing: {rec['raw_bad']} — all writing stopped")
    # v6: The owner's attention is the scarce resource. The digest shows the LESSON_BOXES strongest candidates (a lesson with
    # a cue and an evidence pointer first, then the newest) and counts the rest; they come up in the next digests.
    cands.sort(key=lesson_rank)
    shown, held = cands[:LESSON_BOXES], cands[LESSON_BOXES:]
    boxes = [f"- [ ] approve · [ ] reject — lesson `{B.rel(p)}`: {first_line(p)}" for p in shown]
    boxes += [f"- [ ] approve · [ ] reject — session `{u['session']}` ({u['title']}, unclosed)" for u in rec["unclosed"]]
    waiting, flagged = session_queue()
    # v3 (B4): The owner's verdict on a delivery is the only source of gold labels and of the pilot's cost figure
    boxes += [f"- [ ] approve · [ ] reject — session `{m['id']}` ({str(m.get('title', ''))[:70]}; judge: {(m.get('judge') or {}).get('last') or 'none'})"
              for m in waiting[:15]]
    ex += flagged
    if held:
        ex.append(f"{len(held)} more candidate lesson(s) wait behind the {LESSON_BOXES} shown below (strongest first; the rest follow in the next digest)")
    if len(waiting) > 15:
        ex.append(f"{len(waiting) - 15} older closed session(s) also wait for a verdict (brain_session.py decide --session <id> --approval …)")
    n_err, last_err = B.hook_errors(7)
    if n_err:
        ex.append(f"hook errors in the last 7 days: {n_err} (a gate that errors lets the call through) — last: {last_err[:160]}")
    ex += [f"stale note: {x['note']} depends on {x['depends_on']}, changed after {x['last_verified']}" for x in rec.get("stale_depends", [])]
    ex += [f"lesson not written (no session or raw/ source): queue/{x['queue']} (source {x['source']})" for x in rec.get("uncited", [])]
    if not rec["checks_ok"]:
        ex.append("vault checks failed: this run's writes were set aside, no release")
    if not rec["eval_ok"]:
        ex.append("route eval fails: see tools/route_eval.py output")
    lines += [f"- {e}" for e in ex] or (["- none"] if not boxes else [])
    if boxes:  # v2.1 (O15): tick one box per line, save, then run: python3 -I tools/brain_sleep.py --apply-digest
        lines += ["", "## Decide (tick a box, save, run `python3 -I tools/brain_sleep.py --apply-digest`)", *boxes]
    lines += ["", "## Proposals from the brain's own logs (layer 12 C)"] + ([f"- {p}" for p in rec["proposals"]] or ["- none"])
    lines += ["", f"Judge health v2 checked: {judge_health_age()}"]
    B.atomic_write(path, "\n".join(lines) + "\n")
    return B.rel(path), len(ex), len(boxes)


LESSON_BOXES = 8


def lesson_rank(p):
    """Sort key: structured lessons (cue + evidence) first, then the newest file."""
    try:
        text = open(p, encoding="utf-8", errors="replace").read()
        m = os.path.getmtime(p)
    except OSError:
        return (2, 0)
    structured = bool(re.search(r"^- cue:\s*\S", text, re.M)) and bool(re.search(r"^- evidence:\s*\S", text, re.M))
    return (0 if structured else 1, -m)


def token_week():
    """v6: what the last 7 days cost, from the session analyses the end hook writes (state/analysis/*.jsonl), and what
    the project map answered instead of whole-file reads (state/map-savings.jsonl). Numbers only; no judgement."""
    cut, totals, heavy = time.time() - 7 * 86400, [], ("", 0)
    for f in sorted(glob.glob(os.path.join(B.STATE, "analysis", "*.jsonl")))[-2:]:
        try:
            rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        except (OSError, ValueError):
            continue
        for r in rows:
            t = (r.get("tokens") or {}).get("total")
            if t and (B.local_epoch(r.get("ended")) or 0) >= cut:
                totals.append(t)
                if t > heavy[1]:
                    heavy = (r.get("brain_session") or r.get("claude_session") or "?", t)
    out = "no session analyses in the last 7 days"
    if totals:
        totals.sort()
        out = (f"{len(totals)} analysed session(s) in 7 days, median {totals[len(totals) // 2]:,} tokens, "
               f"heaviest {heavy[1]:,} ({heavy[0]})")
    ans = whole = n = 0
    try:
        for l in open(os.path.join(B.STATE, "map-savings.jsonl"), encoding="utf-8"):
            r = json.loads(l)
            if (B.local_epoch(r.get("t")) or 0) >= cut:
                ans, whole, n = ans + r.get("answer_tokens", 0), whole + r.get("whole_file_tokens", 0), n + 1
    except (OSError, ValueError):
        pass
    if n:
        out += f"; project map: {n} call(s) answered in {ans:,} tokens where the whole files hold {whole:,} (upper bound of the saving)"
    return out


def session_queue():
    """(closed sessions still waiting for the owner's verdict, newest first; exception lines for sessions closed in the
    last 7 days without a judge or on a failed verdict). v3 (B2, B4)."""
    waiting, flagged, cut = [], [], time.time() - 7 * 86400
    for sid in sorted(os.listdir(B.SESSIONS), reverse=True) if os.path.isdir(B.SESSIONS) else []:
        m = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), None)
        if not isinstance(m, dict) or m.get("status") != "closed":
            continue
        if m.get("approval", "pending") == "pending":
            if not m.get("judge"):  # sessions closed before v3 did not record it: read the session's own judge.md
                import brain_session
                rounds, last = brain_session.judge_last(os.path.join(B.SESSIONS, sid))
                m["judge"] = {"rounds": rounds, "last": last}
            waiting.append(m)
        if (B.local_epoch(m.get("closed")) or 0) >= cut:
            if m.get("no_judge"):
                flagged.append(f"closed without a judge: {sid} ({str(m.get('title', ''))[:50]}) — {m['no_judge']}")
            if m.get("unresolved"):
                flagged.append(f"closed on a failed verdict: {sid} ({str(m.get('title', ''))[:50]}) — {m['unresolved']}")
    return waiting, flagged


def record_paths():
    """v3 (C3): what a closed session leaves behind is part of the brain's history and goes into the release:
    its folder, the episodes, the lesson queue and the digests. Open sessions are left alone."""
    out = []
    for sid in sorted(os.listdir(B.SESSIONS)) if os.path.isdir(B.SESSIONS) else []:
        if (B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), {}) or {}).get("status") == "closed":
            out.append(f"sessions/{sid}")
    out += [B.rel(p) for p in glob.glob(os.path.join(B.VAULT, "history", "episodes"))
            + glob.glob(os.path.join(B.VAULT, "history", "learnings"))
            + glob.glob(os.path.join(B.VAULT, "history", "dream-journal.md"))
            + glob.glob(os.path.join(B.VAULT, "lessons", "harness2-experience.md"))
            + glob.glob(os.path.join(B.VAULT, "capabilities", "dream-skill-gaps.md"))
            + glob.glob(os.path.join(B.VAULT, "projects", "*", "episodes"))]
    out += ["queue"] + [B.rel(p) for p in glob.glob(os.path.join(B.ROOT, "reports", "digest-*.md"))
                        + glob.glob(os.path.join(B.ROOT, "reports", "dream-latest.md"))]
    return [p for p in out if os.path.exists(os.path.join(B.ROOT, p))]


def apply_digest(path):
    """the owner's ticked boxes → lesson_decide.py / brain_session.py decide, one pass (v2.1, O15). Both boxes or none: skipped."""
    if path == "latest":
        found = sorted(glob.glob(os.path.join(B.ROOT, "reports", "digest-*.md")))
        if not found:
            sys.exit("no digest in reports/")
        path = found[-1]
    done = []
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^- \[( |x|X)\] approve · \[( |x|X)\] reject — (lesson|session) `([^`]+)`", line)
        if not m:
            continue
        yes, no, kind, ref = m.group(1).strip() != "", m.group(2).strip() != "", m.group(3), m.group(4)
        if yes == no:
            continue
        if kind == "lesson":
            r = run([os.path.join(B.TOOLS, "lesson_decide.py"), ref, "approve" if yes else "reject"])
        else:
            r = run([os.path.join(B.TOOLS, "brain_session.py"), "decide", "--session", ref, "--approval", "approved" if yes else "rejected"])
        done.append({"kind": kind, "ref": ref, "decision": "approve" if yes else "reject", "ok": r[0] == 0, "out": (r[1] or r[2]).strip()[-200:]})
    print(json.dumps({"digest": B.rel(path), "applied": done}, indent=1, ensure_ascii=False))
    return 0 if all(d["ok"] for d in done) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--if-due", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-gym", action="store_true")
    ap.add_argument("--apply-digest", nargs="?", const="latest", help="apply the ticked boxes of a digest")
    a = ap.parse_args()
    if a.apply_digest:
        return apply_digest(a.apply_digest)
    last = B.load_json(LAST, {})
    if a.if_due and last.get("epoch", 0) > time.time() - 20 * 3600:
        return 0
    if not acquire():
        print(json.dumps({"status": "locked"}))
        return 0
    try:
        rec = {"started": B.now(), "dry_run": a.dry_run}
        rec["raw_bad"] = verify_raw()
        if rec["raw_bad"]:
            log(f"STOP raw verify failed {rec['raw_bad']}")
            rec.update({"analysed": [], "unclosed": [], "lessons": [], "dupes": [], "proposals": [], "checks_ok": False,
                        "checks": "skipped (raw/ changed)", "eval_ok": False, "reverted": False})
        else:
            rec["analysed"], rec["unclosed"] = sessions_pass()
            rec["lessons"], rec["dupes"], rec["uncited"] = consolidate(a.dry_run)
            rec["stale_depends"] = stale_depends()
            rec["proposals"] = inspect()
            rec["checks_ok"], rec["checks"] = checks()
            if not rec["checks_ok"] and rec["lessons"] and not a.dry_run:
                dest = os.path.join(B.ROOT, "_to_delete", B.today(), "sleep-rollback")
                os.makedirs(dest, exist_ok=True)
                for p in rec["lessons"]:
                    shutil.move(os.path.join(B.ROOT, p), dest)
                log(f"rollback {rec['lessons']}")
                rec["lessons"] = []
            rec["eval_ok"], rec["eval"], rec["reverted"] = evals_and_revert()
            if not a.no_gym and not a.dry_run and B.load_json(os.path.join(B.STATE, "gym-last.json"), {}).get("epoch", 0) < time.time() - 7 * 86400:
                rc, so, se = run([os.path.join(B.TOOLS, "gym.py")], timeout=3600)
                rec["gym"] = (so.strip().splitlines() or [se.strip()[-200:]])[-1]
        if not a.dry_run and rec["checks_ok"] and rec.get("eval_ok"):
            paths = rec["lessons"] + [p for p in ("Brain System/00-toc",) if os.path.isdir(os.path.join(B.ROOT, p))] + record_paths()
            rec["release"] = git_release(paths, f"{len(rec['lessons'])} candidate lesson(s), TOC, session records")
        rec["digest"], rec["exceptions"], rec["decisions"] = digest(rec)
        rec.update({"finished": B.now(), "epoch": time.time()})
        if not a.dry_run:
            B.atomic_write(LAST, json.dumps(rec, indent=1, ensure_ascii=False))
        log(f"run done release={rec.get('release')} lessons={len(rec['lessons'])} exceptions={rec['exceptions']}")
        print(json.dumps({k: rec[k] for k in ("release", "lessons", "analysed", "checks_ok", "eval_ok", "digest", "exceptions", "decisions") if k in rec}, indent=1))
        return 0
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
