#!/usr/bin/env python3
"""
route_eval.py — measures the brain's retrieval against labeled sets (layer 4 done-when, roadmap 3.2).

    python3 -I route_eval.py                 # both sets, prints a report, exit 0 only if every gate passes
    python3 -I route_eval.py --json

Sets (edit only with a visible label_changes entry; the Gym treats them as protected):
- state/eval/prompt-skills.json  per-message skill hook: positives need an accepted skill in the top 5,
  negatives (conversation, not tasks) must get no suggestion. Gates: recall >= 0.9, false alarms <= 20%.
- state/eval/route-notes.json    brain_route notes: >= 9/10 tasks with an expected note in the top 5,
  0 Brain System/self items for non-personal scopes, "no match" tasks return no notes.
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import brain_hooks as H  # noqa: E402
import brain_route as R  # noqa: E402


def skills_eval(path):
    E = json.load(open(path, encoding="utf-8"))
    miss, fa = [], []
    for c in E["positive"]:
        got = [s["name"].lower() for s in H.pick_skills(c["prompt"])]
        if not set(got) & {a.lower() for a in c["accept"]}:
            miss.append({"prompt": c["prompt"], "got": got})
    for p in E["negative"]:
        got = [s["name"] for s in H.pick_skills(p)]
        if got:
            fa.append({"prompt": p, "got": got})
    n, m = len(E["positive"]), len(E["negative"])
    recall, false_alarm = (n - len(miss)) / n, len(fa) / m
    return {"set": "prompt-skills", "positives": n, "found": n - len(miss), "recall": round(recall, 3),
            "negatives": m, "false_alarms": len(fa), "false_alarm_rate": round(false_alarm, 3),
            "pass": recall >= 0.9 and false_alarm <= 0.2, "misses": miss, "alarms": fa}


def notes_eval(path):
    E = json.load(open(path, encoding="utf-8"))
    tasks = E["tasks"]
    ok, leaks, wrong_match, fails = 0, 0, 0, []
    scored = [t for t in tasks if t.get("expect")]
    for t in tasks:
        r = R.route(t["query"], t["scope"], limit=5, skill_limit=1)
        paths = [n["path"] for n in r["notes"]]
        if t["scope"] not in ("personal", "cv_official"):
            leaks += sum(1 for p in paths if p.startswith("Brain System/self/"))
        if t.get("expect"):
            if any(any(e in p for e in t["expect"]) for p in paths):
                ok += 1
            else:
                fails.append({"query": t["query"], "got": paths})
        elif t.get("no_match") and paths:
            wrong_match += 1
            fails.append({"query": t["query"], "got": paths, "expected": "no match"})
    acc = ok / len(scored) if scored else 0
    return {"set": "route-notes", "tasks": len(tasks), "scored": len(scored), "top5_correct": ok, "accuracy": round(acc, 3),
            "self_leaks": leaks, "no_match_violations": wrong_match,
            "pass": acc >= 0.9 and leaks == 0 and wrong_match == 0, "fails": fails}


def holdout_eval(path):
    """v6: generalisation on prompts the router's authors never tuned against (accept = regexes on the short name).
    Reported, never a gate: a holdout that gates gets tuned against, and then it is no holdout."""
    import re
    R.ensure_index()  # a fresh clone has no index yet: build it before scoring
    E = json.load(open(path, encoding="utf-8"))
    miss, fa = [], []
    for c in E["positive"]:
        got = [s["short"] for s in H.pick_skills(c["prompt"])]
        if not any(re.search(a, g) for g in got for a in c["accept"]):
            miss.append({"prompt": c["prompt"], "got": got})
    for p in E["negative"]:
        got = [s["short"] for s in H.pick_skills(p)]
        if got:
            fa.append({"prompt": p, "got": got})
    n, m = len(E["positive"]), len(E["negative"])
    return {"set": os.path.basename(path)[:-5], "positives": n, "found": n - len(miss), "recall": round((n - len(miss)) / n, 3),
            "negatives": m, "false_alarms": len(fa), "false_alarm_rate": round(len(fa) / m, 3), "gate": "none (reported only)",
            "misses": miss, "alarms": fa}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--holdout", action="store_true", help="v6: report the holdout sets (state/eval/prompt-skills-holdout*.json); never a gate")
    a = ap.parse_args()
    if a.holdout:
        import glob
        hres = [holdout_eval(p) for p in sorted(glob.glob(os.path.join(B.STATE, "eval", "prompt-skills-holdout*.json")))]
        if a.json:
            print(json.dumps(hres, indent=1, ensure_ascii=False))
        else:
            for r in hres:
                print(json.dumps({k: v for k, v in r.items() if k not in ("misses", "alarms")}))
                for k in ("misses", "alarms"):
                    for x in r[k]:
                        print(f"  {k[:-1]}: {json.dumps(x, ensure_ascii=False)[:200]}")
        return 0
    res = []
    for name, fn in (("prompt-skills.json", skills_eval), ("route-notes.json", notes_eval)):
        p = os.path.join(B.STATE, "eval", name)
        if os.path.exists(p):
            res.append(fn(p))
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
    else:
        for r in res:
            print(json.dumps({k: v for k, v in r.items() if k not in ("misses", "alarms", "fails")}))
            for k in ("misses", "alarms", "fails"):
                for x in r.get(k, []):
                    print(f"  {k[:-1]}: {json.dumps(x, ensure_ascii=False)[:200]}")
    return 0 if res and all(r["pass"] for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
