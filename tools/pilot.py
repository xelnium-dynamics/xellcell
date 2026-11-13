#!/usr/bin/env python3
"""
pilot.py — brain-off vs brain-on pilot (layer 13, roadmap 6.1): the one success metric, measured.

    python3 -I pilot.py off [-- <claude args>]      start a BRAIN-OFF Claude session (hooks and card silent), logged
    python3 -I pilot.py report [--since 2026-11-08] write reports/pilot-<date>.md and print the numbers

Arms
- on:  every normal session that opened a brain session (state/analysis + sessions/<id>/).
- off: sessions started through `pilot.py off` (BRAIN_OFF=1, own --session-id, logged in state/pilot/off-sessions.jsonl).
Metric per arm (layer 13): cost per verified useful delivery = all context + output tokens / approved deliveries,
next to the owner's corrections per delivery (his follow-up messages after the first request) and judge failures.
A delivery counts as approved only when the owner approved it (close --approval approved or brain_session.py decide).
For off-arm sessions the owner records the verdict with: pilot.py off-decide --session-id <uuid> --approval approved|rejected
v2.1 (O6): open sessions never count; the cost per delivery uses only approved sessions that have a linked
transcript; fresh tokens (new input + cache writes + output) are reported apart from cache reads, which are cheap
re-reads of the same context; Codex rollouts are found and metered with the Codex parser.
"""
import argparse, glob, json, os, subprocess, sys, uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import token_meter  # noqa: E402

PILOT = os.path.join(B.STATE, "pilot")
OFF_LOG = os.path.join(PILOT, "off-sessions.jsonl")


def transcript(csid, agent="claude"):
    if agent == "codex":
        hits = glob.glob(os.path.expanduser(f"~/.codex/sessions/**/rollout-*{csid}*.jsonl"), recursive=True)
    else:
        hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{csid}.jsonl"))
    return hits[0] if hits else None


def user_turns(path, since=None, until=None):
    """the owner's messages in a transcript (typed prompts, not tool results); corrections = all but the first.
    v3 (C4): with a window, only the messages sent while that brain session was open."""
    n = 0
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("type") == "user" and not r.get("isSidechain") and not r.get("isMeta") and token_meter.inside(r, since, until):
            c = (r.get("message") or {}).get("content")
            if isinstance(c, str) or (isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "text" for x in c)):
                n += 1
    return n


def meter(path, agent="claude", since=None, until=None):
    """{"fresh": new input + cache writes + output, "cache_read": ...} for one transcript (zeros when none).
    v3 (C4): since/until limit it to one brain session's own time, so a conversation is never counted twice."""
    rows = (token_meter.codex if agent == "codex" else token_meter.claude)([path], since=since, until=until) if path else []
    if not rows:
        return {"fresh": 0, "cache_read": 0}
    r = rows[0]
    return {"fresh": max(r["context_in"] - r["cache_read"], 0) + r["output"], "cache_read": r["cache_read"]}



def rows_on(since):
    out = []
    for sid in sorted(os.listdir(B.SESSIONS)) if os.path.isdir(B.SESSIONS) else []:
        if sid[:8] < since.replace("-", ""):
            continue
        m = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), {})
        csid = m.get("claude_session") or B.load_json(os.path.join(B.SESSIONS, sid, "analysis.json"), {}).get("claude_session")
        agent = m.get("agent", "claude")
        tr = transcript(csid, agent) if csid else None
        verdicts = sorted(glob.glob(os.path.join(B.SESSIONS, sid, "verdict-*.json")))
        w0, w1 = token_meter.window(m)  # v3 (C4): this session's own time in the conversation
        mt = meter(tr, agent, w0, w1)
        out.append({"arm": "on", "id": sid, "title": m.get("title"), "tokens": mt["fresh"] + mt["cache_read"], "fresh": mt["fresh"],
                    "cache_read": mt["cache_read"], "transcript": bool(tr),
                    "corrections": max(user_turns(tr, w0, w1) - 1, 0) if tr else None, "judge_rounds": len(verdicts),
                    "approval": m.get("approval", "pending" if m.get("status") == "closed" else "open")})
    return out


def rows_off(since):
    out = []
    if not os.path.exists(OFF_LOG):
        return out
    decided = {}
    for line in open(OFF_LOG, encoding="utf-8"):
        r = json.loads(line)
        if r.get("decision"):
            decided[r["session_id"]] = r["decision"]
    for line in open(OFF_LOG, encoding="utf-8"):
        r = json.loads(line)
        if r.get("decision") or r.get("date", "") < since or decided.get(r["session_id"]) == "excluded":
            continue
        tr = transcript(r["session_id"])
        mt = meter(tr)
        out.append({"arm": "off", "id": r["session_id"], "title": r.get("cwd"), "tokens": mt["fresh"] + mt["cache_read"], "fresh": mt["fresh"],
                    "cache_read": mt["cache_read"], "transcript": bool(tr),
                    "corrections": max(user_turns(tr) - 1, 0) if tr else None, "judge_rounds": 0,
                    "approval": decided.get(r["session_id"], "pending")})
    return out


