#!/usr/bin/env python3
"""
Tests for HYDRO BRAIN (v4) upgrades:
- Unified skill calling (hydro_skills.py): 2-char tokens, .js normalization,
  conversational noise suppression, Three.js/R3F, Figma, Brand/Northwind Cafe, UI/UX.
- Smart contract lint re-route (route_fingerprint in meta.json).
- Fast post-session improvement layer (brain_learn.py): multi-format extraction,
  idempotency, history/learnings ledger, skill telemetry, incremental FTS5 index, close integration.
- Hydro MCP additions (brain_find_skills, brain_learn_session), hydro_install, hydro_verify, tree_validate.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import hydro_skills  # noqa: E402
import tree_validate  # noqa: E402


def _write(base, rel, content):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


FIXTURE_SKILLS = [  # a small, fixed skill library, so routing tests run the same on every machine
    ("threejs-shaders", "Custom GLSL vertex and fragment shaders for three.js: uniforms, varyings, shader chunks, extending built-in materials"),
    ("threejs-postprocessing", "Three.js post-processing: composer pass chains and renderer effects such as bloom, depth of field and ambient occlusion"),
    ("threejs-patterns", "Use when building Three.js 3D scenes, rooms, interiors or product models with the latest three.js release"),
    ("threejs-fundamentals", "Three.js scene setup: scenes and fog, cameras, the renderer and tone mapping, the animation loop and transforms"),
    ("figma-3d-transforms", "Add or edit 3D transforms in Figma: depth, perspective, z-axis rotation, tilt, isometric and parallax looks"),
    ("figma-ui-design", "Figma UI design, component library, design tokens, Auto Layout, Figma variables and Figma-to-code engineering"),
    ("brand-packaging", "Create a packaging design brief: structure, visual direction, hierarchy, materials and unboxing experience"),
    ("brand-identity", "Create a visual identity brief for a brand: logo direction, color palette, typography and imagery style"),
    ("ui-taste", "Anti-slop frontend taste and art direction: landing pages, heroes, UI polish when a page looks generic or AI-made"),
    ("ui-audit-reality-check", "Audit a web app UI for AI slop, weak visual hierarchy and generic layouts against real product references"),
    ("accessibility-audit", "Accessibility audit for web UI: WCAG contrast, focus states, keyboard navigation and screen reader labels"),
    ("seo-audit", "Run a comprehensive SEO audit: keyword research, on-page analysis, content gaps and technical checks"),
    ("pptx", "Create, read or edit PowerPoint slide decks and pitch decks (.pptx)"),
    ("xlsx", "Open, read, edit or create spreadsheet files (.xlsx, .csv) and their formulas"),
    ("mechanical-cad-build123d", "Build dimension-true mechanical parts in Python with build123d and export STEP and STL"),
    ("deep-research", "Research a topic across multiple sources, compare options and write a cited brief"),
    ("code-review", "Review code changes for security, performance and correctness before merging"),
]


class HydroSkillsUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [(n, d, f"/skills/{n}/SKILL.md", "Claude, Codex", "brain-library", "no") for n, d in FIXTURE_SKILLS]

    def test_tokenization_short_domain_and_dot_js(self):
        toks = hydro_skills.tokenize("Build a 3D UI/UX HUD in Three.js and p5.js with CV tracking")
        self.assertIn("3d", toks)
        self.assertIn("ui", toks)
        self.assertIn("ux", toks)
        self.assertIn("cv", toks)
        self.assertIn("threejs", toks)
        self.assertIn("p5js", toks)

    def test_promoted_skills_not_marked_off(self):
        by_name = {r[0]: r for r in self.rows if r[4] == "brain-library"}
        for name in ("brand-identity", "brand-packaging", "threejs-shaders", "figma-ui-design", "ui-taste", "ui-ux-pro-max"):
            if name in by_name:
                self.assertEqual(by_name[name][5], "no", f"{name} should be promoted without off penalty")

    def _top_names(self, prompt, scope="general", strict=True):
        ranked = hydro_skills.rank_skills(
            prompt, self.rows, who="claude", scope=scope, n=6,
            strict_agent=strict, include_drives=not strict,
        )
        return [r["short"] for r in ranked]

    def test_pillar_routing_threejs_figma_brand_uiux(self):
        three = self._top_names("Build an interactive Three.js WebGL scene with custom GLSL shader material and bloom")
        self.assertTrue(any(s in three for s in ("threejs-shaders", "threejs-postprocessing", "threejs-patterns")), three)

        figma = self._top_names("Apply 3D card perspective transforms and auto-layout design tokens in Figma")
        self.assertTrue(any(s in figma for s in ("figma-3d-transforms", "figma-ui-design", "figma-design-to-code", "figma-pilot")), figma)

        nova = self._top_names("Design luxury dark red espresso bag packaging and brand identity for Northwind Cafe", scope="brand")
        self.assertTrue(any(s in nova for s in ("brand-packaging", "brand-identity", "brand")), nova)

        uiux = self._top_names("Audit web app UI for AI slop, accessibility WCAG contrast, and visual hierarchy")
        self.assertTrue(any(s in uiux for s in ("ui-audit-reality-check", "ui-taste", "accessibility-audit", "ui-ux-pro-max")), uiux)

    def test_conversational_negatives_stay_silent(self):
        for prompt in (
            "Good job, please close the current brain session and summarize what we decided.",
            "Can you make the explanation shorter and clearer?",
            "Yes, go ahead with that fix and run the tests again.",
            "Thanks, let us pause here until tomorrow.",
            "Read HANDOFF.md",
        ):
            self.assertEqual(self._top_names(prompt), [], f"False alarm on: {prompt}")


class SmartSessionAndLearnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "hydro")
        v = os.path.join(self.root, "Brain System")
        _write(v, "projects/northwind-cafe/Overview.md", "---\ntitle: Northwind Cafe Overview\nsummary: dark red espresso brand\n---\n# Northwind Cafe\nOverview note.\n")
        _write(v, "domains/design/Packaging guide.md", "---\ntitle: Packaging guide\nsummary: structural dielines and foil finish\n---\n# Packaging guide\nUse matte lamination.\n")
        _write(v, "capabilities/skill-gap.md", "---\ntitle: Skill gap\nsummary: capability tracking\n---\n# Gap\nLog missing tools.\n")
        skills_dir = os.path.join(self.root, "skills")
        _write(skills_dir, "brand-packaging/SKILL.md", "---\nname: brand-packaging\ndescription: Luxury packaging, structural dielines, print specs, and espresso pouch finishes.\n---\n# brand-packaging\nUse Pantone spot colors.\n")
        _write(skills_dir, "threejs-shaders/SKILL.md", "---\nname: threejs-shaders\ndescription: Custom GLSL vertex and fragment shaders in Three.js r187 WebGL scenes.\n---\n# threejs-shaders\nManage uniforms cleanly.\n")
        _write(self.root, "state/folder-projects.json", json.dumps({os.path.join(self.tmp.name, "work", "nova"): "northwind-cafe"}))
        _write(self.root, "state/synonyms.json", open(os.path.join(ROOT, "state", "synonyms.json"), encoding="utf-8").read())
        _write(self.root, "state/skill-families.json", open(os.path.join(ROOT, "state", "skill-families.json"), encoding="utf-8").read())
        _write(self.root, "state/harness-config.json", open(os.path.join(ROOT, "state", "harness-config.json"), encoding="utf-8").read())
        os.makedirs(os.path.join(self.tmp.name, "work", "nova"), exist_ok=True)
        roots = _write(self.tmp.name, "roots.json", "[]")
        self.env = dict(os.environ, BRAIN_ROOT=self.root, BRAIN_SKILL_ROOTS=roots, BRAIN_NO_SLEEP="1")
        self.env.pop("BRAIN_VAULT", None)
        self.env.pop("BRAIN_INDEX_DB", None)
        self._run("brain_index.py")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, script, *args):
        return subprocess.run(
            [sys.executable, "-I", os.path.join(TOOLS, script), *args],
            capture_output=True, text=True, env=self.env, cwd=self.root,
        )

    def test_smart_lint_reroute_and_close_fast_learn(self):
        # 1. Create session (initially without request so no retrieval yet)
        p = self._run(
            "brain_session.py", "new", "--agent", "claude",
            "--cwd", os.path.join(self.tmp.name, "work", "nova"),
            "--title", "Nova packaging", "--lane", "standard", "--scope", "general",
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        sid = json.loads(p.stdout)["session"]
        sdir = os.path.join(self.root, "sessions", sid)
        cpath = os.path.join(sdir, "contract.md")
        c = open(cpath, encoding="utf-8").read()
        c = (
            c.replace("<paste the owner's request exactly>", "Design Northwind Cafe dark red espresso packaging")
             .replace("scope_class: general", "scope_class: brand")
             .replace("- R1: … — check: …", "- R1: Deliver Northwind Cafe pouch packaging spec — check: test -f spec.md")
             .replace("-\n", "- spec.md\n", 1)
        )
        with open(cpath, "w", encoding="utf-8") as f:
            f.write(c)

        # 2. First lint creates retrieval-01.md and stores route_fingerprint
        p_lint1 = self._run("brain_session.py", "lint", "--session", sid)
        self.assertEqual(p_lint1.returncode, 0, p_lint1.stdout + p_lint1.stderr)
        self.assertTrue(os.path.exists(os.path.join(sdir, "retrieval-01.md")))
        fp1 = json.load(open(os.path.join(sdir, "meta.json")))["route_fingerprint"]

        # 3. Repeated identical lint does not spam retrieval-02.md
        p_lint2 = self._run("brain_session.py", "lint", "--session", sid)
        self.assertEqual(p_lint2.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(sdir, "retrieval-02.md")))

        # 4. Updating Deliverables triggers smart re-route -> retrieval-02.md
        with open(cpath, "w", encoding="utf-8") as f:
            f.write(c.replace("Deliver Northwind Cafe pouch packaging spec", "Build custom Three.js GLSL WebGL pouch viewer shader"))
        p_lint3 = self._run("brain_session.py", "lint", "--session", sid)
        self.assertEqual(p_lint3.returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(sdir, "retrieval-02.md")))
        fp2 = json.load(open(os.path.join(sdir, "meta.json")))["route_fingerprint"]
        self.assertNotEqual(fp1, fp2)
        self.assertEqual(json.load(open(os.path.join(sdir, "meta.json")))["scope_class"], "brand")

        # 5. Write rich summaries + retrieval log (using both table + markdown bullet headings)
        _write(sdir, "retrieval-log.jsonl", "\n".join([
            json.dumps({"action": "used", "path": "skills/brand-packaging/SKILL.md"}),
            json.dumps({"action": "missing", "what": "metallic-foil-dieline-template"}),
        ]) + "\n")
        _write(sdir, "task-summary.md", "\n".join([
            "# Task summary — Nova packaging",
            "| Delivered | Print-ready dieline spec and WebGL shader preview |",
            "| Verified (requirement → tier → evidence) | R1 → Tier 0 → spec.md verified |",
            "",
            "## Gotchas",
            "- Matte dark-red ink shifts darker on uncoated kraft stock unless white underbase is specified (zymurgy77token).",
            "",
            "## What worked",
            "- Exporting CMYK + Pantone 188C separation proof prevented press shift.",
        ]) + "\n")
        _write(sdir, "brain-summary.md", "\n".join([
            "# Brain Summary — Nova packaging",
            "| Field | Content |",
            "|---|---|",
            "| Proposed lesson | Always specify white underbase ink under dark-red kraft espresso bags (zymurgy77token). |",
            "| Where the brain helped | skills/brand-packaging/SKILL.md gave finish parameters. |",
        ]) + "\n")

        # 6. Close session -> auto-invokes brain_learn + rebuilds index
        p_close = self._run("brain_session.py", "close", "--session", sid, "--no-judge", "unit test")
        self.assertEqual(p_close.returncode, 0, p_close.stdout + p_close.stderr)
        res = json.loads(p_close.stdout)
        self.assertEqual(res["status"], "closed")
        self.assertIn("learn", res)
        self.assertEqual(res["learn"]["status"], "learned")

        # Verify learn.json, history/learnings ledger, queue, and skill-telemetry
        learn = json.load(open(os.path.join(sdir, "learn.json")))
        self.assertGreaterEqual(learn["insights_count"], 2)
        ledger = os.path.join(self.root, "Brain System", "history", "learnings", "northwind-cafe.md")
        self.assertTrue(os.path.exists(ledger))
        ledger_txt = open(ledger, encoding="utf-8").read()
        self.assertIn("zymurgy77token", ledger_txt)
        tel = json.load(open(os.path.join(self.root, "state", "skill-telemetry.json")))
        self.assertGreaterEqual(tel["skills"]["brand-packaging"]["used"], 1)

        # 7. Idempotency: re-running learn_session with force=False skips cleanly
        p_again = self._run("brain_learn.py", "--session", sid)
        self.assertEqual(p_again.returncode, 0, p_again.stderr)
        self.assertEqual(json.loads(p_again.stdout)["status"], "skipped_already_learned")

        # 8. Fast incremental FTS5 indexing outside full build: simulate new note via brain_learn --no-index vs refresh
        p_route = self._run("brain_route.py", "--query", "zymurgy77token kraft ink", "--scope", "brand", "--json")
        self.assertEqual(p_route.returncode, 0)
        notes = [n["path"] for n in json.loads(p_route.stdout)["notes"]]
        self.assertTrue(any("history/learnings/northwind-cafe.md" in np for np in notes), notes)


class HydroToolingAndVerifyTests(unittest.TestCase):
    def test_mcp_find_skills_and_tree_validate(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "brain_find_skills",
                "arguments": {"request": "Three.js custom GLSL shader and postprocessing", "limit": 4},
            }},
        ]
        p = subprocess.run(
            [sys.executable, "-I", os.path.join(TOOLS, "brain_mcp.py")],
            input="\n".join(json.dumps(m) for m in msgs) + "\n",
            capture_output=True, text=True, cwd=ROOT,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        out = {d["id"]: d for d in map(json.loads, p.stdout.splitlines())}
        self.assertFalse(out[3]["result"].get("isError"), out[3])
        matches = json.loads(out[3]["result"]["content"][0]["text"])
        self.assertGreaterEqual(len(matches), 1)
        self.assertIn("score", matches[0])
        self.assertIn("why", matches[0])

    def test_tree_validate_hydro_root(self):
        err, warn = tree_validate.validate(ROOT)
        self.assertEqual(err, [], f"tree_validate errors: {err}")

    def test_hydro_install_status_and_dry_run_readonly(self):
        for flag in ("--status", "--dry-run"):
            p = subprocess.run(
                [sys.executable, "-I", os.path.join(TOOLS, "hydro_install.py"), flag],
                capture_output=True, text=True, cwd=ROOT,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertTrue(json.loads(p.stdout))


if __name__ == "__main__":
    unittest.main()
