#!/usr/bin/env python3
"""
entry_matrix.py — live entry test (layer 1, roadmap 2.4): does every way a session can start reach the brain?

    python3 -I entry_matrix.py [--only fresh,resume,...] [--skip-codex]

Claude Code cases (real `claude -p` sessions; each is asked to quote its readiness card):
  fresh          new session in a neutral folder              → card present, project none
  task_switch    new session in ~/Desktop/Success             → card names project job-search
  resume         `--resume` of the fresh session              → card present again (SessionStart source=resume)
  missing_index  BRAIN_INDEX_DB points to a missing file      → card says index missing; brain_route rebuilds it
  broken_index   BRAIN_INDEX_DB points to an old-schema db    → brain_route detects it and rebuilds
  crash          BRAIN_ROOT points nowhere                    → card degrades to "offline", the session still works
Codex case:
  codex_fallback `codex exec` in ~/Desktop/Success            → runs the card itself (global AGENTS.md), names job-search
Writes reports/entry-matrix-<date>.json. Uses the CLIs' normal subscription login; no paid API.
"""
import argparse, json, os, re, shutil, sqlite3, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

ASK = ("Look at the Agent Brain readiness card in your context (it arrives at session start). Reply with ONE line only: "
       "card=<yes|no|offline> index=<the word after 'index' on the brain: line, or none> project=<the project after "
       "'project:' on the folder: line, or none>. Do not run any tool.")


def claude(cwd, prompt, env=None, resume=None):
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", ""]
    if resume:
        cmd += ["--resume", resume]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300, env=dict(os.environ, **(env or {})))
    try:
        d = json.loads(p.stdout)
        return d.get("result", ""), d.get("session_id")
    except ValueError:
        return p.stdout[-300:] + p.stderr[-300:], None


def parse(line):
    m = dict(re.findall(r"(card|index|project)=([\w.()-]+)", line or ""))
    return {"card": m.get("card"), "index": m.get("index"), "project": m.get("project"), "raw": (line or "")[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--skip-codex", action="store_true")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    neutral = tempfile.mkdtemp(prefix="brain-entry-")
    success = os.path.expanduser("~/Desktop/Success")
    rows = []

    def case(name, expect, got, extra=None):
        ok = all(got.get(k) == v or (v == "*" and got.get(k)) for k, v in expect.items())
        rows.append({"case": name, "ok": ok, "expect": expect, "got": got, **(extra or {})})

    sid = None
    if not only or {"fresh", "resume"} & only:
        out, sid = claude(neutral, ASK)
        case("fresh", {"card": "yes", "project": "none"}, parse(out))
    if (not only or "resume" in only) and sid:
        out, _ = claude(neutral, ASK, resume=sid)
        case("resume", {"card": "yes"}, parse(out))
    if not only or "task_switch" in only:
        out, _ = claude(success, ASK)
        case("task_switch", {"card": "yes", "project": "job-search"}, parse(out))
    if not only or "missing_index" in only:
        tmpdb = os.path.join(neutral, "missing", "brain.db")
        out, _ = claude(neutral, ASK, env={"BRAIN_INDEX_DB": tmpdb})
        got = parse(out)
        r = subprocess.run([sys.executable, "-I", os.path.join(B.TOOLS, "brain_route.py"), "--query", "blender export", "--json"],
                           capture_output=True, text=True, env=dict(os.environ, BRAIN_INDEX_DB=tmpdb), timeout=600)
        rebuilt = os.path.exists(tmpdb) and bool(json.loads(r.stdout or "{}").get("skills"))
        case("missing_index", {"card": "yes", "index": "missing"}, got, {"route_rebuilt_index": rebuilt})
        rows[-1]["ok"] = rows[-1]["ok"] and rebuilt
    if not only or "broken_index" in only:
        bad = os.path.join(neutral, "old", "brain.db")
        os.makedirs(os.path.dirname(bad))
        con = sqlite3.connect(bad)
        con.execute("CREATE TABLE notes (title TEXT)")
        con.commit()
        con.close()
        r = subprocess.run([sys.executable, "-I", os.path.join(B.TOOLS, "brain_route.py"), "--query", "blender export", "--json"],
                           capture_output=True, text=True, env=dict(os.environ, BRAIN_INDEX_DB=bad), timeout=600)
        ok = r.returncode == 0 and bool(json.loads(r.stdout or "{}").get("skills")) and os.path.exists(bad + ".broken")
        rows.append({"case": "broken_index", "ok": ok, "expect": "route rebuilds, old file kept as .broken", "got": r.stderr[-200:] or "rebuilt"})
    if not only or "crash" in only:
        out, _ = claude(neutral, ASK, env={"BRAIN_ROOT": os.path.join(neutral, "no-brain-here"), "BRAIN_INDEX_DB": os.path.join(neutral, "x.db")})
        got = parse(out)
        case("crash", {"card": "*"}, got)
        rows[-1]["ok"] = got.get("card") in ("offline", "yes", "no") and bool(out)  # the session answered
    if not a.skip_codex and (not only or "codex_fallback" in only):
        p = subprocess.run(["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral",
                            "Follow your global AGENTS.md entry step (run the brain readiness card command if no card is in your context). "
                            "Then reply with ONE line only: card=<yes|no> project=<project after 'project:' on the folder: line>."],
                           cwd=success, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)  # codex exec waits on open stdin
        got = parse((p.stdout.strip().splitlines() or [""])[-1])
        case("codex_fallback", {"card": "yes", "project": "job-search"}, got)
    # never delete: the temp folder is left for macOS's own temp cleanup
    rep = {"date": B.today(), "release": B.git_release(), "cases": rows, "pass": all(r["ok"] for r in rows)}
    # proposal from Codex session 33eb (applied v2.1): BRAIN_ENTRY_OUTPUT lets a read-only reviewer write elsewhere
    output = os.environ.get("BRAIN_ENTRY_OUTPUT") or os.path.join(B.ROOT, "reports", f"entry-matrix-{B.today()}.json")
    B.atomic_write(output, json.dumps(rep, indent=1, ensure_ascii=False))
    print(json.dumps(rep, indent=1, ensure_ascii=False))
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
