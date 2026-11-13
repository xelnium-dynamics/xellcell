#!/usr/bin/env python3
"""
token_meter.py — measure real token use from the CLIs' own local logs. Read-only, zero model tokens.

Claude Code writes one JSONL transcript per session (~/.claude/projects/<project>/<session>.jsonl;
subagent transcripts may sit in sub-folders). Each assistant message carries `usage`; the same
message can appear on several lines, so lines are de-duplicated by message.id.
Codex writes rollout JSONL files (~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl) with `token_count`
events whose info.total_token_usage is a running total; the last one per file is the session total.

Usage:
    python3 -I token_meter.py claude <file-or-folder> [...]
    python3 -I token_meter.py codex  <file-or-folder> [...]
Output: one JSON line per session + a totals line.
  context_in   = tokens the model had to read (input + cache writes + cache reads)
  boot_context = context_in of the first assistant turn (what the session carried before any work)
"""
import json, os, sys


def files(paths):
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            for root, _, fs in os.walk(p):
                for f in sorted(fs):
                    if f.endswith(".jsonl"):
                        yield os.path.join(root, f)
        elif p.endswith(".jsonl"):
            yield p


def stamp(r):
    """Epoch seconds of a transcript line ("timestamp": "2026-11-09T14:44:55.123Z"), or None."""
    ts = r.get("timestamp") if isinstance(r, dict) else None
    if not isinstance(ts, str):
        return None
    try:
        import datetime
        ts = ts.replace("Z", "+00:00")
        m = __import__("re").match(r"(.*\.\d{1,6})\d*([+-]\d\d:\d\d)?$", ts)  # 3.9 reads 3 or 6 fraction digits only
        if m:
            head, frac = m.group(1).rsplit(".", 1)
            ts = f"{head}.{frac.ljust(6, '0')}{m.group(2) or ''}"
        return datetime.datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


def window(meta):
    """(since, until) of a brain session from its meta.json: created .. closed (or now). v3 (C4)."""
    import time
    def ep(x):
        try:
            return time.mktime(time.strptime(str(x)[:19], "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError):
            return None
    since = ep((meta or {}).get("created"))
    return (since, ep((meta or {}).get("closed")) or time.time()) if since else (None, None)


def inside(r, since, until):
    """A line without a readable timestamp always counts (old logs); otherwise it must fall in the window."""
    if since is None and until is None:
        return True
    t = stamp(r)
    return t is None or ((since is None or t >= since) and (until is None or t <= until))


def claude(paths, since=None, until=None):
    rows, seen = [], set()
    for f in files(paths):
        s = {"file": f, "turns": 0, "context_in": 0, "cache_read": 0, "output": 0, "sidechain_turns": 0, "boot_context": None}
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                m = r.get("message")
                if not isinstance(m, dict) or not isinstance(m.get("usage"), dict) or not inside(r, since, until):
                    continue
                key = m.get("id") or (r.get("requestId"), r.get("uuid"))
                if key in seen:
                    continue
                seen.add(key)
                u = m["usage"]
                ctx = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                s["turns"] += 1
                s["context_in"] += ctx
                s["cache_read"] += u.get("cache_read_input_tokens", 0)
                s["output"] += u.get("output_tokens", 0)
                if r.get("isSidechain"):
                    s["sidechain_turns"] += 1
                if s["boot_context"] is None and not r.get("isSidechain"):
                    s["boot_context"] = ctx
        if s["turns"]:
            rows.append(s)
    return rows


def codex(paths, since=None, until=None):
    rows = []
    for f in files(paths):
        last, base = None, None  # Codex logs a running total: a window is (last total in it) - (last total before it)
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                p = r.get("payload")
                if isinstance(p, dict) and p.get("type") == "token_count" and isinstance(p.get("info"), dict):
                    tot, t = p["info"].get("total_token_usage"), stamp(r)
                    if not tot:
                        continue
                    if since is not None and t is not None and t < since:
                        base = tot
                    elif until is None or t is None or t <= until:
                        last = tot
        if last and base:
            last = {k: max(v - base.get(k, 0), 0) if isinstance(v, (int, float)) else v for k, v in last.items()}
        if last:
            rows.append({"file": f, "context_in": last.get("input_tokens", 0) + last.get("cache_write_input_tokens", 0),
                         "cache_read": last.get("cached_input_tokens", 0), "output": last.get("output_tokens", 0),
                         "reasoning_output": last.get("reasoning_output_tokens", 0), "total": last.get("total_tokens", 0)})
    return rows


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("claude", "codex"):
        sys.exit(__doc__)
    rows = claude(sys.argv[2:]) if sys.argv[1] == "claude" else codex(sys.argv[2:])
    for r in rows:
        print(json.dumps(r))
    keys = [k for k in ("turns", "context_in", "cache_read", "output", "reasoning_output", "total") if any(k in r for r in rows)]
    print(json.dumps({"TOTAL_sessions": len(rows), **{k: sum(r.get(k, 0) for r in rows) for k in keys}}))


if __name__ == "__main__":
    main()
