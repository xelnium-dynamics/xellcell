#!/usr/bin/env python3
"""
brain_learn.py — Fast Post-Session Improvement & Knowledge Consolidation Layer (HYDRO BRAIN).

Runs automatically on `brain_session.py close` (all lanes) and `brain_hooks.py end` (fallback for unclosed/ended sessions):
1. Multi-format lesson & gotcha extraction (table cells + markdown headings/bullets + retrieval-log missing items) -> queue/
2. Immediate searchable learning ledger (`Brain System/history/learnings/<project-or-scope>.md`) recording:
   what happened, how the goal was achieved, files/checks verified, skills used, and unresolved limits.
3. Skill-calling telemetry feedback (`state/skill-telemetry.json` & `.jsonl`) comparing recommended vs opened SKILL.md files.
4. Fast incremental FTS5 upsert into `index/brain.db` (< 30ms) so the very next session retrieves new knowledge immediately.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

LEARNINGS_DIR = os.path.join(B.VAULT, "history", "learnings")
TELEMETRY_PATH = os.path.join(B.STATE, "skill-telemetry.json")
TELEMETRY_LOG = os.path.join(B.STATE, "skill-telemetry.jsonl")
MAX_ENTRIES_PER_LEDGER = 25
MAX_QUEUED_PER_SESSION = 3

IGNORE_LESSON = (
    "",
    "none",
    "no",
    "-",
    "n/a",
    "(no reusable improvement spotted)",
    "no reusable improvement spotted",
)


def _norm_text(t):
    return re.sub(r"[\W_]+", " ", (t or "").lower()).strip()


def _existing_lesson_fps():
    fps = set()
    for folder in (B.QUEUE, os.path.join(B.VAULT, "lessons")):
        if not os.path.isdir(folder):
            continue
        for fn in os.listdir(folder):
            if not fn.endswith(".md"):
                continue
            try:
                txt = open(os.path.join(folder, fn), encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            _, body = B.split_frontmatter(txt)
            n = _norm_text(body)
            if len(n) >= 16:
                fps.add(n[:160])
    return fps


def _section(text, heading):
    m = re.search(r"^## " + re.escape(heading) + r"[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def _field(text, label):
    for m in re.finditer(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|$", text, re.M):
        if m.group(1).strip().lower().startswith(label.lower()):
            return m.group(2).strip()
    return ""


def _extract_lessons(brain_text, ret_log, scope, task_text=""):
    """Extract candidate lessons from table cells, markdown headings/bullets, and retrieval missing logs."""
    out = []
    seen = set()

    def add_candidate(lesson, cue="", evidence="", confidence="medium", kind="note"):
        cleaned = re.sub(r"\s+", " ", (lesson or "").strip()).strip("- ").strip()
        low = cleaned.lower().strip(". ")
        if not cleaned or low in IGNORE_LESSON or low.startswith("no reusable improvement") or len(cleaned) < 12:
            return
        fp = _norm_text(cleaned)[:160]
        if fp in seen:
            return
        seen.add(fp)
        out.append({"lesson": cleaned, "cue": cue or scope, "evidence": evidence, "confidence": confidence, "kind": kind})

    # 1. Standard table cell (handles single & minor variants)
    prop = _field(brain_text, "Proposed lesson")
    cue = _field(brain_text, "Lesson cue")
    ev = _field(brain_text, "Lesson evidence")
    conf = _field(brain_text, "Lesson confidence") or "medium"
    if prop:
        add_candidate(prop, cue=cue, evidence=ev, confidence=conf, kind="proposed")

    # 2. Markdown sections & numbered/bulleted lesson/gotcha blocks across brain-summary and task-summary
    combined_md = "\n".join(x for x in (brain_text, task_text) if x)
    for m in re.finditer(r"^##\s*(Lessons?|Gotchas?|Fixes?|Key\s+Takeaways?|What\s+worked)[^\n]*\n(.*?)(?=^##\s|\Z)", combined_md, re.S | re.M | re.I):
        block = m.group(2).strip()
        head_kind = "lesson" if m.group(1).lower().startswith("lesson") else "note"
        for ln in block.splitlines():
            s = ln.strip()
            if not s or s.startswith("|") or s.startswith("<!--"):
                continue
            bm = re.match(r"^(?:[-*]|\d+[.)])\s+(.*)$", s)
            item = bm.group(1).strip() if bm else s
            if len(item) >= 18:
                add_candidate(item, cue=scope, confidence="medium", kind=head_kind)

    # 3. Missing knowledge / missing skill flagged during retrieval (supports both action and brain_fetch mark)
    for row in ret_log:
        gap = row.get("reason") or row.get("what")
        kind = row.get("action") or row.get("mark")
        if kind == "missing" and gap:
            add_candidate(f"Retrieval gap reported: {gap}", cue=scope, evidence="retrieval-log.jsonl", confidence="medium", kind="gap")

    return out


def _read_jsonl(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def _extract_skill_signals(d, task_text, brain_text, ev_rows, ret_log=None):
    shown = []
    for fn in sorted(f for f in os.listdir(d) if f.startswith("retrieval-") and f.endswith(".md")):
        with open(os.path.join(d, fn), encoding="utf-8", errors="ignore") as rfh:
            txt = rfh.read()
        skills_sec = _section(txt, "Skills") or txt
        for m in re.finditer(r"^(?:-|\d+\.)\s+\*\*([^*]+)\*\*", skills_sec, re.M):
            nm = re.sub(r"[\s_]+", "-", m.group(1).split(":", 1)[-1].strip().lower())
            if nm and nm not in shown:
                shown.append(nm)

    used = []
    for r in ev_rows:
        f = str(r.get("file") or r.get("path") or "")
        if r.get("tool") == "Read" and f.endswith("/SKILL.md"):
            nm = re.sub(r"[\s_]+", "-", os.path.basename(os.path.dirname(f)).lower())
            if nm and nm not in used:
                used.append(nm)
    for r in (ret_log or []):
        f = str(r.get("path") or "")
        kind = r.get("action") or r.get("mark")
        if kind == "used" and f.endswith("/SKILL.md"):
            nm = re.sub(r"[\s_]+", "-", os.path.basename(os.path.dirname(f)).lower())
            if nm and nm not in used:
                used.append(nm)
    # Also detect explicitly named shown skills cited in summaries
    # v6: a one-word skill name (ship, start, fix, commit, digest, figma) is also an ordinary word; "we ship it on
    # Friday" is not a use of the skill `ship`. Before v6 such mentions counted as "used" and fed the router's telemetry
    # boost. A summary names a skill when a multi-word name appears as a whole word, or a one-word name is in backticks
    # or next to the word "skill".
    combined = (task_text + "\n" + brain_text).lower()
    for nm in shown:
        if nm in used:
            continue
        e = re.escape(nm)
        if "-" in nm:
            hit = re.search(r"(?<![\w-])" + e + r"(?![\w-])", combined)
        else:
            hit = re.search(r"`" + e + r"`|\bskill[s]?[ :`\"']+" + e + r"\b|\b" + e + r"[`\"']? skill\b", combined)
        if hit:
            used.append(nm)
    return shown, used


def _update_telemetry(sid, shown, used):
    tel = B.load_json(TELEMETRY_PATH, {"processed_sessions": [], "skills": {}})
    if sid in tel.get("processed_sessions", []):
        return {"shown": len(shown), "used": len(used), "already_recorded": True}
    skills = tel.setdefault("skills", {})
    now = B.now()
    for nm in shown:
        st = skills.setdefault(nm, {"shown": 0, "used": 0, "last_seen": now})
        st["shown"] = int(st.get("shown", 0)) + 1
        st["last_seen"] = now
    for nm in used:
        st = skills.setdefault(nm, {"shown": 0, "used": 0, "last_seen": now})
        st["used"] = int(st.get("used", 0)) + 1
        st["last_seen"] = now
    proc = list(tel.get("processed_sessions", [])) + [sid]
    tel["processed_sessions"] = proc[-500:]
    tel["updated"] = now
    os.makedirs(B.STATE, exist_ok=True)
    B.atomic_write(TELEMETRY_PATH, json.dumps(tel, indent=1, ensure_ascii=False) + "\n")
    with open(TELEMETRY_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"session": sid, "ts": now, "shown": shown, "used": used}, ensure_ascii=False) + "\n")
    return {"shown": len(shown), "used": len(used), "already_recorded": False}


def _safe_ascii_english(text):
    """Strip non-English script noise only when outside project/history, keeping clean punctuation."""
    return re.sub(r"\s+", " ", (text or "").strip())


def _upsert_learning_ledger(sid, meta, contract, task, brain, ev_rows, verdict_last, lessons, shown, used):
    project = (meta.get("project") or "none").strip()
    scope = (meta.get("scope_class") or "general").strip()
    key = B.slugify(project) if project not in ("", "none") else f"scope-{B.slugify(scope)}"
    os.makedirs(LEARNINGS_DIR, exist_ok=True)
    path = os.path.join(LEARNINGS_DIR, f"{key}.md")

    title_raw = meta.get("title") or sid
    delivered = _field(task, "Delivered") or _section(task, "Delivered") or "(no delivered summary)"
    verified = _field(task, "Verified") or _section(task, "Verified") or "(not recorded)"
    limits = _field(task, "Limits") or _field(task, "Not verified") or "-"
    edited = sorted({
        str(r.get("file") or "")
        for r in ev_rows
        if r.get("tool") in ("Write", "Edit", "MultiEdit", "NotebookEdit") and r.get("file")
    })
    edited_str = ", ".join(f"`{os.path.basename(p)}`" for p in edited[:10]) or "none logged"

    v_status = verdict_last or ("fast-lane" if meta.get("lane") == "fast" else "unjudged")
    entry_lines = [
        f"<!-- session:{sid} -->",
        f"### {B.today()} — {title_raw} (`{sid}`)",
        f"- **Outcome**: {_safe_ascii_english(delivered)[:280]}",
        f"- **How achieved / verification**: {v_status} · {_safe_ascii_english(verified)[:240]} · edited: {edited_str}",
        f"- **Skills**: shown [{', '.join(shown[:6]) or 'none'}] · used [{', '.join(used[:6]) or 'none'}]",
    ]
    if limits not in ("", "-", "none"):
        entry_lines.append(f"- **Limits / open**: {_safe_ascii_english(limits)[:200]}")
    proposed = [l for l in lessons if l.get("kind") in ("proposed", "lesson")]
    notes = [l for l in lessons if l.get("kind", "note") == "note"]
    if proposed:
        entry_lines.append("- **Lessons captured**: " + " | ".join(l["lesson"][:140] for l in proposed[:4]))
    if notes:  # v6: gotchas, fixes and what worked are searchable here; they do not go to the owner's decision queue
        entry_lines.append("- **Gotchas / what worked**: " + " | ".join(l["lesson"][:160] for l in notes[:5]))
    entry_block = "\n".join(entry_lines)

    existing_blocks = []
    existing_sources = []
    if os.path.isfile(path):
        old_txt = open(path, encoding="utf-8", errors="ignore").read()
        old_fm, old_body = B.split_frontmatter(old_txt)
        if old_fm:
            om = B.parse_frontmatter(old_fm)
            if isinstance(om.get("sources"), list):
                existing_sources = list(om["sources"])
        # Parse existing <!-- session:... --> blocks, replacing if re-run for same sid
        raw_blocks = re.split(r"(?=<!-- session:[^>]+ -->)", old_body)
        for blk in raw_blocks:
            blk = blk.strip()
            if not blk or blk.startswith("# Learnings Ledger"):
                continue
            m = re.match(r"<!-- session:([^\s]+) -->", blk)
            if m and m.group(1) == sid:
                continue
            if blk.startswith("<!-- session:"):
                existing_blocks.append(blk)

    blocks = [entry_block] + existing_blocks[:MAX_ENTRIES_PER_LEDGER - 1]
    src_ref = f"sessions/{sid}/"
    if src_ref not in existing_sources:
        existing_sources = ([src_ref] + existing_sources)[:MAX_ENTRIES_PER_LEDGER]

    label = project if project not in ("", "none") else scope
    ledger_scope = scope if scope in ("cv_official", "personal") else "history"
    fm_sources = json.dumps(existing_sources, ensure_ascii=False)
    summary_str = re.sub(r'["\n\r]+', " ", f"Recent session learnings and verified solutions for {label} (latest: {title_raw[:60]}).")
    doc = [
        "---",
        f'title: "Learnings Ledger: {label}"',
        "type: learning",
        f"scope: {ledger_scope}",
        f'summary: "{summary_str}"',
        f"sources: {fm_sources}",
        f'tags: ["learnings", "hydro-brain", "{B.slugify(scope)}"]',
        f"updated: {B.today()}",
        "---",
        f"# Learnings Ledger: {label}",
        "",
        "Latest session outcomes, verified solutions, skill calls, and gotchas (newest first).",
        "",
        "\n\n".join(blocks),
        "",
    ]
    B.atomic_write(path, "\n".join(doc))
    return path


def _incremental_index_upsert(note_path):
    """Update just the modified learning note in index/brain.db (< 20ms) so next prompt finds it at once."""
    if not os.path.exists(B.INDEX_DB) or not os.path.isfile(note_path):
        return False
    n = B.read_note(note_path)
    col, sub = B.collection_of(note_path)
    m = n["meta"]
    summary = m.get("summary") if isinstance(m.get("summary"), str) else ""
    tags = m.get("tags") if isinstance(m.get("tags"), list) else []
    aliases = m.get("aliases") if isinstance(m.get("aliases"), list) else []
    excerpt = re.sub(r"\s+", " ", re.sub(r"```.*?```", " ", n["body"], flags=re.S))[:1500]
    rel = B.rel(note_path)
    stem = os.path.splitext(os.path.basename(note_path))[0]
    try:
        con = sqlite3.connect(B.INDEX_DB, timeout=2.0)
        con.execute("DELETE FROM notes WHERE path = ?", (rel,))
        con.execute(
            "INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                n["title"], summary, " | ".join(n["headings"][:40]),
                " ".join(str(x) for x in tags), " ".join(str(x) for x in aliases), excerpt,
                rel, stem, col, sub, str(m.get("scope", "")), str(m.get("type", "")),
            ),
        )
        con.commit()
        con.close()
        return True
    except sqlite3.DatabaseError:
        return False


def learn_session(sid, refresh_index=True, force=False):
    d = os.path.join(B.SESSIONS, sid)
    if not os.path.isdir(d):
        return {"session": sid, "error": "session directory not found"}
    learn_marker = os.path.join(d, "learn.json")
    if os.path.isfile(learn_marker) and not force:
        prev = B.load_json(learn_marker, {})
        if isinstance(prev, dict) and prev.get("session") == sid:
            return dict(prev, status="skipped_already_learned")

    meta = B.load_json(os.path.join(d, "meta.json"), {}) or {}
    contract = open(os.path.join(d, "contract.md"), encoding="utf-8", errors="ignore").read() if os.path.isfile(os.path.join(d, "contract.md")) else ""
    task = open(os.path.join(d, "task-summary.md"), encoding="utf-8", errors="ignore").read() if os.path.isfile(os.path.join(d, "task-summary.md")) else ""
    brain = open(os.path.join(d, "brain-summary.md"), encoding="utf-8", errors="ignore").read() if os.path.isfile(os.path.join(d, "brain-summary.md")) else ""
    ret_log = _read_jsonl(os.path.join(d, "retrieval-log.jsonl"))
    ev_rows = _read_jsonl(os.path.join(d, "evidence.jsonl"))
    verdicts = sorted(f for f in os.listdir(d) if f.startswith("verdict-") and f.endswith(".json"))
    v_last = ""
    if verdicts:
        v_last = str(((B.load_json(os.path.join(d, verdicts[-1]), {}) or {}).get("verdict") or {}).get("overall") or "")

    scope = str(meta.get("scope_class") or "general")
    shown, used = _extract_skill_signals(d, task, brain, ev_rows, ret_log=ret_log)
    lessons = _extract_lessons(brain, ret_log, scope, task_text=task)

    if os.environ.get("BRAIN_SESSION_ONLY_CLOSE") == "1":
        res = {"status": "learned", "session": sid, "ts": B.now(), "shared_skipped": True,
               "insights_count": len(lessons), "lessons_extracted": len(lessons), "skills_shown": shown, "skills_used": used}
        B.atomic_write(learn_marker, json.dumps(res, indent=1, ensure_ascii=False) + "\n")
        return res

    # 1. Queue extracted candidate lessons (preserving primary <sid>-lesson.md compatibility)
    os.makedirs(B.QUEUE, exist_ok=True)
    existing_fps = _existing_lesson_fps()
    queued_files = []
    # v6: The owner decides every queued lesson by hand, so the queue takes what the agent PROPOSED as a lesson (the Brain
    # Summary cell, then bullets under a "Lessons" heading), at most MAX_QUEUED_PER_SESSION. Gotchas, fixes and
    # "what worked" bullets stay in the searchable ledger; a retrieval gap is a gap report (sleep and dream count them),
    # not a lesson. Before v6 one session could put eight files in front of the owner.
    queueable = [x for x in lessons if x.get("kind") == "proposed"] + [x for x in lessons if x.get("kind") == "lesson"]
    for idx, item in enumerate(queueable[:MAX_QUEUED_PER_SESSION], 1):
        fp = _norm_text(item["lesson"])[:160]
        if fp in existing_fps:
            continue
        suffix = "" if idx == 1 and not os.path.exists(os.path.join(B.QUEUE, f"{sid}-lesson.md")) else f"-{idx:02d}"
        qpath = os.path.join(B.QUEUE, f"{sid}-lesson{suffix}.md")
        if os.path.exists(qpath):
            continue
        lines = [f"- lesson: {item['lesson']}", f"- cue: {item['cue']}"]
        if item["evidence"]:
            lines.append(f"- evidence: {item['evidence']}")
        lines.append(f"- confidence: {item['confidence']}")
        B.atomic_write(
            qpath,
            f"---\ntitle: \"Candidate lesson from {sid}\"\ntype: lesson\nstatus: candidate\n"
            f"scope: {scope}\nsource: sessions/{sid}/\nupdated: {B.today()}\n---\n" + "\n".join(lines) + "\n",
            exclusive=True,
        )
        existing_fps.add(fp)
        queued_files.append(B.rel(qpath))

    # 2. Update searchable Learnings Ledger in Brain System/history/learnings/
    ledger_path = _upsert_learning_ledger(sid, meta, contract, task, brain, ev_rows, v_last, lessons, shown, used)

    # 3. Record skill-calling telemetry
    tel_res = _update_telemetry(sid, shown, used)

    # 4. Fast incremental DB upsert
    upserted = _incremental_index_upsert(ledger_path) if refresh_index else False

    res = {
        "status": "learned",
        "session": sid,
        "ts": B.now(),
        "insights_count": len(lessons),
        "ledger": B.rel(ledger_path),
        "queued": queued_files,
        "skills_shown": shown,
        "skills_used": used,
        "telemetry": tel_res,
        "index_upserted": upserted,
    }
    B.atomic_write(learn_marker, json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    return res


def rebuild_telemetry():
    """v7: skill telemetry from the session records, from scratch, with the current "used" rule. For the day the rule
    changes (as in v6) or sessions are copied in from another brain: the old file is kept beside the new one, the
    ledgers and the queue are not touched."""
    if os.path.exists(TELEMETRY_PATH):
        keep = TELEMETRY_PATH[:-5] + f".before-rebuild-{B.today()}.json"
        if not os.path.exists(keep):
            os.replace(TELEMETRY_PATH, keep)
    B.atomic_write(TELEMETRY_PATH, json.dumps({"processed_sessions": [], "skills": {}}) + "\n")
    n = 0
    for sid in sorted(os.listdir(B.SESSIONS)) if os.path.isdir(B.SESSIONS) else []:
        d = os.path.join(B.SESSIONS, sid)
        meta = B.load_json(os.path.join(d, "meta.json"), None)
        if not isinstance(meta, dict) or (meta.get("status") != "closed" and not os.path.isfile(os.path.join(d, "analysis.json"))):
            continue
        rd = lambda f: open(os.path.join(d, f), encoding="utf-8", errors="ignore").read() if os.path.isfile(os.path.join(d, f)) else ""
        shown, used = _extract_skill_signals(d, rd("task-summary.md"), rd("brain-summary.md"), _read_jsonl(os.path.join(d, "evidence.jsonl")),
                                             ret_log=_read_jsonl(os.path.join(d, "retrieval-log.jsonl")))
        _update_telemetry(sid, shown, used)
        n += 1
    tel = B.load_json(TELEMETRY_PATH, {})
    return {"rebuilt_from_sessions": n, "skills": len(tel.get("skills", {})),
            "used": {k: v["used"] for k, v in sorted(tel.get("skills", {}).items()) if v.get("used")}}


def find_target_sessions(latest_only=True):
    if not os.path.isdir(B.SESSIONS):
        return []
    out = []
    for sid in sorted(os.listdir(B.SESSIONS), reverse=True):
        sd = os.path.join(B.SESSIONS, sid)
        meta = B.load_json(os.path.join(sd, "meta.json"), {})
        if not isinstance(meta, dict):
            continue
        if meta.get("status") != "closed" and not os.path.isfile(os.path.join(sd, "analysis.json")):
            continue
        if os.path.isfile(os.path.join(sd, "learn.json")):
            continue
        out.append(sid)
        if latest_only:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="Session id to consolidate immediately")
    ap.add_argument("--latest", action="store_true", help="Consolidate the newest closed/ended unlearned session")
    ap.add_argument("--backfill", action="store_true", help="Consolidate all closed/ended sessions missing learn.json")
    ap.add_argument("--force", action="store_true", help="Re-run even if learn.json already exists")
    ap.add_argument("--no-index", action="store_true", help="Skip incremental DB upsert")
    ap.add_argument("--rebuild-telemetry", action="store_true", help="v7: recount state/skill-telemetry.json from all session records")
    a = ap.parse_args()
    if a.rebuild_telemetry:
        print(json.dumps(rebuild_telemetry(), indent=1, ensure_ascii=False))
        return 0

    targets = []
    if a.session:
        targets = [a.session]
    elif a.latest:
        targets = find_target_sessions(latest_only=True)
    elif a.backfill:
        targets = find_target_sessions(latest_only=False)
    else:
        ap.error("pass --session <id>, --latest, or --backfill")

    results = [learn_session(sid, refresh_index=not a.no_index, force=a.force) for sid in targets]
    print(json.dumps(results[0] if len(results) == 1 else {"learned": len(results), "sessions": results}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
