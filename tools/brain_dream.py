#!/usr/bin/env python3
"""
brain_dream.py — Hydro Brain 2 lightweight background "DREAMING" self-improvement layer.

Gently runs when the Mac is idle (or manually with --once), consuming zero paid API tokens ($0):
  1. Unlearned Session Distillation   -> brain_learn on closed/ended sessions missing learn.json
  2. Thinking & Reasoning Mining      -> incremental scan of Claude & Codex JSONL thinking/reasoning + errors + corrections
  3. Missing-Node Knowledge Weaver    -> TF-IDF + tag graph linking across non-private notes (auto-rollback on scan error)
  4. Karpathy Wiki & Judge Lint       -> self-citation provenance, stale depends_on, contradictory rules, >50% escalations
  5. Skill Gap & Synonym Autoresearch -> logs missing/low-converting skills & ratchet-tested synonym tuning
  6. Dream Journal & FTS5 Refresh     -> appends Brain System/history/dream-journal.md + updates index/brain.db

Usage:
    python3 -I brain_dream.py --once [--apply-links] [--apply-tuning] [--dry-run] [--force]
    python3 -I brain_dream.py --if-idle [--min-idle 180] [--max-load 3.0]
    python3 -I brain_dream.py --daemon [--interval 900] [--min-idle 180]
    python3 -I brain_dream.py --status
    python3 -I brain_dream.py --install-launchd | --uninstall-launchd
"""
import argparse
import datetime
import glob
import hashlib
import json
import math
import os
import plistlib
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import hydro_skills as HS  # noqa: E402

DREAM_STATE = os.path.join(B.STATE, "dream-state.json")
DREAM_LAST = os.path.join(B.STATE, "dream-last.json")
DREAM_LOCK = os.path.join(B.STATE, "dream.lock")
DREAM_LOG = os.path.join(B.STATE, "dream.out")
DREAM_EXPERIMENTS = os.path.join(B.STATE, "dream-experiments.jsonl")

DREAM_JOURNAL = os.path.join(B.VAULT, "history", "dream-journal.md")
DREAM_REFLECTIONS = os.path.join(B.VAULT, "history", "learnings", "dream-reflections.md")
DREAM_MAP = os.path.join(B.VAULT, "history", "learnings", "dream-map.md")
DREAM_GAPS = os.path.join(B.VAULT, "capabilities", "dream-skill-gaps.md")
DREAM_REPORT = os.path.join(B.ROOT, "reports", "dream-latest.md")

PLIST_LABEL = "com.hydrobrain.dream"
PLIST_PATH = os.path.expanduser(f"~/Library/LaunchAgents/{PLIST_LABEL}.plist")

LINK_START = "<!-- hydro:dream-links:start -->"
LINK_END = "<!-- hydro:dream-links:end -->"
DEFAULT_TRANSCRIPT_ROOTS = ("~/.claude/projects", "~/.codex/sessions")

CORRECTION_RX = re.compile(
    r"^(?:actually|no[,.! ]|don't|do not|wrong|instead|stop|remember|never|always|make sure)\b",
    re.I,
)
SIGNAL_RX = re.compile(
    r"\b(?:root cause|gotcha|never|always|must|avoid|instead|workaround|fixed by|broke because|"
    r"missed|lesson|fails? when|timeout|schema|lock|cache|realpath|unicode|frontmatter)\b",
    re.I,
)
EMAIL_RX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
LONG_NUM_RX = re.compile(r"\b\d{9,}\b")
# Scripts stripped from reflections: only those the owner forbids in state/vault-policy.json (default: none).
_POLICY_SCRIPTS = [v for v in (B.language_policy().get("disallowed_scripts") or {}).values()]
DISALLOWED_SCRIPT_RX = re.compile("|".join(f"(?:{v})" for v in _POLICY_SCRIPTS)) if _POLICY_SCRIPTS else None
WIKILINK_RX = re.compile(r"\[\[([^\]|#^]+)")
STOP_GRAPH = HS.STOP | frozenset(
    "note notes file files section summary updated title status type scope class brain system"
    " hydro project session sessions true false none list markdown".split()
)

_STOP_DAEMON = False


def _handle_sig(_signum, _frame):
    global _STOP_DAEMON
    _STOP_DAEMON = True


def _apply_low_priority():
    try:
        os.nice(15)
    except OSError:
        pass


def hid_idle_seconds():
    """Return macOS HID idle time in seconds via ioreg, or None if unavailable."""
    ioreg = "/usr/sbin/ioreg"
    if sys.platform != "darwin" or not os.path.exists(ioreg):
        return None
    try:
        r = subprocess.run([ioreg, "-c", "IOHIDSystem", "-r", "-d", "4"], capture_output=True, text=True, timeout=2)
        m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', r.stdout or "")
        if m:
            return round(int(m.group(1)) / 1e9, 1)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def system_ready(min_idle=180.0, max_load=None, check_idle=True, check_load=True, force=False):
    """Return (ok: bool, reason: str, metrics: dict) without straining an active computer."""
    cpu_n = os.cpu_count() or 4
    load_cap = float(max_load if max_load is not None else max(2.5, cpu_n * 0.75))
    try:
        load1 = round(os.getloadavg()[0], 2)
    except OSError:
        load1 = 0.0
    idle = hid_idle_seconds() if check_idle else None
    metrics = {"load_1m": load1, "max_load": load_cap, "idle_s": idle, "min_idle": min_idle}

    if os.path.exists(os.path.join(B.STATE, "sleep.lock")):
        return False, "sleep.lock active", metrics
    repo_lock_p = os.path.join(B.STATE, "repo.lock")
    if os.path.exists(repo_lock_p):
        import fcntl
        fd = None
        try:
            fd = os.open(repo_lock_p, os.O_RDONLY)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            return False, "repo.lock held by active writer", metrics
        except OSError:
            pass
        finally:
            if fd is not None:
                os.close(fd)
    if force:
        return True, "forced", metrics
    if check_load and load1 > load_cap:
        return False, f"cpu_busy (load_1m={load1} > {load_cap})", metrics
    if check_idle and idle is not None and idle < min_idle:
        return False, f"user_active (idle={idle}s < {min_idle}s)", metrics
    return True, "ok", metrics


