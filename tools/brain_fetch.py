#!/usr/bin/env python3
"""
brain_fetch.py — read a vault note inside the session's scope, and log what retrieval gave (layers 3 + 4).

    python3 -I brain_fetch.py --session <id> "Brain System/capabilities/Web Studio.md" [--lines 10-60]
    python3 -I brain_fetch.py --session <id> --used "<path>" | --rejected "<path>" --reason "<why>" | --missing "<what>"

- Prints the note (or the line range) only if its collection is allowed for the contract's scope_class;
  Brain System/self only for cv_official / personal (the same gate the PreToolUse hook applies to Read).
- Every fetch and every used / rejected / missing mark goes to sessions/<id>/retrieval-log.jsonl.
  brain_sleep.py and gym.py read these logs (layer 12 C: re-rank, sharpen do-not-use-when, write missing cards).
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402


def scope_of(sid):
    try:
        c = open(os.path.join(B.SESSIONS, sid, "contract.md"), encoding="utf-8").read()
        m = re.search(r"^scope_class:\s*(\w+)", c, re.M)
        return m.group(1) if m else "general"
    except OSError:
        sys.exit(f"no session {sid}")


def log(sid, rec):
    rec = dict(rec, t=B.now())
    with open(os.path.join(B.SESSIONS, sid, "retrieval-log.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def resolve(path):
    p = path if os.path.isabs(path) else os.path.join(B.ROOT, path)
    real, vault = os.path.realpath(p), os.path.realpath(B.VAULT)
    if not real.startswith(vault + os.sep):
        sys.exit("brain_fetch reads vault notes only (Brain System/...)")
    return os.path.join(B.VAULT, os.path.relpath(real, vault))  # vault-based path: collection_of() works behind symlinks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("path", nargs="?")
    ap.add_argument("--lines")
    ap.add_argument("--outline", action="store_true", help="v6: headings with their line ranges only (then read one with --section)")
    ap.add_argument("--section", help="v6: print only the section under this heading (case-insensitive, part of the heading is enough)")
    ap.add_argument("--used")
    ap.add_argument("--rejected")
    ap.add_argument("--reason", default="")
    ap.add_argument("--missing")
    a = ap.parse_args()
    if a.used or a.rejected or a.missing:
        log(a.session, {"mark": "used" if a.used else "rejected" if a.rejected else "missing",
                        "path": a.used or a.rejected, "what": a.missing, "reason": a.reason})
        print("logged")
        return 0
    if not a.path:
        ap.error("give a path or --used/--rejected/--missing")
    scope = scope_of(a.session)
    p = resolve(a.path)
    col, sub = B.collection_of(p)
    if not B.allowed(col, sub, scope):
        log(a.session, {"mark": "denied", "path": B.rel(p), "reason": f"scope {scope} cannot read {col}"})
        print(f"DENIED: scope '{scope}' may not read collection '{col}'. Allowed: {', '.join(B.SCOPES.get(scope, []))}")
        return 3
    lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    start, end = 1, len(lines)
    if a.outline or a.section:  # v6: a long note costs its outline plus the one section that applies, not the whole note
        import brain_map
        heads = brain_map.parse_md("\n".join(lines))[0]
        if a.outline:
            log(a.session, {"mark": "outlined", "path": B.rel(p)})
            print(f"# {B.rel(p)} — {len(lines)} lines, ~{sum(len(x) for x in lines) // 4} tokens")
            for kind, name, s0, e0, _ in heads:
                print(f"{'  ' * (int(kind[1]) - 1)}L{s0}-L{e0}  {name}")
            return 0
        want = a.section.lower()
        hit = [h for h in heads if h[1].lower() == want] or [h for h in heads if want in h[1].lower()]
        if not hit:
            print(f"no heading like {a.section!r}; headings: " + " | ".join(h[1] for h in heads[:30]))
            return 4
        start, end = hit[0][2], hit[0][3]
    elif a.lines:
        s, _, e = a.lines.partition("-")
        start, end = max(1, int(s)), min(len(lines), int(e or s))
    log(a.session, {"mark": "fetched", "path": B.rel(p), "lines": f"{start}-{end}"})
    for i in range(start - 1, end):
        print(f"{i + 1:>5}  {lines[i]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
