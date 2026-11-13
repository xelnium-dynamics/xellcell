"""Reproduce the session-linker bug: same hook input against the live v3 hook and the v6 hook, each in its own temp brain root."""
import json, os, subprocess, sys, tempfile, time
def run(hooks_py, label):
    root = tempfile.mkdtemp(prefix="linker-repro-")
    for sid, status, age in (("20261113-174230-claude-aaaa", "open", 0), ("20261112-174027-claude-bbbb", "closed", 86400)):
        d = os.path.join(root, "sessions", sid)
        os.makedirs(d)
        json.dump({"id": sid, "status": status}, open(os.path.join(d, "meta.json"), "w"))
        t = time.time() - age
        os.utime(os.path.join(d, "meta.json"), (t, t))
    os.makedirs(os.path.join(root, "state"))
    json.dump({"conv-1": "20261113-174230-claude-aaaa"}, open(os.path.join(root, "state", "live-links.json"), "w"))
    env = dict(os.environ, BRAIN_ROOT=root)
    env.pop("BRAIN_OFF", None)
    data = {"session_id": "conv-1", "tool_name": "Bash",
            "tool_input": {"command": "python3 - <<'EOF'\n# a patch script whose text mentions: brain_session.py new ...\nprint('capsule of a past session')\nEOF"},
            "tool_response": {"stdout": "# Capsule — Northwind Cafe (20261112-174027-claude-bbbb) · lane standard", "stderr": ""}}
    subprocess.run([sys.executable, "-I", hooks_py, "post"], input=json.dumps(data), text=True, env=env, capture_output=True)
    link = json.load(open(os.path.join(root, "state", "live-links.json")))["conv-1"]
    print(f"{label}: conversation conv-1 was linked to the OPEN session ...aaaa; after a command that only mentions the words and prints the id of CLOSED session ...bbbb it is linked to: {link}"
          + ("   <-- re-linked to the closed session: every later shell write is refused" if link.endswith("bbbb") else "   (unchanged)"))
run("~/AgentBrain/tools/brain_hooks.py", "live brain v3  (~/AgentBrain/tools/brain_hooks.py)")
run("~/Desktop/HYDRO BRAIN/tools/brain_hooks.py", "HYDRO v6      (tools/brain_hooks.py)")
