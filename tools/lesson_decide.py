#!/usr/bin/env python3
"""
lesson_decide.py — the owner's decision on a candidate lesson (layer 11: releasing a procedure needs the owner).

    python3 -I lesson_decide.py "Brain System/lessons/<file>.md" approve|reject [--note "..."]

approve → status: released (normal routing uses it) · reject → status: retired (history kept, routing skips it).
The decision is also written to judge/gold/owner-lessons.jsonl (the owner's labels calibrate the judges, layer 8).
v2.1 (O3): it also adds a SCOPE-COVER gold item (state = lesson text + its evidence list): approve -> "yes";
reject --reason scope -> "no" (other reasons to reject say nothing about scope, so they add no label).
The next sleep run re-indexes and releases the change.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("decision", choices=["approve", "reject"])
    ap.add_argument("--note", default="")
    ap.add_argument("--reason", default="", help="why rejected; 'scope' = the evidence does not cover the claim")
    a = ap.parse_args()
    p = a.path if os.path.isabs(a.path) else os.path.join(B.ROOT, a.path)
    text = open(p, encoding="utf-8").read()
    if not re.search(r"^status:\s*candidate\s*$", text, re.M):
        sys.exit("not a candidate lesson (status is not 'candidate')")
    status = "released" if a.decision == "approve" else "retired"
    text = re.sub(r"^status:\s*candidate\s*$", f"status: {status}\ndecided_by: The owner\ndecided: {B.today()}", text, count=1, flags=re.M)
    B.atomic_write(p, text)
    os.makedirs(os.path.join(B.JUDGE, "gold"), exist_ok=True)
    with open(os.path.join(B.JUDGE, "gold", "owner-lessons.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"lesson": B.rel(p), "label": status, "note": a.note, "date": B.today(), "source": "owner"}) + "\n")
    fm, body = B.split_frontmatter(text)
    meta = B.parse_frontmatter(fm) if fm else {}
    ev = meta.get("sources") or meta.get("source") or ""
    state = {"lesson": body.strip()[:4000], "evidence_list": ", ".join(ev) if isinstance(ev, list) else str(ev)}
    label = "yes" if a.decision == "approve" else ("no" if a.reason == "scope" else None)
    added = False
    if label:
        import judge_typed as J
        added = J.add_gold("SCOPE-COVER", state, label, ref=B.rel(p))
    print(json.dumps({"lesson": B.rel(p), "status": status, "gold_added": {"SCOPE-COVER": int(added)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
