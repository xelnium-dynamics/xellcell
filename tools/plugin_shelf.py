#!/usr/bin/env python3
"""
plugin_shelf.py — plugins live in the brain, not in every session's start-up (v2.1, the owner 2026-11-09).

    python3 -I plugin_shelf.py list [--json]          every plugin: surface, on/off, skills in the brain, how to activate
    python3 -I plugin_shelf.py find "<task words>"     which shelved plugin fits a task (name + description + skill names)
    python3 -I plugin_shelf.py activate <name>         switch one plugin on for the NEXT session (backup first)
    python3 -I plugin_shelf.py deactivate <name>       switch it off again (backup first)
    python3 -I plugin_shelf.py verify                  every plugin that is off still has its skills in the brain (exit 1 if not)

The rule: a plugin that is not needed in most sessions is OFF at start. Its skills stay readable in the brain
(skills/plugins/<name>/, found by brain_route.py and the prompt hook). When a task needs the plugin's own TOOLS
(an MCP server, commands), the agent activates it:
- Claude Code local plugin  → ~/.claude/settings.json enabledPlugins (effective in the next session)
- Codex plugin              → ~/.codex/config.toml [plugins."<name>@<market>"] enabled (next Codex session)
- claude.ai account plugin  → cannot be switched by a file: in the Claude desktop app the agent calls its
                              SuggestPluginInstall tool with the plugin id (the owner clicks Add), or the owner turns it on in
                              Customize → Plugins. The status shown here comes from the app's own plugin-list cache.
Every switch writes a timestamped backup to state/backups/<date>/plugin-shelf/ and a line to state/plugin-shelf.log.
"""
import argparse, glob, json, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

HOME = os.path.expanduser("~")
CLAUDE_SETTINGS = os.environ.get("BRAIN_CLAUDE_SETTINGS") or os.path.join(HOME, ".claude", "settings.json")
CLAUDE_INSTALLED = os.path.join(HOME, ".claude", "plugins", "installed_plugins.json")
CODEX_CONFIG = os.environ.get("BRAIN_CODEX_CONFIG") or os.path.join(HOME, ".codex", "config.toml")
CODEX_CACHE = os.path.join(HOME, ".codex", "plugins", "cache")
APP_LISTS = os.environ.get("BRAIN_APP_PLUGIN_LISTS") or os.path.join(HOME, "Library", "Application Support", "Claude", "plugin-list", "*", "*", "plugins.json")
SHELF = os.path.join(B.ROOT, "skills", "plugins")
CORE = {  # kept ON at start, and why
    "context-mode": "Claude: context-window protection used by every session (ctx_* tools)",
    "codex-app-tools": "Codex: the app's own tools",
    "browser": "Codex: built-in browser",
    "unified-computer-use": "Codex: computer use",
}


def brain_copy(name, surface=""):
    for cand in ((f"codex-{name}",) if surface == "codex" else (name,)):
        d = os.path.join(SHELF, cand)
        if os.path.isdir(d):
            return d, len(glob.glob(os.path.join(d, "**", "SKILL.md"), recursive=True))
    return None, 0


def plugin_skill_count(path):
    return len(glob.glob(os.path.join(path, "**", "SKILL.md"), recursive=True)) if path and os.path.isdir(path) else 0


def has_mcp(path):
    return bool(path) and bool(glob.glob(os.path.join(path, "**", ".mcp.json"), recursive=True))


def codex_entries():
    text = open(CODEX_CONFIG, encoding="utf-8").read() if os.path.exists(CODEX_CONFIG) else ""
    out = []
    for m in re.finditer(r'^\[plugins\."([^"@]+)@([^"]+)"\]\s*\n(?:[^\[]*?\n)?\s*enabled\s*=\s*(true|false)', text, re.M):
        name, market, on = m.group(1), m.group(2), m.group(3) == "true"
        vers = sorted(glob.glob(os.path.join(CODEX_CACHE, market, name, "*")))
        out.append({"surface": "codex", "name": name, "key": f"{name}@{market}", "on": on, "path": vers[-1] if vers else None})
    return out


