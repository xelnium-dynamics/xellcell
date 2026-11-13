#!/usr/bin/env python3
"""
brain_session.py — session records for the brain flow (layers 2, 7, 10).

    new        --agent claude|codex --cwd PATH --title "..." [--lane standard] [--scope general] [--project slug]
               creates sessions/<id>/ with meta.json and a contract.md to fill in
    checkpoint --session ID --note "..." [--files f1 f2 ...]   adds checkpoints/NN.md (files hashed)
    close      --session ID [--approval pending|approved|rejected|approved-with-exception] [--project slug]
               needs task-summary.md and brain-summary.md in the session folder (creates templates if missing);
               writes the episode as a NEW file in Brain System/projects/<project>/episodes/ (or Brain System/history/episodes/)
               and queues a lesson file only when the Brain Summary proposes one
    status     [--cwd PATH]   lists open sessions
    capsule    --session ID   v6: the session in one screen, from its records (goal, requirements, done, files, open errors,
               judge fix list); refreshed by every checkpoint, printed by the start hook after a compaction
    lint       --session ID   REQ-TESTABLE + CONSTRAINT-QUOTED checks on the contract (exit 1 on problems)
    decide     --session ID --approval approved|rejected [--failed R2,R3]   the owner's later decision; writes REQ-MET gold labels
               (judge/gold/owner/REQ-MET.jsonl) from the last verdict: approved -> judged-pass requirements are "yes",
               --failed ids are "no"
    handoff    rewrites the auto-updated "Latest sessions" table in HANDOFF.md (all agents)
v2.1 "Ironclad":
- fast lane in one command: new --lane fast --request "<the owner's words>" [--check "<cmd>"] writes a complete contract,
  so the edit gate opens at once; close --summary "<one line>" writes both summaries for a fast-lane session.
- close checks every file the task summary's "Verified" row cites (deterministic CLAIM-SUPPORT, layer 10);
  --force-claims records an override.
- lint copies lane and scope_class from contract.md into meta.json, so the two never disagree.
v3 "Fable Art":
- step 2 runs by itself: `new --request` and a passing `lint` route the contract, write retrieval-NN.md and print the
  notes and skills (BRAIN_NO_AUTOROUTE=1 switches it off).
- close in the standard and deep lanes needs a judge verdict, or --no-judge "<why>"; a last verdict of fail needs
  --unresolved "<why>". Both reasons are recorded in meta.json and shown to the owner in the digest.
- the episode's summary is the Delivered line (not "title — pending"); `decide` updates the episode's approval.
Session folders are working state; the only shared-memory write is the new episode file.
"""
import argparse, json, os, re, secrets, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

CONTRACT = """---
session: {sid}
title: "{title}"
agent: {agent}
cwd: "{cwd}"
created: {created}
contract_version: 1
lane: {lane}            # fast | standard | deep
scope_class: {scope}    # cv_official | personal | engineering | website | brand | research | system | general
novelty: reuse          # reuse | explore
project: {project}
---
# Contract — {title}

## Request (verbatim)
<paste the owner's request exactly>

## Deliverables
-

## Hard requirements (each with its check)
- R1: … — check: …

## Preferences
-

## Constraints (quoted from the request)
- "…"

## Assumptions (confirmed | assumed | unknown)
- A1: … — unknown

## Permissions and spend
No paid API or spend · no image/video generation unless the owner says "generate" · no installs or pushes without the owner.

## Out of scope
-

## Checks (optional, run by brain_judge.py as Tier 0; one per line)
<!-- - R1: cmd: <shell command that exits 0 when R1 is met> -->

## Changes
<!-- v2 — what changed, why, asked by whom -->
"""

TASK_SUMMARY = """# Task Summary — {title}

| Field | Content |
|---|---|
| Delivered | |
| Verified (requirement → tier → evidence) | |
| Not verified (requirement → why) | |
| Limits | |
| Next step / handoff | |
| Approval | pending |
"""

BRAIN_SUMMARY = """# Brain Summary — {title}

| Field | Content |
|---|---|
| Reused (notes, cards, skills) | |
| Observed (facts, failures with conditions) | |
| Proposed lesson | none |
| Lesson cue (when it applies) | |
| Lesson evidence (sessions/<id>/… or raw/…) | |
| Lesson confidence (low / medium / high) | |
| Tested / adopted / rejected | |
| Retrieval: useful · rejected (why) · missing | |
| Brain release | {release} |
"""