def acquire_lock(timeout_s=3600):
    os.makedirs(B.STATE, exist_ok=True)
    if os.path.exists(DREAM_LOCK):
        try:
            age = time.time() - os.path.getmtime(DREAM_LOCK)
            if age > timeout_s:
                os.unlink(DREAM_LOCK)
            else:
                info = B.load_json(DREAM_LOCK, {})
                pid = info.get("pid")
                if pid:
                    try:
                        os.kill(int(pid), 0)
                        return False
                    except OSError:
                        os.unlink(DREAM_LOCK)
        except OSError:
            return False
    try:
        fd = os.open(DREAM_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(fd, json.dumps({"pid": os.getpid(), "started": B.now()}).encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock():
    try:
        if os.path.exists(DREAM_LOCK):
            os.unlink(DREAM_LOCK)
    except OSError:
        pass


def _privacy_terms():
    raw = B.load_json(os.path.join(B.STATE, "privacy-terms.json"), {})
    if isinstance(raw, list):
        return [str(x) for x in raw if len(str(x)) >= 3]
    if isinstance(raw, dict):
        out = []
        for v in raw.values():
            if isinstance(v, list):
                out.extend(str(x) for x in v if len(str(x)) >= 3)
        return out
    return []


def _sanitize_text(text, priv_terms):
    if not text or not isinstance(text, str):
        return ""
    if "Brain System/self" in text or "Brain System\\self" in text:
        return ""
    s = " ".join(text.split())
    if DISALLOWED_SCRIPT_RX is not None and DISALLOWED_SCRIPT_RX.search(s):
        s = DISALLOWED_SCRIPT_RX.sub("", s).strip()
    if not s:
        return ""
    s = EMAIL_RX.sub("[email]", s)
    s = LONG_NUM_RX.sub("[id]", s)
    s = s.replace(os.path.expanduser("~"), "~")
    for term in priv_terms:
        if term.lower() in s.lower():
            return ""
    if len(s) < 20:
        return ""
    return s[:220]


def _signal_sentences(raw):
    """v6: the whole sentence that carries the signal word (plus the next one when it fits), never a 220-character cut
    through the middle of a thought. A reflection nobody can read back is noise in the memory."""
    flat = " ".join(str(raw).split())
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[])", flat)
    for i, sent in enumerate(parts):
        if SIGNAL_RX.search(sent) and 25 <= len(sent) <= 215:
            prev = parts[i - 1] if i else ""
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            refers_back = re.search(r"\binstead\b|^(?:It|This|That|So|Then|I'll|I will|Which)\b", sent)
            if refers_back and prev and len(prev) + len(sent) + 1 <= 215:  # "instead" needs the sentence it answers
                return prev + " " + sent
            return sent + (" " + nxt if nxt and len(sent) + len(nxt) + 1 <= 215 else "")
    return ""


def _stage_learn_sessions(max_sessions, dry_run):
    import brain_learn
    targets = brain_learn.find_target_sessions(latest_only=False)[:max_sessions]
    if dry_run:
        return {"pending": len(targets), "learned": [], "dry_run": True}
    done = []
    for sid in targets:
        try:
            r = brain_learn.learn_session(sid, refresh_index=False)
            done.append({"session": sid, "status": r.get("status"), "insights": r.get("insights_count", 0)})
        except Exception as exc:
            done.append({"session": sid, "status": f"error:{type(exc).__name__}"})
    return {"pending": len(targets), "learned": done}


TOOL_NOISE_RX = re.compile(
    r"requires approval|requested permissions|contains multiple operations|Quoted text in this command",
    re.I,
)


def _extract_from_transcript(path, priv_terms):
    """Extract condensed thinking/reasoning insights, tool failures, and user corrections from Claude/Codex JSONL."""
    thoughts, errors, corrections = [], [], []
    is_codex = "rollout-" in os.path.basename(path) or "/.codex/" in path.replace("\\", "/")
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for idx, line in enumerate(fh):
                if idx > 4000:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if is_codex:
                    rtype = rec.get("type")
                    payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
                    ptype = payload.get("type") or ""
                    if rtype in ("response_item", "event_msg") and ptype in ("reasoning", "agent_reasoning"):
                        raw_t = payload.get("text") or ""
                        if not raw_t and isinstance(payload.get("summary"), list):
                            raw_t = " ".join(str(x.get("text", "")) for x in payload["summary"] if isinstance(x, dict))
                        if raw_t and SIGNAL_RX.search(raw_t):
                            c = _sanitize_text(_signal_sentences(raw_t), priv_terms) if "Brain System/self" not in raw_t else ""
                            if c:
                                thoughts.append(c)
                    elif rtype == "response_item" and ptype == "function_call_output":
                        out = str(payload.get("output") or "")
                        if re.search(r"exit code\s+[1-9]|traceback|error:", out, re.I):
                            c = _sanitize_text(out[:240], priv_terms)
                            if c:
                                errors.append(c)
                    elif rtype == "event_msg" and ptype == "user_message":
                        msg = str(payload.get("message") or "").strip()
                        if CORRECTION_RX.match(msg) and len(msg) <= 240:
                            c = _sanitize_text(msg, priv_terms)
                            if c:
                                corrections.append(c)
                else:
                    msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
                    content = msg.get("content")
                    if rec.get("type") == "assistant" and isinstance(content, list):
                        for blk in content:
                            if not isinstance(blk, dict):
                                continue
                            if blk.get("type") == "thinking":
                                raw_t = str(blk.get("thinking") or "")
                                if raw_t and SIGNAL_RX.search(raw_t):
                                    c = _sanitize_text(_signal_sentences(raw_t), priv_terms) if "Brain System/self" not in raw_t else ""
                                    if c:
                                        thoughts.append(c)
                    elif rec.get("type") == "user":
                        if isinstance(content, str) and CORRECTION_RX.match(content.strip()) and len(content.strip()) <= 240:
                            c = _sanitize_text(content.strip(), priv_terms)
                            if c:
                                corrections.append(c)
                        elif isinstance(content, list):
                            for blk in content:
                                if not isinstance(blk, dict):
                                    continue
                                if blk.get("type") == "tool_result" and blk.get("is_error"):
                                    raw_e = str(blk.get("content") or "")[:240]
                                    if TOOL_NOISE_RX.search(raw_e):
                                        continue
                                    c = _sanitize_text(raw_e, priv_terms)
                                    if c:
                                        errors.append(c)
                                elif blk.get("type") == "text":
                                    txt = str(blk.get("text") or "").strip()
                                    if CORRECTION_RX.match(txt) and len(txt) <= 240:
                                        c = _sanitize_text(txt, priv_terms)
                                        if c:
                                            corrections.append(c)
    except OSError:
        return [], [], []
    return thoughts[:6], errors[:4], corrections[:4]


def _stage_mine_transcripts(roots, state, max_transcripts, dry_run):
    priv = _privacy_terms()
    seen = state.setdefault("transcripts", {})
    candidates = []
    for root in roots:
        rp = os.path.expanduser(root)
        if not os.path.isdir(rp):
            continue
        for dp, dirs, fs in os.walk(rp):
            dirs[:] = [d for d in dirs if d not in (".git", "_to_delete", "node_modules")]
            for fn in fs:
                if not fn.endswith(".jsonl"):
                    continue
                fp = os.path.join(dp, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                if st.st_size < 120 or st.st_size > 25 * 1024 * 1024:
                    continue
                prev = seen.get(fp)
                if prev and prev.get("mtime_ns") == st.st_mtime_ns and prev.get("size") == st.st_size:
                    continue
                candidates.append((st.st_mtime_ns, st.st_size, fp))

    candidates.sort(key=lambda x: -x[0])
    picked = candidates[:max_transcripts]
    reflections = []
    err_counts, err_first = {}, {}
    for mtime_ns, size, fp in picked:
        th, er, co = _extract_from_transcript(fp, priv)
        stem = os.path.splitext(os.path.basename(fp))[0][:18]
        for item in th:
            reflections.append(("thinking", stem, item))
        for item in co:
            reflections.append(("correction", stem, item))
        for item in er:
            sig = re.sub(r"\d+|/[^\s]+", "<x>", item[:90]).strip()
            err_counts[sig] = err_counts.get(sig, 0) + 1
            err_first.setdefault(sig, (stem, item))
        if not dry_run:
            seen[fp] = {"mtime_ns": mtime_ns, "size": size, "scanned_at": B.now()}

    # v6: one failed command is an event, not a lesson. A tool error enters the memory only when the same signature
    # came back (>= 2 times in this cycle), with its count.
    for sig, cnt in sorted(err_counts.items(), key=lambda x: -x[1]):
        if cnt >= 2:
            stem, item = err_first[sig]
            reflections.append(("tool_error", stem, f"({cnt}x) {item}"))

    # Hook errors: one line per distinct error with its count, not the last 100 log lines
    herr_path = os.path.join(B.STATE, "analysis", "hook-errors.log")
    if os.path.isfile(herr_path):
        try:
            with open(herr_path, encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()[-200:]
            hsig, cut = {}, time.time() - 14 * 86400
            for ln in lines:
                if (B.local_epoch(ln[:19]) or 0) < cut:
                    continue  # v7: an error from weeks ago (long fixed) is not news; only the last 14 days count
                body = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s*", "", ln).strip()
                if body:
                    hsig[body] = hsig.get(body, 0) + 1
            for body, cnt in sorted(hsig.items(), key=lambda x: -x[1])[:5]:
                c = _sanitize_text(f"hook error ({cnt}x in the log): {body}", priv)
                if c:
                    reflections.append(("hook_error", "hooks", c))
        except OSError:
            pass

    # Write cumulative Brain System/history/learnings/dream-reflections.md (preserving latest 80 lines)
    existing = []
    if os.path.isfile(DREAM_REFLECTIONS):
        with open(DREAM_REFLECTIONS, encoding="utf-8", errors="ignore") as fh:
            for ln in fh:
                if ln.startswith("- `"):
                    existing.append(ln.rstrip("\n"))
    added = 0
    seen_hashes = {hashlib.sha1(e.split("] ", 1)[-1].encode("utf-8", "ignore")).hexdigest()[:10] for e in existing if "] " in e}
    new_bullets = []
    for kind, stem, text in reflections:
        h = hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:10]
        if h in seen_hashes:
            continue
        seen_hashes.add(h)
        new_bullets.append(f"- `{B.today()}` · [{kind}:{stem}] {text}")
        added += 1

    queued_candidates = []
    if not dry_run and new_bullets:
        os.makedirs(os.path.dirname(DREAM_REFLECTIONS), exist_ok=True)
        merged = (new_bullets[:25] + existing)[:80]
        body = (
            "---\n"
            "title: Dream Reflections (Thinking & Error Mining)\n"
            "type: log\n"
            "status: active\n"
            "scope_class: engineering\n"
            "sources:\n"
            "  - tools/brain_dream.py\n"
            "  - state/analysis/\n"
            f"updated: {B.today()}\n"
            "---\n\n"
            "# Dream Reflections\n\n"
            "Privacy-sanitized patterns distilled incrementally from local Claude/Codex thinking, reasoning, tool errors, and user corrections.\n\n"
            "## Recent distilled insights\n\n"
            + "\n".join(merged)
            + "\n"
        )
        B.atomic_write(DREAM_REFLECTIONS, body)

        # Promote recurring error/correction patterns into queue/ candidate cards (max 2 per cycle)
        for sig, cnt in sorted(err_counts.items(), key=lambda x: -x[1])[:2]:
            if cnt >= 2:
                slug = hashlib.sha1(sig.encode("utf-8", "ignore")).hexdigest()[:8]
                qp = os.path.join(B.QUEUE, f"dream-{slug}.md")
                if not os.path.exists(qp):
                    B.atomic_write(
                        qp,
                        "---\n"
                        f"title: \"Dream pattern ({slug})\"\n"
                        "type: lesson\n"
                        "status: candidate\n"
                        "source: tools/brain_dream.py\n"
                        f"updated: {B.today()}\n"
                        "---\n"
                        f"Recurring tool error seen {cnt}x across recent local transcripts: `{sig}`.\n"
                        "Investigate root cause and add a deterministic Tier-0 or hook guard before release.\n",
                    )
                    queued_candidates.append(B.rel(qp))

    return {
        "scanned_transcripts": len(picked),
        "remaining_backlog": max(0, len(candidates) - len(picked)),
        "new_reflections": added,
        "queued_candidates": queued_candidates,
        "reflections_file": B.rel(DREAM_REFLECTIONS) if (added or os.path.exists(DREAM_REFLECTIONS)) else None,
    }


def _note_tokens(title, tags, body):
    text = f"{title} {' '.join(tags)} {body[:1800]}".lower()
    raw = re.findall(r"[a-z][a-z0-9\-]{2,}", text)
    return {w for w in raw if w not in STOP_GRAPH and not w.isdigit() and not re.search(r"\d{2,}", w) and len(w) <= 24}


def _collection_scope_compat(rel_a, rel_b):
    top_a, top_b = rel_a.split("/", 1)[0], rel_b.split("/", 1)[0]
    if "self" in (top_a, top_b):
        return False
    if top_a == "projects" and top_b == "projects":
        return rel_a.split("/")[1:2] == rel_b.split("/")[1:2]
    return True


def _stage_weave_graph(max_links, apply_links, dry_run):
    """Find disconnected / under-linked non-private notes and weave safe [[rel_no_ext|Title]] bridges."""
    nodes = {}
    indeg = {}
    outdeg = {}
    for p in B.iter_notes(B.VAULT):
        rel = os.path.relpath(p, B.VAULT).replace(os.sep, "/")
        if rel.startswith(("self/", "00-toc/", "drawings/")):
            continue
        with open(p, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        fm, body = B.split_frontmatter(text)
        meta = B.parse_frontmatter(fm) if fm else {}
        if meta.get("authority") == "legacy":
            continue
        tags = meta.get("tags", []) if isinstance(meta.get("tags"), list) else []
        title = str(meta.get("title") or os.path.splitext(os.path.basename(rel))[0]).strip()
        links = [m.group(1).strip() for m in WIKILINK_RX.finditer(body)]
        toks = _note_tokens(title, [str(t) for t in tags], body)
        nodes[rel] = {
            "anchor": _note_tokens(title, [str(t) for t in tags], ""),
            "abs": p,
            "rel_no_ext": rel[:-3] if rel.endswith(".md") else rel,
            "title": title,
            "toks": toks,
            "raw_text": text,
            "links_raw": set(links),
        }
        outdeg[rel] = len(links)
        indeg.setdefault(rel, 0)
        for lk in links:
            norm_lk = lk[:-3] if lk.endswith(".md") else lk
            for cand_rel in list(nodes):
                if cand_rel[:-3] == norm_lk or os.path.basename(cand_rel[:-3]) == norm_lk:
                    indeg[cand_rel] = indeg.get(cand_rel, 0) + 1

    # Recount normalized in-degree cleanly once all nodes are loaded
    by_rel_no_ext = {v["rel_no_ext"].lower(): k for k, v in nodes.items()}
    by_stem = {}
    for k, v in nodes.items():
        st = os.path.basename(v["rel_no_ext"]).lower()
        by_stem.setdefault(st, []).append(k)
    peer_in = {k: 0 for k in nodes}
    peer_out = {k: set() for k in nodes}
    for rel, info in nodes.items():
        if rel == "history/learnings/dream-map.md":
            continue
        for lk in info["links_raw"]:
            n_lk = (lk[:-3] if lk.endswith(".md") else lk).lower()
            dest = by_rel_no_ext.get(n_lk)
            if not dest and len(by_stem.get(os.path.basename(n_lk), [])) == 1:
                dest = by_stem[os.path.basename(n_lk)][0]
            if dest and dest != rel:
                peer_out[rel].add(dest)
                peer_in[dest] += 1

    N = max(1, len(nodes))
    df = {}
    for info in nodes.values():
        for t in info["toks"]:
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((N + 1.0) / (1.0 + c)) for t, c in df.items() if c <= max(3, int(N * 0.45))}

    weak_nodes = [
        rel
        for rel in sorted(nodes)
        if rel not in ("history/learnings/dream-map.md", "history/learnings/dream-reflections.md", "history/dream-journal.md")
        and (len(peer_out[rel]) == 0 or peer_in[rel] == 0)
        and len(nodes[rel]["toks"]) >= 4
    ]

    bridges = []
    for src in weak_nodes:
        src_t = nodes[src]["toks"]
        scored = []
        for dst, dinfo in nodes.items():
            if dst == src or dst in peer_out[src]:
                continue
            if not _collection_scope_compat(src, dst):
                continue
            if dst in ("history/learnings/dream-map.md",):
                continue
            shared = [t for t in (src_t & dinfo["toks"]) if t in idf]
            if len(shared) < 2:
                continue
            # v6 topical anchor: two notes are related when they share a word of their TITLE or TAGS, not because both
            # happen to contain "entirely" and "wanna". Without an anchor there is no bridge, however high the score.
            if not (nodes[src]["anchor"] & dinfo["anchor"]):
                continue
            score = sum(idf[t] for t in shared) / math.sqrt(max(1, len(src_t)) * max(1, len(dinfo["toks"])))
            anchor = nodes[src]["anchor"] & dinfo["anchor"]
            shared.sort(key=lambda t: (t not in anchor, -idf[t]))  # show the title/tag words first: they are the reason
            if score >= 0.35:
                scored.append((round(score, 3), dst, shared[:4]))
        scored.sort(key=lambda x: (-x[0], x[1]))
        if scored:
            bridges.append({"source": src, "targets": [{"rel": d, "rel_no_ext": nodes[d]["rel_no_ext"], "title": nodes[d]["title"], "score": sc, "shared": sh} for sc, d, sh in scored[:2]]})
        if len(bridges) >= max_links:
            break

    if not dry_run and bridges:
        os.makedirs(os.path.dirname(DREAM_MAP), exist_ok=True)
        lines = [
            "---",
            "title: Dream Graph Map (Connected Missing Nodes)",
            "type: log",
            "status: active",
            "scope_class: engineering",
            "sources:",
            "  - tools/brain_dream.py",
            f"updated: {B.today()}",
            "---",
            "",
            "# Dream Graph Map",
            "",
            "Semantic bridges connecting isolated or unlinked non-private notes using exact path wikilinks (`0` ambiguous stems).",
            "",
            "## Discovered Missing Bridges",
            "",
        ]
        for br in bridges:
            src_info = nodes[br["source"]]
            tgts = ", ".join(f"[[{t['rel_no_ext']}|{t['title']}]] (`{','.join(t['shared'])}`)" for t in br["targets"])
            lines.append(f"- [[{src_info['rel_no_ext']}|{src_info['title']}]] -> {tgts}")
        B.atomic_write(DREAM_MAP, "\n".join(lines) + "\n")

    edited = []
    rolled_back = False
    if apply_links and not dry_run and bridges:
        backups = {}
        eligible_prefixes = ("lessons/", "concepts/", "capabilities/", "history/learnings/")
        for br in bridges[:8]:
            src = br["source"]
            if not src.startswith(eligible_prefixes):
                continue
            info = nodes[src]
            block_lines = [LINK_START, "## Related nodes", ""]
            for t in br["targets"]:
                block_lines.append(f"- [[{t['rel_no_ext']}|{t['title']}]] *(shared: {', '.join(t['shared'])})*")
            block_lines.append(LINK_END)
            block = "\n".join(block_lines) + "\n"
            old = info["raw_text"]
            if LINK_START in old and LINK_END in old:
                new_text = re.sub(re.escape(LINK_START) + r".*?" + re.escape(LINK_END) + r"\n?", block, old, flags=re.S)
            else:
                new_text = old.rstrip() + "\n\n" + block
            if new_text != old:
                backups[info["abs"]] = old
                B.atomic_write(info["abs"], new_text)
                edited.append(src)

        if edited:
            import tempfile
            tmp_out = tempfile.mkdtemp(prefix="dream-verify-")
            scan_p = subprocess.run([sys.executable, "-I", os.path.join(B.TOOLS, "vault_scan.py"), "--vault", B.VAULT, "--out", os.path.join(tmp_out, "scan")],
                                    capture_output=True, text=True, timeout=120)
            audit_p = subprocess.run([sys.executable, "-I", os.path.join(B.TOOLS, "vault_audit.py"), "--vault", B.VAULT, "--out", os.path.join(tmp_out, "audit")],
                                     capture_output=True, text=True, timeout=120)
            scan_ok = scan_p.returncode == 0 and "ghosts=0" in scan_p.stdout and "errors=0" in scan_p.stdout
            audit_ok = audit_p.returncode == 0 and '"errors": 0' in audit_p.stdout
            if not (scan_ok and audit_ok):
                for path, orig in backups.items():
                    B.atomic_write(path, orig)
                edited = []
                rolled_back = True

    return {
        "isolated_candidates": len(weak_nodes),
        "bridges_found": len(bridges),
        "links_woven": len(edited),
        "rolled_back": rolled_back,
        "map_file": B.rel(DREAM_MAP) if bridges else None,
    }


def _find_lesson_contradictions():
    """Detect pairs of released/candidate lesson notes asserting conflicting always/never imperatives on shared terms."""
    imperatives = []
    rx = re.compile(r"\b(always|never|must not|do not)\s+([^.;\n]{12,85})", re.I)
    for folder in (os.path.join(B.VAULT, "lessons"), os.path.join(B.VAULT, "problems")):
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(folder, fn)
            rel = B.rel(p)
            with open(p, encoding="utf-8", errors="ignore") as fh:
                txt = fh.read()
            _, body = B.split_frontmatter(txt)
            for m in rx.finditer(body):
                pol = "pos" if m.group(1).lower() == "always" else "neg"
                toks = {w for w in re.findall(r"[a-z0-9]{3,}", m.group(2).lower()) if w not in STOP_GRAPH}
                if len(toks) >= 2:
                    imperatives.append((rel, pol, toks, m.group(0).strip()[:100]))
    conflicts = []
    for i, (r1, p1, t1, s1) in enumerate(imperatives):
        for r2, p2, t2, s2 in imperatives[i + 1:]:
            if r1 == r2 or p1 == p2:
                continue
            ov = t1 & t2
            if len(ov) >= 3:
                conflicts.append({"notes": [r1, r2], "shared": sorted(ov)[:4], "a": s1, "b": s2})
                if len(conflicts) >= 5:
                    return conflicts
    return conflicts


def _stage_wiki_lint_and_gaps(dry_run):
    import judge_typed as J
    import vault_audit as VA
    import brain_sleep as BS

    _, errs, warns, _ = VA.audit(B.VAULT, B.ROOT)
    self_cites = sum(1 for _, _, w, _ in warns if "self-citation loop" in w)
    stale = BS.stale_depends() if hasattr(BS, "stale_depends") else []
    j_status = J.calibration_status()
    conflicts = _find_lesson_contradictions()

    # Skill gap & retrieval gap aggregation
    missing_gaps = {}
    for f in glob.glob(os.path.join(B.SESSIONS, "*", "retrieval-log.jsonl")):
        with open(f, encoding="utf-8", errors="ignore") as fh:
            for ln in fh:
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                kind = row.get("mark") or row.get("action")
                what = row.get("what") or row.get("reason")
                if kind == "missing" and what:
                    missing_gaps[what] = missing_gaps.get(what, 0) + 1

    tel = B.load_json(os.path.join(B.STATE, "skill-telemetry.json"), {}).get("skills", {})
    low_conv = [
        (nm, info.get("shown", 0), info.get("used", 0))
        for nm, info in tel.items()
        if info.get("shown", 0) >= 6 and info.get("used", 0) == 0
    ]
    low_conv.sort(key=lambda x: -x[1])

    if not dry_run:
        os.makedirs(os.path.dirname(DREAM_GAPS), exist_ok=True)
        lines = [
            "---",
            "title: Dream Skill & Retrieval Gaps",
            "type: learning",
            "status: active",
            "scope_class: engineering",
            "sources:",
            "  - tools/brain_dream.py",
            "  - state/skill-telemetry.json",
            f"updated: {B.today()}",
            "---",
            "",
            "# Dream Skill & Retrieval Gaps",
            "",
            "## Missing capabilities / notes reported in sessions",
            "",
        ]
        if missing_gaps:
            for what, cnt in sorted(missing_gaps.items(), key=lambda x: -x[1])[:20]:
                lines.append(f"- `{cnt}x` {what}")
        else:
            lines.append("- None recorded yet.")
        lines += ["", "## Shown repeatedly without being read (`shown >= 6, used == 0`)", ""]
        if low_conv:
            for nm, sh, us in low_conv[:20]:
                lines.append(f"- `{nm}`: shown={sh}, used={us}")
        else:
            lines.append("- No chronically ignored skills detected.")
        lines += ["", "## Potential contradictions & calibration alerts", ""]
        for c in conflicts:
            lines.append(f"- Conflict `{c['notes'][0]}` vs `{c['notes'][1]}` on `{', '.join(c['shared'])}`")
        for al in j_status.get("alerts", []):
            lines.append(f"- Typed judge alert `{al['question']}`: {al.get('why') or 'escalation=' + str(al.get('escalation_rate'))} -> {al['action']}")
        if not conflicts and not j_status.get("alerts"):
            lines.append("- Clean: 0 contradictions, 0 judge alerts.")
        B.atomic_write(DREAM_GAPS, "\n".join(lines) + "\n")

    return {
        "audit_errors": len(errs),
        "audit_warnings": len(warns),
        "self_citation_warnings": self_cites,
        "stale_depends": len(stale),
        "judge_alerts": j_status.get("alerts", []),
        "contradictions": conflicts,
        "missing_skill_gaps": len(missing_gaps),
        "low_conversion_skills": len(low_conv),
    }


def _stage_synonym_autoresearch(apply_tuning, dry_run):
    """Counts the prompt-skills cases the router misses. v6 note: this stage MEASURES only. With --apply-tuning it logs a
    route_eval baseline to state/dream-experiments.jsonl; it proposes and keeps nothing ("kept": false always). Real
    tuning stays in gym.py, against a held-out set."""
    ps = B.load_json(os.path.join(B.STATE, "eval", "prompt-skills.json"), {})
    import brain_hooks as H
    misses = []
    for case in ps.get("positive", []):
        want = {x.lower() for x in case.get("accept", [])}
        got = {s["name"].lower() for s in H.pick_skills(case["prompt"])}
        if not (got & want):
            misses.append({"prompt": case["prompt"], "expected": sorted(want)[:3]})

    tuned = []
    if apply_tuning and misses and not dry_run:
        # Safe Karpathy autoresearch ratchet: log baseline and only keep if route_eval improves cleanly
        rc, out, _ = _run_route_eval()
        rec = {"at": B.now(), "baseline_misses": len(misses), "route_eval_rc": rc, "kept": False, "details": out[:200]}
        os.makedirs(B.STATE, exist_ok=True)
        with open(DREAM_EXPERIMENTS, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        tuned.append(rec)
    return {"prompt_skill_misses": len(misses), "samples": misses[:3], "tuning_trials": tuned}


def _run_route_eval():
    p = subprocess.run(
        [sys.executable, "-I", os.path.join(B.TOOLS, "route_eval.py")],
        capture_output=True, text=True, timeout=120, cwd=B.ROOT,
    )
    return p.returncode, (p.stdout or p.stderr).strip(), p.stderr


def _record_journal_and_refresh(summary, dry_run):
    if dry_run:
        return False
    os.makedirs(os.path.dirname(DREAM_JOURNAL), exist_ok=True)
    os.makedirs(os.path.dirname(DREAM_REPORT), exist_ok=True)
    existing = []
    if os.path.isfile(DREAM_JOURNAL):
        with open(DREAM_JOURNAL, encoding="utf-8", errors="ignore") as fh:
            existing = [ln.rstrip("\n") for ln in fh if ln.startswith("- `")][:90]

    learn_n = len(summary["sessions"].get("learned", []))
    tr = summary["transcripts"]
    gr = summary["graph"]
    lt = summary["lint"]
    sy = summary["synonyms"]
    entry = (
        f"- `{summary['finished']}` · sessions={learn_n} · "
        f"transcripts={tr['scanned_transcripts']} (+{tr['new_reflections']} reflections, +{len(tr['queued_candidates'])} queue) · "
        f"graph_bridges={gr['bridges_found']} (woven={gr['links_woven']}) · "
        f"lint_errs={lt['audit_errors']} self_cites={lt['self_citation_warnings']} conflicts={len(lt['contradictions'])} · "
        f"skill_misses={sy['prompt_skill_misses']}"
    )
    journal_body = (
        "---\n"
        "title: Dream Journal\n"
        "type: log\n"
        "status: active\n"
        "scope_class: engineering\n"
        "sources:\n"
        "  - tools/brain_dream.py\n"
        "  - state/dream-state.json\n"
        f"updated: {B.today()}\n"
        "---\n\n"
        "# Dream Journal (Append-Only Log)\n\n"
        + "\n".join([entry] + existing)
        + "\n"
    )
    B.atomic_write(DREAM_JOURNAL, journal_body)

    rep_md = (
        f"# Hydro Brain 2 — Dream Cycle Report ({summary['finished']})\n\n"
        f"- Status: `{summary['status']}` · Duration: `{summary['seconds']}s` · Mode: `{summary['mode']}`\n"
        f"- Sessions distilled: `{learn_n}` (pending before cycle: `{summary['sessions'].get('pending', 0)}`)\n"
        f"- Transcripts scanned: `{tr['scanned_transcripts']}` (backlog left: `{tr['remaining_backlog']}`, "
        f"new reflections: `{tr['new_reflections']}`, queued: `{len(tr['queued_candidates'])}`)\n"
        f"- Graph bridges discovered: `{gr['bridges_found']}` (woven into notes: `{gr['links_woven']}`, "
        f"rolled back: `{gr['rolled_back']}`)\n"
        f"- Wiki lint: errors=`{lt['audit_errors']}`, self_citation_warnings=`{lt['self_citation_warnings']}`, "
        f"stale_depends=`{lt['stale_depends']}`, contradictions=`{len(lt['contradictions'])}`, "
        f"judge_alerts=`{len(lt['judge_alerts'])}`\n"
        f"- Prompt-skill misses: `{sy['prompt_skill_misses']}` · Missing capability reports: `{lt['missing_skill_gaps']}`\n"
    )
    B.atomic_write(DREAM_REPORT, rep_md)
    B.atomic_write(DREAM_LAST, json.dumps(summary, indent=1, ensure_ascii=False) + "\n")

    try:
        import brain_learn
        for p in (DREAM_JOURNAL, DREAM_REFLECTIONS, DREAM_MAP, DREAM_GAPS):
            if os.path.isfile(p):
                brain_learn._incremental_index_upsert(p)
        return True
    except Exception:
        return False


def run_cycle(
    check_idle=False,
    check_load=True,
    min_idle=180.0,
    max_load=None,
    max_transcripts=12,
    max_sessions=12,
    max_links=20,
    apply_links=False,
    apply_tuning=False,
    dry_run=False,
    force=False,
    transcript_roots=None,
):
    _apply_low_priority()
    ok, reason, metrics = system_ready(min_idle=min_idle, max_load=max_load, check_idle=check_idle, check_load=check_load, force=force)
    if not ok:
        return {"status": "skipped", "reason": reason, "metrics": metrics, "at": B.now()}

    if not acquire_lock():
        return {"status": "locked", "reason": "dream.lock held", "metrics": metrics, "at": B.now()}

    t0, started = time.time(), B.now()
    try:
        state = B.load_json(DREAM_STATE, {"cycles": 0, "transcripts": {}})
        roots = transcript_roots or list(DEFAULT_TRANSCRIPT_ROOTS)

        sess_res = _stage_learn_sessions(max_sessions, dry_run)
        tr_res = _stage_mine_transcripts(roots, state, max_transcripts, dry_run)
        gr_res = _stage_weave_graph(max_links, apply_links, dry_run)
        lt_res = _stage_wiki_lint_and_gaps(dry_run)
        sy_res = _stage_synonym_autoresearch(apply_tuning, dry_run)

        summary = {
            "status": "dreamed",
            "mode": "dry-run" if dry_run else ("apply-links" if apply_links else "gentle"),
            "started": started,
            "finished": B.now(),
            "seconds": round(time.time() - t0, 2),
            "epoch": time.time(),
            "metrics": metrics,
            "sessions": sess_res,
            "transcripts": tr_res,
            "graph": gr_res,
            "lint": lt_res,
            "synonyms": sy_res,
        }
        refreshed = _record_journal_and_refresh(summary, dry_run)
        summary["index_refreshed"] = refreshed
        if not dry_run:
            state["cycles"] = int(state.get("cycles", 0)) + 1
            state["last_dream"] = summary["finished"]
            state["last_epoch"] = summary["epoch"]
            # Trim transcript cursor if huge (>2000 files) keeping most recently scanned
            if len(state["transcripts"]) > 2000:
                keep = sorted(state["transcripts"].items(), key=lambda kv: kv[1].get("mtime_ns", 0), reverse=True)[:1500]
                state["transcripts"] = dict(keep)
            B.atomic_write(DREAM_STATE, json.dumps(state, indent=1, ensure_ascii=False) + "\n")
        return summary
    finally:
        release_lock()


def launchd_plist_dict(interval=1800, min_idle=180):
    py = sys.executable or "/usr/bin/python3"
    return {
        "Label": PLIST_LABEL,
        "ProgramArguments": [
            py, "-I", os.path.join(B.TOOLS, "brain_dream.py"),
            "--if-idle", "--min-idle", str(int(min_idle)),  # v6: maps bridges only; weaving into notes needs the owner (--apply-links by hand)
        ],
        "WorkingDirectory": B.ROOT,
        "StartInterval": int(interval),
        "RunAtLoad": False,
        "Nice": 15,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": DREAM_LOG,
        "StandardErrorPath": DREAM_LOG,
    }


def install_launchd(interval=1800, min_idle=180):
    os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(DREAM_LOG), exist_ok=True)
    data = launchd_plist_dict(interval=interval, min_idle=min_idle)
    with open(PLIST_PATH, "wb") as fh:
        plistlib.dump(data, fh)
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", PLIST_PATH], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", PLIST_PATH], capture_output=True, text=True)
    return {"installed": True, "plist": PLIST_PATH, "interval_s": interval, "bootstrap_rc": r.returncode,
            "note": (r.stderr or "loaded cleanly").strip()}


