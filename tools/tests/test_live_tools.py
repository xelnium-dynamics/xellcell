"""Tests for the live brain tools: start card, sessions, index + router (scope gate), judge runner,
old-vault migration and vault audit. Every test builds a throwaway brain in a temp folder (BRAIN_ROOT),
so the real brain is never touched. Run: bash tools/test_all.sh"""
import csv, json, os, stat, subprocess, sys, tempfile, unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


class Brain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "brain")
        v = os.path.join(self.root, "Brain System")
        write(v, "self/identity.md", "---\ntitle: Identity\nsummary: names of the owner\n---\n# Identity\nMark Al Lex portfolio.\n")
        write(v, "projects/client-a/Client-A labels.md", "---\ntitle: Client-A labels\nsummary: coffee label maps\n---\n# Client-A labels\nCoffee label map with street doodles.\n")
        write(v, "projects/client-a/Client-A - history.md", "---\ntitle: Client-A - history\nsummary: history\n---\n# Client-A - history\n- 2026-10-30 (Claude — Recruiter Jane Roe replied about the label job)\n")
        write(v, "domains/engineering/Airflow basics.md", "---\ntitle: Airflow basics\nsummary: wind tunnel airflow simulation notes\n---\n# Airflow basics\nCFD airflow over a car body in a wind tunnel.\n")
        write(v, "system/brain-v2-map.md", "---\ntitle: Map\nsummary: map\n---\n# Map\nThe brain map.\n")
        self.skills = os.path.join(self.tmp.name, "skills")
        write(self.skills, "blender-export/SKILL.md", "---\nname: blender-export\ndescription: Export Blender models for airflow simulation tools\n---\nbody\n")
        write(self.skills, "zh-skill/SKILL.md", "---\nname: zh-skill\ndescription: 为 智能体 锻造完整的 设定\n---\nbody\n")
        roots = os.path.join(self.tmp.name, "roots.json")
        with open(roots, "w") as f:
            json.dump([{"path": self.skills, "agent": "Claude", "kind": "claude-personal", "autoload": "yes"}], f)
        os.makedirs(os.path.join(self.root, "state"), exist_ok=True)
        with open(os.path.join(self.root, "state", "folder-projects.json"), "w") as f:
            json.dump({os.path.join(self.tmp.name, "work", "client-a"): "client-a"}, f)
        os.makedirs(os.path.join(self.tmp.name, "work", "client-a"), exist_ok=True)
        self.env = dict(os.environ, BRAIN_ROOT=self.root, BRAIN_SKILL_ROOTS=roots, BRAIN_NO_SLEEP="1")
        self.env.pop("BRAIN_VAULT", None)
        self.env.pop("BRAIN_INDEX_DB", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, script, *args, stdin=None, env=None):
        p = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, script), *args], capture_output=True, text=True,
                           input=stdin, env=env or self.env)
        return p.returncode, p.stdout, p.stderr


class StartAndSessionTests(Brain):
    def test_start_card_hook_shape_and_no_personal_data(self):
        rc, so, se = self.run_tool("brain_start.py", "--agent", "codex", stdin=json.dumps({"cwd": os.path.join(self.tmp.name, "work", "client-a")}))
        self.assertEqual(rc, 0, se)
        out = json.loads(so)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("project: client-a", ctx)
        self.assertIn("brain_session.py", ctx)
        self.assertNotIn("the owner Al Lex", ctx)  # no knowledge or personal content in the card
        self.assertIn("2026-10-30 (newest entry in Brain System/projects/client-a/Client-A - history.md)", ctx)
        self.assertNotIn("Jane Roe", ctx)  # history content and names stay out of the card
        self.assertLess(len(ctx.splitlines()), 40)

    def test_start_card_never_fails(self):
        env = dict(self.env, BRAIN_ROOT=os.path.join(self.tmp.name, "missing"))
        rc, so, _ = self.run_tool("brain_start.py", "--agent", "claude", "--format", "text", env=env)
        self.assertEqual(rc, 0)
        self.assertIn("Agent Brain", so)

    def test_session_new_checkpoint_close(self):
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", os.path.join(self.tmp.name, "work", "client-a"), "--title", "Label test")
        self.assertEqual(rc, 0, se)
        sid = json.loads(so)["session"]
        d = os.path.join(self.root, "sessions", sid)
        self.assertTrue(os.path.exists(os.path.join(d, "contract.md")))
        self.assertEqual(json.load(open(os.path.join(d, "meta.json")))["project"], "client-a")
        rc, so, _ = self.run_tool("brain_session.py", "checkpoint", "--session", sid, "--note", "milestone one")
        self.assertEqual(json.loads(so)["checkpoint"], 1)
        rc, so, _ = self.run_tool("brain_session.py", "close", "--session", sid)
        self.assertEqual(rc, 1)  # summaries missing: templates created, not closed
        self.assertEqual(json.loads(so)["status"], "fill_summaries")
        rc, so, _ = self.run_tool("brain_session.py", "close", "--session", sid)
        self.assertEqual(json.loads(so)["status"], "summaries_still_empty")
        write(d, "task-summary.md", "# Task Summary — t\n\n| Field | Content |\n|---|---|\n| Delivered | x.pdf |\n| Verified (requirement → tier → evidence) | R1 → 0 → log |\n")
        write(d, "brain-summary.md", "# Brain Summary — t\n\n| Field | Content |\n|---|---|\n| Proposed lesson | check fonts before export |\n")
        rc, so, se = self.run_tool("brain_session.py", "close", "--session", sid, "--approval", "approved",
                                   "--no-judge", "unit test")  # v3: a standard-lane close names why it has no verdict
        self.assertEqual(rc, 0, se)
        res = json.loads(so)
        self.assertTrue(res["episode"].startswith("Brain System/projects/client-a/episodes/"))
        self.assertTrue(os.path.exists(os.path.join(self.root, res["queued"])))
        self.assertEqual(res["index"], "rebuilt")  # the episode is linked from the TOC at once
        ep_stem = os.path.basename(res["episode"])[:-3]
        toc = open(os.path.join(self.root, "Brain System", "00-toc", "toc-projects.md"), encoding="utf-8").read()
        self.assertIn(ep_stem, toc)
        self.assertTrue(os.path.exists(os.path.join(self.root, "Brain System", "00-toc", "toc-inbox.md")))
        rc, so, _ = self.run_tool("brain_session.py", "status")
        self.assertEqual(json.loads(so)["open"], [])
        # the protocol's own "nothing to learn" phrase never becomes a queued lesson
        rc, so, _ = self.run_tool("brain_session.py", "new", "--agent", "claude", "--title", "Quiet")
        sid2 = json.loads(so)["session"]
        d2 = os.path.join(self.root, "sessions", sid2)
        write(d2, "task-summary.md", "# Task Summary\n\n| Field | Content |\n|---|---|\n| Delivered | x |\n| Verified (requirement → tier → evidence) | R1 → 0 → log |\n")
        write(d2, "brain-summary.md", "# Brain Summary\n\n| Field | Content |\n|---|---|\n| Proposed lesson | No reusable improvement; existing procedures worked |\n")
        rc, so, _ = self.run_tool("brain_session.py", "close", "--session", sid2, "--no-judge", "unit test")  # v3
        self.assertIsNone(json.loads(so)["queued"])


