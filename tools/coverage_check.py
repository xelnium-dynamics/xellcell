#!/usr/bin/env python3
"""
coverage_check.py — prove that a cleanup placement plan accounts for EVERY block (and so every line).

Inputs:
    --blocks  blocks.jsonl from segment.py
    --plan    plan.csv with header: block_id,action,target,reason
Actions:
    place         the block goes into note `target` (vault-relative path ending in .md)
    duplicate_of  the block is a copy; `target` is the block_id of the copy that is kept
    raw_only      the block stays only in the raw snapshot; `reason` is required
                  (e.g. "obsolete Hermes cron instruction", "empty template line")
Checks: every block listed exactly once · no unknown ids · valid actions · place targets are
relative .md paths without ".." · one filename never maps to two folders (no ambiguous links) ·
duplicate_of chains end at a placed block, without cycles · raw_only has a reason.
Exit 0 only when all checks pass and 100% of block lines are accounted for.
"""
import argparse, csv, json, os, sys
from collections import Counter, defaultdict

ACTIONS = {"place", "duplicate_of", "raw_only"}


def main():
    ap = argparse.ArgumentParser(description="Verify a placement plan covers every block")
    ap.add_argument("--blocks", required=True)
    ap.add_argument("--plan", required=True)
    a = ap.parse_args()
    blocks = {}
    with open(a.blocks, encoding="utf-8") as fh:
        for line in fh:
            b = json.loads(line)
            blocks[b["block_id"]] = b
    errors, plan, seen = [], {}, Counter()
    with open(a.plan, encoding="utf-8", newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=2):
            bid = (r.get("block_id") or "").strip()
            seen[bid] += 1
            act, tgt, why = (r.get("action") or "").strip(), (r.get("target") or "").strip(), (r.get("reason") or "").strip()
            if bid not in blocks:
                errors.append(f"line {i}: unknown block_id {bid!r}")
                continue
            if act not in ACTIONS:
                errors.append(f"line {i}: invalid action {act!r}")
                continue
            if act == "place" and (not tgt.endswith(".md") or tgt.startswith("/") or ".." in tgt.split("/")):
                errors.append(f"line {i}: place target must be a relative .md path, got {tgt!r}")
            if act == "raw_only" and not why:
                errors.append(f"line {i}: raw_only needs a reason")
            if act == "duplicate_of" and tgt not in blocks:
                errors.append(f"line {i}: duplicate_of points to unknown block {tgt!r}")
            plan[bid] = (act, tgt)
    for bid, c in seen.items():
        if c > 1:
            errors.append(f"block listed {c} times: {bid}")
    missing = [b for b in blocks if b not in plan]
    for b in missing[:20]:
        errors.append(f"block not in plan: {b} ({blocks[b]['path']}:{blocks[b]['line_start']})")
    if len(missing) > 20:
        errors.append(f"... and {len(missing) - 20} more blocks not in plan")
    stems = defaultdict(set)
    for act, tgt in plan.values():
        if act == "place":
            stems[os.path.basename(tgt).lower()].add(os.path.dirname(tgt).lower())
    for stem, dirs in stems.items():
        if len(dirs) > 1:
            errors.append(f"filename {stem!r} used in {len(dirs)} folders (ambiguous wikilinks): {sorted(dirs)}")
    for bid, (act, tgt) in plan.items():
        if act != "duplicate_of":
            continue
        cur, hops = tgt, 0
        while cur in plan and plan[cur][0] == "duplicate_of" and hops < 50:
            cur, hops = plan[cur][1], hops + 1
        if hops >= 50 or cur not in plan or plan[cur][0] != "place":
            errors.append(f"duplicate_of chain from {bid} does not end at a placed block")
    lines = Counter()
    for bid, b in blocks.items():
        lines[plan.get(bid, ("missing",))[0]] += b["line_end"] - b["line_start"] + 1
    total = sum(lines.values())
    accounted = total - lines.get("missing", 0)
    report = {"blocks": len(blocks), "plan_rows": sum(seen.values()), "lines_total": total,
              "lines_by_action": dict(lines), "accounted_pct": round(100.0 * accounted / total, 3) if total else 100.0,
              "errors": len(errors)}
    print(json.dumps(report))
    for e in errors[:50]:
        print("ERROR:", e)
    sys.exit(0 if not errors and accounted == total else 1)


if __name__ == "__main__":
    main()