def summary(rows):
    closed = [r for r in rows if r["approval"] != "open"]
    approved = [r for r in closed if r["approval"] in ("approved", "approved-with-exception")]
    measured = [r for r in approved if r["transcript"] and r["tokens"] > 0]
    corr = [r["corrections"] for r in approved if r["corrections"] is not None]
    fresh = sum(r.get("fresh", 0) for r in measured)
    return {"sessions": len(rows), "open_excluded": len(rows) - len(closed), "approved": len(approved), "approved_measured": len(measured),
            "fresh_tokens_closed": sum(r.get("fresh", 0) for r in closed), "cache_read_closed": sum(r.get("cache_read", 0) for r in closed),
            "tokens_per_approved_delivery": round(fresh / len(measured)) if measured else None,
            "cache_read_per_approved_delivery": round(sum(r.get("cache_read", 0) for r in measured) / len(measured)) if measured else None,
            "corrections_per_approved_delivery": round(sum(corr) / len(corr), 2) if corr else None}


def report(since):
    on, off = rows_on(since), rows_off(since)
    s_on, s_off = summary(on), summary(off)
    verdict = "not enough data (each arm needs at least 3 approved deliveries on matched tasks)"
    if s_on["approved"] >= 3 and s_off["approved"] >= 3:
        cheaper = s_on["tokens_per_approved_delivery"] <= s_off["tokens_per_approved_delivery"]
        not_worse = (s_on["corrections_per_approved_delivery"] or 0) <= (s_off["corrections_per_approved_delivery"] or 0)
        verdict = "brain-on is not worse (keep)" if not_worse else "brain-on needs more corrections: review the features that do not pay"
        verdict += "; cheaper per delivery" if cheaper else "; more tokens per delivery"
    row = lambda name, x: (f"| {name} | {x['sessions']} ({x['open_excluded']} open, not counted) | {x['approved']} ({x['approved_measured']} with transcript) | "
                           f"{x['tokens_per_approved_delivery']} | {x['cache_read_per_approved_delivery']} | {x['corrections_per_approved_delivery']} |")
    lines = [f"# Pilot report — {B.today()} (since {since})", "",
             "Fresh tokens = new input + cache writes + output. Cache reads (re-reading the same context) are shown apart. "
             "Open sessions are left out; a delivery's cost uses only approved sessions with a linked transcript.", "",
             "| Arm | Sessions | Approved | Fresh tokens / approved delivery | Cache reads / approved delivery | Corrections / approved delivery |",
             "|---|---|---|---|---|---|", row("brain on", s_on), row("brain off", s_off),
             "", f"**Never-worse gate:** {verdict}", "", "## Sessions", "",
             "| Arm | Id | Title | Fresh tokens | Cache reads | Transcript | Corrections | Judge rounds | Approval |", "|---|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['arm']} | {r['id']} | {str(r['title'])[:50]} | {r.get('fresh', 0)} | {r.get('cache_read', 0)} | {'yes' if r['transcript'] else 'no'} | "
              f"{r['corrections']} | {r['judge_rounds']} | {r['approval']} |" for r in on + off]
    path = os.path.join(B.ROOT, "reports", f"pilot-{B.today()}.md")
    B.atomic_write(path, "\n".join(lines) + "\n")
    return {"report": B.rel(path), "on": s_on, "off": s_off, "verdict": verdict}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("off")
    o.add_argument("rest", nargs=argparse.REMAINDER)
    d = sub.add_parser("off-decide")
    d.add_argument("--session-id", required=True)
    d.add_argument("--approval", required=True, choices=["approved", "rejected", "excluded"])
    r = sub.add_parser("report")
    r.add_argument("--since", default="2026-11-08")
    a = ap.parse_args()
    os.makedirs(PILOT, exist_ok=True)
    if a.cmd == "off":
        sid = str(uuid.uuid4())
        with open(OFF_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"session_id": sid, "cwd": os.getcwd(), "date": B.today(), "arm": "off"}) + "\n")
        rest = [x for x in a.rest if x != "--"]
        return subprocess.call(["claude", "--session-id", sid] + rest, env=dict(os.environ, BRAIN_OFF="1"))
    if a.cmd == "off-decide":
        with open(OFF_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"session_id": a.session_id, "decision": a.approval, "date": B.today()}) + "\n")
        print("recorded")
        return 0
    print(json.dumps(report(a.since), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
