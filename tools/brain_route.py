#!/usr/bin/env python3
"""
brain_route.py — find the right notes and skills for a task, inside the task's scope (layers 3 + 4).

    python3 -I brain_route.py --query "quarterly invoice reconciliation export" [--scope engineering] [--limit 8]
    python3 -I brain_route.py --session <id>      # reads the session contract (title, request, requirements, scope)

Returns card headers only (title, path, collection, summary) plus matching skills, within a budget.
"No match" is a valid answer. Personal notes (Brain System/self) are returned only for scopes that allow them.
The index is rebuilt first if it is older than the vault (database only: a lookup never rewrites the 00-toc pages;
BRAIN_ROUTE_READONLY=1 skips the rebuild whenever an index exists).
v2.1 "Ironclad": --novelty explore (from the contract's `novelty:`) drops exemplars (episodes, history) and puts
constraints first; --budget caps the answer (default 2,500 tokens, a quarter reserved for constraints);
state/synonyms.json widens the query (resume -> cv ...); an exact skill-name match ranks first; an installed copy
ranks above a copy on an external drive.
"""
import argparse, json, os, re, sqlite3, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402
import hydro_skills as HS  # noqa: E402

STOP = HS.STOP | {"old", "one", "two", "three", "task", "tasks", "over", "via", "per", "vs"}


def tokens(text, limit=32):
    return HS.tokenize(text, limit=limit, strip_noise=True)


EXEMPLAR_TYPES = {"episode", "history", "exemplar", "learning"}
CONSTRAINT_TYPES = {"rules", "decision", "decisions", "constraint", "exclusion", "system", "procedure", "lesson"}
MAX_EXEMPLARS = 2  # v3 (C2): past sessions are examples; they may not crowd out knowledge cards


def expand(toks):
    """Add synonyms from state/synonyms.json keeping short domain terms (ui, ux, 3d, ...)."""
    _, out = HS.expand(toks, limit=48)
    return out


def est_tokens(text):
    return len(text) // 4 + 1


def fts_query(toks):
    return " OR ".join('"' + t.replace('"', "") + '"' for t in toks)


CONTINUATION_RX = re.compile(
    r"\b(?:bring\s+up\s+(?:the\s+)?last|last\s+session|pick\s+up\s+where|continue(?:\s+from)?|same\s+project|next\s+round)\b",
    re.I,
)


def _continuation_context(sid, cwd, project):
    """If this session continues recent work, pull title + scope hints from the prior session in same project/cwd."""
    best = None
    try:
        entries = sorted((e for e in os.listdir(B.SESSIONS) if e != sid), reverse=True)
    except OSError:
        return "", None
    for other in entries[:25]:
        om = B.load_json(os.path.join(B.SESSIONS, other, "meta.json"), {})
        if not isinstance(om, dict):
            continue
        if (project and om.get("project") == project) or (cwd and om.get("cwd") == cwd):
            best = om
            break
    if not best:
        return "", None
    hint = f"{best.get('title', '')} {best.get('project', '')}".strip()
    sc = best.get("scope_class")
    return hint, sc