class IndexRouteTests(Brain):
    def test_scope_gate_skills_and_no_match(self):
        write(self.root, "state/vault-policy.json", json.dumps({"english_only_descriptions": True}))  # this test checks the English-only option
        rc, so, se = self.run_tool("brain_index.py")
        self.assertEqual(rc, 0, se)
        self.assertEqual(json.loads(so)["skills"], 2)
        reg = "".join(open(os.path.join(self.root, "Brain System", "00-toc", f), encoding="utf-8").read()
                      for f in os.listdir(os.path.join(self.root, "Brain System", "00-toc")) if f.endswith(".md"))
        self.assertIn("zh-skill", reg)                                # the skill is listed...
        self.assertNotIn("锻造", reg)  # non-English descriptions never reach the vault
        rc, so, _ = self.run_tool("brain_route.py", "--query", "airflow simulation blender export", "--scope", "engineering", "--json")
        r = json.loads(so)
        self.assertEqual(r["notes"][0]["path"], "Brain System/domains/engineering/Airflow basics.md")
        self.assertEqual(r["skills"][0]["name"], "blender-export")
        rc, so, _ = self.run_tool("brain_route.py", "--query", "the owner Al portfolio identity", "--scope", "website", "--json")
        self.assertFalse([n for n in json.loads(so)["notes"] if n["collection"].startswith("self")])  # scope gate
        rc, so, _ = self.run_tool("brain_route.py", "--query", "the owner Al identity", "--scope", "personal", "--json")
        self.assertTrue([n for n in json.loads(so)["notes"] if n["collection"].startswith("self")])
        rc, so, _ = self.run_tool("brain_route.py", "--query", "zzqx unknownword", "--scope", "general")
        self.assertIn("No match", so)

    def test_brain_copy_is_the_home_and_prompt_hook_finds_it(self):
        lib = os.path.join(self.root, "skills")
        write(lib, "blender-export/SKILL.md", "---\nname: blender-export\ndescription: Export Blender models for airflow simulation tools\n---\nbody\n")
        write(lib, "plugins/kiln/skills/glaze/SKILL.md", "---\nname: glaze\ndescription: Glaze ceramic pottery kiln recipes\n---\nbody\n")
        write(self.skills, "quiet/SKILL.md", "---\nname: quiet\ndescription: Quiet airflow fan tuning\n---\nbody\n")
        roots = os.path.join(self.tmp.name, "roots2.json")
        with open(roots, "w") as f:
            json.dump([{"path": lib, "agent": "Claude + Codex (brain library, on demand)", "kind": "brain-library", "autoload": "no"},
                       {"path": self.skills, "agent": "Claude", "kind": "claude-personal", "autoload": "yes"}], f)
        settings = os.path.join(self.tmp.name, "claude-settings.json")
        with open(settings, "w") as f:
            json.dump({"skillOverrides": {"quiet": "off"}}, f)
        env = dict(self.env, BRAIN_SKILL_ROOTS=roots, BRAIN_CLAUDE_SETTINGS=settings)
        rc, so, se = self.run_tool("brain_index.py", env=env)
        self.assertEqual(rc, 0, se)
        self.assertEqual(json.loads(so)["skills"], 4)  # blender-export only once: the brain copy wins over ~/.claude/skills
        rc, so, _ = self.run_tool("brain_route.py", "--query", "airflow blender export quiet fan glaze kiln", "--json", env=env)
        sk = {s["name"]: s for s in json.loads(so)["skills"]}
        self.assertIn("/skills/blender-export/", sk["blender-export"]["where"])
        self.assertEqual(sk["blender-export"]["loads_at_start"], "no")
        self.assertEqual(sk["quiet"]["loads_at_start"], "no (off)")  # label follows skillOverrides
        self.assertIn("/skills/plugins/kiln/", sk["glaze"]["where"])
        rc, so, se = self.run_tool("brain_skill_hook.py", stdin=json.dumps({"prompt": "glaze recipes for my kiln pottery"}), env=env)
        self.assertEqual(rc, 0, se)
        out = json.loads(so)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        self.assertIn("glaze", out["additionalContext"])
        for prompt in ("/loop 5m", "ok", "{bad"):
            rc, so, _ = self.run_tool("brain_skill_hook.py", stdin=prompt if prompt == "{bad" else json.dumps({"prompt": prompt}), env=env)
            self.assertEqual((rc, so), (0, ""))  # silent, never blocks a prompt


