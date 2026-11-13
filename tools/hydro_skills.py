"""
hydro_skills.py — unified skill-calling, domain-family, synonym, and telemetry engine for HYDRO BRAIN.

Single source of truth for brain_route.py, brain_hooks.py, and brain_mcp.py:
- Keeps 2-char domain terms (ui, ux, 3d, 2d, cv, js, ts, gl, ar, vr, ai, ds) and dot-js tokens (p5.js -> p5js, three.js -> threejs).
- Filters Brain-meta GENERIC chatter + conversational noise so casual prompts never misfire.
- Matches exact tokens + clean plurals + multi-word accidental-hit guard (no naive stem prefix collisions like close -> closed).
- Uses full logarithmic rarity (bounded floor >= 1.35 for domain heads) + surgical family affinity + scope floor + telemetry.
"""
import math
import os
import re

import brainlib as B

SHORT_DOMAIN = frozenset({"ui", "ux", "3d", "2d", "cv", "js", "ts", "gl", "ar", "vr", "ai", "ds"})

CONVERSATIONAL_NOISE_RX = re.compile(
    r"\b(?:good\s+job|great\s+job|nice\s+job|yes\s+go\s+ahead|go\s+ahead|that\s+looks\s+good|"
    r"looks\s+good|summarize\s+what\s+we\s+decided|close\s+(?:the\s+)?(?:current\s+)?(?:brain\s+)?session|"
    r"explain\s+your\s+previous\s+answer|read\s+handoff|tell\s+me\s+what\s+is\s+the\s+final|"
    r"pause\s+here(?:\s+until\s+tomorrow)?|thank\s+you|thanks\s+a\s+lot)\b",
    re.I,
)

SKILL_CREATE_RX = re.compile(r"\b(?:write|create|author|make|build|draft)\s+(?:a\s+)?(?:new\s+)?skill\b", re.I)

GENERIC = frozenset(
    "system systems session sessions agent agents work works working everything thing things need "
    "want like help just whole functional functionality ready must mistake claude codex brain new now each start show tell "
    "know good better best look looks find give take see time way part parts use used done sure right also really please make "
    "made create let lets get got able there here what which when where why how who whom whose yes not okay fine thanks "
    "wire wired layer layers paper information useless status explain changed change changes continue left fail failed "
    "final order commit confirm understand purpose exist exists perfectly demand first refining plan analyzed analyse analyze "
    "again shorter longer previous answer question today tomorrow until pause current hello read nothing flood decided ahead".split()
)

STOP = GENERIC | frozenset(
    "the a an and or for to of in on with is are be this that it as by at from into "
    "my your our their we you i me us was were been will would can could should may "
    "do does did have has had all each more some any every all both either neither old one two three task tasks "
    "about than then too very out up over under "
    "und oder der die das ein eine mit für von zu im ist sind auf".split()
)

# v7.1 (the owner's labels, 2026-11-14): "tokens" in his messages means AI usage ("each session eats tons of tokens"), and it
# pulled design-token skills into 3 of 18 labelled requests and into the holdout's "how many tokens did we use". The word
# counts toward skills only next to a design word.
DESIGN_CONTEXT = frozenset("design designs designer color colors colour colours palette palettes spacing typography type font fonts "
                           "figma css scss theme themes ui ux tailwind brand branding style styles variables radius shadow".split())
WEAK_SINGLE = frozenset(
    "file report md handoff close open fix run test tests check checks add update remove change "
    "text red blue green dark light fast small big".split()
)

DEFAULTS = {
    "skill_threshold": 8.0,
    "note_threshold": 9.0,
    "off_factor": 1.15,
    "rel_cut": 0.48,
    "len_norm": 9,
    "len_cap": 1.45,
    "route_min_overlap": 2,
    "family_weight": 1.0,
    "telemetry_weight": 1.0,
}

# Runtime override populated transiently by gym.py / autoresearch sweeps (never mutates disk by itself).
CFG_OVERRIDE = {}
_JSON_CACHE = {}
_PREP_CACHE = {}


def _load_json_cached(path, default):
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return default
    hit = _JSON_CACHE.get(path)
    if hit and hit[0] == key:
        return hit[1]
    data = B.load_json(path, default)
    _JSON_CACHE[path] = (key, data)
    return data


def load_config():
    raw = _load_json_cached(os.path.join(B.STATE, "harness-config.json"), {})
    cfg = dict(DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS})
    for k, v in CFG_OVERRIDE.items():
        if k in cfg:
            cfg[k] = v
    return cfg


def _norm_tok(w):
    w = w.strip(".-").lower()
    if w.endswith(".js") and len(w) > 3:
        w = w[:-3] + "js"
    return w