def contract_text(sid):
    d = os.path.join(B.SESSIONS, sid)
    meta = B.load_json(os.path.join(d, "meta.json"), {})
    try:
        c = open(os.path.join(d, "contract.md"), encoding="utf-8").read()
    except OSError:
        sys.exit(f"no contract for session {sid}")
    fm, body = B.split_frontmatter(c)
    # Priority order: title -> deliverables -> hard requirements -> verbatim request
    # so concise structural nouns aren't crowded out by long prose or color adjectives.
    keep = [meta.get("title", "")]
    for name in ("Deliverables", "Hard requirements", "Request (verbatim)"):
        m = re.search(r"^## " + re.escape(name) + r"[^\n]*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
        if m:
            keep.append(re.sub(r"<[^>]+>", " ", m.group(1)))
    fmd = B.parse_frontmatter(fm) if fm else {}
    scope = str(fmd.get("scope_class") or meta.get("scope_class") or "general").split()[0]
    novelty = str(fmd.get("novelty") or "reuse").split()[0]
    project = str(fmd.get("project") or meta.get("project") or "")
    text = " ".join(p for p in keep if p).strip()
    if CONTINUATION_RX.search(text) or len(tokens(text)) < 3:
        prev_hint, prev_scope = _continuation_context(sid, meta.get("cwd"), project)
        if prev_hint:
            text = (text + " " + prev_hint).strip()
        if scope == "general" and prev_scope in B.SCOPES:
            scope = prev_scope
    return text, scope, novelty


def overlap(toks, text):
    """How many query terms occur in the text (whole word or shared 6-letter stem)."""
    words = set(re.findall(r"[\w]+", text.lower(), flags=re.U))
    n = 0
    for t in toks:
        t = t.lower()
        if t in words or (len(t) > 4 and any(w.startswith(t[:6]) for w in words)):
            n += 1
    return n


def ensure_index():
    """Missing, stale or unreadable (old schema, corrupt) index → rebuild before routing (entry matrix case)."""
    ok = os.path.exists(B.INDEX_DB) and os.path.getmtime(B.INDEX_DB) >= B.vault_max_mtime()
    if ok:
        try:
            con = sqlite3.connect(B.INDEX_DB)
            con.execute("SELECT name, kind, autoload FROM skills LIMIT 1").fetchall()
            con.execute("SELECT title, path, collection, sub, summary, headings, tags, aliases, excerpt FROM notes LIMIT 1").fetchall()
            con.close()
        except sqlite3.DatabaseError:
            ok = False
            try:
                os.replace(B.INDEX_DB, B.INDEX_DB + ".broken")
            except OSError:
                pass
    if not ok:
        if os.environ.get("BRAIN_ROUTE_READONLY") == "1" and os.path.exists(B.INDEX_DB):
            return  # proposal from Codex session 33eb: hooks and judges route read-only
        import brain_index
        try:
            brain_index.build(toc=False, timeout_s=20)  # v2.1 (O11): database only, under the index lock
        except B.LockBusy:
            if not os.path.exists(B.INDEX_DB):
                raise


def route(query, scope, limit=8, skill_limit=6, novelty="reuse", budget=2500):
    ensure_index()
    base = tokens(query)
    toks = expand(base)
    res = {"query": query, "scope": scope, "allowed": B.SCOPES.get(scope, B.SCOPES["general"]), "notes": [], "skills": [],
           "novelty": novelty, "budget_tokens": budget}
    if not toks:
        return res
    con = sqlite3.connect(B.INDEX_DB)
    q = fts_query(toks)
    rows = con.execute("SELECT title, path, collection, sub, summary, headings, tags, aliases, excerpt, "
                       "bm25(notes, 10.0, 4.0, 3.0, 3.0, 3.0, 1.0) AS s "
                       "FROM notes WHERE notes MATCH ? ORDER BY s LIMIT 200", (q,)).fetchall()
    cfg = HS.load_config()
    need = min(int(cfg.get("route_min_overlap", 2)), len(base))  # layer 4: never forced by one shared word
    types = {}
    try:
        types = dict(con.execute("SELECT path, type FROM notes").fetchall())
    except sqlite3.DatabaseError:
        pass
    cands = []
    for title, path, col, sub, summary, heads, tags, aliases, excerpt, score in rows:
        if col == "00-toc" or not B.allowed(col, sub, scope):
            continue
        if overlap(toks, " ".join(x or "" for x in (title, path, summary, heads, tags, aliases, excerpt))) < need:
            continue
        if col == "lessons" and not B.lesson_visible(path, scope):
            continue  # v3 (C1): only lessons the owner released; private-session lessons only in private scopes
        ntype = (types.get(path) or "").lower()
        if ntype == "log":
            continue  # v6: machine journals (dream journal, reflections, graph map) are records, never retrieval answers
        if novelty == "explore" and ntype in EXEMPLAR_TYPES:
            continue  # layer 4: exploring a new design, past examples would anchor it
        cands.append({"title": title, "path": path, "collection": f"{col}/{sub}" if sub else col, "type": ntype,
                      "summary": (summary or "")[:160], "score": round(-score, 2), "constraint": ntype in CONSTRAINT_TYPES})
    # layer 4 budget: a quarter is reserved for constraint cards; other cards may not eat into what is still reserved
    reserve = budget // 4 if any(c["constraint"] for c in cands) else 0
    spent = c_spent = 0
    ordered = [c for c in cands if c["constraint"]] + [c for c in cands if not c["constraint"]] if novelty == "explore" else cands
    exemplars = 0
    for c in ordered:
        if c["type"] in EXEMPLAR_TYPES:
            exemplars += 1
            if exemplars > MAX_EXEMPLARS:
                continue
        cost = est_tokens(c["title"] + c["path"] + c["summary"]) + 8
        room = budget - spent - (0 if c["constraint"] else max(0, reserve - c_spent))
        if cost > room:
            continue
        res["notes"].append(c)
        spent += cost
        c_spent += cost if c["constraint"] else 0
        if len(res["notes"]) >= limit:
            break
    res["spent_tokens"] = spent
    if skill_limit <= 0:
        con.close()
        return res
    all_skills = con.execute("SELECT name, description, location, agent, kind, autoload FROM skills").fetchall()
    ranked = HS.rank_skills(query, all_skills, who="claude", scope=scope, n=skill_limit * 2)
    # Build lookup by (name, where) to recover exact agent/kind/loads_at_start metadata
    meta_by_loc = {}
    for sname, sdesc, sloc, sagent, skind, sauto in all_skills:
        w = str(sloc).replace(os.path.expanduser("~"), "~")
        meta_by_loc[(sname, w)] = (sagent, skind, sauto)
    seen = set()
    for s in ranked:
        name = s["name"]
        name_k = name.lower().split(":", 1)[-1]
        if name.lower() in seen or name_k in seen:
            continue
        seen.update((name_k, name.lower()))
        sagent, skind, sauto = meta_by_loc.get((name, s["where"]), ("claude, codex", s.get("kind", "brain-library"), "no"))
        res["skills"].append({
            "name": name,
            "description": s["description"][:140],
            "where": s["where"],
            "agent": sagent,
            "kind": skind,
            "loads_at_start": sauto,
            "score": s["score"],
        })
        if len(res["skills"]) >= skill_limit:
            break
    con.close()
    return res


def for_session(sid, limit=8):
    """v3 (B1): step 2 as a function. Routes from the session's contract, writes sessions/<id>/retrieval-NN.md and
    returns the result, so `brain_session.py new --request` and `lint` run it without a second command."""
    query, scope, novelty = contract_text(sid)
    scope = scope if scope in B.SCOPES else "general"
    r = route(query, scope, limit, novelty=novelty if novelty in ("reuse", "explore") else "reuse")
    d = os.path.join(B.SESSIONS, sid)
    n = len([f for f in os.listdir(d) if f.startswith("retrieval-") and f.endswith(".md")]) + 1
    B.atomic_write(os.path.join(d, f"retrieval-{n:02d}.md"), render(r) + "\n", exclusive=True)
    r["file"] = f"sessions/{sid}/retrieval-{n:02d}.md"
    return r


def render(r):
    lines = [f"# Route — scope `{r['scope']}` (allowed: {', '.join(r['allowed'])})", f"Query terms from: {r['query'][:160]!r}", ""]
    if r["notes"]:
        lines.append("## Notes (read the header; open only if it applies; cite path:line)")
        for i, n in enumerate(r["notes"], 1):
            lines.append(f"{i}. **{n['title']}** — `{n['path']}` · {n['collection']}" + (f"\n   {n['summary']}" if n["summary"] else ""))
    if r["skills"]:
        lines += ["", "## Skills"]
        lines += [f"- **{s['name']}** ({s['agent']}; loads at start: {s['loads_at_start']}) — {s['description']} · `{s['where']}`" for s in r["skills"]]
    if not r["notes"] and not r["skills"]:
        lines.append("**No match.** Plan from first principles and record the gap in the Brain Summary.")
    elif not r["notes"]:
        lines.append("\nNo brain notes match inside this scope; only skills were found.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query")
    ap.add_argument("--session")
    ap.add_argument("--scope")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--novelty", choices=["reuse", "explore"])
    ap.add_argument("--budget", type=int, default=2500)
    ap.add_argument("--skills-only", action="store_true", help="Output only matched skills (faster concise skill lookup)")
    a = ap.parse_args()
    if not a.query and not a.session:
        ap.error("give --query or --session")
    query, scope, novelty = (a.query or ""), (a.scope or "general"), (a.novelty or "reuse")
    if a.session:
        q2, s2, n2 = contract_text(a.session)
        query = (query + " " + q2).strip()
        scope = a.scope or s2
        novelty = a.novelty or n2
    if scope not in B.SCOPES:
        scope = "general"
    r = route(query, scope, a.limit, novelty=novelty if novelty in ("reuse", "explore") else "reuse", budget=a.budget)
    if a.skills_only:
        r_view = {"query": r["query"], "scope": r["scope"], "notes": [], "skills": r["skills"]}
        text = json.dumps(r_view, ensure_ascii=False, indent=1) if a.json else render(r_view)
    else:
        text = json.dumps(r, ensure_ascii=False, indent=1) if a.json else render(r)
    if a.session:
        n = len([f for f in os.listdir(os.path.join(B.SESSIONS, a.session)) if f.startswith("retrieval-") and f.endswith(".md")]) + 1
        B.atomic_write(os.path.join(B.SESSIONS, a.session, f"retrieval-{n:02d}.md"), render(r) + "\n", exclusive=True)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