def shelf():
    rows = []
    for f in glob.glob(APP_LISTS):
        for p in (B.load_json(f, {}) or {}).get("plugins", []):
            rows.append({"surface": "claude-account", "name": p.get("name"), "key": p.get("id"), "on": bool(p.get("enabled")),
                         "path": p.get("installPath"), "account_id": os.path.basename(p.get("installPath") or "")})
    settings = B.load_json(CLAUDE_SETTINGS, {}) or {}
    enabled = settings.get("enabledPlugins") or {}
    installed = (B.load_json(CLAUDE_INSTALLED, {}) or {}).get("plugins") or {}
    for key in sorted(set(installed) | set(enabled)):
        path = next((i.get("installPath") for i in installed.get(key) or [] if i.get("installPath")), None)
        rows.append({"surface": "claude-local", "name": key.split("@")[0], "key": key, "on": bool(enabled.get(key)), "path": path})
    rows += codex_entries()
    for r in rows:
        r["skills"] = plugin_skill_count(r["path"])
        r["mcp"] = has_mcp(r["path"])
        r["brain_copy"], r["brain_skills"] = brain_copy(r["name"], r["surface"])
        r["core"] = CORE.get(r["name"])
    return rows


def how(r):
    if r["surface"] == "claude-account":
        return (f"Claude app: call SuggestPluginInstall with pluginId {r['account_id']} (the owner clicks Add), "
                f"or the owner: Customize → Plugins → {r['name']} on")
    return f"python3 -I tools/plugin_shelf.py activate {r['name']}  (effective in the next {'Codex' if r['surface'] == 'codex' else 'Claude'} session)"


def backup(path, why):
    d = os.path.join(B.STATE, "backups", B.today(), "plugin-shelf")
    os.makedirs(d, exist_ok=True)
    stem = os.path.join(d, f"{os.path.basename(path)}.{B.now().replace(' ', '_').replace(':', '')}")
    n = 0
    while os.path.exists(f"{stem}{'-' + str(n) if n else ''}.bak"):  # two switches in one second never share a backup
        n += 1
    dst = f"{stem}{'-' + str(n) if n else ''}.bak"
    shutil.copy2(path, dst)
    with open(os.path.join(B.STATE, "plugin-shelf.log"), "a", encoding="utf-8") as fh:
        fh.write(f"{B.now()} {why} backup={B.rel(dst)}\n")
    return dst