def tokenize(text, limit=32, strip_noise=True):
    clean = CONVERSATIONAL_NOISE_RX.sub(" ", text) if strip_noise else text
    extra = ["skill-creator"] if (strip_noise and SKILL_CREATE_RX.search(text)) else []
    words = re.findall(r"[\w][\w\-\.]*|\.[a-z0-9]{2,5}\b", clean.lower(), flags=re.U)
    out = list(extra)
    for raw in words:
        w = _norm_tok(raw)
        if not w or w in STOP or w.isdigit():
            continue
        if len(w) < 3 and w not in SHORT_DOMAIN:
            continue
        if w not in out:
            out.append(w)
    return out[:limit]


def doc_tokens(text):
    normed = re.sub(r"\b([a-z0-9]+)\.js\b", r"\1js", text.lower())
    words = re.findall(r"[a-z0-9+#]+", normed)
    return {w for w in words if len(w) >= 3 or w in SHORT_DOMAIN}


def expand(toks, limit=48):
    """Return (base_tokens, expanded_tokens) preserving order using state/synonyms.json."""
    syn = _load_json_cached(os.path.join(B.STATE, "synonyms.json"), {})
    base = list(toks)
    out = list(base)
    seen = set(out)
    for t in base:
        candidates = syn.get(t, [])
        if not candidates and t.endswith("s") and len(t) > 3:
            candidates = syn.get(t[:-1], [])
        for x in candidates:
            for w in tokenize(x, limit=6, strip_noise=False):
                if w not in seen:
                    out.append(w)
                    seen.add(w)
                if len(out) >= limit:
                    return base, out
    return base, out


def variants(qtok):
    """The plural forms v4 already matched, in one place for the index lookup and for token_match. Whole words only.
    v6 note: a verb <-> -ing rule (rig <-> rigging) was built and withdrawn the same day: on the owner's 63 real requests it
    changed the offered skills for 32, and with no labels nobody could say for better or worse (tools/route_real.py)."""
    out = []
    n = len(qtok)
    if n >= 3:
        out += [qtok + "s", qtok + "es"]
        if qtok.endswith("s") and n >= 4:
            out.append(qtok[:-1])
        if qtok.endswith("es") and n >= 5:
            out.append(qtok[:-2])
    return out


def token_match(qtok, dtoks):
    """Safe exact + clean plural/extension match without partial prefix collisions."""
    if qtok in dtoks:
        return True
    if any(v in dtoks for v in variants(qtok)):
        return True
    if "-" in qtok:
        parts = [p for p in qtok.split("-") if p and p not in STOP]
        if parts and all(p in dtoks for p in parts):
            return True
    if len(qtok) >= 3:
        if (qtok + "s") in dtoks or (qtok + "es") in dtoks:
            return True
        if qtok.endswith("s") and len(qtok) >= 4 and qtok[:-1] in dtoks:
            return True
        if qtok.endswith("es") and len(qtok) >= 5 and qtok[:-2] in dtoks:
            return True
    return False


def detect_families(base_tokens, scope="general"):
    data = _load_json_cached(os.path.join(B.STATE, "skill-families.json"), {}).get("families", {})
    tokset = set(base_tokens)
    matched = []
    skill_bonus = {}
    floor = []
    for fid, fam in data.items():
        trigs = set(fam.get("triggers", []))
        hits = sum(1 for t in tokset if token_match(t, trigs))
        scope_match = scope in fam.get("scopes", [])
        # Surgical gating: family activates strongly only on >=2 triggers or explicit scope lock
        if hits >= 2 or scope_match:
            matched.append((fid, hits + (2 if scope_match else 0)))
            for s in fam.get("skills", []):
                skill_bonus[s] = max(skill_bonus.get(s, 0.0), 1.6 + min(hits, 4) * 0.45)
            for fs in fam.get("floor", []):
                if fs not in floor:
                    floor.append(fs)
    matched.sort(key=lambda x: -x[1])
    return [m[0] for m in matched], skill_bonus, floor


def load_telemetry_boost():
    tel = _load_json_cached(os.path.join(B.STATE, "skill-telemetry.json"), {}).get("skills", {})
    boosts = {}
    for name, info in tel.items():
        used = info.get("used", 0)
        shown = info.get("shown", 0)
        if used > 0:
            boosts[name] = round(min(1.5, 0.35 * math.log1p(used)), 3)
        elif shown >= 6 and used == 0:
            boosts[name] = -0.4
    return boosts


