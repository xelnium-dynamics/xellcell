#!/usr/bin/env python3
"""
route_real.py — how the skill router behaves on the owner's own words (v6, layer 4). Reported, never a gate.

    python3 -I route_real.py [--sessions DIR] [--transcripts DIR ...] [--json] [--out FILE]

Why it exists: a prompt set written by the same agent that wrote the router cannot be blind for that router, however
honestly it is kept apart (judge rounds 2 and 3 of the v6 session said so, and they were right). The only prompts no
router author has shaped are the ones the owner really typed. This tool measures three things on them, with no label that an
agent had to invent:

 A  requests   every closed, non-private session's "Request (verbatim)": which skills the per-message hook would offer.
               Printed per session (skill names only), so two router versions can be compared request by request:
               same list, gained a skill, lost a skill.
 B  read hits  the sessions whose evidence log holds a real Read of a SKILL.md: was that skill among the five offered
               for the request? This is the one true label the records carry. It is small today and grows by itself,
               because the PostToolUse hook logs every Read.
 C  short messages  the owner's real typed messages of at most four words from the local Claude Code transcripts
               (machine-made messages, slash commands and test-harness folders left out): how many would get a skill
               list injected. Four words is a fixed rule, not a judgement; some short messages are real tasks, so this
               is a measure of noise on real traffic, not a false-alarm rate.

Privacy: the output holds session ids, skill names, counts and a 10-character hash per short message; never the text of
a message. Sessions of scope cv_official / personal are skipped. Nothing is written unless --out is given.
"""
import argparse, glob, hashlib, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import brain_hooks as H  # noqa: E402

MACHINE = re.compile(r"^\s*(?:<|\[|/|Caveat:|This session is being continued)", re.I)
SKIP_PROJECT = re.compile(r"^-private-(?:tmp|var)|scratchpad|brain-entry|brain-e2e", re.I)


_INDEX_READY = []


def offered(text, scope="general"):
    if not _INDEX_READY:  # a fresh clone has no index yet: build it before scoring
        import brain_route
        brain_route.ensure_index()
        _INDEX_READY.append(True)
    return [s.get("short") or re.sub(r"[\s_]+", "-", s["name"].split(":", 1)[-1].lower()) for s in H.pick_skills(text, scope=scope)]


def requests(sessions_dir, keep_text=False):
    rows = []
    for sid in sorted(os.listdir(sessions_dir)) if os.path.isdir(sessions_dir) else []:
        d = os.path.join(sessions_dir, sid)
        meta = B.load_json(os.path.join(d, "meta.json"), None)
        if not isinstance(meta, dict) or meta.get("status") != "closed":
            continue
        try:
            c = open(os.path.join(d, "contract.md"), encoding="utf-8").read()
        except OSError:
            continue
        sm = re.search(r"^scope_class:\s*(\w+)", c, re.M)
        if (sm.group(1) if sm else meta.get("scope_class")) in B.PRIVATE_SCOPES:
            continue
        m = re.search(r"^## Request \(verbatim\)[^\n]*\n(.*?)(?=^## |\Z)", c, re.S | re.M)
        req = m.group(1).strip() if m else ""
        if not req or "<paste the owner's request exactly>" in req:
            continue
        read = set()
        try:
            for line in open(os.path.join(d, "evidence.jsonl"), encoding="utf-8"):
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                f = str(r.get("file") or "")
                if r.get("tool") == "Read" and f.endswith("/SKILL.md"):
                    read.add(os.path.basename(os.path.dirname(f)).lower())
        except OSError:
            pass
        # v7 (Argon, round 4): the live hook routes with the session's scope once a contract exists (family boosts and
        # the brand / website floor depend on it); `offered_general` is what the very first message would get.
        scope = (sm.group(1) if sm else meta.get("scope_class")) or "general"
        scope = scope if scope in B.SCOPES else "general"
        got = offered(req, scope)
        rows.append({"session": sid, "scope": scope, "words": len(req.split()), "offered": got,
                     "offered_general": got if scope == "general" else offered(req, "general"), "skills_read": sorted(read),
                     "read_hit": bool(read & set(got)) if read else None, **({"text": req} if keep_text else {})})
    return rows


