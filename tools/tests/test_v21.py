"""v2.1 "Ironclad" tests: one per fix from Argon's review (O1–O15, F1–F8) and the gaps found while building it (N1–N4).
Each test builds a throwaway brain (BRAIN_ROOT in a temp folder); the real brain is never touched.
Run: bash tools/test_all.sh"""
import json, os, shutil, struct, subprocess, sys, time, unittest

from test_live_tools import Brain, TOOLS, write

REAL = os.path.dirname(TOOLS)


class V21(Brain):
    def setUp(self):
        super().setUp()
        shutil.copytree(os.path.join(REAL, "judge", "questions"), os.path.join(self.root, "judge", "questions"))

    def hook(self, mode, data, env=None):
        env = dict(env or self.env, BRAIN_FREE_WRITE=os.path.expanduser("~/.claude") + os.sep)
        rc, so, se = self.run_tool("brain_hooks.py", mode, stdin=json.dumps(data), env=env)
        self.assertEqual(rc, 0, se)
        return json.loads(so)["hookSpecificOutput"]["permissionDecision"] if so.strip() else "allow"

    def bash(self, cmd, csid="nobody"):
        return self.hook("pre", {"session_id": csid, "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.root})

    def new(self, *extra, csid=None):
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "t", *extra)
        self.assertEqual(rc, 0, se)
        sid = json.loads(so)["session"]
        if csid:
            self.hook("post", {"session_id": csid, "tool_name": "Bash", "tool_input": {"command": "python3 brain_session.py new"},
                               "tool_response": {"stdout": so, "stderr": ""}})
        return sid

    # ---- O4 + N4: gates that hold ----
    def test_o4_self_gate_bypasses_denied(self):
        for cmd in ('cat "Brain System/./self/identity.md"', 'cat "Brain System/sel"*/identity.md',
                    'cd "Brain System" && cat self/identity.md',
                    "python3 -c \"print(open('Brain System/' + 'self/identity.md').read())\"",
                    'grep -rn the owner "Brain System"', "rg the owner", 'find . -name "*.md"'):
            self.assertEqual(self.bash(cmd), "deny", cmd)
        for cmd in ('grep -rn x "Brain System/projects"', 'grep -rn --exclude-dir=self x "Brain System"', 'ls "Brain System"',
                    'echo "words: rsync, cd x, grep -r, self/" | wc -c'):
            self.assertEqual(self.bash(cmd), "allow", cmd)
        g = lambda path: self.hook("pre", {"session_id": "n", "tool_name": "Grep", "tool_input": {"pattern": "x", "path": path}, "cwd": self.root})
        self.assertEqual((g(os.path.join(self.root, "Brain System")), g(os.path.join(self.root, "Brain System", "projects"))), ("deny", "allow"))

    def test_o4_writes_before_contract_denied(self):
        for cmd in ("python3 -c \"open('x.txt','w').write('1')\"", "sed -i '' s/a/b/ AGENTS.md", "perl -pi -e s/a/b/ x",
                    "curl -o out.html https://example.com", "git checkout -- tools/x.py", "dd if=/dev/zero of=f count=1", "tar -xf a.tar"):
            self.assertEqual(self.bash(cmd), "deny", cmd)
        for cmd in ("git status", "sed -n 1,3p AGENTS.md", "git commit -m 'a -> b'", "curl -s https://example.com"):
            self.assertEqual(self.bash(cmd), "allow", cmd)

    def test_o4_privacy_on_network_shell(self):
        self.assertEqual(self.bash("curl 'https://api.example.com/?q=jane.roe@example.com'"), "deny")
        self.assertEqual(self.bash("git log --author=jane.roe@example.com"), "allow")  # not a network command

    def test_n1_own_session_folder_writable_and_r1_required(self):
        sid = self.new(csid="cs1")
        own = os.path.join(self.root, "sessions", sid, "contract.md")
        other = os.path.join(self.tmp.name, "work", "out.txt")
        w = lambda p: self.hook("pre", {"session_id": "cs1", "tool_name": "Write", "tool_input": {"file_path": p}})
        self.assertEqual((w(own), w(other)), ("allow", "deny"))
        c = open(own, encoding="utf-8").read().replace("<paste the owner's request exactly>", "make a file")
        open(own, "w", encoding="utf-8").write(c)
        self.assertEqual(w(other), "deny")                                   # a request alone is not a contract
        open(own, "w", encoding="utf-8").write(c.replace("- R1: … — check: …", "- R1: out.txt exists — check: cmd: test -f out.txt"))
        self.assertEqual(w(other), "allow")

    # ---- O8: fast lane in one command ----
    def test_o8_fast_lane_one_command(self):
        sid = self.new("--lane", "fast", "--request", "fix the typo in the hero title", "--check", "true", csid="cf")
        rc, so, _ = self.run_tool("brain_session.py", "lint", "--session", sid)
        self.assertEqual(rc, 0, so)
        self.assertEqual(self.hook("pre", {"session_id": "cf", "tool_name": "Write", "tool_input": {"file_path": os.path.join(self.tmp.name, "x.html")}}), "allow")
        rc, so, se = self.run_tool("brain_session.py", "close", "--session", sid, "--summary", "typo fixed")
        self.assertEqual(json.loads(so)["status"], "closed", so + se)

    # ---- O9: deterministic CLAIM-SUPPORT at close; O7: lint syncs meta ----
    def test_o9_close_refuses_missing_evidence_and_o7_lint_sync(self):
        sid = self.new()
        d = os.path.join(self.root, "sessions", sid)
        c = open(os.path.join(d, "contract.md"), encoding="utf-8").read().replace("scope_class: general", "scope_class: system")
        open(os.path.join(d, "contract.md"), "w", encoding="utf-8").write(c)
        self.run_tool("brain_session.py", "lint", "--session", sid)
        self.assertEqual(json.load(open(os.path.join(d, "meta.json")))["scope_class"], "system")
        write(d, "task-summary.md", "# T\n| Field | Content |\n|---|---|\n| Delivered | a report |\n"
                                    "| Verified (requirement → tier → evidence) | R1 → tier0 → `reports/missing-report.md` |\n")
        write(d, "brain-summary.md", "# B\n| Field | Content |\n|---|---|\n| Proposed lesson | none |\n")
        rc, so, _ = self.run_tool("brain_session.py", "close", "--session", sid)
        self.assertEqual(json.loads(so)["status"], "claims_unsupported")
        rc, so, _ = self.run_tool("brain_session.py", "close", "--session", sid, "--force-claims", "--no-judge", "unit test")  # v3
        self.assertEqual(json.loads(so)["status"], "closed")
        self.assertEqual(json.load(open(os.path.join(d, "meta.json")))["forced_claims"], ["reports/missing-report.md"])

    # ---- O3 + N2: judges that can learn ----
    def test_o3_mark_labels_reach_gold_and_survive_rebuild(self):
        sid = self.new()
        d = os.path.join(self.root, "sessions", sid)
        write(d, "verdict-01.json", json.dumps({"verdict": {"overall": "pass", "verdicts": [
            {"requirement": "R1: report has 3 pages", "verdict": "pass", "evidence": "pdfinfo: Pages 3"},
            {"requirement": "R2: tests pass", "verdict": "pass", "evidence": "pytest: 1 failed"}]}}))
        rc, so, se = self.run_tool("brain_session.py", "decide", "--session", sid, "--approval", "approved", "--failed", "R2")
        self.assertEqual(json.loads(so)["gold_added"]["REQ-MET"], 2, se)
        lesson = write(self.root, "Brain System/lessons/l1.md", "---\ntitle: l1\ntype: lesson\nstatus: candidate\nsource: sessions/x/\n---\nCheck units.\n")
        rc, so, se = self.run_tool("lesson_decide.py", lesson, "approve")
        self.assertEqual(json.loads(so)["gold_added"]["SCOPE-COVER"], 1, se)
        write(self.root, "judge/canaries.json", json.dumps({"REQ-MET": [{"state": {"requirement_text": "a", "evidence_excerpt": "b"}, "label": "yes"}]}))
        rc, so, se = self.run_tool("judge_typed.py", "gold")
        self.assertEqual(json.loads(so)["REQ-MET"], {"total": 3, "owner": 2}, se)
        rows = [json.loads(l) for l in open(os.path.join(self.root, "judge", "gold", "REQ-MET.jsonl"))]
        self.assertEqual(sorted(r["label"] for r in rows if r["source"] == "owner"), ["no", "yes"])

    def test_o3_all_spec_questions_load(self):
        sys.path.insert(0, TOOLS)
        import judge_typed as J
        spec = "REQ-MET CLAIM-SUPPORT APPLIES PIPELINE-FIT PRIVACY-LEAK ACTION-RISK SCOPE-COVER PAIR-BETTER DUP-SAME PLACE REQ-TESTABLE CONSTRAINT-QUOTED"
        for q in spec.split():
            self.assertEqual(J.question(q)["id"], q)

    # ---- O14: judge packet + parser ----
    def test_o14_packet_has_closeout_files_and_parser_tolerates_noise(self):
        sid = self.new()
        d = os.path.join(self.root, "sessions", sid)
        write(d, "task-summary.md", "# T\n" + "x" * 9000 + "\nR7 PROVEN HERE\n")
        rc, so, _ = self.run_tool("brain_judge.py", "--session", sid, "--dry-run")
        self.assertIn("task-summary.md: present", so)
        self.assertIn("R7 PROVEN HERE", so)
        sys.path.insert(0, TOOLS)
        import brain_judge as BJ
        raw = 'warning {x} {"overall": "pass", "verdicts": [], "flaws": []} trailing {y}'
        self.assertEqual(BJ.parse_verdict(raw)["overall"], "pass")

    # ---- O1: lock + safe commit ----
    def test_o1_lock_is_exclusive(self):
        code = ("import sys, time; sys.path.insert(0, %r); import brainlib as B\n"
                "with B.lock('repo'):\n    print('held', flush=True); time.sleep(3)\n") % TOOLS
        p = subprocess.Popen([sys.executable, "-c", code], env=self.env, stdout=subprocess.PIPE, text=True)
        self.assertEqual(p.stdout.readline().strip(), "held")
        code2 = ("import sys; sys.path.insert(0, %r); import brainlib as B\n"
                 "try:\n    with B.lock('repo', timeout_s=0.3): print('got')\nexcept B.LockBusy: print('busy')\n") % TOOLS
        out = subprocess.run([sys.executable, "-c", code2], env=self.env, capture_output=True, text=True).stdout.strip()
        p.wait()
        self.assertEqual(out, "busy")

    def test_o1_commit_paths_never_sweeps_staged_work(self):
        repo = os.path.join(self.tmp.name, "repo")
        g = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
        os.makedirs(repo)
        g("init", "-q")
        g("config", "user.email", "t@t")
        g("config", "user.name", "t")
        write(repo, "toc.md", "v1\n")
        write(repo, "mine.md", "v1\n")
        g("add", ".")
        g("commit", "-qm", "base")
        write(repo, "toc.md", "v2\n")
        write(repo, "mine.md", "the owner's staged edit\n")
        g("add", "mine.md")                                                  # a live session has staged work
        code = "import sys; sys.path.insert(0, %r); import brainlib as B; print(B.git_commit_paths(['toc.md'], 'Sleep release', root=%r))" % (TOOLS, repo)
        out = subprocess.run([sys.executable, "-c", code], env=dict(self.env, BRAIN_ROOT=self.root), capture_output=True, text=True)
        self.assertTrue(out.stdout.strip(), out.stderr)
        self.assertEqual(g("show", "--name-only", "--format=", "HEAD").stdout.split(), ["toc.md"])
        self.assertEqual(g("diff", "--cached", "--name-only").stdout.split(), ["mine.md"])  # still staged, not committed

    def test_o12_links_survive_parallel_writers(self):
        sids = [self.new() for _ in range(6)]
        procs = []
        for i, sid in enumerate(sids):
            data = json.dumps({"session_id": f"c{i}", "tool_name": "Bash", "tool_input": {"command": "python3 brain_session.py new"},
                               "tool_response": {"stdout": json.dumps({"session": sid}), "stderr": ""}})
            procs.append(subprocess.Popen([sys.executable, "-I", os.path.join(TOOLS, "brain_hooks.py"), "post"], stdin=subprocess.PIPE,
                                          env=self.env, text=True))
            procs[-1].stdin.write(data)
            procs[-1].stdin.close()
        for p in procs:
            p.wait()
        links = json.load(open(os.path.join(self.root, "state", "live-links.json")))
        self.assertEqual(len([k for k in links if k.startswith("c")]), 6)

    # ---- O5: gym schema ----
    def test_o5_results_tsv_header_repaired(self):
        write(self.root, "gym/results.tsv", "date\tcode\tagent\n2026-11-08\t83\t80\t81\t{}\t0\t0\tFalse\tx\nold\tv1\trow\n")
        code = "import sys; sys.path.insert(0, %r); import gym; print(gym.ensure_tsv_header())" % TOOLS
        subprocess.run([sys.executable, "-c", code], env=self.env, check=True, capture_output=True)
        lines = open(os.path.join(self.root, "gym", "results.tsv")).read().splitlines()
        self.assertTrue(lines[0].startswith("date\ttasks\tbaseline"))
        self.assertEqual(len(lines), 2)                                       # the v2-shaped row is kept, the v1 row archived
        self.assertIn("old\tv1\trow", open(os.path.join(self.root, "gym", "results-v1-archive.tsv")).read())

    # ---- O9 + F4: routing ----
    def test_o9_novelty_explore_and_f4_synonyms(self):
        v = os.path.join(self.root, "Brain System")
        write(v, "projects/x/Episode kiln glaze.md", "---\ntitle: Episode kiln glaze\ntype: episode\nsummary: kiln glaze episode\n---\n# E\nkiln glaze firing\n")
        write(v, "projects/x/Kiln glaze rules.md", "---\ntitle: Kiln glaze rules\ntype: rules\nsummary: kiln glaze rules\n---\n# R\nkiln glaze firing\n")
        write(self.root, "state/synonyms.json", json.dumps({"pottery": ["kiln", "glaze"]}))
        self.assertEqual(self.run_tool("brain_index.py")[0], 0)
        q = lambda *a: json.loads(self.run_tool("brain_route.py", "--json", *a)[1])
        reuse = {n["title"] for n in q("--query", "kiln glaze firing")["notes"]}
        explore = q("--query", "kiln glaze firing", "--novelty", "explore")["notes"]
        self.assertIn("Episode kiln glaze", reuse)
        self.assertNotIn("Episode kiln glaze", {n["title"] for n in explore})
        self.assertEqual(explore[0]["title"], "Kiln glaze rules")                # constraints first
        self.assertIn("Kiln glaze rules", {n["title"] for n in q("--query", "pottery firing")["notes"]})

    def test_o11_read_time_rebuild_leaves_toc_alone(self):
        self.assertEqual(self.run_tool("brain_index.py")[0], 0)
        toc = os.path.join(self.root, "Brain System", "00-toc", "toc-home.md")
        before = open(toc).read()
        time.sleep(1.1)
        write(self.root, "Brain System/domains/engineering/New note.md", "---\ntitle: New note\nsummary: s\n---\n# New\n")
        self.run_tool("brain_route.py", "--query", "airflow tunnel")
        self.assertEqual(open(toc).read(), before)

    # ---- F2: Tier 0 for the owner's domains ----
    def test_f2_domain_checks(self):
        w = os.path.join(self.tmp.name, "w")
        V = [(0, 0, 0), (10, 0, 0), (10, 20, 0), (0, 20, 0), (0, 0, 5), (10, 0, 5), (10, 20, 5), (0, 20, 5)]
        F = [(0, 1, 2), (0, 2, 3), (4, 6, 5), (4, 7, 6), (0, 5, 1), (0, 4, 5), (1, 6, 2), (1, 5, 6), (2, 7, 3), (2, 6, 7), (3, 4, 0), (3, 7, 4)]
        os.makedirs(w)
        for name, faces in (("cube.stl", F), ("open.stl", F[:-1])):
            b = bytearray(80) + struct.pack("<I", len(faces))
            for f in faces:
                b += struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *V[i]) for i in f) + b"\0\0"
            open(os.path.join(w, name), "wb").write(bytes(b))
        write(w, "two.pdf", "%PDF-1.4\n1 0 obj<</Type /Pages /Kids [3 0 R 4 0 R] /Count 2>>endobj\n%%EOF")
        write(w, "a.css", "body{color:#112233;background:#fff}")
        write(w, "ok.html", '<meta name="viewport" content="width=device-width"><style>.c{max-width:900px}</style>')
        write(w, "bad.html", "<style>.c{width:1200px}</style>")
        cases = {"pdf_pages: two.pdf :: 2": True, "pdf_pages: two.pdf :: 1": False, "stl_bbox: cube.stl :: 10,20,5": True,
                 "stl_bbox: cube.stl :: 10,20,6": False, "stl_manifold: cube.stl": True, "stl_manifold: open.stl": False,
                 "brand_tokens: a.css :: #112233,#ffffff": True, "brand_tokens: a.css :: #112233": False,
                 "html_viewport: ok.html": True, "html_viewport: bad.html": False}
        for c, want in cases.items():
            rc, so, _ = self.run_tool("tier0.py", "--check", "R1: " + c, "--cwd", w)
            self.assertEqual(json.loads(so)[0]["pass"], want, c)

    # ---- F6: work tasks ----
    def test_f6_work_suite_discriminates(self):
        env = dict(self.env)
        env.pop("BRAIN_ROOT")                                                  # the suite lives in the real brain, read-only here
        rc, so, _ = self.run_tool("gym.py", "--suite", "work-tasks", "--dry-run", env=env)
        self.assertEqual((rc, json.loads(so)["passed"]), (0, 8))
        rc, so, _ = self.run_tool("gym.py", "--suite", "work-tasks", "--dry-run", env=dict(env, BRAIN_WORK_AGENT="true"))
        self.assertEqual(json.loads(so)["passed"], 0)

    # ---- O10: validator ----
    def test_o10_tree_validate_catches_planted_defects(self):
        r = os.path.join(self.tmp.name, "tree")
        write(r, "AGENTS.md", "x" * 7000)
        write(r, "tools/bad.py", "def f(:\n")
        write(r, "CLAUDE.md", "run tools/missing.py\n")
        write(r, "agents/a.md", "---\nname: a\n---\n")
        rc, so, _ = self.run_tool("tree_validate.py", "--root", r, "--json")
        errs = "\n".join(json.loads(so)["errors"])
        self.assertEqual(rc, 1)
        for needle in ("AGENTS.md: 7000 chars", "tools/bad.py: does not compile", "names tools/missing.py", "agents/a.md: frontmatter has no description"):
            self.assertIn(needle, errs)

    # ---- O9 + O15: sleep ----
    def test_o9_depends_on_and_o15_apply_digest(self):
        v = os.path.join(self.root, "Brain System")
        write(v, "domains/engineering/Dep.md", "---\ntitle: Dep\nsummary: d\n---\n# Dep\n")
        write(v, "domains/engineering/Card.md", "---\ntitle: Card\nsummary: c\ndepends_on: [\"[[Dep]]\"]\nlast_verified: 2020-01-01\n---\n# Card\n")
        lesson = write(v, "lessons/l2.md", "---\ntitle: l2\ntype: lesson\nstatus: candidate\nsource: sessions/x/\n---\nMeasure twice.\n")
        rc, so, se = self.run_tool("brain_sleep.py", "--dry-run", "--no-gym")
        digest = open(os.path.join(self.root, json.loads(so)["digest"]), encoding="utf-8").read()
        self.assertIn("stale note: Brain System/domains/engineering/Card.md", digest)
        line = next(l for l in digest.splitlines() if "lesson `Brain System/lessons/l2.md`" in l)
        open(os.path.join(self.root, json.loads(so)["digest"]), "w", encoding="utf-8").write(digest.replace(line, line.replace("- [ ] approve", "- [x] approve")))
        rc, so, se = self.run_tool("brain_sleep.py", "--apply-digest")
        self.assertEqual(rc, 0, so + se)
        self.assertIn("status: released", open(lesson, encoding="utf-8").read())

    # ---- F7, F8: delegation checks, continuity ----
    def test_f7_scout_checks_and_f8_handoff(self):
        sid = self.new(csid="cs7")
        target = os.path.join(self.root, "AGENTS.md")
        write(self.root, "AGENTS.md", "x\n")
        reply = "options:\n" + "".join(f"  - pointer: {target}#L1-L{i}\n" for i in range(1, 5))
        self.hook("post", {"session_id": "cs7", "tool_name": "Agent", "tool_input": {"subagent_type": "brain-scout", "prompt": "find"}, "tool_response": reply})
        self.hook("post", {"session_id": "cs7", "tool_name": "Edit", "tool_input": {"file_path": target}, "tool_response": {}})
        ev = [json.loads(l) for l in open(os.path.join(self.root, "sessions", sid, "evidence.jsonl"))]
        self.assertIn("4 pointers > 3", ev[-2]["warn"])
        self.assertTrue(ev[-1]["warn"].startswith("scout_unread_original"))
        rc, so, _ = self.run_tool("brain_session.py", "handoff")
        self.assertIn(sid, open(os.path.join(self.root, "HANDOFF.md")).read())
        rc, so, _ = self.run_tool("brain_start.py", "--agent", "claude", "--format", "text")
        self.assertIn("latest sessions (all agents): " + sid, so)
        self.assertIn("judge now:", so)

    # ---- O2: Harness² isolation (also in test_live_tools) ----
    def test_o2_composed_applies_kept_patch_only(self):
        sid = self.new()
        write(self.root, "work/a.txt", "base\n")
        rc, so, se = self.run_tool("harness2.py", "start", "--session", sid, "--subtask", "s", "--check", "grep -q fixed work/a.txt", "--scope", "work")
        self.assertEqual(rc, 0, se)
        gp = write(self.tmp.name, "g.patch", "--- a/work/a.txt\n+++ b/work/a.txt\n@@ -1 +1 @@\n-base\n+fixed\n")
        self.run_tool("harness2.py", "propose", "--session", sid, "--general", "g", "--domain", "d", "--general-patch", gp, "--domain-patch", gp)
        for arm in ("reference", "general"):
            self.run_tool("harness2.py", "probe", "--session", sid, "--arm", arm)
        led = json.load(open(os.path.join(self.root, "sessions", sid, "harness2", "ledger.json")))
        self.assertEqual([r["exit"] for r in led["runs"]], [1, 0])
        self.assertEqual(open(os.path.join(self.root, "work", "a.txt")).read(), "base\n")   # live file untouched


