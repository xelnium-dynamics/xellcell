#!/usr/bin/env python3
"""
Regression & integration suite for Hydro Brain 2 (v5):
1. Gym live config propagation (HS.CFG_OVERRIDE), expanded PROTECTED surface, _complexity() tie-break.
2. retrieval-log.jsonl "mark" vs "action" unification across brain_learn.py & brain_sleep.py.
3. Full Harness² lifecycle: HARNESS_PARTS, EXPERIENCE.md, AUTO-HYPOTHESES.md, composed PAIR-BETTER,
   state/harness2-experience.jsonl, Brain System/lessons/harness2-experience.md, and learn_session() close.
4. judge_typed.py status >50% escalation rewrite alert & cold-start check.
5. vault_audit.py Karpathy provenance / self-citation loop guard.
6. brain_dream.py idle/load/lock safety, Claude/Codex thinking/reasoning mining + self/ privacy sanitization,
   missing-node graph weaving + scan verification + rollback safety, contradiction lint, incremental cursor skip,
   launchd plist spec, and MCP brain_dream endpoint.
7. Readiness card & AGENTS.md compatibility limits.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import brain_dream  # noqa: E402
import brainlib as B  # noqa: E402
import gym  # noqa: E402
import hydro_skills as HS  # noqa: E402


def _write(base, rel, content):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)
    return p


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class HydroBrain2UnitAndIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "hb2")
        self.vault = os.path.join(self.root, "Brain System")
        os.makedirs(self.vault, exist_ok=True)
        os.makedirs(os.path.join(self.root, "state", "eval"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "sessions"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "queue"), exist_ok=True)
        os.makedirs(os.path.join(self.root, "reports"), exist_ok=True)
        self.skills = os.path.join(self.tmp.name, "skills")
        _write(
            self.skills,
            "threejs-shaders/SKILL.md",
            "---\nname: threejs-shaders\ndescription: Custom Three.js GLSL vertex and fragment shaders and postprocessing\n---\nShader guide\n",
        )
        roots = os.path.join(self.tmp.name, "roots.json")
        with open(roots, "w", encoding="utf-8") as fh:
            json.dump([{"path": self.skills, "agent": "Claude, Codex", "kind": "brain-library", "autoload": "no"}], fh)
        self.env = dict(os.environ, BRAIN_ROOT=self.root, BRAIN_SKILL_ROOTS=roots, BRAIN_NO_SLEEP="1")
        self.env.pop("BRAIN_VAULT", None)
        self.env.pop("BRAIN_INDEX_DB", None)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, script, *args, stdin=None):
        p = subprocess.run(
            [sys.executable, "-I", os.path.join(TOOLS, script), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=self.env,
            cwd=self.root,
        )
        return p.returncode, p.stdout, p.stderr

    def test_gym_live_cfg_override_and_protected_surface(self):
        import brain_hooks as H
        prev_override = dict(HS.CFG_OVERRIDE)
        try:
            HS.CFG_OVERRIDE.clear()
            HS.CFG_OVERRIDE["skill_threshold"] = 999.0
            self.assertEqual(HS.load_config()["skill_threshold"], 999.0)
            self.assertEqual(H.pick_skills("Custom Three.js GLSL shader postprocessing"), [])
        finally:
            HS.CFG_OVERRIDE.clear()
            HS.CFG_OVERRIDE.update(prev_override)

        for req in ("tools/hydro_skills.py", "state/skill-families.json", "tools/tier0.py"):
            self.assertIn(req, gym.PROTECTED)

        base_cfg = dict(HS.DEFAULTS)
        tweaked_cfg = dict(HS.DEFAULTS, skill_threshold=7.0, off_factor=1.5)
        self.assertEqual(gym._complexity(base_cfg), 0)
        self.assertEqual(gym._complexity(tweaked_cfg), 2)

    def test_fetch_mark_and_action_unified_in_learn_and_sleep(self):
        _write(self.vault, "system/doc.md", "---\ntitle: Doc\nsummary: base doc\n---\n# Doc\nBase engineering rule.\n")
        self.assertEqual(self._run("brain_index.py")[0], 0)

        sid = "20261113-010000-claude-t5a1"
        work_cwd = os.path.join(self.tmp.name, "proj")
        os.makedirs(work_cwd, exist_ok=True)
        rc, _, se = self._run(
            "brain_session.py", "new", "--agent", "claude", "--cwd", work_cwd, "--title", "Shader fix",
            "--lane", "fast", "--scope", "engineering", "--request", "Build Three.js GLSL shader",
        )
        self.assertEqual(rc, 0, se)
        # Rename session dir or look up newest session id
        actual_sid = sorted(os.listdir(os.path.join(self.root, "sessions")))[-1]
        sdir = os.path.join(self.root, "sessions", actual_sid)
        with open(os.path.join(sdir, "retrieval-log.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"mark": "missing", "what": "custom-lut-baker skill"}) + "\n")
            fh.write(json.dumps({"mark": "used", "path": os.path.join(self.skills, "threejs-shaders", "SKILL.md")}) + "\n")
            fh.write(json.dumps({"mark": "rejected", "path": "Brain System/system/doc.md", "reason": "wrong scope"}) + "\n")
            fh.write(json.dumps({"mark": "rejected", "path": "Brain System/system/doc.md", "reason": "stale"}) + "\n")

        _write(sdir, "task-summary.md", "# Task Summary\nDelivered: glsl pipeline\nVerified: pytest exit 0\n")
        _write(sdir, "brain-summary.md", "# Brain Summary\nLesson: Always bind float32 render targets cleanly.\n")
        rc, so, se = self._run("brain_session.py", "close", "--session", actual_sid, "--summary", "done")
        self.assertEqual(rc, 0, se)
        learn = json.loads(_read(os.path.join(sdir, "learn.json")))
        self.assertIn("threejs-shaders", learn["skills_used"])

        tel = json.loads(_read(os.path.join(self.root, "state", "skill-telemetry.json")))
        self.assertGreaterEqual(tel["skills"]["threejs-shaders"]["used"], 1)

        rc, so, se = self._run("brain_sleep.py", "--dry-run")
        self.assertEqual(rc, 0, se)
        dig = json.loads(so)["digest"]
        dig_txt = _read(os.path.join(self.root, dig))
        self.assertIn("custom-lut-baker skill", dig_txt)
        self.assertIn("Card rejected 2x", dig_txt)

    def test_harness2_experience_parts_and_close_learn(self):
        _write(self.vault, "lessons/sample.md", "---\ntitle: Shader lesson\ntype: lesson\nstatus: released\nscope_class: engineering\nsources:\n  - sessions/seed/\n---\n# Shader lesson\nAlways validate GLSL compile logs in WebGL shader probes.\n")
        self.assertEqual(self._run("brain_index.py")[0], 0)
        ws = os.path.join(self.tmp.name, "ws")
        _write(ws, "check.py", "import sys; sys.exit(1)\n")
        os.makedirs(os.path.join(self.root, "state"), exist_ok=True)
        with open(os.path.join(self.root, "state", "harness2-experience.jsonl"), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"session": "seed-0", "subtask": "fix shader compile probe", "result": "improved", "parts": {"general": "scripts"}}) + "\n")

        rc, _, se = self._run(
            "brain_session.py", "new", "--agent", "claude", "--cwd", ws, "--title", "Fix probe",
            "--lane", "standard", "--scope", "engineering", "--request", "Fix shader check probe",
        )
        self.assertEqual(rc, 0, se)
        sid = sorted(os.listdir(os.path.join(self.root, "sessions")))[-1]
        sdir = os.path.join(self.root, "sessions", sid)
        _write(sdir, "verdict-01.json", json.dumps({"checks": [{"command": "python3 check.py", "pass": False, "tail": "exit 1"}]}))

        rc, so, se = self._run("harness2.py", "start", "--session", sid, "--subtask", "fix shader compile probe", "--check", "python3 check.py")
        self.assertEqual(rc, 0, se)
        rc, so, se = self._run("harness2.py", "adapt", "--session", sid)
        self.assertEqual(rc, 0, se)
        ad_res = json.loads(so)
        self.assertEqual(len(ad_res["parts_catalog"]), 8)
        self.assertGreaterEqual(ad_res["experience_hits"], 1)
        ctx = os.path.join(sdir, "harness2", "context")
        self.assertTrue(os.path.isfile(os.path.join(ctx, "EXPERIENCE.md")))
        self.assertTrue(os.path.isfile(os.path.join(ctx, "AUTO-HYPOTHESES.md")))
        self.assertIn("seed-0", _read(os.path.join(ctx, "EXPERIENCE.md")))

        patch = "--- a/check.py\n+++ b/check.py\n@@ -1 +1 @@\n-import sys; sys.exit(1)\n+import sys; sys.exit(0)\n"
        patch_p = os.path.join(self.tmp.name, "fix.patch")
        with open(patch_p, "w", encoding="utf-8") as fh:
            fh.write(patch)

        self.assertEqual(self._run("harness2.py", "probe", "--session", sid, "--arm", "reference")[0], 0)
        rc, _, se = self._run(
            "harness2.py", "propose", "--session", sid,
            "--general", "Make check deterministic", "--domain", "Validate shader target",
            "--general-patch", patch_p, "--inv-part", "scripts", "--dom-part", "skills",
        )
        self.assertEqual(rc, 0, se)
        self.assertEqual(self._run("harness2.py", "probe", "--session", sid, "--arm", "general")[0], 0)
        self.assertEqual(self._run("harness2.py", "compose", "--session", sid, "--keep", "general")[0], 0)
        self.assertEqual(self._run("harness2.py", "probe", "--session", sid, "--arm", "composed")[0], 0)
        rc, so, se = self._run("harness2.py", "compare", "--session", sid)
        self.assertEqual(rc, 0, se)
        self.assertEqual(json.loads(so)["vs_reference"]["composed"], "win")

        _write(sdir, "task-summary.md", "# Task Summary\nDelivered: fixed probe\nVerified: check.py exit 0\n")
        _write(sdir, "brain-summary.md", "# Brain Summary\nLesson: Always check shader exit codes cleanly.\n")
        rc, so, se = self._run("harness2.py", "close", "--session", sid)
        self.assertEqual(rc, 0, se)
        cl = json.loads(so)
        self.assertEqual(cl["result"], "improved")
        self.assertEqual(cl["parts"], {"general": "scripts", "domain": "skills"})
        self.assertTrue(os.path.isfile(os.path.join(self.root, "state", "harness2-experience.jsonl")))
        self.assertTrue(os.path.isfile(os.path.join(self.vault, "lessons", "harness2-experience.md")))
        self.assertTrue(os.path.isfile(os.path.join(sdir, "learn.json")))

    def test_judge_typed_status_and_escalation_alert(self):
        qdir = os.path.join(self.root, "judge", "questions")
        gdir = os.path.join(self.root, "judge", "gold", "owner")
        _write(
            qdir,
            "REQ-MET.json",
            json.dumps({"id": "REQ-MET", "question": "Met?", "labels": ["yes", "no"], "state_fields": ["x"], "threshold": {"value": None}}),
        )
        _write(
            gdir,
            "REQ-MET.jsonl",
            "".join(json.dumps({"state": {"x": i}, "label": "yes", "source": "owner"}) + "\n" for i in range(32)),
        )
        _write(
            self.root,
            "judge/log.jsonl",
            "".join(json.dumps({"question_id": "REQ-MET", "tier": 2, "escalated_from": 1}) + "\n" for _ in range(5))
            + json.dumps({"question_id": "REQ-MET", "tier": 1, "escalated_from": None}) + "\n",
        )
        rc, so, se = self._run("judge_typed.py", "status")
        self.assertEqual(rc, 0, se)
        st = json.loads(so)
        self.assertFalse(st["questions"]["REQ-MET"]["cold_start"])
        self.assertGreater(st["questions"]["REQ-MET"]["escalation_rate"], 0.5)
        self.assertTrue(st["questions"]["REQ-MET"]["rewrite_alert"])
        self.assertEqual(st["alerts"][0]["action"], "rewrite_question_not_threshold")

    def test_vault_audit_self_citation_guard(self):
        _write(
            self.vault,
            "lessons/loop-only.md",
            "---\ntitle: Secondary loop\ntype: lesson\nstatus: candidate\nsources:\n  - Brain System/lessons/another-lesson.md\n---\n# Secondary loop\nOnly cites another synthesis note.\n",
        )
        _write(
            self.vault,
            "lessons/grounded.md",
            "---\ntitle: Grounded\ntype: lesson\nstatus: candidate\nsources:\n  - sessions/20261113-0001/\n---\n# Grounded\nCites real session evidence.\n",
        )
        out = os.path.join(self.tmp.name, "audit")
        rc, so, se = self._run("vault_audit.py", "--vault", self.vault, "--out", out)
        self.assertEqual(rc, 0, se)
        rep = json.loads(so)
        self.assertEqual(rep["self_citation_warnings"], 1)
        audit_md = _read(os.path.join(out, "audit.md"))
        self.assertIn("lessons/loop-only.md", audit_md)
        self.assertNotIn("lessons/grounded.md", audit_md)

    def test_brain_dream_end_to_end_graph_privacy_and_mcp(self):
        # 1. Vault with two isolated matching notes + one private self note + contradicting lessons
        _write(
            self.vault,
            "concepts/webgl-shaders.md",
            "---\ntitle: WebGL Shaders\ntype: domain\ntags: [threejs, shaders, glsl]\nsummary: Custom GLSL uniform buffers for Three.js\n---\n# WebGL Shaders\nAlways validate GLSL uniform alignment and float textures in WebGL postprocessing pipelines.\n",
        )
        _write(
            self.vault,
            "concepts/threejs-postfx.md",
            "---\ntitle: Three.js PostFX\ntype: domain\ntags: [threejs, glsl]\nsummary: Three.js postprocessing shader passes\n---\n# Three.js PostFX\nPostprocessing passes rely on WebGL float textures and GLSL uniform validation.\n",
        )
        _write(
            self.vault,
            "self/private-journal.md",
            "---\ntitle: Private\ntype: personal\n---\n# Private\nPersonal webgl shader postprocessing glsl secret thoughts.\n",
        )
        _write(
            self.vault,
            "lessons/rule-pos.md",
            "---\ntitle: Rule Pos\ntype: lesson\nsources:\n  - sessions/s1/\n---\n# Rule Pos\nAlways enable strict mipmap texture validation for custom shader passes.\n",
        )
        _write(
            self.vault,
            "lessons/rule-neg.md",
            "---\ntitle: Rule Neg\ntype: lesson\nsources:\n  - sessions/s2/\n---\n# Rule Neg\nNever enable mipmap texture validation during render target swap.\n",
        )
        self.assertEqual(self._run("brain_index.py")[0], 0)

        # 2. Transcripts (Claude thinking + error + self leak, and Codex reasoning)
        tr_dir = os.path.join(self.tmp.name, "transcripts")
        _write(
            tr_dir,
            "claude-01.jsonl",
            "\n".join([
                json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Root cause: WebGL render targets silently fail when HalfFloatType lacks mipmap bounds."}]}}),
                json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Brain System/self/private-journal.md secret item alex@example.com should never leak."}]}}),
                json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "Error: build failed exit code 2 on glsl-validator"}]}}),
            ]) + "\n",
        )
        _write(
            tr_dir,
            "codex/rollout-01.jsonl",
            "\n".join([
                json.dumps({"type": "response_item", "payload": {"type": "reasoning", "summary": [{"text": "Fixed by checking realpath before writing FTS5 sqlite index under lock."}]}}),
                json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Actually always run vault_scan after linking notes in Brain System."}}),
            ]) + "\n",
        )

        # 3. First dream cycle (--once --apply-links)
        rc, so, se = self._run("brain_dream.py", "--once", "--apply-links", "--transcript-roots", tr_dir)
        self.assertEqual(rc, 0, se)
        res = json.loads(so)
        self.assertEqual(res["status"], "dreamed")
        self.assertEqual(res["transcripts"]["scanned_transcripts"], 2)
        self.assertGreaterEqual(res["transcripts"]["new_reflections"], 3)
        self.assertGreaterEqual(res["graph"]["bridges_found"], 1)
        self.assertGreaterEqual(res["graph"]["links_woven"], 1)
        self.assertFalse(res["graph"]["rolled_back"])
        self.assertGreaterEqual(len(res["lint"]["contradictions"]), 1)

        refl_txt = _read(os.path.join(self.vault, "history", "learnings", "dream-reflections.md"))
        self.assertIn("HalfFloatType", refl_txt)
        self.assertIn("FTS5 sqlite index", refl_txt)
        self.assertNotIn("private-journal", refl_txt)
        self.assertNotIn("alex@example.com", refl_txt)

        map_txt = _read(os.path.join(self.vault, "history", "learnings", "dream-map.md"))
        self.assertNotIn("self/", map_txt)
        sh_txt = _read(os.path.join(self.vault, "concepts", "webgl-shaders.md"))
        self.assertIn("[[concepts/threejs-postfx|", sh_txt)

        # Verify vault_scan + vault_audit remain clean (0 ghosts, 0 errors)
        scan_out = os.path.join(self.tmp.name, "scan")
        rc, so, se = self._run("vault_scan.py", "--vault", self.vault, "--out", scan_out)
        self.assertEqual(rc, 0, se)
        self.assertIn("ghosts=0", so)
        audit_out = os.path.join(self.tmp.name, "aud")
        rc, so, se = self._run("vault_audit.py", "--vault", self.vault, "--out", audit_out)
        self.assertEqual(rc, 0, se)
        self.assertEqual(json.loads(so)["errors"], 0)

        # 4. Second run skips unchanged transcripts via incremental cursor
        rc, so, se = self._run("brain_dream.py", "--once", "--transcript-roots", tr_dir)
        self.assertEqual(rc, 0, se)
        self.assertEqual(json.loads(so)["transcripts"]["scanned_transcripts"], 0)

        # 5. Idle/load guard skips cleanly when load exceeds max-load 0.0
        rc, so, se = self._run("brain_dream.py", "--if-idle", "--max-load", "0.0")
        self.assertEqual(rc, 0, se)
        self.assertEqual(json.loads(so)["status"], "skipped")

        # 6. sleep.lock yields cleanly
        _write(self.root, "state/sleep.lock", "locked\n")
        rc, so, se = self._run("brain_dream.py", "--once")
        self.assertEqual(json.loads(so)["status"], "skipped")
        os.unlink(os.path.join(self.root, "state", "sleep.lock"))

        # 7. LaunchAgent plist hygiene check
        pl = brain_dream.launchd_plist_dict(interval=1800, min_idle=180)
        self.assertEqual(pl["Label"], "com.hydrobrain.dream")
        self.assertEqual(pl["Nice"], 15)
        self.assertTrue(pl["LowPriorityIO"])

        # 8. MCP brain_dream server integration
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "brain_dream", "arguments": {"mode": "status"}}},
        ]
        rc, so, se = self._run("brain_mcp.py", stdin="\n".join(json.dumps(m) for m in msgs) + "\n")
        self.assertEqual(rc, 0, se)
        out = {d["id"]: d for d in map(json.loads, so.splitlines())}
        self.assertEqual(len(out[2]["result"]["tools"]), 10)
        self.assertFalse(out[3]["result"].get("isError"))
        self.assertIn("cycles", out[3]["result"]["content"][0]["text"])

    def test_protocol_sizes_and_v3_invariants_preserved(self):
        agents_txt = _read(os.path.join(ROOT, "AGENTS.md"))
        self.assertLessEqual(len(agents_txt), 6000)
        self.assertIn("v3 Fable Art", agents_txt)
        p = subprocess.run(
            [sys.executable, "-I", os.path.join(TOOLS, "brain_start.py"), "--agent", "claude", "--format", "text"],
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertLess(len(p.stdout), 4057)
        self.assertIn('v3 "Fable Art"', p.stdout)


if __name__ == "__main__":
    unittest.main()