def short_messages(roots, max_words=4, keep_text=False):
    seen, rows = set(), []
    for root in roots:
        root = os.path.expanduser(root)
        for proj in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            if SKIP_PROJECT.search(proj):
                continue
            for fp in sorted(glob.glob(os.path.join(root, proj, "*.jsonl"))):
                try:
                    fh = open(fp, encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                with fh:
                    for line in fh:
                        if '"type":"user"' not in line and '"type": "user"' not in line:
                            continue
                        try:
                            rec = json.loads(line)
                        except ValueError:
                            continue
                        if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain"):
                            continue
                        content = (rec.get("message") or {}).get("content")
                        if isinstance(content, list):
                            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                                continue
                            content = " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
                        text = str(content or "").strip()
                        if not text or MACHINE.match(text) or "\n" in text or len(text.split()) > max_words or len(text) < 2:
                            continue
                        key = re.sub(r"\s+", " ", text.lower())
                        if key in seen:
                            continue
                        seen.add(key)
                        got = offered(text)
                        rows.append({"hash": hashlib.sha1(key.encode("utf-8")).hexdigest()[:10], "words": len(text.split()), "offered": got,
                                     **({"text": text} if keep_text else {})})
    return rows


def summary(req_rows, msg_rows):
    labelled = [r for r in req_rows if r["read_hit"] is not None]
    hit = [r for r in msg_rows if r["offered"]]
    return {"requests": len(req_rows), "requests_with_an_offer": sum(1 for r in req_rows if r["offered"]),
            "skills_offered_total": sum(len(r["offered"]) for r in req_rows),
            "requests_whose_scope_changes_the_offer": sum(1 for r in req_rows if r["offered"] != r["offered_general"]),
            "sessions_with_a_real_skill_read": len(labelled), "read_skill_was_offered": sum(1 for r in labelled if r["read_hit"]),
            "short_messages": len(msg_rows), "short_messages_that_get_a_skill_list": len(hit),
            "short_message_trigger_rate": round(len(hit) / len(msg_rows), 3) if msg_rows else None,
            "gate": "none (reported only)"}


def write_sheet(path, req_rows, msg_rows):
    """v7: the one thing no agent can do for the owner — say which offered skill was right. A local sheet with his own requests
    and short messages; he ticks boxes, `--labels` scores the router against them. The sheet holds his words: it stays on
    this machine (reports/route-labels*.md is git-ignored) and no result file ever copies them."""
    out = ["# Router label sheet — tick what is right, save, then: python3 -I tools/route_real.py --labels <this file>", "",
           "For a request: tick every offered skill that really fits; tick `none of these fit` when none does; name a skill that",
           "should have been offered after `missing:`. Leave a block untouched to skip it. For a short message: tick task or talk.", "",
           "## Requests"]
    for r in req_rows:
        out += ["", f"### {r['session']} (scope {r['scope']})", "> " + re.sub(r"\s+", " ", r.get("text", ""))[:400]]
        out += [f"- [ ] {s}" for s in r["offered"]] + ["- [ ] none of these fit", "- missing: "]
    out += ["", "## Short messages (is it a task that deserves skills, or just talk?)"]
    for m in msg_rows:
        out.append(f"- [ ] task · [ ] talk — `{m['hash']}` \"{m.get('text', '')}\" → offered: {', '.join(m['offered']) or 'nothing'}")
    B.atomic_write(path, "\n".join(out) + "\n")


def read_labels(path, req_rows, msg_rows):
    """Score the CURRENT router against the owner's ticks. Returns counts only."""
    text = open(path, encoding="utf-8").read()
    now = {r["session"]: r for r in req_rows}
    lab = hit = none_fit = none_fit_quiet = right = offered_n = missing = 0
    for block in re.split(r"^### ", text, flags=re.M)[1:]:
        sid = block.split()[0]
        ticked = set(re.findall(r"^- \[[xX]\] (?!none of these fit)(\S+)", block, re.M))
        nofit = bool(re.search(r"^- \[[xX]\] none of these fit", block, re.M))
        wanted = [w.strip() for w in re.findall(r"^- missing:[ \t]*(\S.*)$", block, re.M)]
        if sid not in now or not (ticked or nofit or wanted):
            continue
        lab += 1
        got = set(now[sid]["offered"])
        offered_n += len(got)
        right += len(got & ticked)
        hit += bool(got & ticked)
        none_fit += nofit
        none_fit_quiet += nofit and not got
        missing += len(wanted)
    talk_alarm = task_miss = talk = task = 0
    cur = {m["hash"]: m for m in msg_rows}
    for t1, t2, h in re.findall(r"^- \[([ xX])\] task · \[([ xX])\] talk — `(\w+)`", text, re.M):
        if h not in cur or (t1 == " ") == (t2 == " "):
            continue
        if t2 != " ":
            talk, talk_alarm = talk + 1, talk_alarm + bool(cur[h]["offered"])
        else:
            task, task_miss = task + 1, task_miss + (not cur[h]["offered"])
    return {"labelled_requests": lab, "requests_with_a_right_skill_offered": hit, "offered_skills": offered_n, "offered_and_ticked_right": right,
            "requests_where_nothing_offered_fits": none_fit, "skills_named_as_missing": missing,
            "short_messages_marked_talk": talk, "talk_that_got_a_skill_list": talk_alarm,
            "short_messages_marked_task": task, "task_that_got_nothing": task_miss, "gate": "none (reported only)"}


def main():
    ap = argparse.ArgumentParser(description="Router behaviour on the owner's real requests and short messages (reported, never a gate).")
    ap.add_argument("--sheet", metavar="FILE", help="v7: write a local label sheet (the owner's requests and short messages with tick boxes)")
    ap.add_argument("--labels", metavar="FILE", help="v7: score the current router against a ticked label sheet (prints counts only)")
    ap.add_argument("--sessions", default=B.SESSIONS)
    ap.add_argument("--transcripts", nargs="*", default=["~/.claude/projects"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="write the full result (ids, skill names, hashes; no message text) to this file")
    a = ap.parse_args()
    if a.sheet or a.labels:
        req_rows, msg_rows = requests(a.sessions, keep_text=bool(a.sheet)), short_messages(a.transcripts, keep_text=bool(a.sheet))
        if a.sheet:
            write_sheet(os.path.expanduser(a.sheet), req_rows, msg_rows)
            print(json.dumps({"sheet": a.sheet, "requests": len(req_rows), "short_messages": len(msg_rows),
                              "next": "tick the boxes, save, then run with --labels <file>"}, indent=1))
        else:
            print(json.dumps(read_labels(os.path.expanduser(a.labels), req_rows, msg_rows), indent=1))
        return 0
    req_rows, msg_rows = requests(a.sessions), short_messages(a.transcripts)
    res = {"router_sha256": B.sha256_file(os.path.join(B.TOOLS, "hydro_skills.py")) if os.path.exists(os.path.join(B.TOOLS, "hydro_skills.py")) else None,
           "at": B.now(), "sessions_dir": a.sessions, "summary": summary(req_rows, msg_rows), "requests": req_rows, "short_messages": msg_rows}
    if a.out:
        B.atomic_write(a.out, json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(res if a.json else {k: res[k] for k in ("router_sha256", "at", "summary")}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