class JudgeTests(Brain):
    def fake(self, name, verdict):
        p = os.path.join(self.tmp.name, "bin", name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        body = ("#!/bin/sh\n# fake judge CLI\nout=''\nwhile [ $# -gt 0 ]; do [ \"$1\" = \"-o\" ] && out=\"$2\"; shift; done\n"
                "cat > /dev/null\n" + f"printf '%s' '{json.dumps(verdict)}' > \"$out\"\n")
        with open(p, "w") as f:
            f.write(body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        return p

    def test_blind_packet_tier0_and_verdict(self):
        rc, so, _ = self.run_tool("brain_session.py", "new", "--agent", "claude", "--title", "Judge me")
        sid = json.loads(so)["session"]
        d = os.path.join(self.root, "sessions", sid)
        c = open(os.path.join(d, "contract.md")).read().replace("<!-- - R1: cmd: <shell command that exits 0 when R1 is met> -->", "- R1: cmd: test -f /definitely/missing/file")
        write(d, "contract.md", c)
        self.run_tool("brain_session.py", "checkpoint", "--session", sid, "--note", "SECRET-MAKER-REASONING")
        art = write(self.tmp.name, "out/result.txt", "deliverable text")
        rc, so, _ = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, "--dry-run")
        self.assertIn("deliverable text", so)
        self.assertNotIn("SECRET-MAKER-REASONING", so)  # blindness: no checkpoints or chat in the packet
        good = {"overall": "pass", "verdicts": [{"requirement": "R1", "verdict": "pass", "evidence": "x", "severity": "none"}], "flaws": []}
        env = dict(self.env, BRAIN_CODEX_BIN=self.fake("codex", good))
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, env=env)
        res = json.loads(so)
        self.assertEqual((res["judge"], res["overall"], rc), ("codex", "fail", 1))  # failed Tier-0 check beats the model's pass
        self.assertTrue(os.path.exists(os.path.join(self.root, res["verdict_file"])))


class MigrationAuditTests(unittest.TestCase):
    def test_migrate_fixture_end_to_end(self):
        with tempfile.TemporaryDirectory() as t:
            snap, base, out = os.path.join(t, "snap"), os.path.join(t, "base"), os.path.join(t, "out")
            write(base, "system/brain-v2-map.md", "---\ntitle: Map\n---\n# Map\nmap\n")
            write(snap, "04 Projects/Alpha.md", "---\ntags: [alpha]\n---\n# Alpha\nLinks [[Beta]] and [[Gone Note]] and [[HUB]].\n\n- chinese line 中文 here\n\n- bilingual by default line\n")
            write(snap, "06 Brain & Knowledge/Beta.md", "# Beta\nBeta knowledge body text here.\n")
            write(snap, "HUB.md", "# HUB\nold hub\n")
            write(snap, "04 Projects/Current State.md", "# Current State\n\n- 2026-10-01 (Claude — **ALPHA SHIPPED**) — done [[Alpha]]\n- 2026-09-01 (Claude) — something general\n")
            cfg = {"snapshot_rel": "raw/snap", "migrated": "2026-11-08",
                   "folder_rules": [{"prefix": "04 Projects/", "action": "place", "collection": "projects/alpha"}],
                   "overrides": {"HUB.md": {"action": "raw_only", "reason": "old hub", "redirect": "toc-home"},
                                 "04 Projects/Current State.md": {"action": "split"}},
                   "default_06": {"action": "place", "collection": "domains/research"},
                   "name_redirects": {}, "blocks": {},
                   "drop_blocks": [{"path": "04 Projects/Alpha.md", "contains": "bilingual by default", "reason": "language rule"}],
                   "disallowed_scripts": {"CJK": "[\\u4e00-\\u9fff]"},
                   "split": {"04 Projects/Current State.md": {"rules": [["alpha", "alpha"]], "history_buckets": ["general"],
                             "hermes_reason": "h", "structural_reason": "s", "entry_overrides": {}}},
                   "projects": {"alpha": "Alpha", "general": "General"}}
            cp = os.path.join(t, "cfg.json")
            with open(cp, "w") as f:
                json.dump(cfg, f)
            p = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "migrate_old_vault.py"), "--snapshot", snap, "--config", cp,
                                "--base-vault", base, "--out", out], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            alpha = open(os.path.join(out, "vault", "projects", "alpha", "Alpha.md"), encoding="utf-8").read()
            self.assertIn("[[Beta]]", alpha)                 # moved note keeps its link
            self.assertIn("[[toc-home|HUB]]", alpha)         # retired hub -> redirect
            self.assertNotIn("[[Gone Note]]", alpha)         # ghost -> plain text
            self.assertNotIn("中文", alpha)                   # disallowed script stays in raw only
            self.assertNotIn("bilingual by default", alpha)  # drop rule
            self.assertIn('tags: ["alpha"]', alpha)                  # old tags preserved as YAML
            hist = open(os.path.join(out, "vault", "projects", "alpha", "Alpha - history.md"), encoding="utf-8").read()
            self.assertIn("ALPHA SHIPPED", hist)
            self.assertIn("[L3–3]", hist)                    # line reference back to the source
            self.assertTrue(os.path.exists(os.path.join(out, "vault", "history", "General - history.md")))
            cc = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "coverage_check.py"), "--blocks",
                                 os.path.join(out, "segments", "blocks.jsonl"), "--plan", os.path.join(out, "plan.csv")], capture_output=True, text=True)
            self.assertEqual(cc.returncode, 0, cc.stdout)
            with open(os.path.join(out, "plan.csv"), encoding="utf-8") as f:
                reasons = {r["reason"] for r in csv.DictReader(f) if r["action"] == "raw_only"}
            self.assertTrue(any("CJK" in r for r in reasons) and "language rule" in reasons and "old hub" in reasons)

    def test_audit_flags_and_clean(self):
        with tempfile.TemporaryDirectory() as t:
            v, o = os.path.join(t, "v"), os.path.join(t, "o")
            write(v, "domains/x/Clean.md", "---\ntitle: Clean\n---\n# Clean\nGreek σ is fine in math.\n")
            rc = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "vault_audit.py"), "--vault", v, "--out", o, "--root", t]).returncode
            self.assertEqual(rc, 0)
            write(v, "domains/x/Bad.md", "---\ntitle: Bad\n---\n# Bad\n中文 text\n- every deliverable is bilingual by default\n")
            write(v, "domains/x/Empty.md", "---\ntitle: Empty\n---\n# Empty\n")
            p = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "vault_audit.py"), "--vault", v, "--out", o, "--root", t], capture_output=True, text=True)
            self.assertEqual((p.returncode, json.loads(p.stdout)["errors"]), (1, 1))      # no policy: every language allowed, only the empty note
            write(t, "state/vault-policy.json", json.dumps({"disallowed_scripts": {"Chinese": "[\u4e00-\u9fff]"}, "forbidden_rules": ["bilingual by default"]}))
            p = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "vault_audit.py"), "--vault", v, "--out", o, "--root", t], capture_output=True, text=True)
            self.assertEqual((p.returncode, json.loads(p.stdout)["errors"]), (1, 3))      # with the owner's policy: script + rule + empty note


