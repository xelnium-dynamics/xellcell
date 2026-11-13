#!/usr/bin/env python3
"""
tree_validate.py — validates the brain's executable harness surface before it is used or released (v2.1, Argon O10;
port of the checks in Google Harness² core/tree.py: always-on cap, skill frontmatter, script compile + references,
hook schema).

    python3 -I tree_validate.py [--json] [--root PATH]

Errors (exit 1) — the brain's own components:
- always-on text: AGENTS.md <= 6,000 chars, CLAUDE.md <= 1,500 (adding prose means cutting prose)
- tools/*.py and tools/tests/*.py compile; skills/**/scripts/*.py compile
- every `tools/<name>.py` mentioned in AGENTS.md, CLAUDE.md, START-HERE.md, HANDOFF.md, agents/*.md and
  tools/tools-v2-readme.md exists
- agents/*.md have frontmatter with name + description
- hooks that call the brain (~/.claude/settings.json, ~/.codex/hooks.json): known event names, type "command",
  and the brain script they run exists
Warnings (exit 0) — third-party skills in skills/: SKILL.md without a name or a description of >= 20 characters
(the router can only find a skill by its description: that is its trigger line).
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

CAPS = {"AGENTS.md": 6000, "CLAUDE.md": 1500}
DOCS = ["AGENTS.md", "CLAUDE.md", "START-HERE.md", "HANDOFF.md", "tools/tools-v2-readme.md"]
EVENTS = {"SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "SubagentStop",
          "Notification", "PreCompact", "PostCompact", "PermissionRequest", "InstructionsLoaded"}
BRAIN_NAMES = ("Agent Brain", "AgentBrain", "HYDRO BRAIN", "XELCELL", "xellcell")


def compiles(path):
    try:
        compile(open(path, encoding="utf-8").read(), path, "exec")
        return None
    except (SyntaxError, ValueError, UnicodeDecodeError) as e:
        return f"{type(e).__name__}: {e}"


def hook_commands(cfg):
    for event, groups in (cfg.get("hooks") or {}).items():
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                yield event, h


def validate(root):
    err, warn = [], []
    for f, cap in CAPS.items():
        p = os.path.join(root, f)
        if os.path.exists(p) and len(open(p, encoding="utf-8").read()) > cap:
            err.append(f"{f}: {len(open(p, encoding='utf-8').read())} chars > cap {cap} (always-on text: cut before adding)")
    for p in sorted(glob.glob(os.path.join(root, "tools", "*.py")) + glob.glob(os.path.join(root, "tools", "tests", "*.py")) +
                    glob.glob(os.path.join(root, "skills", "**", "scripts", "*.py"), recursive=True)):
        e = compiles(p)
        if e:
            (err if "/skills/" not in p else warn).append(f"{os.path.relpath(p, root)}: does not compile ({e})")
    docs = ([os.path.join(root, d) for d in DOCS]
            + sorted(glob.glob(os.path.join(root, "agents", "*.md")))
            + sorted(glob.glob(os.path.join(root, ".claude", "rules", "*.md")))
            + sorted(glob.glob(os.path.join(root, ".claude", "commands", "*.md"))))
    for d in docs:
        if not os.path.exists(d):
            continue
        for ref in sorted(set(re.findall(r"\btools/([\w-]+\.(?:py|sh))\b", open(d, encoding="utf-8").read()))):
            if not os.path.exists(os.path.join(root, "tools", ref)):
                err.append(f"{os.path.relpath(d, root)}: names tools/{ref}, which does not exist")
    for a in sorted(glob.glob(os.path.join(root, "agents", "*.md"))):
        meta = B.parse_frontmatter(B.split_frontmatter(open(a, encoding="utf-8").read())[0] or "")
        for k in ("name", "description"):
            if not meta.get(k):
                err.append(f"{os.path.relpath(a, root)}: frontmatter has no {k}")
    for rfile in sorted(glob.glob(os.path.join(root, ".claude", "rules", "*.md"))):
        txt = open(rfile, encoding="utf-8", errors="replace").read().strip()
        if not txt:
            err.append(f"{os.path.relpath(rfile, root)}: empty rule file")
    for cfile in sorted(glob.glob(os.path.join(root, ".claude", "commands", "*.md"))):
        txt = open(cfile, encoding="utf-8", errors="replace").read().strip()
        if not txt:
            err.append(f"{os.path.relpath(cfile, root)}: empty command file")
    cfg_paths = (
        os.path.join(root, ".claude", "settings.json"),
        os.path.expanduser("~/.claude/settings.json"),
        os.path.expanduser("~/.codex/hooks.json"),
    )
    for cfg_path in cfg_paths:
        cfg = B.load_json(cfg_path, None)
        if not isinstance(cfg, dict):
            continue
        for event, h in hook_commands(cfg):
            cmd = str(h.get("command", "")) if isinstance(h, dict) else ""
            if not any(bn in cmd for bn in BRAIN_NAMES) and "$BRAIN_ROOT" not in cmd:
                continue
            where = cfg_path.replace(root, ".").replace(os.path.expanduser("~"), "~")
            if event not in EVENTS:
                err.append(f"{where}: unknown hook event {event}")
            if h.get("type") != "command":
                err.append(f"{where}: {event} hook is not type 'command'")
            for script in re.findall(r"(?:Agent Brain|AgentBrain|HYDRO BRAIN|XELCELL|xellcell|\$BRAIN_ROOT|\"\$CLAUDE_PROJECT_DIR\")/tools/([\w-]+\.py)", cmd):
                if not os.path.exists(os.path.join(root, "tools", script)):
                    err.append(f"{where}: {event} runs tools/{script}, which does not exist")
    # v3 (A6): brain_hooks.py post logs Read (scout originals) and Agent/Task (scout replies); a matcher without them
    # leaves the layer-6 checks dead although their code and tests exist
    cfg = B.load_json(os.path.expanduser("~/.claude/settings.json"), None)
    for g in ((cfg or {}).get("hooks") or {}).get("PostToolUse") or [] if isinstance(cfg, dict) else []:
        cmds = " ".join(str(h.get("command", "")) for h in (g.get("hooks") or []) if isinstance(h, dict)) if isinstance(g, dict) else ""
        m = str(g.get("matcher", "")) if isinstance(g, dict) else ""
        if "brain_hooks.py" in cmds and " post" in cmds and m not in ("", "*"):
            lacking = [t for t in ("Read", "Agent") if t not in m.split("|")]
            if lacking:
                warn.append(f"~/.claude/settings.json: the PostToolUse matcher for brain_hooks.py post lacks {', '.join(lacking)} "
                            f"(scout checks and Read evidence never run); matcher now: {m}")
    for s in sorted(glob.glob(os.path.join(root, "skills", "**", "SKILL.md"), recursive=True)):
        meta = B.parse_frontmatter(B.split_frontmatter(open(s, encoding="utf-8", errors="replace").read())[0] or "")
        desc = meta.get("description")
        desc = " ".join(desc) if isinstance(desc, list) else str(desc or "")
        if not meta.get("name") or len(desc.strip()) < 20:
            warn.append(f"{os.path.relpath(s, root)}: " + ("no name" if not meta.get("name") else "description under 20 chars (the router cannot find it)"))
    return err, warn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=B.ROOT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    err, warn = validate(a.root)
    if a.json:
        print(json.dumps({"errors": err, "warnings": warn}, indent=1, ensure_ascii=False))
    else:
        print(f"tree_validate: {len(err)} error(s), {len(warn)} warning(s)")
        for e in err:
            print("ERROR", e)
        for w in warn[:20]:
            print("warn ", w)
        if len(warn) > 20:
            print(f"warn  … {len(warn) - 20} more (use --json)")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