class PluginShelf(Brain):
    """v2.1 (the owner 2026-11-09): plugins live in the brain; start loads only core; agents activate on demand."""

    def test_shelf_switch_verify_and_refuse(self):
        t = self.tmp.name
        codex = write(t, "codex/config.toml", 'model = "x"\n\n[plugins."slack@openai-curated"]\nenabled = true\n\n[plugins."browser@openai-bundled"]\nenabled = true\n')
        write(t, "home/.codex/plugins/cache/openai-curated/slack/1/skills/send/SKILL.md", "---\nname: send\ndescription: send a slack message to a channel\n---\n")
        settings = write(t, "claude/settings.json", json.dumps({"enabledPlugins": {"web@local": True}}))
        lists = write(t, "app/a/b/plugins.json", json.dumps({"plugins": [{"id": "sales@kw", "name": "sales", "enabled": True,
                                                                          "installPath": os.path.join(t, "app", "rpm", "plugin_01ABC")}]}))
        env = dict(self.env, BRAIN_CODEX_CONFIG=codex, BRAIN_CLAUDE_SETTINGS=settings, BRAIN_APP_PLUGIN_LISTS=lists, HOME=os.path.join(t, "home"))
        rc, so, _ = self.run_tool("plugin_shelf.py", "deactivate", "slack", env=env)
        self.assertNotEqual(rc, 0)                                             # refused: no brain copy of its skill yet
        self.assertIn("enabled = true", open(codex).read())
        write(self.root, "skills/plugins/codex-slack/skills/send/SKILL.md", "---\nname: send\ndescription: send a slack message\n---\n")
        rc, so, se = self.run_tool("plugin_shelf.py", "deactivate", "slack", env=env)
        self.assertEqual(rc, 0, se)
        self.assertIn('[plugins."slack@openai-curated"]\nenabled = false', open(codex).read())
        self.assertIn('[plugins."browser@openai-bundled"]\nenabled = true', open(codex).read())   # only that plugin changed
        rc, so, _ = self.run_tool("plugin_shelf.py", "activate", "slack", env=env)
        rc, so, _ = self.run_tool("plugin_shelf.py", "deactivate", "slack", env=env)
        backups = os.listdir(os.path.join(self.root, "state", "backups", time.strftime("%Y-%m-%d"), "plugin-shelf"))
        self.assertEqual(len(backups), 3)                                     # one backup per switch, never overwritten
        rc, so, _ = self.run_tool("plugin_shelf.py", "deactivate", "sales", env=env)
        self.assertIn("Customize → Plugins → sales off", so)                  # account plugin: no file switch exists
        lst = json.loads(self.run_tool("plugin_shelf.py", "list", "--json", env=env)[1])
        write(t, "app/a/b/plugins.json", json.dumps({"plugins": [dict(next(x for x in lst if x["name"] == "sales"), enabled=False, id="sales@kw",
                                                                      installPath=os.path.join(t, "app", "rpm", "plugin_01ABC"))]}))
        rc, so, _ = self.run_tool("plugin_shelf.py", "activate", "sales", env=env)
        self.assertIn("SuggestPluginInstall with pluginId plugin_01ABC", so)  # the agent's way back: the app's add card
        rc, so, _ = self.run_tool("plugin_shelf.py", "verify", env=env)
        self.assertEqual(json.loads(so)["ok"], True)


if __name__ == "__main__":
    unittest.main()