def rank_skills(query_text, rows, who="claude", scope="general", n=6, threshold=None, cfg=None,
                strict_agent=False, include_drives=True):
    """
    Unified scorer for skill rows: (name, description, location, agent, kind, autoload).
    Returns list of dicts sorted best-first.
    """
    cfg = cfg or load_config()
    base = tokenize(query_text, limit=32, strip_noise=True)
    if any(w in ("token", "tokens") for w in base) and not (set(base) & DESIGN_CONTEXT):
        base = [w for w in base if w not in ("token", "tokens")]
    if not base:
        return []
    _, q_exp = expand(base, limit=48)
    fam_ids, fam_bonus, floor = detect_families(base, scope=scope)
    tel_boost = load_telemetry_boost()
    q_norm = re.sub(r"\s+", " ", query_text.lower()).strip()

    substantive = [t for t in base if t not in WEAK_SINGLE]
    if not substantive and not fam_ids and "-" not in query_text:
        return []

    thin = len(substantive) <= 2
    who_l = str(who).lower()
    prep_key = None
    if len(rows) >= 40:
        prep_key = (who_l, strict_agent, include_drives, hash(tuple(tuple(r[:6]) for r in rows)))
        cached_docs = _PREP_CACHE.get(prep_key)
    else:
        cached_docs = None
    if cached_docs is not None:
        docs, postings_exact, v1_indices = cached_docs
    else:
        docs = []
        postings_exact = {}
        v1_indices = set()
        for row in rows:
            name, desc, loc, ag, kind, auto = row[:6]
            ag_s = str(ag or "")
            auto_s = str(auto or "")
            is_drive = auto_s.startswith("no: on drive") or str(kind).startswith("drive-")
            if not include_drives and (is_drive or "not installed" in ag_s):
                continue
            if strict_agent and who_l not in ag_s.lower():
                continue
            short_tmp = re.sub(r"[\s_]+", "-", name.split(":", 1)[-1].lower())
            tier = 0 if kind == "brain-library" else (2 if auto_s.startswith(("no (off)", "no (switched off", "no: on drive")) else 1)
            ntoks = doc_tokens(name.replace("-", " ").replace(":", " "))
            btoks = doc_tokens(desc or "")
            full_t = ntoks | btoks
            idx = len(docs)
            docs.append((name, ntoks, full_t, desc or "", loc, kind, tier, ag_s, auto_s, short_tmp, short_tmp.replace("-", " ")))
            for tok in full_t:
                postings_exact.setdefault(tok, []).append(idx)
            if short_tmp.endswith(("-v1", "-v2-experimental")):
                v1_indices.add(idx)
        postings_exact = {k: frozenset(v) for k, v in postings_exact.items()}
        v1_indices = frozenset(v1_indices)
        if prep_key is not None:
            if len(_PREP_CACHE) > 8:
                _PREP_CACHE.clear()
            _PREP_CACHE[prep_key] = (docs, postings_exact, v1_indices)

    excl_v1 = {i for i in v1_indices if docs[i][9] not in q_norm} if v1_indices else set()
    EMPTY_FS = frozenset()

    def _matched_docs(qtok):
        s = set(postings_exact.get(qtok, EMPTY_FS))
        if "-" in qtok:
            parts = [p for p in qtok.split("-") if p and p not in STOP]
            if parts:
                part_sets = [postings_exact.get(p) for p in parts]
                if all(part_sets):
                    inter = set(part_sets[0])
                    for ps in part_sets[1:]:
                        inter &= ps
                    s |= inter
        for v in variants(qtok):  # v6: one list of inflections for the index lookup and for token_match
            s |= postings_exact.get(v, EMPTY_FS)
        if excl_v1:
            s -= excl_v1
        return s

    N = (len(docs) - len(excl_v1)) or 1
    base_set = set(base)
    idf = {}
    cand_indices = set()
    for w in q_exp:
        mset = _matched_docs(w)
        cand_indices |= mset
        df = len(mset)
        raw_idf = math.log((N + 1.0) / (1.0 + df))
        # Preserve high IDF for rare specialist terms while flooring core domain headwords >= 1.35
        w_idf = max(1.35, raw_idf)
        if w not in base_set:
            w_idf *= 0.68
        idf[w] = w_idf

    base_T = cfg["skill_threshold"] if threshold is None else float(threshold)
    if N < 50 and threshold is None:
        base_T = min(base_T, max(2.2, 1.5 * math.log(N + 1)))
    ratio = max(0.0, len(base) - cfg["len_norm"]) / max(1.0, float(cfg["len_norm"]))
    scale = min(float(cfg.get("len_cap", 1.45)), 1.0 + 0.35 * ratio)
    T = base_T * scale
    min_ov = int(cfg.get("route_min_overlap", 2))

    best_by_name = {}
    for idx in sorted(cand_indices):
        name, name_t, full_t, desc, loc, kind, tier, ag_s, auto_s, short, name_slug = docs[idx]
        exact_name = (
            (short in base_set)
            or (short in q_norm)
            or (name_slug in q_norm and len(name_slug) >= 4)
        )

        found_q = [w for w in q_exp if token_match(w, full_t)]
        found_base = [w for w in base if token_match(w, full_t)]
        found_sub = [w for w in found_base if w not in WEAK_SINGLE]
        if not found_q:
            continue

        # Compute max IDF matched by original query words so rare exact technical concepts
        # (p5js, remotion, wcag, mcp, fillet, step, threejs, figma) aren't choked by min_ov=2
        max_hit_idf = max((idf.get(w, 0.0) for w in found_base), default=0.0)
        fam_b = fam_bonus.get(short, 0.0)
        name_words = [p for p in short.split("-") if p]

        # Guard against single weak generic word accidentally hitting multi-word skill names
        if (
            threshold is None
            and not exact_name
            and fam_b == 0.0
            and max_hit_idf < 4.5
            and len(found_sub) < min_ov
            and len(substantive) >= 2
            and len(name_words) >= 2
        ):
            if len(found_q) < min_ov + 1:
                continue

        if threshold is None and not exact_name and fam_b == 0.0 and len(found_base) == 1 and max_hit_idf < 4.3:
            if found_base[0] in WEAK_SINGLE:
                continue

        # v6 evidence gate: a message with one or two content words (an acknowledgement, a question about the
        # session, a pointer like "that one") is usually talk, not a task. It may call a skill only on real evidence: two of its words hit
        # the skill and one of them is in the skill's NAME, or a rare word hits the name and nothing else in the
        # message points elsewhere. A description that happens to share one word is not evidence.
        if thin and threshold is None and fam_b == 0.0 and not (exact_name and "-" in short):
            name_hits = [w for w in found_sub if token_match(w, name_t)]
            strong = len(found_sub) >= 2 and name_hits
            rare = name_hits and max_hit_idf >= 4.5 and len(found_sub) == len(substantive)
            if not (strong or rare):
                continue

        raw_score = 0.0
        for w in found_q:
            mult = 2.0 if token_match(w, name_t) else 1.0
            raw_score += idf[w] * mult
        # Extra precision bump when a candidate's own name words account for >=2 distinct query hits
        name_base_hits = sum(1 for w in found_base if token_match(w, name_t))
        if name_base_hits >= 2:
            raw_score += 2.2
        if exact_name:
            raw_score += 4.0
        if tier == 0:
            raw_score += 0.8
        raw_score += fam_b * float(cfg.get("family_weight", 1.0)) + tel_boost.get(short, 0.0) * float(cfg.get("telemetry_weight", 1.0))
        if who_l in ag_s.lower():
            raw_score += 0.15
        if not auto_s.startswith("no: on drive"):
            raw_score += 0.25

        need = T * (cfg["off_factor"] if tier == 2 else 1.0)
        if raw_score < need:
            continue

        item = {
            "name": name,
            "short": short,
            "description": desc[:140],
            "where": str(loc).replace(os.path.expanduser("~"), "~"),
            "kind": kind,
            "autoload": auto_s,
            "tier": tier,
            "score": round(raw_score, 2),
            "overlap": len(found_base),
            "why": f"hits={found_base[:5]}" + (f" fam={round(fam_b, 2)}" if fam_b else ""),
        }
        prev = best_by_name.get(short)
        rank_key = (item["score"] + (0.6 if item["tier"] == 0 else 0.0), 1 if item["name"].lower() == short else 0)
        prev_key = (prev["score"] + (0.6 if prev["tier"] == 0 else 0.0), 1 if prev["name"].lower() == short else 0) if prev else (-1, -1)
        if prev is None or rank_key > prev_key:
            best_by_name[short] = item

    # Explicit scope skill floor: guarantees canonical skills for brand/website scopes aren't dropped
    if floor and scope in ("brand", "website", "cv_official"):
        floor_rows = {}
        for row in rows:
            nm = re.sub(r"[\s_]+", "-", row[0].split(":", 1)[-1].lower())
            if nm in floor and row[4] == "brain-library" and nm not in best_by_name:
                floor_rows[nm] = row
        for fnm in floor[:3]:
            if len(best_by_name) >= n:
                break
            if fnm in floor_rows:
                r = floor_rows[fnm]
                best_by_name[fnm] = {
                    "name": r[0],
                    "short": fnm,
                    "description": (r[1] or "")[:140],
                    "where": str(r[2]).replace(os.path.expanduser("~"), "~"),
                    "kind": r[4],
                    "tier": 0,
                    "score": round(T + 0.1, 2),
                    "overlap": 1,
                }

    ranked = sorted(best_by_name.values(), key=lambda x: (-x["score"], x["tier"], x["name"]))
    if not ranked:
        return []
    cut = max(ranked[0]["score"] * float(cfg.get("rel_cut", 0.48)), base_T * 0.7)
    # Soften rel_cut slightly on multi-intent prompts ("find jobs in Lisbon for a CAD designer")
    if len(base) >= 4:
        cut = min(cut, max(ranked[0]["score"] * 0.36, base_T * 0.75))
    return [r for r in ranked if r["score"] >= cut][:n]
