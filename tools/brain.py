#!/usr/bin/env python3
"""
brain.py — one short entry point for every step of the flow (v6). Same for Claude and Codex.

    python3 -I brain.py new|lint|checkpoint|close|status|decide|capsule|handoff ...   -> brain_session.py
    python3 -I brain.py fetch ...        -> brain_fetch.py          python3 -I brain.py route ...   -> brain_route.py
    python3 -I brain.py judge ...        -> brain_judge.py          python3 -I brain.py map ...     -> brain_map.py
    python3 -I brain.py preflight ...    -> brain_judge.py --preflight
    python3 -I brain.py learn|verify|start|skills|plugins ...        -> brain_learn / hydro_verify / brain_start / route --skills-only / plugin_shelf
    python3 -I brain.py help

It only forwards: every tool keeps its own name, arguments and exit code, so the long forms keep working. The card and
AGENTS.md name this one file once instead of repeating a long quoted path on every line.
"""
import os, runpy, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION = ("new", "lint", "checkpoint", "close", "status", "decide", "capsule", "handoff")
OTHER = {"fetch": ("brain_fetch.py", []), "route": ("brain_route.py", []), "judge": ("brain_judge.py", []),
         "preflight": ("brain_judge.py", ["--preflight"]), "map": ("brain_map.py", []), "learn": ("brain_learn.py", []),
         "verify": ("hydro_verify.py", []), "start": ("brain_start.py", []), "skills": ("brain_route.py", ["--skills-only"]),
         "plugins": ("plugin_shelf.py", []), "dream": ("brain_dream.py", []), "sleep": ("brain_sleep.py", []),
         "tier0": ("tier0.py", []), "typed": ("judge_typed.py", [])}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd in SESSION:
        script, argv = "brain_session.py", [cmd] + rest
    elif cmd in OTHER:
        script, extra = OTHER[cmd]
        argv = extra + rest  # v7: first, so a trailing `--artifacts a b` (nargs="*") cannot swallow the forwarded flag
    else:
        print(f"brain.py: unknown command {cmd!r}. Try: " + ", ".join(SESSION + tuple(OTHER)), file=sys.stderr)
        return 2
    path = os.path.join(HERE, script)
    sys.argv = [path] + argv
    sys.path.insert(0, HERE)
    runpy.run_path(path, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