def sdir(sid):
    d = os.path.join(B.SESSIONS, sid)
    if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-z]+-[0-9a-f]{4}", sid) or not os.path.isdir(d):
        sys.exit(f"unknown session: {sid}")
    return d


def fast_contract(text, request, check):
    """Fill the template for a fast-lane task: verbatim request + one requirement, nothing else to write."""
    text = text.replace("<paste the owner's request exactly>", request.strip())
    req = (f"- R1: the requested change is made and nothing else changed — check: cmd: {check}" if check else
           "- R1: the requested change is made, reversible in git, nothing else changed — check: The owner sees the result (fast lane)")
    text = text.replace("- R1: … — check: …", req)
    text = text.replace('- "…"', "- (none quoted)").replace("- A1: … — unknown", "- A1: small and reversible (fast lane) — assumed")
    if check:
        text = text.replace("<!-- - R1: cmd: <shell command that exits 0 when R1 is met> -->", f"- R1: cmd: {check}")
    return text


def auto_route(sid):
    """v3 (B1): step 2 without a second command. Never fails the caller; an error is reported, not raised."""
    if os.environ.get("BRAIN_NO_AUTOROUTE") == "1":
        return None
    try:
        import brain_route as R
        r = R.for_session(sid)
    except (Exception, SystemExit) as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {"file": r["file"], "notes": [f"{n['title']} · {n['path']}" for n in r["notes"][:6]],
            "skills": [f"{s['name']} · {s['where']}" for s in r["skills"][:5]],
            "next": f"open what fits: brain_fetch.py --session {sid} <path>; read the SKILL.md of each skill that fits"}


def has_retrieval(d):
    return any(f.startswith("retrieval-") and f.endswith(".md") for f in os.listdir(d))


def judge_last(d):
    """(rounds, last overall) from the session's judge.md, which carries the Tier 0 override."""
    vs = [f for f in os.listdir(d) if f.startswith("verdict-") and f.endswith(".json")]
    last = None
    jp = os.path.join(d, "judge.md")
    if os.path.exists(jp):
        hits = re.findall(r"round \d+: (\w+)", open(jp, encoding="utf-8").read())
        last = hits[-1] if hits else None
    return len(vs), last


def cmd_new(a):
    sid = time.strftime("%Y%m%d-%H%M%S") + f"-{a.agent}-{secrets.token_hex(2)}"
    d = os.path.join(B.SESSIONS, sid)
    os.makedirs(os.path.join(d, "checkpoints"))
    cwd = os.path.realpath(os.path.expanduser(a.cwd or os.getcwd()))
    project = a.project or B.project_for_cwd(cwd) or "none"
    lane = a.lane if a.lane in B.LANES else "standard"
    scope = a.scope if a.scope in B.SCOPES else "general"
    title = a.title.replace('"', "'")
    meta = {"id": sid, "agent": a.agent, "cwd": cwd, "title": title, "created": B.now(), "status": "open",
            "lane": lane, "scope_class": scope, "project": project, "brain_release": B.git_release()}
    B.atomic_write(os.path.join(d, "meta.json"), json.dumps(meta, indent=1, ensure_ascii=False) + "\n", exclusive=True)
    contract = CONTRACT.format(sid=sid, title=title, agent=a.agent, cwd=cwd, created=meta["created"], lane=lane, scope=scope, project=project)
    if a.request:
        contract = fast_contract(contract, a.request, a.check) if lane == "fast" else contract.replace("<paste the owner's request exactly>", a.request.strip())
    B.atomic_write(os.path.join(d, "contract.md"), contract, exclusive=True)
    out = {"session": sid, "folder": d, "contract": os.path.join(d, "contract.md")}
    if a.request:
        r = auto_route(sid)
        if r:
            out["retrieval"] = r
    print(json.dumps(out, ensure_ascii=False))


def _jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return [r for r in rows if isinstance(r, dict)]


