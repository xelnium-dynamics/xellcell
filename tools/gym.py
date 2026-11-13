#!/usr/bin/env python3
"""
gym.py — the night shift (layer 12 B, roadmap 8.1): improve the harness only when it provably wins.

    python3 -I gym.py [--dry-run]

What it improves: state/harness-config.json (the retrieval settings every session uses: skill/note thresholds,
off-skill factor, relative cut, length normalisation, router minimum overlap). Nothing else is writable.
Tasks: the labeled sets in state/eval/ (prompt → skill, task → note, chat → no suggestion).
Rules (layer 12):
- Holdout: a fixed 20% of tasks (by hash) is never shown to the improver; it decides the release.
- Protected surface: eval sets, judge questions, gold, canaries, AGENTS.md and the project settings are hashed before
  and after; any change aborts the run.
- Steps: baseline → propose one GENERAL change (thresholds) and one DOMAIN change (skill ranking) on the training split →
  compose → final composed run on holdout + full regression set.
- Ratchet by sample size on the tasks whose outcome differs: < 3 → candidate only · 3–4 → win all, lose none ·
  ≥ 5 → win ≥ 60 %, lose none. Equal quality → keep the current (simpler) config.
- Release: previous config kept as harness-config.prev.json (the sleep job auto-reverts on a later eval drop),
  git commit of the config + tag, one line in gym/results.tsv, morning digest reports/gym-<date>.md.
"""
import argparse, hashlib, json, os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import brain_hooks as H  # noqa: E402
import brain_route as R  # noqa: E402
import hydro_skills as HS  # noqa: E402

CFG_P = os.path.join(B.STATE, "harness-config.json")
PREV_P = os.path.join(B.STATE, "harness-config.prev.json")
PROTECTED = [
    "state/eval",
    "judge/questions",
    "judge/gold",
    "judge/canaries.json",
    "AGENTS.md",
    ".claude/settings.json",
    "tools/hydro_skills.py",
    "state/skill-families.json",
    "tools/tier0.py",
]
TSV = os.path.join(B.ROOT, "gym", "results.tsv")


TSV_HEADER = "date\ttasks\tbaseline\tcandidate\tchange\tholdout_w\tholdout_l\treleased\trule\n"


def ensure_tsv_header():
    """v2.1 (O5): results.tsv must carry the v2 header. A file with another header is moved, whole, to
    gym/results-v1-archive.tsv; rows already in the v2 shape (9 columns, a number of tasks) are carried over."""
    if os.path.exists(TSV) and os.path.getsize(TSV) > 0:
        with open(TSV, encoding="utf-8") as fh:
            lines = fh.read().splitlines(True)
        if lines[0] == TSV_HEADER:
            return False
        with open(os.path.join(os.path.dirname(TSV), "results-v1-archive.tsv"), "a", encoding="utf-8") as fh:
            fh.write("".join(lines))
        keep = [l for l in lines[1:] if len(l.rstrip("\n").split("\t")) == 9 and l.split("\t")[1].isdigit()]
        B.atomic_write(TSV, TSV_HEADER + "".join(keep))
        return True
    os.makedirs(os.path.dirname(TSV), exist_ok=True)
    B.atomic_write(TSV, TSV_HEADER)
    return True


