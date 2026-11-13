#!/usr/bin/env python3
"""
brain_skill_hook.py — standalone UserPromptSubmit skill hook delegating directly
to Hydro Brain's unified engine (`brain_hooks.pick_skills` -> `hydro_skills.py`).
Prints skill suggestions only when relevant; stays completely silent otherwise.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain_hooks as H  # noqa: E402


def main():
    raw = sys.stdin.read().strip()
    if not raw:
        return 0
    try:
        data = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    prompt = (data.get("prompt") or "").strip()
    if not prompt or prompt.startswith("/"):
        return 0
    skills = H.pick_skills(prompt, scope=data.get("scope", "general"))
    if not skills:
        return 0
    lines = ["HYDRO BRAIN skills relevant to this request (read each SKILL.md that fits):"]
    for s in skills:
        lines.append(f"- {s['name']} ({s['where']}): {s['description']}")
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "\n".join(lines)}}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
