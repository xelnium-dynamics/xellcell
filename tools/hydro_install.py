#!/usr/bin/env python3
"""
hydro_install.py — opt-in, reversible switcher that connects Claude Code, Codex CLI,
and Claude Desktop MCP configs to HYDRO BRAIN (with --dry-run by default).

Usage:
    python3 -I tools/hydro_install.py --status
    python3 -I tools/hydro_install.py --dry-run
    python3 -I tools/hydro_install.py --apply
    python3 -I tools/hydro_install.py --restore state/install-backups/<timestamp>
"""
import argparse, datetime, glob, json, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brainlib as B  # noqa: E402

HYDRO_ROOT = B.ROOT
AGENT_BRAIN_PATTERNS = tuple(p for p in (
    "~/Desktop/Agent Brain",
    "~/AgentBrain",
    "~/Desktop/HYDRO BRAIN",  # v7: the folder this brain was built in before it became XELCELL
    "~/Desktop/XELCELL",      # v7 delivery folder before it became ~/xellcell
) if p != HYDRO_ROOT)
BACKUP_BASE = os.path.join(B.STATE, "install-backups")


def _replace_roots(text):
    out = text
    for old in AGENT_BRAIN_PATTERNS:
        out = out.replace(old, HYDRO_ROOT)
    return out


def _replace_in_obj(obj):
    if isinstance(obj, str):
        return _replace_roots(obj)
    if isinstance(obj, list):
        return [_replace_in_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _replace_in_obj(v) for k, v in obj.items()}
    return obj


def _status_of_path(path):
    if not os.path.exists(path):
        return "missing"
    raw = open(path, encoding="utf-8", errors="replace").read()
    has_hydro = HYDRO_ROOT in raw
    has_legacy = any(p in raw for p in AGENT_BRAIN_PATTERNS)
    if has_hydro and not has_legacy:
        return "hydro-brain"
    if has_hydro and has_legacy:
        return "mixed"
    if has_legacy:
        return "agent-brain"
    return "unlinked"


def inspect_targets():
    claude_settings = os.path.expanduser("~/.claude/settings.json")
    codex_hooks = os.path.expanduser("~/.codex/hooks.json")
    desktop_cfg = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    claude_agents_dir = os.path.expanduser("~/.claude/agents")
    dream_plist = os.path.expanduser("~/Library/LaunchAgents/com.hydrobrain.dream.plist")
    return {
        "hydro_root": HYDRO_ROOT,
        "targets": {
            claude_settings: _status_of_path(claude_settings),
            codex_hooks: _status_of_path(codex_hooks),
            desktop_cfg: _status_of_path(desktop_cfg),
            claude_agents_dir: "present" if os.path.isdir(claude_agents_dir) else "missing",
            dream_plist: _status_of_path(dream_plist) if os.path.exists(dream_plist) else "not-installed",
        },
        "packaged_agents": sorted(os.path.basename(p) for p in glob.glob(os.path.join(HYDRO_ROOT, "agents", "brain-*.md"))),
    }


def plan_changes():
    actions = []
    for path in (
        os.path.expanduser("~/.claude/settings.json"),
        os.path.expanduser("~/.codex/hooks.json"),
        os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json"),
    ):
        if not os.path.exists(path):
            continue
        raw = open(path, encoding="utf-8").read()
        data = json.loads(raw)
        updated = _replace_in_obj(data)
        new_raw = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
        if json.dumps(data, sort_keys=True) != json.dumps(updated, sort_keys=True):
            actions.append({"kind": "json_rewrite", "path": path, "new_content": new_raw})

    agents_dst_dir = os.path.expanduser("~/.claude/agents")
    for src in sorted(glob.glob(os.path.join(HYDRO_ROOT, "agents", "brain-*.md"))):
        name = os.path.basename(src)
        dst = os.path.join(agents_dst_dir, name)
        src_txt = open(src, encoding="utf-8").read()
        dst_txt = open(dst, encoding="utf-8").read() if os.path.exists(dst) else None
        if dst_txt != src_txt:
            actions.append({"kind": "agent_sync", "path": dst, "source": src, "new_content": src_txt})
    return actions


def apply_actions(actions):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bdir = os.path.join(BACKUP_BASE, stamp)
    os.makedirs(bdir, exist_ok=True)
    manifest = {"created": B.now(), "hydro_root": HYDRO_ROOT, "files": []}

    for idx, act in enumerate(actions):
        dst = act["path"]
        bname = f"{idx:02d}_{os.path.basename(dst)}"
        bpath = os.path.join(bdir, bname)
        existed = os.path.exists(dst)
        if existed:
            shutil.copy2(dst, bpath)
        manifest["files"].append({"dst": dst, "backup": bname if existed else None, "existed": existed})
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        B.atomic_write(dst, act["new_content"])

    B.atomic_write(os.path.join(bdir, "manifest.json"), json.dumps(manifest, indent=2) + "\n")
    return {"applied": len(actions), "backup_dir": bdir, "targets": [a["path"] for a in actions]}


def restore_backup(bdir):
    bdir = os.path.realpath(bdir)
    mpath = os.path.join(bdir, "manifest.json")
    if not os.path.exists(mpath):
        raise FileNotFoundError(f"no manifest.json in {bdir}")
    manifest = B.load_json(mpath, {})
    restored = []
    for entry in manifest.get("files", []):
        dst = entry["dst"]
        if entry.get("existed") and entry.get("backup"):
            shutil.copy2(os.path.join(bdir, entry["backup"]), dst)
            restored.append({"dst": dst, "action": "restored"})
        elif os.path.exists(dst):
            trash_dir = os.path.join(B.ROOT, "_to_delete", "install-restored")
            os.makedirs(trash_dir, exist_ok=True)
            shutil.move(dst, os.path.join(trash_dir, os.path.basename(dst)))
            restored.append({"dst": dst, "action": "moved_to_to_delete"})
    return {"backup_dir": bdir, "restored": restored}


def main():
    ap = argparse.ArgumentParser(description="Opt-in switcher for HYDRO BRAIN hooks, agents, and MCP config.")
    ap.add_argument("--status", action="store_true", help="Show current hook/config targets without modifying anything")
    ap.add_argument("--dry-run", action="store_true", help="Preview changes without touching user configs (default)")
    ap.add_argument("--apply", action="store_true", help="Back up live configs and switch targets to HYDRO BRAIN")
    ap.add_argument("--with-dream", action="store_true", help="Also install macOS background dreaming LaunchAgent (with --apply)")
    ap.add_argument("--restore", metavar="BACKUP_DIR", help="Restore configs from a prior backup directory")
    a = ap.parse_args()

    if a.status:
        print(json.dumps(inspect_targets(), indent=2))
        return 0
    if a.restore:
        print(json.dumps(restore_backup(a.restore), indent=2))
        return 0

    actions = plan_changes()
    if a.apply:
        res = apply_actions(actions)
        if a.with_dream:
            import brain_dream
            res["dream_launchd"] = brain_dream.install_launchd()
        print(json.dumps(res, indent=2))
        return 0

    print(json.dumps({
        "mode": "dry-run",
        "hydro_root": HYDRO_ROOT,
        "planned_changes": len(actions),
        "targets": [{"kind": x["kind"], "path": x["path"]} for x in actions],
        "note": "Pass --apply to back up current files and activate HYDRO BRAIN.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