def switch(name, on):
    rows = [r for r in shelf() if r["name"] == name or r["key"] == name]
    if not rows:
        sys.exit(f"no plugin named {name!r} (see: plugin_shelf.py list)")
    done = []
    for r in rows:
        if r["on"] == on:
            done.append({"plugin": r["key"], "surface": r["surface"], "result": "already " + ("on" if on else "off")})
            continue
        if r["surface"] == "claude-account":
            done.append({"plugin": r["key"], "surface": r["surface"], "result": "not switchable by a file",
                         "how": how(r) if on else f"the owner: Claude app → Customize → Plugins → {r['name']} off (its skills stay in "
                                                     f"skills/plugins/{r['name']}/; an agent re-adds it with SuggestPluginInstall, id {r['account_id']})"})
            continue
        if not on and not r["brain_skills"] and r["skills"]:
            sys.exit(f"refused: {r['key']} has {r['skills']} skills and no copy in skills/plugins/{r['name']}/ (copy them first)")
        if r["surface"] == "claude-local":
            b = backup(CLAUDE_SETTINGS, f"{'activate' if on else 'deactivate'} {r['key']}")
            s = B.load_json(CLAUDE_SETTINGS, {})
            s.setdefault("enabledPlugins", {})[r["key"]] = on
            B.atomic_write(CLAUDE_SETTINGS, json.dumps(s, indent=2, ensure_ascii=False) + "\n")
        else:
            b = backup(CODEX_CONFIG, f"{'activate' if on else 'deactivate'} {r['key']}")
            text = open(CODEX_CONFIG, encoding="utf-8").read()
            pat = re.compile(r'(^\[plugins\."' + re.escape(r["key"]) + r'"\]\s*\n(?:[^\[]*?\n)?\s*enabled\s*=\s*)(true|false)', re.M)
            text, n = pat.subn(lambda m: m.group(1) + ("true" if on else "false"), text, count=1)
            if n != 1:
                sys.exit(f"could not find the enabled line of {r['key']} in {CODEX_CONFIG}")
            B.atomic_write(CODEX_CONFIG, text)
        done.append({"plugin": r["key"], "surface": r["surface"], "result": ("on" if on else "off") + " from the next session", "backup": B.rel(b)})
    return done


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    li = sub.add_parser("list")
    li.add_argument("--json", action="store_true")
    fi = sub.add_parser("find")
    fi.add_argument("words")
    for c in ("activate", "deactivate"):
        sub.add_parser(c).add_argument("name")
    sub.add_parser("verify")
    a = ap.parse_args()
    if a.cmd == "list":
        rows = shelf()
        if a.json:
            print(json.dumps(rows, indent=1, ensure_ascii=False))
            return 0
        print("| Plugin | Surface | At start | Skills (plugin / brain copy) | MCP tools | Activate |\n|---|---|---|---|---|---|")
        for r in sorted(rows, key=lambda r: (r["surface"], r["name"])):
            print(f"| {r['name']} | {r['surface']} | {'ON' + (' (core)' if r['core'] else '') if r['on'] else 'off'} | {r['skills']} / {r['brain_skills']} | "
                  f"{'yes' if r['mcp'] else '-'} | {'-' if r['on'] else how(r)} |")
        return 0
    if a.cmd == "find":
        import brain_route as R
        q = set(R.expand(R.tokens(a.words)))
        hits = []
        for r in shelf():
            names = " ".join(os.path.basename(os.path.dirname(p)) for p in glob.glob(os.path.join(r["brain_copy"] or "/nonexistent", "**", "SKILL.md"), recursive=True))
            text = f"{r['name']} {names}".lower().replace("-", " ")
            score = sum(1 for t in q if t in text)
            if score:
                hits.append((score, r))
        for score, r in sorted(hits, key=lambda x: -x[0])[:5]:
            print(f"{r['name']} ({r['surface']}, {'on' if r['on'] else 'off'}) · skills in the brain: {r['brain_copy'] and B.rel(r['brain_copy'])} · {how(r) if not r['on'] else 'already on'}")
        if not hits:
            print("no shelved plugin matches; use brain_route.py for skills and notes")
        return 0
    if a.cmd in ("activate", "deactivate"):
        print(json.dumps(switch(a.name, a.cmd == "activate"), indent=1, ensure_ascii=False))
        return 0
    rows = shelf()
    bad, gaps, changed = [], {}, {}
    for r in rows:
        if r["on"] or not r["skills"]:
            continue
        if not r["brain_skills"]:
            bad.append(r["key"])
            continue
        src, dst = skill_map(r["path"]), skill_map(r["brain_copy"])
        miss = sorted(set(src) - set(dst))
        diff = sorted(n for n in set(src) & set(dst) if src[n] != dst[n])
        if miss:
            gaps[r["key"]] = miss
        if diff:
            changed[r["key"]] = diff  # the brain copy differs from the installed one (newer plugin version): reported, not fatal
    ok = not bad and not gaps
    print(json.dumps({"plugins": len(rows), "on_at_start": sorted(r["key"] for r in rows if r["on"]),
                      "off_checked": sum(1 for r in rows if not r["on"] and r["skills"]),
                      "off_without_brain_copy": bad, "skills_missing_in_brain_copy": gaps,
                      "skills_differing_from_installed": changed, "ok": ok}, indent=1, ensure_ascii=False))
    return 0 if ok else 1


def skill_map(root):
    """{skill folder name: sha256 of SKILL.md} for every skill under root (complete coverage + content check)."""
    out = {}
    for f in glob.glob(os.path.join(root or "/nonexistent", "**", "SKILL.md"), recursive=True):
        try:
            out[os.path.basename(os.path.dirname(f))] = B.sha256_file(f)
        except OSError:
            pass
    return out


if __name__ == "__main__":
    sys.exit(main())