class HookTests(Brain):
    """brain_hooks.py: contract gate, scope gate, ACTION-RISK, PRIVACY-LEAK, evidence + link, session analysis."""

    def hook(self, mode, data, env=None):
        env = dict(env or self.env, BRAIN_FREE_WRITE=os.path.expanduser("~/.claude") + os.sep)
        rc, so, se = self.run_tool("brain_hooks.py", mode, stdin=json.dumps(data), env=env)
        self.assertEqual(rc, 0, se)
        return json.loads(so)["hookSpecificOutput"] if so.strip() else None

    def new_session(self, csid, scope="general"):
        rc, so, _ = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.tmp.name, "--title", "hook test")
        sid = json.loads(so)["session"]
        c = os.path.join(self.root, "sessions", sid, "contract.md")
        text = open(c, encoding="utf-8").read().replace("scope_class: general", f"scope_class: {scope}").replace(
            "<paste the owner's request exactly>", "make a file").replace("- R1: … — check: …", "- R1: the file exists — check: cmd: test -f out.txt")
        open(c, "w", encoding="utf-8").write(text)
        cmd = f'python3 -I "{os.path.join(TOOLS, "brain_session.py")}" new --agent claude --title t'
        self.assertIsNone(self.hook("post", {"session_id": csid, "tool_name": "Bash", "tool_input": {"command": cmd},
                                             "tool_response": {"stdout": so, "stderr": ""}}))
        return sid

    def test_gates(self):
        target = os.path.join(self.tmp.name, "work", "out.txt")
        o = self.hook("pre", {"session_id": "c1", "tool_name": "Write", "tool_input": {"file_path": target}})
        self.assertEqual(o["permissionDecision"], "deny")                  # no contract yet
        self.assertIn("brain_session.py", o["permissionDecisionReason"])
        self.assertIsNone(self.hook("pre", {"session_id": "c1", "tool_name": "Write",
                                            "tool_input": {"file_path": os.path.expanduser("~/.claude/plans/p.md")}}))
        sid = self.new_session("c1")
        self.assertIsNone(self.hook("pre", {"session_id": "c1", "tool_name": "Write", "tool_input": {"file_path": target}}))
        selfp = os.path.join(self.root, "Brain System", "self", "identity.md")
        self.assertEqual(self.hook("pre", {"session_id": "c1", "tool_name": "Read", "tool_input": {"file_path": selfp}})["permissionDecision"], "deny")
        self.new_session("c2", scope="personal")
        self.assertIsNone(self.hook("pre", {"session_id": "c2", "tool_name": "Read", "tool_input": {"file_path": selfp}}))
        for cmd in ("git push origin main", "rm notes.txt", "brew install jq", "curl -X POST https://x.io/api"):
            self.assertEqual(self.hook("pre", {"session_id": "c1", "tool_name": "Bash", "tool_input": {"command": cmd}})["permissionDecision"], "ask", cmd)
        self.assertIsNone(self.hook("pre", {"session_id": "c1", "tool_name": "Bash", "tool_input": {"command": "git status && ls -la"}}))
        o = self.hook("pre", {"session_id": "c1", "tool_name": "WebSearch", "tool_input": {"query": "jobs for alex@example.com in Lisbon"}})
        self.assertIn("e-mail", o["permissionDecisionReason"])
        self.assertIsNone(self.hook("pre", {"session_id": "c1", "tool_name": "WebSearch", "tool_input": {"query": "blender 5.2 release notes 2026-11-08"}}))
        # evidence and analysis
        self.hook("post", {"session_id": "c1", "tool_name": "Bash", "tool_input": {"command": "pytest -q"},
                           "tool_response": {"stdout": "3 passed", "stderr": ""}})
        ev = open(os.path.join(self.root, "sessions", sid, "evidence.jsonl"), encoding="utf-8").read().splitlines()
        self.assertEqual(json.loads(ev[-1])["command"], "pytest -q")
        tr = write(self.tmp.name, "t.jsonl", json.dumps({"message": {"id": "m1", "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n")
        self.assertIsNone(self.hook("end", {"session_id": "c1", "transcript_path": tr, "cwd": self.tmp.name}))
        a = json.load(open(os.path.join(self.root, "sessions", sid, "analysis.json")))
        self.assertEqual(a["tokens"]["output"], 5)
        self.assertEqual(a["flow"]["evidence_lines"], 2)  # the "new" command itself + pytest
        self.assertIn("close", a["flow"]["missing_steps"])
        self.assertTrue(json.load(open(os.path.join(self.root, "sessions", sid, "meta.json")))["unclosed"])
        # shell writes need a filled contract too; harmless redirects pass
        outside = os.path.join(self.tmp.name, "work", "o.txt")
        o = self.hook("pre", {"session_id": "c9", "tool_name": "Bash", "tool_input": {"command": f"echo hi > '{outside}'"}, "cwd": self.tmp.name})
        self.assertEqual(o["permissionDecision"], "deny")
        self.assertIsNone(self.hook("pre", {"session_id": "c9", "tool_name": "Bash", "tool_input": {"command": "ls 2>&1 >/dev/null | head"}}))
        self.assertIsNone(self.hook("pre", {"session_id": "c9", "tool_name": "Bash",                       # quoted text and arrows are not redirects
                                            "tool_input": {"command": "git commit -m \"size 40,243 -> 8,243 > before\" && echo 'a > b'"}, "cwd": self.tmp.name}))
        o = self.hook("pre", {"session_id": "c9", "tool_name": "Bash", "tool_input": {"command": f"echo hi > \"{outside}\""}, "cwd": self.tmp.name})
        self.assertEqual(o["permissionDecision"], "deny")                                                  # a quoted redirect target still counts
        o = self.hook("pre", {"session_id": "c9", "tool_name": "Bash",
                              "tool_input": {"command": f"cat > '{outside}' <<'EOF'\nx > y\nEOF"}, "cwd": self.tmp.name})
        self.assertEqual(o["permissionDecision"], "deny")              # a heredoc written to a file is a write
        self.assertIn(outside, o["permissionDecisionReason"])          # ...and its body ("x > y") is not mistaken for a target
        # an opened but unfilled contract does not open the gate
        rc, so, _ = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.tmp.name, "--title", "empty")
        self.hook("post", {"session_id": "c8", "tool_name": "Bash", "tool_input": {"command": "python3 brain_session.py new --title e"},
                           "tool_response": {"stdout": so, "stderr": ""}})
        o = self.hook("pre", {"session_id": "c8", "tool_name": "Write", "tool_input": {"file_path": target}})
        self.assertIn("empty template", o["permissionDecisionReason"])
        # Codex: exec_command with "cmd" links the session; apply_patch is logged as evidence
        rc, so, _ = self.run_tool("brain_session.py", "new", "--agent", "codex", "--cwd", self.tmp.name, "--title", "codex")
        csid = json.loads(so)["session"]
        self.hook("post", {"session_id": "x1", "tool_name": "exec_command", "tool_input": {"cmd": ["python3", "brain_session.py", "new"]},
                           "tool_response": so})
        self.hook("post", {"session_id": "x1", "tool_name": "apply_patch", "tool_input": {"command": "*** Begin Patch\n*** Add File: a.txt\n+x\n*** End Patch"}})
        ev = [json.loads(l) for l in open(os.path.join(self.root, "sessions", csid, "evidence.jsonl"), encoding="utf-8")]
        self.assertEqual(ev[-1]["files"], ["a.txt"])
        # brain off: every hook silent
        off = dict(self.env, BRAIN_OFF="1")
        self.assertIsNone(self.hook("pre", {"session_id": "zz", "tool_name": "Write", "tool_input": {"file_path": target}}, env=off))
        # a broken input never blocks
        rc, so, _ = self.run_tool("brain_hooks.py", "pre", stdin="{not json")
        self.assertEqual((rc, so), (0, ""))


class WiredLayerTests(Brain):
    """Tier 0, contract lint, scope-gated fetch, Harness², typed judge cascade, MCP server, sleep job, Gym ratchet."""

    def session(self, lane="standard", scope="general", fill=True):
        rc, so, _ = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.tmp.name, "--title", "wired test",
                                  "--lane", lane, "--scope", scope)
        sid = json.loads(so)["session"]
        c = os.path.join(self.root, "sessions", sid, "contract.md")
        if fill:
            t = open(c, encoding="utf-8").read().replace("<paste the owner's request exactly>", "make the report with 3 pages")
            t = t.replace("- R1: … — check: …", "- R1: report has 3 pages — check: pdfinfo page count").replace('- "…"', '- "3 pages"')
            open(c, "w", encoding="utf-8").write(t)
        return sid

    def test_tier0_and_lint(self):
        write(self.tmp.name, "site/index.html", '<div id="app" class="hero"><a href="gone.html">x</a></div>')
        for check, want in (("R1: exists: site/index.html", 0), ("R2: html: site/index.html :: div#app", 0),
                            ("R3: html: site/index.html :: section", 1), ("R4: links: site/index.html", 1)):
            rc, so, _ = self.run_tool("tier0.py", "--check", check, "--cwd", self.tmp.name)
            self.assertEqual(rc, want, check)
        import importlib.util
        spec = importlib.util.spec_from_file_location("t0", os.path.join(TOOLS, "tier0.py"))
        t0 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t0)
        lines = t0.checks_section("## Checks\n- R1: vault\n- R2: cmd: true\n- R3: exists: a.txt\n")
        self.assertEqual([x[0] for x in lines], ["R1", "R2", "R3"])  # an argument-less line never swallows the next one
        two = t0.checks_section("## Checks (optional)\n<!-- - R1: cmd: x -->\n\n## Changes\nv2\n\n## Checks\n- R4: cmd: true\n")
        self.assertEqual([x[0] for x in two], ["R4"])  # a second Checks section is read too; commented lines are not
        sid = self.session(fill=False)
        rc, so, _ = self.run_tool("brain_session.py", "lint", "--session", sid)
        self.assertEqual(rc, 1)
        sid = self.session()
        rc, so, _ = self.run_tool("brain_session.py", "lint", "--session", sid)
        self.assertEqual(rc, 0, so)

    def test_fetch_scope_gate(self):
        sid = self.session(scope="website")
        rc, so, _ = self.run_tool("brain_fetch.py", "--session", sid, "Brain System/self/identity.md")
        self.assertEqual(rc, 3)
        rc, so, _ = self.run_tool("brain_fetch.py", "--session", sid, "Brain System/projects/client-a/Client-A labels.md", "--lines", "1-3")
        self.assertEqual(rc, 0)
        sid2 = self.session(scope="personal")
        rc, so, _ = self.run_tool("brain_fetch.py", "--session", sid2, "Brain System/self/identity.md")
        self.assertEqual(rc, 0)
        log = open(os.path.join(self.root, "sessions", sid, "retrieval-log.jsonl")).read()
        self.assertIn('"denied"', log)
        self.assertIn('"fetched"', log)

    def test_harness2_budget_and_final_run(self):
        sid = self.session()
        d = os.path.join(self.root, "sessions", sid)
        for i in (1, 2):
            write(d, f"verdict-0{i}.json", json.dumps({"verdict": {"overall": "fail"}}))
        rc, so, _ = self.run_tool("harness2.py", "qualifies", "--session", sid)
        self.assertTrue(json.loads(so)["qualifies"])
        work = os.path.join(self.tmp.name, "work")
        write(work, "README.md", "task folder\n")
        self.run_tool("harness2.py", "start", "--session", sid, "--subtask", "export glb", "--check", "test -f work/ok.flag", "--scope", "work")
        self.assertNotEqual(self.run_tool("harness2.py", "probe", "--session", sid, "--arm", "general")[0], 0)  # propose first
        gen = write(self.tmp.name, "gen.patch", "--- /dev/null\n+++ b/work/ok.flag\n@@ -0,0 +1 @@\n+ok\n")
        dom = write(self.tmp.name, "dom.patch", "--- a/work/README.md\n+++ b/work/README.md\n@@ -1 +1 @@\n-task folder\n+task folder (scale 1:1)\n")
        self.run_tool("harness2.py", "propose", "--session", sid, "--general", "plan units first", "--domain", "apply scale",
                      "--general-patch", gen, "--domain-patch", dom)
        def probe(arm):  # the tool exits 0 when a run is recorded; the check's own exit is in the ledger
            rc, _, _ = self.run_tool("harness2.py", "probe", "--session", sid, "--arm", arm)
            self.assertEqual(rc, 0, arm)
            return json.load(open(os.path.join(d, "harness2", "ledger.json")))["runs"][-1]["exit"]
        self.assertEqual(probe("reference"), 1)
        self.assertEqual(probe("general"), 0)
        # v2.1 (Argon O2): domain runs in its own copy; the flag the general patch created is NOT there
        self.assertEqual(probe("domain"), 1)
        self.assertFalse(os.path.exists(os.path.join(work, "ok.flag")))           # the live folder was never touched
        rc, so, _ = self.run_tool("harness2.py", "compare", "--session", sid)
        vs = json.loads(so)["vs_reference"]
        self.assertEqual((vs["general"], vs["domain"]), ("win", "tie"))         # both arms judged, not just one
        self.assertNotEqual(self.run_tool("harness2.py", "compose", "--session", sid, "--keep", "domain")[0], 0)  # unsupported
        self.assertEqual(self.run_tool("harness2.py", "compose", "--session", sid, "--keep", "general")[0], 0)
        self.assertNotEqual(self.run_tool("harness2.py", "close", "--session", sid)[0], 0)  # final run is mandatory
        self.assertEqual(probe("composed"), 0)                                   # 3rd extra run: the kept patch makes it pass
        self.assertNotEqual(self.run_tool("harness2.py", "probe", "--session", sid, "--arm", "general")[0], 0)  # 4th: budget spent
        rc, so, _ = self.run_tool("harness2.py", "close", "--session", sid)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(so)["budget"]["R_rollouts"], 4)
        self.assertTrue(os.path.exists(os.path.join(self.root, "queue", f"{sid}-harness2.md")))

    def test_harness2_adapt_builds_context(self):
        sid = self.session()
        self.run_tool("harness2.py", "start", "--session", sid, "--subtask", "export glb", "--check", "true", "--scope", "work")
        rc, so, _ = self.run_tool("harness2.py", "adapt", "--session", sid)
        self.assertEqual(rc, 0)
        ctx = os.path.join(self.root, "sessions", sid, "harness2", "context")
        for f in ("contract.md", "BRIEF-INV.md", "BRIEF-DOM.md", "task.md", "ledger.json"):
            self.assertTrue(os.path.exists(os.path.join(ctx, f)), f)

    def fake_cli(self, name, label):
        p = os.path.join(self.tmp.name, "bin", name)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        payload = json.dumps({"label": label, "reason": "fake"})
        body = ("#!/bin/sh\n[ \"$1\" = \"--version\" ] && { echo 'fake 1'; exit 0; }\nout=''\n"
                "while [ $# -gt 0 ]; do [ \"$1\" = \"-o\" ] && out=\"$2\"; shift; done\n"
                f"if [ -n \"$out\" ]; then cat > /dev/null; printf '%s' '{payload}' > \"$out\"; "
                f"else printf '%s' '{json.dumps({'structured_output': json.loads(payload)})}'; fi\n")
        open(p, "w").write(body)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        return p

    def test_typed_judge_cascade(self):
        import shutil
        shutil.copytree(os.path.join(os.path.dirname(TOOLS), "judge", "questions"), os.path.join(self.root, "judge", "questions"))
        env = dict(self.env, BRAIN_CLAUDE_BIN=self.fake_cli("claude", "yes"), BRAIN_CODEX_BIN=self.fake_cli("codex", "no"))
        st = write(self.tmp.name, "state.json", json.dumps({"requirement_text": "R1: 3 pages — check: pdfinfo"}))
        rc, so, se = self.run_tool("judge_typed.py", "ask", "--question", "REQ-TESTABLE", "--state", st, env=env)
        r = json.loads(so)
        self.assertEqual((r["tier"], r["label"]), (2, "no"))           # cold start: Tier 1 agreed but must escalate
        self.assertEqual(r["tier1"]["runs"], ["yes", "yes"])
        qp = os.path.join(self.root, "judge", "questions", "REQ-TESTABLE.json")
        q = json.load(open(qp))
        q["threshold"].update({"value": 1.0, "labels_used": 30, "cli_version": "fake 1", "expires_on": "2099-01-01"})
        json.dump(q, open(qp, "w"))
        rc, so, se = self.run_tool("judge_typed.py", "ask", "--question", "REQ-TESTABLE", "--state", st, env=env)
        self.assertEqual((json.loads(so)["tier"], json.loads(so)["label"]), (1, "yes"))   # calibrated + agreement → Tier 1
        rc, so, se = self.run_tool("judge_typed.py", "ask", "--question", "REQ-TESTABLE", "--state", st, "--kind", "derived_verdict", env=env)
        self.assertEqual(json.loads(so)["tier"], 1)  # REQ-TESTABLE has no direct-to-Tier-2 kinds
        rc, so, se = self.run_tool("judge_typed.py", "ask", "--question", "REQ-MET", "--state", st, "--kind", "derived_verdict", env=env)
        self.assertEqual(json.loads(so)["tier"], 2)  # derived verdicts skip Tier 1

    def test_mcp_server(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "brain_read", "arguments": {"path": "Brain System/self/identity.md"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "brain_read", "arguments": {"path": "Brain System/projects/client-a/Client-A labels.md"}}}]
        rc, so, se = self.run_tool("brain_mcp.py", stdin="\n".join(json.dumps(m) for m in msgs) + "\n")
        out = {d["id"]: d for d in map(json.loads, so.splitlines())}
        self.assertIn("brain_card", out[1]["result"]["instructions"])
        self.assertEqual(len(out[2]["result"]["tools"]), 10)
        tool_names = {t["name"] for t in out[2]["result"]["tools"]}
        self.assertIn("brain_find_skills", tool_names)
        self.assertIn("brain_learn_session", tool_names)
        self.assertIn("brain_dream", tool_names)
        self.assertTrue(out[3]["result"]["isError"])                    # scope gate
        self.assertIn("Coffee label map", out[4]["result"]["content"][0]["text"])

    def test_agent_definitions(self):
        adir = os.path.join(os.path.dirname(TOOLS), "agents")
        want = {"brain-scout": "haiku", "brain-hunter": "sonnet", "brain-scribe": "haiku", "brain-worker": "sonnet"}
        for name, model in want.items():
            text = open(os.path.join(adir, name + ".md"), encoding="utf-8").read()
            fm = text.split("---")[1]
            self.assertIn(f"name: {name}", fm)
            self.assertIn(f"model: {model}", fm)
            self.assertRegex(fm, r"description: .{40,}")
            self.assertRegex(fm, r"tools: \w")
            if name in ("brain-scout", "brain-hunter"):
                self.assertNotRegex(fm, r"tools:.*\b(Edit|Write)\b")      # read-only searchers
        self.assertIn("not_found", open(os.path.join(adir, "brain-scout.md")).read())  # menu may say "not found"

    def test_pilot_report_and_entry_parse(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("em", os.path.join(TOOLS, "entry_matrix.py"))
        em = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(em)
        self.assertEqual(em.parse("card=yes index=fresh project=job-search")["project"], "job-search")
        self.assertEqual(em.parse("no card here")["card"], None)
        home = os.path.join(self.tmp.name, "home")
        tr = write(home, ".claude/projects/p/off-1.jsonl",
                   json.dumps({"type": "user", "message": {"content": "do it"}}) + "\n" +
                   json.dumps({"type": "user", "message": {"content": "no, smaller"}}) + "\n" +
                   json.dumps({"message": {"id": "m1", "usage": {"input_tokens": 100, "output_tokens": 50}}}) + "\n")
        os.makedirs(os.path.join(self.root, "state", "pilot"), exist_ok=True)
        with open(os.path.join(self.root, "state", "pilot", "off-sessions.jsonl"), "w") as f:
            f.write(json.dumps({"session_id": "off-1", "cwd": "/x", "date": "2026-11-08", "arm": "off"}) + "\n")
            f.write(json.dumps({"session_id": "off-1", "decision": "approved", "date": "2026-11-08"}) + "\n")
        rc, so, se = self.run_tool("pilot.py", "report", env=dict(self.env, HOME=home))
        r = json.loads(so)
        self.assertEqual((r["off"]["sessions"], r["off"]["approved"], r["off"]["fresh_tokens_closed"]), (1, 1, 150))
        self.assertEqual(r["off"]["tokens_per_approved_delivery"], 150)        # v2.1: only approved sessions with a transcript
        self.assertEqual(r["off"]["corrections_per_approved_delivery"], 1.0)   # one follow-up message after the request
        self.assertIn("not enough data", r["verdict"])

    def test_harness2_token_cap_and_codex_scope(self):
        sid = self.session()
        home = os.path.join(self.tmp.name, "home2")
        tr = write(home, ".claude/projects/p/cs-1.jsonl", json.dumps({"message": {"id": "a", "usage": {"input_tokens": 10, "output_tokens": 0}}}) + "\n")
        mp = os.path.join(self.root, "sessions", sid, "meta.json")
        meta = json.load(open(mp))
        meta["claude_session"] = "cs-1"
        json.dump(meta, open(mp, "w"))
        env = dict(self.env, HOME=home)
        self.run_tool("harness2.py", "start", "--session", sid, "--subtask", "s", "--check", "true", "--token-cap", "100", env=env)
        with open(tr, "a") as f:
            f.write(json.dumps({"message": {"id": "b", "usage": {"input_tokens": 500, "output_tokens": 0}}}) + "\n")
        rc, so, se = self.run_tool("harness2.py", "probe", "--session", sid, "--arm", "reference", env=env)
        self.assertNotEqual(rc, 0)
        self.assertIn("token cap spent", se)
        env2 = dict(self.env, BRAIN_FREE_WRITE=os.path.expanduser("~/.claude") + os.sep)
        rc, so, _ = self.run_tool("brain_hooks.py", "pre", stdin=json.dumps({"session_id": "zz", "tool_name": "exec_command",
                                  "tool_input": {"cmd": ["cat", "Brain System/self/identity.md"]}}), env=env2)
        self.assertEqual(json.loads(so)["hookSpecificOutput"]["permissionDecision"], "deny")   # Codex "cmd" is gated too

    def test_codex_skill_switches_and_codex_token_analysis(self):
        cskills = os.path.join(self.tmp.name, "codex-skills")
        on = write(cskills, "kept/SKILL.md", "---\nname: kept\ndescription: Kept loaded skill for airflow notes\n---\nb\n")
        off = write(cskills, "hidden/SKILL.md", "---\nname: hidden\ndescription: Hidden skill for airflow notes\n---\nb\n")
        cfg = write(self.tmp.name, "codex-config.toml", f'model = "x"\n\n[[skills.config]]\npath = "{off}"\nenabled = false\n\n[plugins."p@m"]\nenabled = true\n')
        roots = write(self.tmp.name, "roots3.json", json.dumps([{"path": cskills, "agent": "Codex", "kind": "codex-personal", "autoload": "yes"}]))
        env = dict(self.env, BRAIN_SKILL_ROOTS=roots, BRAIN_CODEX_CONFIG=cfg)
        self.assertEqual(self.run_tool("brain_index.py", env=env)[0], 0)
        rc, so, _ = self.run_tool("brain_route.py", "--query", "airflow notes kept hidden", "--json", env=env)
        lab = {s["name"]: s["loads_at_start"] for s in json.loads(so)["skills"]}
        self.assertEqual(lab["kept"], "yes")
        self.assertTrue(lab["hidden"].startswith("no (switched off"))
        # a Codex session's end-of-session analysis reads Codex's own log format
        sid = self.session()
        rollout = write(self.tmp.name, "rollout.jsonl", json.dumps({"payload": {"type": "token_count", "info": {"total_token_usage":
                        {"input_tokens": 900, "cached_input_tokens": 800, "output_tokens": 40, "reasoning_output_tokens": 5, "total_tokens": 940}}}}) + "\n")
        self.run_tool("brain_hooks.py", "post", "--agent", "codex", stdin=json.dumps({"session_id": "cx9", "tool_name": "exec_command",
                      "tool_input": {"cmd": "python3 brain_session.py new"}, "tool_response": json.dumps({"session": sid})}))
        self.run_tool("brain_hooks.py", "end", "--agent", "codex", stdin=json.dumps({"session_id": "cx9", "transcript_path": rollout, "cwd": self.tmp.name}))
        a = json.load(open(os.path.join(self.root, "sessions", sid, "analysis.json")))
        self.assertEqual((a["tokens"]["total"], a["tokens"]["output"]), (940, 40))

    def test_sleep_dry_run_and_gym_ratchet(self):
        write(self.root, "queue/s1-lesson.md", "---\ntitle: x\ntype: lesson\nstatus: candidate\nsource: sessions/s1/\n---\nCheck units before export.\n")
        write(self.root, "sessions/s1/meta.json", "{}")
        write(self.root, "queue/s2-lesson.md", "---\ntitle: y\ntype: lesson\nstatus: candidate\nsource: Brain System/x.md\n---\nTrust the notes.\n")
        rc, so, se = self.run_tool("brain_sleep.py", "--dry-run", "--no-gym")
        r = json.loads(so)
        self.assertEqual(len(r["lessons"]), 1)                                   # v2.1: s2 cites only a brain note -> not written
        digest = open(os.path.join(self.root, r["digest"]), encoding="utf-8").read()
        self.assertIn("s2-lesson.md", digest)
        self.assertFalse(os.path.exists(os.path.join(self.root, r["lessons"][0])))  # dry run writes no lesson
        self.assertFalse(os.path.exists(os.path.join(self.root, "state", "sleep.lock")))  # lock released
        code = ("import sys; sys.path.insert(0, %r); import gym; "
                "print(gym.ratchet({'a':1,'b':1,'c':0},{'a':1,'b':0,'c':1})[0], gym.ratchet({'a':0,'b':0,'c':0},{'a':1,'b':1,'c':1})[0], "
                "gym.ratchet({'a':0},{'a':1})[0])") % TOOLS
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.stdout.split(), ["False", "True", "False"], p.stderr)  # a loss blocks · 3 wins pass · 1 task = candidate only