def capsule(sid, write=True):
    """v6: the session in one screen, built from its records (never from memory): goal, requirements with their last
    Tier-0 state, what the checkpoints say was done, files touched, open errors, the judge's fix list, what was reused.
    It is what an agent reads after a compaction or a hand-off instead of re-deriving the session. Maker-side only:
    the judge never sees it. Kept under ~2,000 characters."""
    import brain_judge as J
    d = sdir(sid)
    meta = B.load_json(os.path.join(d, "meta.json"), {}) or {}
    contract = open(os.path.join(d, "contract.md"), encoding="utf-8").read() if os.path.exists(os.path.join(d, "contract.md")) else ""
    one = lambda t, n: re.sub(r"\s+", " ", str(t)).strip()[:n]
    vs = sorted(f for f in os.listdir(d) if f.startswith("verdict-") and f.endswith(".json"))
    last = (B.load_json(os.path.join(d, vs[-1]), {}) or {}) if vs else {}
    t0 = {str(r.get("requirement")): ("pass" if r.get("exit") == 0 else "FAIL") for r in last.get("tier0") or []}
    jv = {}
    for r in ((last.get("verdict") or {}).get("verdicts") or []):
        m = re.search(r"\b(R\d+)\b", str(r.get("requirement", "")))
        if m:
            jv[m.group(1)] = r.get("verdict")
    lines = [f"# Capsule — {meta.get('title', sid)} ({sid}) · lane {meta.get('lane')} · scope {meta.get('scope_class')} · {B.now()}",
             "Goal: " + (one(section(contract, "Request (verbatim)"), 320) or "(contract not filled)")]
    reqs = J.requirements(contract)
    if reqs:
        lines.append("Requirements: " + " · ".join(
            f"{rid} {one(text, 60)} [{'judge ' + str(jv[rid]) if rid in jv else 'T0 ' + t0[rid] if rid in t0 else 'open'}]" for rid, text, _ in reqs[:9]))
    cp_dir = os.path.join(d, "checkpoints")
    cps = sorted(f for f in os.listdir(cp_dir) if f.endswith(".md")) if os.path.isdir(cp_dir) else []
    if cps:
        lines.append(f"Done ({len(cps)} checkpoint(s), newest last):")
        for c in cps[-5:]:
            body = open(os.path.join(cp_dir, c), encoding="utf-8").read().split("\n", 2)
            lines.append(f"- {c[:-3]}: {one(body[2] if len(body) > 2 else '', 170)}")
    ev = _jsonl(os.path.join(d, "evidence.jsonl"))
    changed = J.changed_files(ev, os.path.realpath(d))
    if changed:
        top = sorted(changed.items(), key=lambda kv: -kv[1])[:8]
        home = os.path.expanduser("~")
        lines.append("Files touched (edits): " + " · ".join(f"{p.replace(home, '~')}×{n}" for p, n in top)
                     + (f" · +{len(changed) - 8} more" if len(changed) > 8 else ""))
    open_err, _ = J.error_events(ev, limit=3)
    for r in open_err:
        tail = one(str(r.get("stderr_tail") or "") or str(r.get("stdout_tail") or ""), 110)
        lines.append(f"Open error: `{one(r.get('command', ''), 80)}` → {tail}")
    rounds, overall = judge_last(d)
    if rounds:
        lines.append(f"Judge: {rounds} round(s), last {overall}")
        lines += [f"- fix {one(x['requirement'], 40)}: {one(x['fix'], 150)}" for x in J.fix_list(last.get("verdict"), last.get("tier0") or [])[:4]]
    used = [r.get("path") for r in _jsonl(os.path.join(d, "retrieval-log.jsonl")) if (r.get("mark") or r.get("action")) == "used" and r.get("path")]
    skills = sorted({os.path.basename(os.path.dirname(str(r.get("file")))) for r in ev if r.get("tool") == "Read" and str(r.get("file", "")).endswith("/SKILL.md")})
    if used or skills:
        lines.append("Reused: " + " · ".join(list(dict.fromkeys(used))[:5] + [f"skill {x}" for x in skills[:6]]))
    lines.append(f"Records: {B.rel(d)}/ (contract.md, checkpoints/, evidence.jsonl{', ' + vs[-1] if vs else ''})")
    text = "\n".join(lines)[:2400]
    if write:
        try:
            B.atomic_write(os.path.join(d, "capsule.md"), text + "\n")
        except OSError:
            pass
    return text


def cmd_capsule(a):
    print(capsule(a.session))
    return 0