def uninstall_launchd():
    uid = os.getuid()
    if os.path.exists(PLIST_PATH):
        subprocess.run(["launchctl", "bootout", f"gui/{uid}", PLIST_PATH], capture_output=True)
        trash = os.path.join(B.ROOT, "_to_delete", "launchd")
        os.makedirs(trash, exist_ok=True)
        shutil.move(PLIST_PATH, os.path.join(trash, f"{B.today()}-{os.path.basename(PLIST_PATH)}"))
        return {"uninstalled": True, "moved_to": B.rel(os.path.join(trash, f"{B.today()}-{os.path.basename(PLIST_PATH)}"))}
    return {"uninstalled": False, "reason": "plist not installed"}


def status():
    st = B.load_json(DREAM_STATE, {})
    last = B.load_json(DREAM_LAST, {})
    idle = hid_idle_seconds()
    try:
        load1 = round(os.getloadavg()[0], 2)
    except OSError:
        load1 = None
    return {
        "cycles": st.get("cycles", 0),
        "tracked_transcripts": len(st.get("transcripts", {})),
        "last_dream": st.get("last_dream"),
        "lock_held": os.path.exists(DREAM_LOCK),
        "launchd_installed": os.path.exists(PLIST_PATH),
        "launchd_plist": PLIST_PATH,
        "idle_s": idle,
        "load_1m": load1,
        "last_summary": {k: last.get(k) for k in ("status", "mode", "finished", "seconds", "graph", "lint", "synonyms") if last} or None,
    }