def surface_hash():
    h = hashlib.sha256()
    for rel in PROTECTED:
        p = os.path.join(B.ROOT, rel)
        files = sorted(os.path.join(d, f) for d, _, fs in os.walk(p) for f in fs) if os.path.isdir(p) else ([p] if os.path.exists(p) else [])
        for f in files:
            h.update(f.encode())
            with open(f, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def tasks():
    out = []
    ps = B.load_json(os.path.join(B.STATE, "eval", "prompt-skills.json"), {})
    for c in ps.get("positive", []):
        out.append({"id": "pos:" + c["prompt"], "kind": "skill+", "prompt": c["prompt"], "accept": {a.lower() for a in c["accept"]}})
    for p in ps.get("negative", []):
        out.append({"id": "neg:" + p, "kind": "skill-", "prompt": p})
    rn = B.load_json(os.path.join(B.STATE, "eval", "route-notes.json"), {})
    for t in rn.get("tasks", []):
        out.append({"id": "note:" + t["query"], "kind": "note", **t})
    for t in out:
        t["holdout"] = int(hashlib.sha1(t["id"].encode()).hexdigest(), 16) % 5 == 0
    return out


def _apply_cfg(cfg):
    HS.CFG_OVERRIDE.clear()
    HS.CFG_OVERRIDE.update({k: v for k, v in cfg.items() if k in HS.DEFAULTS})
    H.CFG.update({k: v for k, v in cfg.items() if k in H.DEFAULTS})


def correct(t, cfg):
    _apply_cfg(cfg)
    if t["kind"] == "skill+":
        return bool({s["name"].lower() for s in H.pick_skills(t["prompt"])} & t["accept"])
    if t["kind"] == "skill-":
        return not H.pick_skills(t["prompt"])
    paths = [n["path"] for n in R.route(t["query"], t["scope"], limit=5, skill_limit=0)["notes"]]
    if t["scope"] not in ("personal", "cv_official") and any(p.startswith("Brain System/self/") for p in paths):
        return False
    if t.get("expect"):
        return any(any(e in p for e in t["expect"]) for p in paths)
    if t.get("no_match"):
        return not paths
    return True


def score(items, cfg):
    prev_hs = dict(HS.CFG_OVERRIDE)
    prev_hook = dict(H.CFG)
    prev_ro = os.environ.get("BRAIN_ROUTE_READONLY")
    R.ensure_index()
    os.environ["BRAIN_ROUTE_READONLY"] = "1"
    try:
        return {t["id"]: correct(t, cfg) for t in items}
    finally:
        HS.CFG_OVERRIDE.clear()
        HS.CFG_OVERRIDE.update(prev_hs)
        H.CFG.clear()
        H.CFG.update(prev_hook)
        if prev_ro is None:
            os.environ.pop("BRAIN_ROUTE_READONLY", None)
        else:
            os.environ["BRAIN_ROUTE_READONLY"] = prev_ro


def ratchet(base, cand):
    wins = sum(1 for k in base if cand[k] and not base[k])
    losses = sum(1 for k in base if base[k] and not cand[k])
    n = wins + losses
    if losses:
        return False, wins, losses, "loses tasks"
    if n == 0:
        return False, wins, losses, "equal quality: keep the current (simpler) config"
    if n < 3:
        return False, wins, losses, "fewer than 3 differing tasks: candidate only"
    if n <= 4:
        return wins == n, wins, losses, "3-4 tasks: must win all"
    return wins / n >= 0.6, wins, losses, ">= 5 tasks: win >= 60%"


def _complexity(cfg):
    return sum(1 for k, v in HS.DEFAULTS.items() if cfg.get(k) != v)


def best_on(train, base_cfg, grid):
    base = score(train, base_cfg)
    best, best_s, best_c = None, sum(base.values()), _complexity(base_cfg)
    note_tasks = [t for t in train if t["kind"] == "note"]
    skill_tasks = [t for t in train if t["kind"] != "note"]
    for change in grid:
        cfg = dict(base_cfg, **change)
        if cfg == base_cfg:
            continue
        # Only re-evaluate the task subset actually sensitive to the changed parameter(s)
        affects_notes = any(k == "route_min_overlap" for k in change)
        affects_skills = any(k != "note_threshold" for k in change)
        s = dict(base)
        if affects_skills and skill_tasks:
            s.update(score(skill_tasks, cfg))
        if affects_notes and note_tasks:
            s.update(score(note_tasks, cfg))
        tot = sum(s.values())
        if any(base[k] and not s[k] for k in base):
            continue
        c = _complexity(cfg)
        if tot > best_s or (tot == best_s and c < best_c):
            best, best_s, best_c = change, tot, c
    return best


WORK = os.path.join(B.STATE, "eval", "work-tasks.json")


def work_suite(dry):
    """v2.1 (Argon F6): real task execution on the owner's four domains, scored by Tier 0 (no model judges here)."""
    import shutil, tempfile, tier0
    suite = B.load_json(WORK, {}).get("tasks", [])
    agent = os.environ.get("BRAIN_WORK_AGENT")
    rows = []
    for t in suite:
        base = os.path.join(B.STATE, "eval", "work-tasks", t["id"])
        ws = tempfile.mkdtemp(prefix=f"brain-work-{t['id']}-")
        if os.path.isdir(os.path.join(base, "setup")):
            shutil.copytree(os.path.join(base, "setup"), ws, dirs_exist_ok=True)
        cmd = (agent + " " + json.dumps(t["prompt"])) if agent else f"{sys.executable} -I {json.dumps(os.path.join(base, 'solution.py'))}"
        t0 = time.time()
        r = B.shell_run(cmd, cwd=ws, capture_output=True, text=True, timeout=1800)
        checks = tier0.run("## Checks\n" + "".join(f"- R{i + 1}: {c}\n" for i, c in enumerate(t["checks"])), ws)
        ok = r.returncode == 0 and bool(checks) and all(c["pass"] for c in checks)
        rows.append({"id": t["id"], "domain": t["domain"], "pass": ok, "exit": r.returncode, "seconds": round(time.time() - t0, 1),
                     "failed_checks": [c["command"] + " → " + c["tail"][:120] for c in checks if not c["pass"]], "workspace": ws})
    rec = {"date": B.now(), "suite": "work-tasks", "runner": agent or "reference solutions", "tasks": len(rows),
           "passed": sum(r["pass"] for r in rows), "by_domain": {}, "rows": rows}
    for r in rows:
        d = rec["by_domain"].setdefault(r["domain"], [0, 0])
        d[0] += r["pass"]
        d[1] += 1
    if not dry:
        B.atomic_write(os.path.join(B.ROOT, "reports", f"gym-work-{B.today()}.md"),
                       f"# Gym work-task suite — {B.today()}\n\n```json\n{json.dumps(rec, indent=1)}\n```\n")
    print(json.dumps({k: v for k, v in rec.items() if k != "rows"} | {"failed": [r for r in rows if not r["pass"]]}, indent=1))
    return 0 if rec["passed"] == rec["tasks"] else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--suite", default="routing", choices=["routing", "work-tasks"])
    a = ap.parse_args()
    if a.suite == "work-tasks":
        return work_suite(a.dry_run)
    before = surface_hash()
    cfg0 = HS.load_config()
    items = tasks()
    train = [t for t in items if not t["holdout"]]
    hold = [t for t in items if t["holdout"]]
    t0 = time.time()
    general = best_on(
        train,
        cfg0,
        [{"skill_threshold": round(cfg0["skill_threshold"] + d, 2)} for d in (-2.0, -1.0, -0.5, 0.5, 1.0, 2.0)]
        + [{"note_threshold": round(cfg0["note_threshold"] + d, 2)} for d in (-2.0, -1.0, 1.0, 2.0)]
        + [{"route_min_overlap": m} for m in (1, 2, 3)],
    )
    domain = best_on(
        train,
        cfg0,
        [{"off_factor": f} for f in (1.0, 1.15, 1.25, 1.5, 2.0)]
        + [{"rel_cut": r} for r in (0.36, 0.42, 0.48, 0.55, 0.65)]
        + [{"len_norm": n} for n in (6, 8, 9, 10, 12)]
        + [{"len_cap": c} for c in (1.25, 1.35, 1.45, 1.65)]
        + [{"family_weight": fw} for fw in (0.75, 1.0, 1.25, 1.5)]
        + [{"telemetry_weight": tw} for tw in (0.5, 1.0, 1.5)],
    )
    composed = dict(cfg0, **(general or {}), **(domain or {}))
    base_all, cand_all = score(items, cfg0), score(items, composed)
    base_hold = {k: base_all[k] for k in base_all if k in {t["id"] for t in hold}}
    cand_hold = {k: cand_all[k] for k in base_hold}
    ok_hold, w, l, why = ratchet(base_hold, cand_hold)
    ok_all, w_all, l_all, why_all = ratchet(base_all, cand_all)
    simpler = _complexity(composed) < _complexity(cfg0)
    release = (ok_hold or (w_all == 0 and l_all == 0 and simpler)) and l_all == 0 and composed != cfg0
    after = surface_hash()
    if before != after:
        release, why = False, "protected surface changed during the run: aborted"
    tag = None
    if release and not a.dry_run:
        B.atomic_write(PREV_P, json.dumps(B.load_json(CFG_P, cfg0), indent=1))
        new = dict(B.load_json(CFG_P, {}), **composed)
        new.update({"version": int(new.get("version", 1)) + 1, "released": B.today(), "by": "gym"})
        B.atomic_write(CFG_P, json.dumps(new, indent=1))
        try:  # v2.1 (O1): private index + repo lock, never sweeps in a live session's staged work
            commit = B.git_commit_paths(["state/harness-config.json", "state/harness-config.prev.json"],
                                        f"Gym release: {json.dumps({**(general or {}), **(domain or {})})}")
        except B.LockBusy:
            commit = None
        if commit:
            tag = B.next_release_tag()
            subprocess.run(["git", "-C", B.ROOT, "tag", tag, commit], capture_output=True, text=True)
    rec = {"date": B.now(), "tasks": len(items), "holdout": len(hold), "baseline_correct": sum(base_all.values()),
           "candidate_correct": sum(cand_all.values()), "general": general, "domain": domain, "holdout_wins": w, "holdout_losses": l,
           "all_wins": w_all, "all_losses": l_all, "rule": why, "released": bool(tag) if not a.dry_run else f"dry-run ({release})",
           "tag": tag, "seconds": round(time.time() - t0, 1), "protected_surface": "unchanged" if before == after else "CHANGED"}
    if not a.dry_run:
        ensure_tsv_header()
        with open(TSV, "a", encoding="utf-8") as fh:
            fh.write(f"{rec['date']}\t{len(items)}\t{rec['baseline_correct']}\t{rec['candidate_correct']}\t"
                     f"{json.dumps({**(general or {}), **(domain or {})})}\t{w}\t{l}\t{rec['released']}\t{why}\n")
        B.atomic_write(os.path.join(B.ROOT, "reports", f"gym-{B.today()}.md"),
                       f"# Gym morning digest — {B.today()}\n\n```json\n{json.dumps(rec, indent=1)}\n```\n")
        B.atomic_write(os.path.join(B.STATE, "gym-last.json"), json.dumps(dict(rec, epoch=time.time()), indent=1))
    print(json.dumps(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main())