class ExternalDriveTests(Brain):
    def test_scan_external_filters_folds_and_pages(self):
        drive = os.path.join(self.tmp.name, "DRIVE")
        sk = lambda rel, name, desc, body="Body in English.\n": write(drive, rel, f"---\nname: {name}\ndescription: {desc}\n---\n# {name}\n{body}")
        sk("repo/skills/good-one/SKILL.md", "good-one", "Make neat wind tunnel charts for airflow studies")
        sk("repo/docs/ja-JP/skills/good-one/SKILL.md", "good-one", "Make neat charts", "日本語のテキストです。" * 20)
        sk("repo/skills/zh-only/SKILL.md", "zh-only", "为 智能体 锻造完整的 设定")
        sk("repo/tests/fixtures/fake/SKILL.md", "fake", "Fixture skill used by tests only")
        sk("snap/hermes-agent/creative/thing/SKILL.md", "thing", "A creative helper")
        sk("snap/other/hermes-gateway/SKILL.md", "hermes-gateway", "Run the gateway")
        sk("snap/blender-export/SKILL.md", "blender-export", "Export Blender models for airflow simulation tools")
        for app in ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet",
                    "kilo", "lima", "mike", "november", "oscar", "papa"]:
            sk(f"apps/{app}-automation/SKILL.md", f"{app}-automation", f"Automate {app.title()} tasks via Rube MCP (Composio). Always search tools first")
        write(drive, "repo/.git/config", '[remote "origin"]\n\turl = git@github.com:someone/airflow-kit.git\n')
        write(drive, "repo/.git/logs/HEAD", "0000 1111 A <a@b> 1793000000 +0100\tcommit: x\n")
        before = {os.path.join(d, f): os.path.getmtime(os.path.join(d, f)) for d, _, fs in os.walk(drive) for f in fs}
        write(self.root, "state/vault-policy.json", json.dumps({"english_only_descriptions": True}))  # the catalogue's English-only option
        rc, so, se = self.run_tool("scan_external.py", "--root", drive, "--label", "TESTDRIVE")
        self.assertEqual(rc, 0, se)
        res = json.loads(so)
        self.assertEqual(res["templated_skills_folded"], 16)
        self.assertEqual(res["excluded"].get("belongs to the removed Hermes agent"), 2)
        self.assertEqual(res["excluded"].get("test, fixture, backup or archive folder"), 1)
        self.assertEqual(res["excluded"].get("skill text not in English"), 1)
        self.assertEqual(res["excluded"].get("no English description"), 1)
        after = {os.path.join(d, f): os.path.getmtime(os.path.join(d, f)) for d, _, fs in os.walk(drive) for f in fs}
        self.assertEqual(before, after)  # the drive is never written
        cat = json.load(open(os.path.join(self.root, "state", "external", "TESTDRIVE.json")))
        good = [s for s in cat["skills"] if s["name"] == "good-one"][0]
        self.assertNotIn("ja-JP", good["location"])  # the English original wins over a translation
        self.assertEqual(cat["repos"][0]["slug"], "someone/airflow-kit")
        rc, so, se = self.run_tool("brain_index.py")
        self.assertEqual(rc, 0, se)
        toc = os.path.join(self.root, "Brain System", "00-toc")
        page = open(os.path.join(toc, "drive-testdrive.md"), encoding="utf-8").read()
        self.assertIn("Skill names already installed on this Mac: 1", page)  # blender-export is installed in the fixture
        self.assertTrue(os.path.exists(os.path.join(toc, "drive-testdrive-repos.md")))
        self.assertIn("[[drive-testdrive]]", open(os.path.join(toc, "toc-home.md"), encoding="utf-8").read())
        rc, so, _ = self.run_tool("brain_route.py", "--query", "wind tunnel charts")
        self.assertIn("good-one", so)
        self.assertIn("no: on drive TESTDRIVE", so)


class ScannerEscapeTest(unittest.TestCase):
    def test_table_escaped_pipe_resolves(self):
        with tempfile.TemporaryDirectory() as t:
            v, o = os.path.join(t, "v"), os.path.join(t, "o")
            write(v, "Note.md", "# Note\nx\n")
            write(v, "a.md", "| col |\n|---|\n| [[Note\\|alias]] |\n")
            subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "vault_scan.py"), "--vault", v, "--out", o], check=True, capture_output=True)
            st = [json.loads(l)["status"] for l in open(os.path.join(o, "links.jsonl"))]
            self.assertEqual(st, ["resolved"])


if __name__ == "__main__":
    unittest.main()