def main():
    ap = argparse.ArgumentParser(description="Hydro Brain 2 lightweight background dreaming self-improvement layer.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="Run one incremental dream cycle now")
    mode.add_argument("--if-idle", action="store_true", help="Run one cycle only if user HID is idle and CPU load is low")
    mode.add_argument("--daemon", action="store_true", help="Run continuously at low priority, waking only on idle intervals")
    mode.add_argument("--status", action="store_true", help="Print dreaming status and metrics")
    mode.add_argument("--install-launchd", action="store_true", help="Install macOS LaunchAgent for gentle background dreaming")
    mode.add_argument("--uninstall-launchd", action="store_true", help="Unload and move LaunchAgent plist to _to_delete/")

    ap.add_argument("--min-idle", type=float, default=180.0)
    ap.add_argument("--max-load", type=float, default=None)
    ap.add_argument("--interval", type=int, default=900, help="Daemon / launchd check interval in seconds")
    ap.add_argument("--max-transcripts", type=int, default=12)
    ap.add_argument("--max-sessions", type=int, default=12)
    ap.add_argument("--max-links", type=int, default=20)
    ap.add_argument("--apply-links", action="store_true", help="Weave verified missing-node links into non-private notes")
    ap.add_argument("--apply-tuning", action="store_true", help="Run ratchet-gated synonym experiment check")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--transcript-roots", nargs="*", help="Override transcript scan directories")
    a = ap.parse_args()

    if a.status:
        print(json.dumps(status(), indent=1, ensure_ascii=False))
        return 0
    if a.install_launchd:
        print(json.dumps(install_launchd(interval=max(300, a.interval), min_idle=a.min_idle), indent=1))
        return 0
    if a.uninstall_launchd:
        print(json.dumps(uninstall_launchd(), indent=1))
        return 0
    if a.daemon:
        signal.signal(signal.SIGTERM, _handle_sig)
        signal.signal(signal.SIGINT, _handle_sig)
        while not _STOP_DAEMON:
            res = run_cycle(
                check_idle=not a.force,
                check_load=not a.force,
                min_idle=a.min_idle,
                max_load=a.max_load,
                max_transcripts=a.max_transcripts,
                max_sessions=a.max_sessions,
                max_links=a.max_links,
                apply_links=a.apply_links,
                apply_tuning=a.apply_tuning,
                dry_run=a.dry_run,
                force=a.force,
                transcript_roots=a.transcript_roots,
            )
            print(json.dumps(res, ensure_ascii=False), flush=True)
            for _ in range(max(10, a.interval)):
                if _STOP_DAEMON:
                    break
                time.sleep(1)
        return 0

    res = run_cycle(
        check_idle=a.if_idle,
        check_load=a.if_idle or (a.max_load is not None),
        min_idle=a.min_idle,
        max_load=a.max_load,
        max_transcripts=a.max_transcripts,
        max_sessions=a.max_sessions,
        max_links=a.max_links,
        apply_links=a.apply_links,
        apply_tuning=a.apply_tuning,
        dry_run=a.dry_run,
        force=a.force,
        transcript_roots=a.transcript_roots,
    )
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