def cmd_checkpoint(a):
    d = sdir(a.session)
    cp = os.path.join(d, "checkpoints")
    n = len([f for f in os.listdir(cp) if f.endswith(".md")]) + 1
    lines = [f"# Checkpoint {n:02d} — {B.now()}", "", a.note.strip(), ""]
    for f in a.files or []:
        p = os.path.realpath(os.path.expanduser(f))
        lines.append(f"- `{p}` sha256 {B.sha256_file(p)}" if os.path.isfile(p) else f"- `{p}` (missing)")
    B.atomic_write(os.path.join(cp, f"{n:02d}.md"), "\n".join(lines) + "\n", exclusive=True)
    try:  # v6: every milestone refreshes the resume note; a failure here never costs the checkpoint
        capsule(a.session)
    except (Exception, SystemExit):
        pass
    print(json.dumps({"session": a.session, "checkpoint": n}))


def section(text, name):
    m = re.search(r"^## " + re.escape(name) + r"[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def field(task, name):
    """A task-summary field in either accepted form: the template's table row, or a line `Name: text` (v3, B8)."""
    m = (re.search(r"^\|\s*" + name + r"[^|\n]*\|\s*(.*?)\s*\|\s*$", task, re.M | re.I)
         or re.search(r"^[ \t>*-]*\**" + name + r"\**[^:|\n]{0,60}:\**[ \t]*(\S.*)$", task, re.M | re.I))
    return m.group(1).strip() if m else ""


def cmd_close(a):
    d = sdir(a.session)
    meta = B.load_json(os.path.join(d, "meta.json"), {})
    if meta.get("status") == "closed":
        sys.exit("session already closed")
    ts, bs = os.path.join(d, "task-summary.md"), os.path.join(d, "brain-summary.md")
    if a.summary and meta.get("lane") == "fast" and not os.path.exists(ts):  # v2.1 (O8): fast lane closes in one line
        ev = len(open(os.path.join(d, "evidence.jsonl"), encoding="utf-8").read().splitlines()) if os.path.exists(os.path.join(d, "evidence.jsonl")) else 0
        B.atomic_write(ts, TASK_SUMMARY.format(title=meta.get("title", "")).replace("| Delivered | |", f"| Delivered | {a.summary} |")
                       .replace("| Verified (requirement → tier → evidence) | |", f"| Verified (requirement → tier → evidence) | R1 → fast lane → evidence.jsonl ({ev} lines) |"), exclusive=True)
        if not os.path.exists(bs):
            B.atomic_write(bs, BRAIN_SUMMARY.format(title=meta.get("title", ""), release=B.git_release()), exclusive=True)
    missing = []
    for path, tpl in ((ts, TASK_SUMMARY), (bs, BRAIN_SUMMARY)):
        if not os.path.exists(path):
            B.atomic_write(path, tpl.format(title=meta.get("title", ""), release=B.git_release()), exclusive=True)
            missing.append(path)
    if missing:
        print(json.dumps({"status": "fill_summaries", "files": missing}))
        return 1
    task, brain = open(ts, encoding="utf-8").read(), open(bs, encoding="utf-8").read()
    if "| Delivered | |" in task or "| Verified (requirement → tier → evidence) | |" in task:
        print(json.dumps({"status": "summaries_still_empty", "file": ts}))
        return 1
    if not field(task, "Delivered") or not field(task, "Verified"):  # v3 (B8): a free-form summary hid from the claim check
        print(json.dumps({"status": "summary_fields_missing", "file": ts, "fix": "task-summary.md needs a Delivered and a Verified entry "
                          "(the template's table rows, or lines starting `Delivered:` and `Verified:`): the claim check, the episode "
                          "summary and the judge read them"}))
        return 1
    unsupported = unsupported_claims(task, meta.get("cwd") or B.ROOT, d)
    if unsupported and not a.force_claims:
        print(json.dumps({"status": "claims_unsupported", "missing_files": unsupported,
                          "fix": "correct the Verified row in task-summary.md, or rerun close with --force-claims"}, ensure_ascii=False))
        return 1
    if unsupported:
        meta["forced_claims"] = unsupported
    contract = open(os.path.join(d, "contract.md"), encoding="utf-8").read()
    lm = re.search(r"^lane:\s*(\w+)", contract, re.M)
    lane = lm.group(1) if lm and lm.group(1) in B.LANES else (meta.get("lane") or "standard")
    rounds, last = judge_last(d)
    if lane != "fast":  # v3 (B2): step 6 is checked where it cannot be forgotten; the way out is one recorded sentence
        if not rounds and not a.no_judge:
            print(json.dumps({"status": "judge_missing", "fix": f"step 6: brain_judge.py --session {a.session} --artifacts <files>; "
                              "or rerun close with --no-judge \"<why>\" (recorded, shown to the owner in the digest)"}))
            return 1
        if last == "fail" and not a.unresolved:
            print(json.dumps({"status": "judge_failed", "fix": "the last verdict is fail: fix and judge again (max 2 fix rounds, then "
                              "harness2.py or the owner); or rerun close with --unresolved \"<why>\" (recorded, shown to the owner in the digest)"}))
            return 1
    meta["judge"] = {"rounds": rounds, "last": last}
    if a.no_judge:
        meta["no_judge"] = a.no_judge
    if a.unresolved:
        meta["unresolved"] = a.unresolved
    if os.environ.get("BRAIN_SESSION_ONLY_CLOSE") == "1":  # proposal from Codex session 33eb (applied v2.1): no shared write
        meta.update({"status": "closed", "closed": B.now(), "approval": a.approval, "episode": None, "episode_pending": True})
        B.atomic_write(os.path.join(d, "meta.json"), json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
        print(json.dumps({"status": "closed", "episode": None, "index": "unchanged", "episode_pending": True}))
        return 0
    project = a.project or meta.get("project") or "none"
    approval = a.approval
    base = os.path.join(B.VAULT, "projects", project, "episodes") if project not in ("", "none") else os.path.join(B.VAULT, "history", "episodes")
    title = meta.get("title", "untitled")
    ep_name = f"{a.session[:8]} {title[:60]} ({a.session[-4:]}).md".replace("/", "-")
    cps = sorted(f for f in os.listdir(os.path.join(d, "checkpoints")) if f.endswith(".md"))
    summary = re.sub(r"\s+", " ", field(task, "Delivered") or title).replace('"', "'")[:200]  # v3 (C2): says what was done
    ep = [
        "---", f"title: \"Episode: {title}\"", "type: episode", f"id: ep-{a.session}", f"project: {project}",
        f"agent: {meta.get('agent')}", f"lane: {meta.get('lane')}", f"approval: {approval}",
        f"brain_release: {meta.get('brain_release')}", "authority: agent-observation", f"judge: {last or 'none'}",
        f"summary: \"{summary}\"", f"sources: [\"sessions/{a.session}/\"]", f"updated: {B.today()}", "---",
        f"# Episode: {title}", "", "## Task (verbatim)", section(contract, "Request (verbatim)") or "(not recorded)", "",
        task.split("\n", 1)[1].strip() if task.startswith("# ") else task.strip(), "",
        brain.split("\n", 1)[1].strip() if brain.startswith("# ") else brain.strip(), "",
        "## Checkpoints", *([f"- sessions/{a.session}/checkpoints/{c}" for c in cps] or ["- none"]), "",
    ]
    ep_path = os.path.join(base, ep_name)
    B.atomic_write(ep_path, "\n".join(ep) + "\n", exclusive=True)
    queued = None
    meta.update({"status": "closed", "closed": B.now(), "approval": approval, "episode": B.rel(ep_path)})
    B.atomic_write(os.path.join(d, "meta.json"), json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    learn_res = None
    try:  # v4 Hydro: immediately capture session learnings, gotchas, and skill telemetry
        import brain_learn
        learn_res = brain_learn.learn_session(a.session, refresh_index=False, force=True)
        queued_rel = (learn_res or {}).get("queued") or []
        queued = os.path.join(B.ROOT, queued_rel[0]) if queued_rel else None
    except Exception as e:
        learn_res = {"error": f"{type(e).__name__}: {e}"}
    # v7 (Argon, round 4): brain_learn.py is the one place that queues lessons (max 3, deduplicated, one naming scheme).
    # The v3 code below runs only when brain_learn failed, so a proposed lesson is never lost.
    m = re.search(r"\|\s*Proposed lesson\s*\|\s*(.*?)\s*\|", brain)
    proposal = m.group(1).strip().lower() if m else ""
    if "error" in (learn_res or {}) and m and proposal not in ("", "none", "no", "-") and not proposal.startswith("no reusable improvement"):
        queued = os.path.join(B.QUEUE, f"{a.session}-lesson.md")
        fields = []  # v2.1 (O15): structured lesson, as Harness² EXPERIENCE.md (cue / lesson / evidence / confidence)
        for label, key in (("Lesson cue", "cue"), ("Lesson evidence", "evidence"), ("Lesson confidence", "confidence")):
            fm_ = re.search(r"\|\s*" + re.escape(label) + r"[^|]*\|\s*(.*?)\s*\|", brain)
            if fm_ and fm_.group(1).strip():
                fields.append(f"- {key}: {fm_.group(1).strip()}")
        body = "\n".join([f"- lesson: {m.group(1).strip()}"] + fields) if fields else m.group(1).strip()
        B.atomic_write(queued, f"---\ntitle: \"Candidate lesson from {a.session}\"\ntype: lesson\nstatus: candidate\n"
                       f"source: sessions/{a.session}/\nupdated: {B.today()}\n---\n{body}\n", exclusive=True)
    index = "rebuilt"
    try:  # link the new episode into the TOC pages at once, so Obsidian shows it connected
        import brain_index
        brain_index.build()
    except Exception as e:  # the episode is safe on disk; brain_route.py rebuilds a stale index later
        index = f"not rebuilt ({type(e).__name__}); brain_route.py will rebuild it"
    out = {"status": "closed", "episode": B.rel(ep_path), "queued": B.rel(queued) if queued else None, "index": index}
    if learn_res is not None:
        out["learn"] = learn_res
    print(json.dumps(out))
    return 0


EXT = r"(?:md|json|jsonl|py|sh|txt|html|css|js|pdf|png|svg|tsv|csv|glb|stl|step)"
CLAIM_PATH = re.compile(r"`([^`\n]*?/[^`\n]*?\." + EXT + r")`|`([^`\s]+/[^`\s]*)`|(?<![\w/.~`-])((?:[\w.~-]+/)+[\w.-]+\." + EXT + r")\b")


def unsupported_claims(task, cwd, sdir_):
    """Deterministic CLAIM-SUPPORT (layer 10): every file the Verified row cites must exist (brain root, the
    session's cwd or the session folder). Prose is not judged here; the blind judge does that."""
    verified = field(task, "Verified")
    if not verified:
        return []
    missing = []
    for g1, g2, g3 in CLAIM_PATH.findall(verified):
        ref = (g1 or g2 or g3).split(":")[0].split("#")[0].rstrip(".,;)")
        if ref.startswith(("http", "~/.")) or "*" in ref:
            continue
        cands = [ref] + ([ref.split()[-1]] if " " in ref else [])  # `python3 tools/x.py` cites tools/x.py
        if not any(os.path.exists(os.path.join(b, os.path.expanduser(c))) for c in cands for b in (B.ROOT, cwd, sdir_)) \
                and not any(os.path.exists(os.path.expanduser(c)) for c in cands):
            missing.append(ref)
    return sorted(set(missing))


def lint(contract):
    """REQ-TESTABLE and CONSTRAINT-QUOTED, decided by code (Tier 0): every hard requirement names its check,
    every quoted constraint appears in the verbatim request, no template placeholder is left."""
    problems = []
    if "<paste the owner's request exactly>" in contract or "- R1: … — check: …" in contract:
        problems.append("template placeholders left (request or R1)")
    request = section(contract, "Request (verbatim)")
    if not request.strip():
        problems.append("REQUEST: empty")
    reqs = re.findall(r"^[ \t]*-[ \t]*(R\d+)[ \t]*:(.*)$", section(contract, "Hard requirements"), re.M)
    if not reqs:
        problems.append("REQ-TESTABLE: no hard requirements")
    for rid, text in reqs:
        m = re.search(r"check\s*:\s*(\S.{3,})", text, re.I)
        if not m or m.group(1).strip() in ("…", "...", "-"):
            problems.append(f"REQ-TESTABLE: {rid} has no concrete check")
    norm = lambda s: re.sub(r"[\W_]+", " ", s.lower()).strip()
    req_n = norm(request)
    for q in re.findall(r"[\"“]([^\"”]{3,})[\"”]", section(contract, "Constraints")):
        if q.strip() in ("…", "...") or norm(q) not in req_n:
            problems.append(f"CONSTRAINT-QUOTED: not in the verbatim request: {q[:60]!r}")
    return problems


def cmd_lint(a):
    import hashlib
    d = sdir(a.session)
    c = open(os.path.join(d, "contract.md"), encoding="utf-8").read()
    p = lint(c)
    meta = B.load_json(os.path.join(d, "meta.json"), {})  # v2.1 (O7): meta follows the contract
    changed = {}
    for key, allowed in (("lane", B.LANES), ("scope_class", tuple(B.SCOPES))):
        m = re.search(rf"^{key}:\s*(\w+)", c, re.M)
        if m and m.group(1) in allowed and meta.get(key) != m.group(1):
            changed[key] = m.group(1)
    nm = re.search(r"^novelty:\s*([\w-]+)", c, re.M)
    if nm and meta.get("novelty") != nm.group(1):
        changed["novelty"] = nm.group(1)
    if changed and meta:
        meta.update(changed)
        B.atomic_write(os.path.join(d, "meta.json"), json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    out = {"session": a.session, "ok": not p, "problems": p}
    fp_src = "|".join([
        (meta or {}).get("scope_class", "general"),
        (meta or {}).get("novelty", ""),
        section(c, "Deliverables"),
        section(c, "Hard requirements"),
    ])
    fp = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()[:12]
    if not p and (not has_retrieval(d) or (meta and meta.get("route_fingerprint") != fp)):  # v4 Hydro: re-route when filled contract changes
        r = auto_route(a.session)
        if r:
            out["retrieval"] = r
        if meta:
            meta["route_fingerprint"] = fp
            B.atomic_write(os.path.join(d, "meta.json"), json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if not p else 1


def decision_gold(d, approval, failed):
    """REQ-MET gold items from the session's last blind verdict (v2.1, N2/O3). The owner's approval confirms the
    requirements the judge passed; requirements the owner names with --failed are "no". Nothing else is guessed."""
    vs = sorted(f for f in os.listdir(d) if f.startswith("verdict-") and f.endswith(".json"))
    if not vs:
        return []
    v = (B.load_json(os.path.join(d, vs[-1]), {}) or {}).get("verdict") or {}
    items = []
    for r in v.get("verdicts") or []:
        rid = (re.match(r"\s*(R\d+)", str(r.get("requirement", ""))) or [None, None])[1]
        state = {"requirement_text": str(r.get("requirement", ""))[:2000], "evidence_excerpt": str(r.get("evidence", ""))[:4000]}
        if rid and rid in failed:
            items.append((state, "no"))
        elif approval.startswith("approved") and r.get("verdict") == "pass":
            items.append((state, "yes"))
    return items


def cmd_decide(a):
    """the owner's decision on a closed session after the fact (feeds the gold set)."""
    d = sdir(a.session)
    mp = os.path.join(d, "meta.json")
    meta = B.load_json(mp, {})
    meta.update({"approval": a.approval, "decided": B.now(), "decision_note": a.note or ""})
    B.atomic_write(mp, json.dumps(meta, indent=1, ensure_ascii=False))
    ep = meta.get("episode") or "-"
    ep = os.path.join(B.ROOT, "Brain System/" + ep[6:] if ep.startswith("vault/") else ep)  # the vault folder was renamed on 2026-11-08
    if os.path.isfile(ep):  # v3 (C2): the episode carries the owner's verdict, not the "pending" it was filed with
        t = open(ep, encoding="utf-8").read()
        t2 = re.sub(r"^approval:.*$", f"approval: {a.approval}", t, count=1, flags=re.M)
        if t2 != t:
            B.atomic_write(ep, t2)
    failed = {x.strip() for x in (a.failed or "").split(",") if x.strip()}
    import judge_typed as J
    added = sum(J.add_gold("REQ-MET", st, lab, ref=f"sessions/{a.session}") for st, lab in decision_gold(d, a.approval, failed))
    print(json.dumps({"session": a.session, "approval": a.approval, "gold_added": {"REQ-MET": added}}))
    return 0


def cmd_handoff(a):
    """Auto table at the end of HANDOFF.md: the latest sessions of every agent, with their judge result (F8)."""
    rows = []
    for sid in sorted(os.listdir(B.SESSIONS), reverse=True) if os.path.isdir(B.SESSIONS) else []:
        m = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), None)
        if not isinstance(m, dict):
            continue
        j = os.path.join(B.SESSIONS, sid, "judge.md")
        last = open(j, encoding="utf-8").read().strip().splitlines()[-1] if os.path.exists(j) else ""
        jm = re.search(r"round (\d+): (\w+)", last)
        rows.append(f"| `{sid}` | {m.get('agent')} | {str(m.get('title', '')).replace('|', '/')[:70]} | {m.get('status')} | "
                    f"{m.get('approval', '-')} | {('round ' + jm.group(1) + ' ' + jm.group(2)) if jm else '-'} |")
        if len(rows) >= a.limit:
            break
    block = ["<!-- AUTO:latest-sessions (brain_session.py handoff; do not edit by hand) -->", f"## Latest sessions (auto-updated {B.now()})", "",
             "| Session | Agent | Title | Status | Approval | Judge |", "|---|---|---|---|---|---|", *rows, "<!-- /AUTO:latest-sessions -->"]
    hp = os.path.join(B.ROOT, "HANDOFF.md")
    text = open(hp, encoding="utf-8").read() if os.path.exists(hp) else "# Agent Brain — full handoff\n"
    text = re.sub(r"\n*<!-- AUTO:latest-sessions.*?<!-- /AUTO:latest-sessions -->\n?", "\n", text, flags=re.S).rstrip() + "\n\n" + "\n".join(block) + "\n"
    B.atomic_write(hp, text)
    print(json.dumps({"handoff": "HANDOFF.md", "sessions": len(rows)}))
    return 0


def cmd_status(a):
    rows = []
    if os.path.isdir(B.SESSIONS):
        for sid in sorted(os.listdir(B.SESSIONS)):
            m = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), None)
            if m and m.get("status") != "closed":
                if a.cwd and os.path.realpath(m.get("cwd", "")) != os.path.realpath(os.path.expanduser(a.cwd)):
                    continue
                rows.append({"session": sid, "title": m.get("title"), "agent": m.get("agent"), "cwd": m.get("cwd")})
    print(json.dumps({"open": rows}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("--agent", required=True, choices=["claude", "codex"])
    n.add_argument("--cwd")
    n.add_argument("--title", required=True)
    n.add_argument("--lane", default="standard")
    n.add_argument("--scope", default="general")
    n.add_argument("--project")
    n.add_argument("--request", help="the owner's words verbatim; with --lane fast the whole contract is written")
    n.add_argument("--check", help="fast lane: a shell command that exits 0 when the change is right")
    c = sub.add_parser("checkpoint")
    c.add_argument("--session", required=True)
    c.add_argument("--note", required=True)
    c.add_argument("--files", nargs="*")
    cl = sub.add_parser("close")
    cl.add_argument("--session", required=True)
    cl.add_argument("--approval", default="pending", choices=["pending", "approved", "rejected", "approved-with-exception"])
    cl.add_argument("--project")
    cl.add_argument("--summary", help="fast lane: one line; writes both summaries")
    cl.add_argument("--force-claims", action="store_true", help="close although the Verified row cites missing files (recorded)")
    cl.add_argument("--no-judge", help="standard/deep: why this session closes without a judge verdict (recorded for the owner)")
    cl.add_argument("--unresolved", help="why this session closes although the last verdict is fail (recorded for the owner)")
    li = sub.add_parser("lint")
    li.add_argument("--session", required=True)
    de = sub.add_parser("decide")
    de.add_argument("--session", required=True)
    de.add_argument("--approval", required=True, choices=["approved", "rejected", "approved-with-exception"])
    de.add_argument("--note")
    de.add_argument("--failed", help="requirement ids the owner found unmet, e.g. R2,R3 (gold 'no')")
    ho = sub.add_parser("handoff")
    ho.add_argument("--limit", type=int, default=8)
    s = sub.add_parser("status")
    s.add_argument("--cwd")
    ca = sub.add_parser("capsule", help="the session in one screen, from its records (resume note)")
    ca.add_argument("--session", required=True)
    a = ap.parse_args()
    rc = {"new": cmd_new, "checkpoint": cmd_checkpoint, "close": cmd_close, "status": cmd_status,
          "lint": cmd_lint, "decide": cmd_decide, "handoff": cmd_handoff, "capsule": cmd_capsule}[a.cmd](a)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
