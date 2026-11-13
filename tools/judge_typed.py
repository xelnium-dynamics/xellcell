#!/usr/bin/env python3
"""
judge_typed.py — typed questions, Tier 1 → Tier 2 cascade, calibration and judge health v2 (layer 8, roadmap 4.2/4.3).

    python3 -I judge_typed.py ask --question REQ-MET --state state.json [--subject R1] [--maker claude] [--kind derived_verdict]
    python3 -I judge_typed.py calibrate --question REQ-MET      # gold set -> threshold (needs >= 30 labels, else cold start)
    python3 -I judge_typed.py canaries [--question ID]          # planted-defect run: every canary must be judged right
    python3 -I judge_typed.py health                            # judge health v2 -> judge/health-v2.json
    python3 -I judge_typed.py gold                              # rebuild judge/gold from canaries + the owner's labels
v2.1 (O3): The owner's labels live in judge/gold/owner/<qid>.jsonl (append-only, never overwritten); `gold` merges them
with the canaries into judge/gold/<qid>.jsonl, deduplicated by state. brain_session.py decide and lesson_decide.py
add them. calibrate --tier2-vendor picks the vendor whose accuracy Tier 1 must match.

Cascade (layer 8):
- Tier 1: a small model (Claude Haiku) answers the typed question twice; pairwise questions run in both orders.
  It is accepted only when both runs agree AND the question has a live threshold (>= 30 gold labels, not expired,
  same model + CLI version). Otherwise the question escalates (cold start = always escalate; that is by design).
- Tier 2: the OTHER vendor (Codex for Claude's work), blind, read-only, in an empty temp folder, never sees Tier 1.
- Kinds Tier 1 is weak at (route_direct_to_tier2_when) skip Tier 1.
The state holds only the question's state_fields: no maker chat, no reasoning, no grading hints (blindness).
Every answer is appended to judge/log.jsonl. Fake CLIs for tests: BRAIN_CLAUDE_BIN / BRAIN_CODEX_BIN.
"""
import argparse, datetime, json, math, os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

QDIR = os.path.join(B.JUDGE, "questions")
GOLD = os.path.join(B.JUDGE, "gold")
LOG = os.path.join(B.JUDGE, "log.jsonl")
TIER1_MODEL = "haiku"


def question(qid):
    return json.load(open(os.path.join(QDIR, qid + ".json"), encoding="utf-8"))


def cli_version(exe):
    try:
        return subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()[:60]
    except Exception:
        return "unknown"


def prompt_for(q, state):
    lines = [f"Typed question {q['id']}: {q['question']}", f"Answer with exactly one label from: {', '.join(q['labels'])}.",
             "Judge only from the state below. Do not use tools.", "", "STATE:"]
    for f in q["state_fields"]:
        lines.append(f"--- {f} ---\n{str(state.get(f, '(missing)'))[:12000]}")
    return "\n".join(lines)


def schema_for(q):
    return {"type": "object", "additionalProperties": False, "required": ["label", "reason"],
            "properties": {"label": {"type": "string", "enum": q["labels"]}, "reason": {"type": "string"}}}


def run_cli(vendor, text, schema, model=None, timeout=300):
    """One blind call in an empty temp folder with the brain's hooks off. Returns the label or None."""
    tmp = tempfile.mkdtemp(prefix="brain-typed-")
    env = dict(os.environ, BRAIN_OFF="1")
    try:
        if vendor == "codex":
            sp, op = os.path.join(tmp, "schema.json"), os.path.join(tmp, "out.json")
            json.dump(schema, open(sp, "w"))
            cmd = [os.environ.get("BRAIN_CODEX_BIN", "codex"), "exec", "--sandbox", "read-only", "--ephemeral",
                   "--skip-git-repo-check", "--output-schema", sp, "-o", op]
            if model:
                cmd += ["--model", model]
            p = subprocess.run(cmd + ["-"], cwd=tmp, input=text, capture_output=True, text=True, timeout=timeout, env=env)
            raw = open(op, encoding="utf-8").read() if os.path.exists(op) else p.stdout
        else:
            cmd = [os.environ.get("BRAIN_CLAUDE_BIN", "claude"), "-p", text, "--model", model or TIER1_MODEL,
                   "--allowedTools", "", "--permission-mode", "dontAsk", "--output-format", "json", "--json-schema", json.dumps(schema)]
            p = subprocess.run(cmd, cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, env=env)
            raw = p.stdout
        return parse_label(raw, schema["properties"]["label"]["enum"])
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        pass  # never delete: the temp folder (packet + schema only) is left for macOS's own temp cleanup


def parse_label(raw, labels):
    def find(o):
        if isinstance(o, dict):
            if o.get("label") in labels:
                return o["label"]
            for k in ("structured_output", "result", "response"):
                v = o.get(k)
                if isinstance(v, str):
                    try:
                        v = json.loads(v)
                    except ValueError:
                        v = None
                r = find(v)
                if r:
                    return r
        return None
    try:
        return find(json.loads(raw))
    except (ValueError, TypeError):
        o = B.last_json(raw or "", lambda x: find(x) is not None)  # v2.1 (O14): tolerate text around the JSON
        return find(o) if o else None


def swapped(state):
    s = dict(state)
    for a, b in (("output_a", "output_b"), ("record_a", "record_b")):
        if a in s and b in s:
            s[a], s[b] = s[b], s[a]
    return s


def unswap(label):
    return {"A": "B", "B": "A"}.get(label, label)


def threshold_live(q, version):
    t = q.get("threshold") or {}
    if t.get("value") is None and t.get("labels_used", 0) >= 30 and t.get("tier1_lower_bound") is not None \
            and t.get("expires_on", "") >= B.today():  # v7: calibrated, and Tier 1 lost: that is an answer, not a gap
        return False, (f"calibrated {t.get('set_on')}: Tier 1 too weak (lower bound {t.get('tier1_lower_bound')} vs Tier 2 "
                       f"{t.get('tier2_accuracy')}), every call escalates until {t.get('expires_on')}")
    if t.get("value") is None or t.get("labels_used", 0) < 30:
        return False, "cold start (fewer than 30 gold labels)"
    if t.get("expires_on", "") < B.today():
        return False, "threshold expired"
    if t.get("cli_version") != version:
        return False, "CLI version changed since calibration"
    return True, "live"


def tier1(q, state):
    a = run_cli("claude", prompt_for(q, state), schema_for(q))
    s2 = swapped(state) if q.get("order_swap") else state
    b = run_cli("claude", prompt_for(q, s2), schema_for(q))
    if q.get("order_swap"):
        b = unswap(b)
    return a, b


def to_verdict(qid, label):
    good = {"REQ-MET": "yes", "CLAIM-SUPPORT": "supported", "APPLIES": "yes", "PIPELINE-FIT": "yes", "PRIVACY-LEAK": "no",
            "SCOPE-COVER": "yes", "REQ-TESTABLE": "yes", "CONSTRAINT-QUOTED": "supported"}
    if label is None or label in ("insufficient", "unsure"):
        return "inconclusive"
    if qid in good:
        return "pass" if label == good[qid] else "fail"
    return "pass"  # classification questions (PLACE, ACTION-RISK, PAIR-BETTER, DUP-SAME) report the label itself


def ask(qid, state, subject="", maker="claude", kind=None):
    q = question(qid)
    version = cli_version(os.environ.get("BRAIN_CLAUDE_BIN", "claude"))
    rec = {"question_id": qid, "subject": subject, "at": B.now(), "evidence": [f"state:{f}" for f in q["state_fields"]]}
    direct = kind in (q.get("route_direct_to_tier2_when") or [])
    a = b = None
    if not direct:
        a, b = tier1(q, state)
        live, why = threshold_live(q, version)
        if a is not None and a == b and live:
            rec.update({"label": a, "tier": 1, "agreement": {"runs": 2, "same_label": True}, "confidence": 1.0,
                        "decided_by": {"vendor": "claude", "model": TIER1_MODEL, "cli_version": version}})
        rec["tier1"] = {"runs": [a, b], "accepted": "label" in rec, "why_not": None if "label" in rec else (why if a == b else "runs disagree")}
    if "label" not in rec:
        vendor = "codex" if maker == "claude" else "claude"
        label = run_cli(vendor, prompt_for(q, state), schema_for(q), model=None if vendor == "codex" else "sonnet")
        rec.update({"label": label, "tier": 2, "escalated_from": None if direct else 1,
                    "decided_by": {"vendor": vendor, "model": "default" if vendor == "codex" else "sonnet"}})
    rec["verdict"] = to_verdict(qid, rec["label"])
    os.makedirs(B.JUDGE, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def wilson_lower(k, n, z=1.645):
    if n == 0:
        return 0.0
    p = k / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def _read_jsonl(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _skey(state):
    return json.dumps(state, sort_keys=True, ensure_ascii=False)


def merged_gold(qid, canary_rows=None):
    """Canaries + the owner's labels, one row per state. The owner's label wins over a canary on the same state."""
    rows = canary_rows if canary_rows is not None else [r for r in _read_jsonl(os.path.join(GOLD, qid + ".jsonl")) if r.get("source") == "canary"]
    out = {}
    for r in rows + _read_jsonl(os.path.join(GOLD, "owner", qid + ".jsonl")):
        if isinstance(r.get("state"), dict) and r.get("label") is not None:
            out[_skey(r["state"])] = r
    return list(out.values())


def add_gold(qid, state, label, ref="", source="owner"):
    """Append one human label (layer 8 gold) and refresh the merged file. Returns False for a duplicate."""
    question(qid)  # unknown question id -> error now, not at calibration time
    mp = os.path.join(GOLD, "owner", qid + ".jsonl")
    if any(_skey(r.get("state")) == _skey(state) and r.get("label") == label for r in _read_jsonl(mp)):
        return False
    os.makedirs(os.path.dirname(mp), exist_ok=True)
    with open(mp, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"state": state, "label": label, "source": source, "ref": ref, "date": B.today()}, ensure_ascii=False) + "\n")
    rows = merged_gold(qid)
    B.atomic_write(os.path.join(GOLD, qid + ".jsonl"), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return True


def gold_items(qid):
    return merged_gold(qid)


def calibrate(qid, tier2_vendor="codex"):
    """Threshold rule: accept Tier-1 agreement only if its one-sided 95% lower bound on accuracy is within
    2 points of Tier 2's measured accuracy on the same gold items. Fewer than 30 labels: cold start."""
    q = question(qid)
    items = gold_items(qid)
    version = cli_version(os.environ.get("BRAIN_CLAUDE_BIN", "claude"))
    t = {"labels_used": len(items), "model": TIER1_MODEL, "cli_version": version, "set_on": B.today(),
         "expires_on": (datetime.date.today() + datetime.timedelta(days=30)).isoformat()}
    if len(items) < 30:
        t.update({"value": None, "rule": "cold_start_escalate_all"})
        q["threshold"] = t
        json.dump(q, open(os.path.join(QDIR, qid + ".json"), "w"), indent=1)
        return {"question": qid, "labels": len(items), "threshold": None, "why": "cold start: fewer than 30 gold labels"}
    agreed = right1 = right2 = 0
    for it in items:
        a, b = tier1(q, it["state"])
        if a is not None and a == b:
            agreed += 1
            right1 += a == it["label"]
        right2 += run_cli(tier2_vendor, prompt_for(q, it["state"]), schema_for(q),
                          model=None if tier2_vendor == "codex" else "sonnet") == it["label"]
    acc2 = right2 / len(items)
    lb = wilson_lower(right1, agreed)
    ok = agreed >= 30 and lb >= acc2 - 0.02
    t["tier2_vendor"] = tier2_vendor
    t.update({"value": 1.0 if ok else None, "rule": "lower_bound_95_within_2pts" if ok else "cold_start_escalate_all",
              "tier1_agreed": agreed, "tier1_right": right1, "tier1_lower_bound": round(lb, 3), "tier2_accuracy": round(acc2, 3)})
    q["threshold"] = t
    q["version"] = q.get("version", 1) + 1
    json.dump(q, open(os.path.join(QDIR, qid + ".json"), "w"), indent=1)
    return {"question": qid, "labels": len(items), "threshold": t["value"], "tier1_lower_bound": round(lb, 3), "tier2_accuracy": round(acc2, 3)}


def build_gold():
    """Gold = planted canaries (label known by construction) + the owner's own approvals/rejections of closed sessions."""
    os.makedirs(GOLD, exist_ok=True)
    canaries = B.load_json(os.path.join(B.JUDGE, "canaries.json"), {})
    counts = {}
    qids = set(canaries) | {f[:-6] for f in os.listdir(os.path.join(GOLD, "owner"))} if os.path.isdir(os.path.join(GOLD, "owner")) else set(canaries)
    for qid in sorted(qids):
        rows = merged_gold(qid, [{"state": it["state"], "label": it["label"], "source": "canary"} for it in canaries.get(qid, [])])
        B.atomic_write(os.path.join(GOLD, qid + ".jsonl"), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        counts[qid] = {"total": len(rows), "owner": sum(1 for r in rows if r.get("source") == "owner")}
    approvals = []
    for sid in sorted(os.listdir(B.SESSIONS)) if os.path.isdir(B.SESSIONS) else []:
        m = B.load_json(os.path.join(B.SESSIONS, sid, "meta.json"), {})
        if m.get("approval") in ("approved", "rejected"):
            approvals.append({"session": sid, "title": m.get("title"), "label": m["approval"], "source": "owner", "closed": m.get("closed")})
    with open(os.path.join(GOLD, "owner-approvals.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in approvals))
    counts["owner-approvals"] = len(approvals)
    return counts


def canary_run(only=None):
    canaries = B.load_json(os.path.join(B.JUDGE, "canaries.json"), {})
    out = []
    for qid, items in canaries.items():
        if only and qid != only:
            continue
        for i, it in enumerate(items):
            r = ask(qid, it["state"], subject=f"canary-{i}")
            out.append({"question": qid, "canary": i, "expected": it["label"], "got": r["label"], "tier": r["tier"], "ok": r["label"] == it["label"]})
    return out


def health():
    res = {"checked": B.now(), "vendors": {}, "questions": {}}
    probe = question("REQ-TESTABLE")
    for vendor in ("claude", "codex"):
        exe = os.environ.get("BRAIN_CLAUDE_BIN" if vendor == "claude" else "BRAIN_CODEX_BIN", vendor)
        good = run_cli(vendor, prompt_for(probe, {"requirement_text": "The file out/report.pdf exists and has 3 pages (check: count pages with pdfinfo)."}),
                       schema_for(probe), model=None if vendor == "codex" else TIER1_MODEL, timeout=180)
        bad = run_cli(vendor, prompt_for(probe, {"requirement_text": "The design should feel nice."}),
                      schema_for(probe), model=None if vendor == "codex" else TIER1_MODEL, timeout=180)
        res["vendors"][vendor] = {"version": cli_version(exe), "connected": good is not None or bad is not None,
                                  "follows_schema": good in probe["labels"] and bad in probe["labels"],
                                  "canaries_right": good == "yes" and bad == "no"}
    for f in sorted(os.listdir(QDIR)):
        q = json.load(open(os.path.join(QDIR, f), encoding="utf-8"))
        live, why = threshold_live(q, res["vendors"]["claude"]["version"])
        res["questions"][q["id"]] = {"calibrated": live, "status": why, "gold_labels": len(gold_items(q["id"]))}
    B.atomic_write(os.path.join(B.JUDGE, "health-v2.json"), json.dumps(res, indent=1))
    return res


def calibration_status():
    """Summarize cold-start (<30 labels), live calibration thresholds, and >50% escalation alerts per typed question."""
    claude_ver = cli_version(os.environ.get("BRAIN_CLAUDE_BIN", "claude"))
    log_rows = _read_jsonl(LOG)
    stats = {}
    for r in log_rows:
        qid = r.get("question_id")
        if not qid:
            continue
        st = stats.setdefault(qid, {"calls": 0, "tier1": 0, "escalated": 0, "direct_tier2": 0, "uncalibrated": 0})
        st["calls"] += 1
        why = str((r.get("tier1") or {}).get("why_not") or "")
        if r.get("escalated_from") == 1 and why and why != "runs disagree":
            # v6: Tier 1 agreed with itself and escalated only because no threshold is live (cold start, expired,
            # CLI changed). That is the cascade working as designed and says nothing about the question's wording.
            st["uncalibrated"] += 1
        elif r.get("escalated_from") == 1:
            st["escalated"] += 1
            st["tier1"] += 1
        elif r.get("tier") == 1:
            st["tier1"] += 1
        elif r.get("tier") == 2:
            st["direct_tier2"] += 1

    questions = {}
    alerts = []
    for f in sorted(os.listdir(QDIR)) if os.path.isdir(QDIR) else []:
        if not f.endswith(".json"):
            continue
        with open(os.path.join(QDIR, f), encoding="utf-8") as fh:
            q = json.load(fh)
        qid = q["id"]
        gold_n = len(gold_items(qid))
        cold_start = gold_n < 30
        live, why = threshold_live(q, claude_ver)
        st = stats.get(qid, {"calls": 0, "tier1": 0, "escalated": 0, "direct_tier2": 0, "uncalibrated": 0})
        esc_rate = round(st["escalated"] / st["tier1"], 3) if st["tier1"] else 0.0
        # Layer 8 rule: >50% escalations -> rewrite the question rather than lowering the threshold
        rewrite_alert = (not cold_start and st["tier1"] >= 4 and esc_rate > 0.5) or (st["tier1"] >= 6 and esc_rate > 0.5)
        if rewrite_alert:
            alerts.append({"question": qid, "escalation_rate": esc_rate, "action": "rewrite_question_not_threshold"})
        elif not cold_start and not live and st["uncalibrated"] >= 4 and not why.startswith("calibrated"):  # v6: enough labels, nobody ran the calibration
            alerts.append({"question": qid, "uncalibrated_escalations": st["uncalibrated"], "action": "calibrate_threshold",
                           "why": f"{gold_n} gold labels exist but no threshold is live ({why}): run judge_typed.py calibrate --question {qid}"})
        questions[qid] = {
            "gold_labels": gold_n,
            "cold_start": cold_start,
            "calibrated": live,
            "status": why,
            "calls": st["calls"],
            "tier1_calls": st["tier1"],
            "escalated": st["escalated"],
            "uncalibrated_escalations": st.get("uncalibrated", 0),
            "direct_tier2": st["direct_tier2"],
            "escalation_rate": esc_rate,
            "rewrite_alert": rewrite_alert,
        }
    return {
        "checked": B.now(),
        "cold_start_min_labels": 30,
        "escalation_rewrite_cutoff": 0.5,
        "alerts": alerts,
        "questions": questions,
    }


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("ask")
    a1.add_argument("--question", required=True)
    a1.add_argument("--state", required=True, help="JSON file with the question's state fields")
    a1.add_argument("--subject", default="")
    a1.add_argument("--maker", default="claude")
    a1.add_argument("--kind")
    c = sub.add_parser("calibrate")
    c.add_argument("--question", required=True)
    c.add_argument("--tier2-vendor", default="codex", choices=["codex", "claude"])
    k = sub.add_parser("canaries")
    k.add_argument("--question")
    sub.add_parser("health")
    sub.add_parser("gold")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "ask":
        with open(a.state, encoding="utf-8") as fh:
            st_obj = json.load(fh)
        r = ask(a.question, st_obj, a.subject, a.maker, a.kind)
    elif a.cmd == "calibrate":
        r = calibrate(a.question, a.tier2_vendor)
    elif a.cmd == "canaries":
        r = canary_run(a.question)
        print(json.dumps(r, indent=1))
        return 0 if r and all(x["ok"] for x in r) else 1
    elif a.cmd == "health":
        r = health()
    elif a.cmd == "status":
        r = calibration_status()
    else:
        r = build_gold()
    print(json.dumps(r, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
