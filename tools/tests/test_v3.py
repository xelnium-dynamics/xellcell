"""v3 "Fable Art" tests: one per flaw found in the 2026-11-10 analysis (versions/v3-fable-art/ANALYSIS.md).
A = gates that failed open or existed on paper only · B = flow steps that were skipped or noisy · C = memory and
accounting. Each test builds a throwaway brain (BRAIN_ROOT in a temp folder); the real brain is never touched.
Every test here fails on the v2.1 code (versions/v3-fable-art/evidence/v3-tests-on-v21-code.txt).
Run: bash tools/test_all.sh"""
import json, os, stat, subprocess, sys, time, unittest

from test_live_tools import Brain, TOOLS, write

REAL = os.path.dirname(TOOLS)
SUMMARY = "# Task Summary — t\n\n| Field | Content |\n|---|---|\n| Delivered | {d} |\n| Verified (requirement → tier → evidence) | R1 → 0 → log |\n"
BRAIN_SUMMARY = "# Brain Summary — t\n\n| Field | Content |\n|---|---|\n| Proposed lesson | none |\n"


class V3(Brain):
    def hook(self, mode, data, env=None):
        env = dict(env or self.env, BRAIN_FREE_WRITE=os.path.expanduser("~/.claude") + os.sep)
        rc, so, se = self.run_tool("brain_hooks.py", mode, stdin=json.dumps(data), env=env)
        self.assertEqual(rc, 0, se)
        return json.loads(so)["hookSpecificOutput"]["permissionDecision"] if so.strip() else "allow"

    def new(self, *extra, csid=None):
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "t", *extra)
        self.assertEqual(rc, 0, se)
        sid = json.loads(so)["session"]
        if csid:
            self.hook("post", {"session_id": csid, "tool_name": "Bash", "tool_input": {"command": "python3 brain_session.py new"},
                               "tool_response": {"stdout": so, "stderr": ""}})
        return sid

    def fast(self, csid):
        """A linked session with a filled contract, so the contract gate is open and the other gates are what is tested."""
        return self.new("--lane", "fast", "--request", "tidy the notes folder", "--check", "true", csid=csid)

    def bash(self, cmd, csid):
        return self.hook("pre", {"session_id": csid, "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.root})

    def sdir(self, sid):
        return os.path.join(self.root, "sessions", sid)

    def meta(self, sid):
        return json.load(open(os.path.join(self.sdir(sid), "meta.json"), encoding="utf-8"))

    def py(self, code, env=None):
        p = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {TOOLS!r})\n" + code],
                           capture_output=True, text=True, env=env or self.env)
        self.assertEqual(p.returncode, 0, (p.stderr.strip().splitlines() or ["no error text"])[-1])  # the real error, not a JSON one
        return p.returncode, p.stdout, p.stderr

    # ---- A1: a token that is not a valid glob never switches the gates off ----
    def test_a1_bad_glob_token_does_not_open_the_gates(self):
        self.fast("a1")
        for cmd in ("echo 'x[z-a]' ; git push origin main", "python3 -c 'print(s[::-1], t[e-a])' && git push", "grep '[i-g]' f; git push"):
            self.assertEqual(self.bash(cmd, "a1"), "ask", cmd)
        self.assertFalse(os.path.exists(os.path.join(self.root, "state", "analysis", "hook-errors.log")))  # no crash at all

    # ---- A2: one crashing gate is logged and skipped; the other gates still decide ----
    def test_a2_a_crashing_gate_does_not_skip_the_others(self):
        self.fast("a2")
        data = {"session_id": "a2", "tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": self.root}
        rc, so, se = self.py("import io, json, brain_hooks as H\n"
                             "H.touches_self = lambda *a, **k: 1 / 0\n"
                             f"sys.argv = ['brain_hooks.py', 'pre']; sys.stdin = io.StringIO({json.dumps(json.dumps(data))})\n"
                             "H.main()")
        self.assertEqual(rc, 0, se)
        self.assertEqual(json.loads(so)["hookSpecificOutput"]["permissionDecision"], "ask")
        log = open(os.path.join(self.root, "state", "analysis", "hook-errors.log"), encoding="utf-8").read()
        self.assertIn("gate_scope ZeroDivisionError", log)

    # ---- A3: every common way to delete asks the owner ----
    def test_a3_delete_forms_ask(self):
        self.fast("a3")
        for cmd in ("cd /tmp\nrm -rf important", "ls | xargs rm", "if true; then rm -rf x; fi", "for f in *; do rm $f; done",
                    "find 'Brain System/projects' -name '*.md' -delete", "find 'Brain System/projects' -name x -exec rm {} +", "git clean -fdx",
                    "python3 - <<'EOF'\nimport shutil\nshutil.rmtree('notes')\nEOF", "python3 -c \"import os; os.remove('a.txt')\""):
            self.assertEqual(self.bash(cmd, "a3"), "ask", cmd)
        for cmd in ("git status", "grep -rn --exclude-dir=self term notes", "echo performance > notes.txt", "ls -la && wc -l notes.txt"):
            self.assertEqual(self.bash(cmd, "a3"), "allow", cmd)

    # ---- A4: raw/ is read-only and another session's folder is a record ----
    def test_a4_raw_and_other_session_folders_are_gated(self):
        sid = self.fast("a4")
        other = self.new()
        w = lambda p: self.hook("pre", {"session_id": "a4", "tool_name": "Write", "tool_input": {"file_path": p}, "cwd": self.root})
        os.makedirs(os.path.join(self.root, "raw", "manifests"))
        self.assertEqual(w(os.path.join(self.root, "raw", "note.md")), "deny")
        self.assertEqual(self.bash("echo hi > raw/manifests/x.json", "a4"), "deny")
        self.assertEqual(self.bash("cp notes.txt raw/notes.txt", "a4"), "deny")
        self.assertEqual(w(os.path.join(self.sdir(other), "contract.md")), "ask")
        self.assertEqual(w(os.path.join(self.sdir(sid), "report.md")), "allow")
        self.assertEqual(w(os.path.join(self.root, "Brain System", "projects", "client-a", "x.md")), "allow")
        self.assertEqual(self.bash("cat raw/manifests/x.json", "a4"), "allow")  # reading evidence is the point of it

    # ---- A5: hook errors are shown, not hidden in a log nobody opens ----
    def errlog(self):
        write(self.root, "state/analysis/hook-errors.log",
              "2020-01-01 10:00:00 ['pre'] error: old one\n" + time.strftime("%Y-%m-%d %H:%M:%S") + " ['pre'] gate_scope error: fresh one\n")

    def test_a5_card_shows_hook_errors(self):
        self.errlog()
        rc, so, se = self.run_tool("brain_start.py", "--agent", "claude", "--format", "text", "--cwd", self.root)
        self.assertIn("HOOK ERRORS  1 in the last 7 days", so, se)
        self.assertIn("fresh one", so)

    def test_a5_digest_shows_hook_errors(self):
        self.errlog()
        rc, so, se = self.run_tool("brain_sleep.py", "--dry-run", "--no-gym")
        digest = open(os.path.join(self.root, json.loads(so)["digest"]), encoding="utf-8").read()
        self.assertIn("hook errors in the last 7 days: 1", digest)

    # ---- A7: a closed session's evidence is a finished record ----
    def test_a7_closed_session_takes_no_more_evidence(self):
        sid = self.fast("a7")
        self.run_tool("brain_session.py", "close", "--session", sid, "--summary", "done")
        ev = os.path.join(self.sdir(sid), "evidence.jsonl")
        before = open(ev, encoding="utf-8").read()
        self.hook("post", {"session_id": "a7", "tool_name": "Bash", "tool_input": {"command": "echo later work"},
                           "tool_response": {"stdout": "later work", "stderr": ""}})
        self.assertEqual(open(ev, encoding="utf-8").read(), before)

    # ---- A8: a session is linked even when the output of `new` was piped through something ----
    def test_a8_session_link_survives_piped_output(self):
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "t",
                                   "--lane", "fast", "--request", "tidy the notes folder", "--check", "true")
        sid = json.loads(so)["session"]
        self.hook("post", {"session_id": "a8", "tool_name": "Bash", "tool_input": {"command": "python3 brain_session.py new ... | python3 -c ..."},
                           "tool_response": {"stdout": sid + "\nsessions/" + sid + "/retrieval-01.md\n", "stderr": ""}})
        self.assertEqual(json.load(open(os.path.join(self.root, "state", "live-links.json"), encoding="utf-8")).get("a8"), sid)
        w = self.hook("pre", {"session_id": "a8", "tool_name": "Write", "tool_input": {"file_path": os.path.join(self.tmp.name, "x.md")}, "cwd": self.root})
        self.assertEqual(w, "allow")

    # ---- A6: the installed hook matcher must cover what the hook code handles ----
    def test_a6_tree_validate_warns_when_post_matcher_lacks_read_and_agent(self):
        home = os.path.join(self.tmp.name, "home")
        hooks = lambda m: {"hooks": {"PostToolUse": [{"matcher": m, "hooks": [
            {"type": "command", "command": f'python3 -I "{REAL}/tools/brain_hooks.py" post'}]}]}}
        for matcher, expect in (("Bash|Write|Edit", True), ("Bash|Write|Edit|Read|Agent|Task", False), ("*", False)):
            write(home, ".claude/settings.json", json.dumps(hooks(matcher)))
            rc, so, se = self.run_tool("tree_validate.py", "--root", REAL, "--json", env=dict(self.env, HOME=home))
            warned = any("PostToolUse matcher" in w for w in json.loads(so)["warnings"])
            self.assertEqual(warned, expect, matcher)

    # ---- B1: step 2 runs by itself ----
    def test_b1_retrieval_runs_with_new_and_lint(self):
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "wind tunnel",
                                   "--lane", "fast", "--request", "export the blender model for the airflow simulation")
        out = json.loads(so)
        self.assertTrue(os.path.exists(os.path.join(self.root, out["retrieval"]["file"])), se)
        self.assertTrue(any("blender-export" in s for s in out["retrieval"]["skills"]), out)
        self.assertTrue(any("Airflow basics" in n for n in out["retrieval"]["notes"]), out)
        sid = self.new()                                                     # standard lane, no --request: lint routes it
        d = self.sdir(sid)
        self.assertFalse([f for f in os.listdir(d) if f.startswith("retrieval-")])
        c = open(os.path.join(d, "contract.md"), encoding="utf-8").read()
        write(d, "contract.md", c.replace("<paste the owner's request exactly>", "airflow simulation notes for the wind tunnel")
              .replace("- R1: … — check: …", "- R1: a note exists — check: cmd: test -f out.md").replace('- "…"', "- (none quoted)"))
        rc, so, se = self.run_tool("brain_session.py", "lint", "--session", sid)
        self.assertEqual(rc, 0, so + se)
        self.assertTrue(any("Airflow basics" in n for n in json.loads(so)["retrieval"]["notes"]))
        self.run_tool("brain_session.py", "lint", "--session", sid)          # a second lint does not route again
        self.assertEqual([f for f in os.listdir(d) if f.startswith("retrieval-")], ["retrieval-01.md"])

    # ---- B1 (counter): the fetch log is not a retrieval run ----
    def test_b1_fetch_log_is_not_counted_as_a_retrieval_run(self):
        sid = self.new(csid="b1c")                                           # no --request: nothing was routed
        write(self.sdir(sid), "retrieval-log.jsonl", "{}\n")
        self.hook("end", {"session_id": "b1c", "transcript_path": None, "cwd": self.root})
        flow = json.load(open(os.path.join(self.sdir(sid), "analysis.json"), encoding="utf-8"))["flow"]
        self.assertEqual(flow["retrieval_runs"], 0)

    # ---- B2: a standard-lane close answers for step 6 ----
    def test_b2_close_needs_a_verdict_or_a_recorded_reason(self):
        close = lambda sid, *x: (lambda r: (r[0], json.loads(r[1])["status"]))(self.run_tool("brain_session.py", "close", "--session", sid, *x))
        sid = self.new()
        write(self.sdir(sid), "task-summary.md", SUMMARY.format(d="a report"))
        write(self.sdir(sid), "brain-summary.md", BRAIN_SUMMARY)
        self.assertEqual(close(sid), (1, "judge_missing"))
        self.assertEqual(close(sid, "--no-judge", "the owner looked at it himself"), (0, "closed"))
        self.assertEqual(self.meta(sid)["no_judge"], "the owner looked at it himself")
        sid = self.new()
        write(self.sdir(sid), "task-summary.md", SUMMARY.format(d="a report"))
        write(self.sdir(sid), "brain-summary.md", BRAIN_SUMMARY)
        write(self.sdir(sid), "verdict-01.json", "{}")
        write(self.sdir(sid), "judge.md", "- 2026-11-10 10:00:00 round 1: fail (judge codex, strong; tier0 1 checks)\n")
        self.assertEqual(close(sid), (1, "judge_failed"))
        self.assertEqual(close(sid, "--unresolved", "the render needs the owner's eye"), (0, "closed"))
        m = self.meta(sid)
        self.assertEqual((m["unresolved"], m["judge"]), ("the render needs the owner's eye", {"rounds": 1, "last": "fail"}))
        sid = self.fast("b2")                                                # the fast lane has no step 6
        self.assertEqual(close(sid, "--summary", "typo fixed"), (0, "closed"))
        rc, so, se = self.run_tool("brain_sleep.py", "--dry-run", "--no-gym")
        digest = open(os.path.join(self.root, json.loads(so)["digest"]), encoding="utf-8").read()
        self.assertIn("closed without a judge:", digest)
        self.assertIn("closed on a failed verdict:", digest)

    # ---- B8: a free-form summary no longer hides from the claim check ----
    def test_b8_close_needs_delivered_and_verified_in_either_form(self):
        close = lambda sid: json.loads(self.run_tool("brain_session.py", "close", "--session", sid)[1])["status"]
        sid = self.fast("b8")                                                # fast lane: no judge rule in the way
        write(self.sdir(sid), "brain-summary.md", BRAIN_SUMMARY)
        write(self.sdir(sid), "task-summary.md", "# Task summary\nRequest: a report.\nIt went fine.\n")
        self.assertEqual(close(sid), "summary_fields_missing")
        write(self.sdir(sid), "task-summary.md", "# Task summary\nDelivered: a report\nVerified: R1 → tier0 → `reports/not-there.md`\n")
        self.assertEqual(close(sid), "claims_unsupported")                   # the line form is checked like the table row
        write(self.sdir(sid), "task-summary.md", "# Task summary\nDelivered: a report\nVerified: R1 → tier0 → `AGENTS.md`\n")
        write(self.root, "AGENTS.md", "protocol\n")
        self.assertEqual(close(sid), "closed")

    # ---- B3: the fast lane never "skipped" a checkpoint ----
    def test_b3_fast_lane_analysis_is_lane_aware(self):
        sid = self.fast("b3")
        self.hook("end", {"session_id": "b3", "transcript_path": None, "cwd": self.root})
        flow = json.load(open(os.path.join(self.sdir(sid), "analysis.json"), encoding="utf-8"))["flow"]
        self.assertNotIn("checkpoint", flow["missing_steps"])
        rc, so, se = self.run_tool("brain_sleep.py", "--dry-run", "--no-gym")
        digest = open(os.path.join(self.root, json.loads(so)["digest"]), encoding="utf-8").read()
        self.assertNotIn("skipped in 1 session(s): checkpoint", digest)

    # ---- B4: The owner's verdict is one tick away ----
    def test_b4_digest_lists_sessions_waiting_and_applies_the_tick(self):
        sid = self.fast("b4")
        rc, so, se = self.run_tool("brain_session.py", "close", "--session", sid, "--summary", "notes tidied")
        episode = os.path.join(self.root, json.loads(so)["episode"])
        rc, so, se = self.run_tool("brain_sleep.py", "--dry-run", "--no-gym")
        r = json.loads(so)
        self.assertEqual(r["decisions"], 1, so)                                # counted apart from the exception queue
        dp = os.path.join(self.root, r["digest"])
        digest = open(dp, encoding="utf-8").read()
        line = next(x for x in digest.splitlines() if f"session `{sid}`" in x)
        write(self.root, r["digest"], digest.replace(line, line.replace("- [ ] approve", "- [x] approve")))
        rc, so, se = self.run_tool("brain_sleep.py", "--apply-digest", dp)
        self.assertEqual(rc, 0, so + se)
        self.assertEqual(self.meta(sid)["approval"], "approved")
        self.assertIn("approval: approved", open(episode, encoding="utf-8").read())  # the episode follows the owner's verdict

    # ---- B4 (old sessions): the digest reads the judge result of a session closed before v3 ----
    def test_b4_digest_shows_the_judge_result_of_older_sessions(self):
        old = self.new()                                                     # closed before v3: no "judge" in its meta.json
        write(self.sdir(old), "judge.md", "- 2026-11-09 10:00:00 round 1: pass (judge codex, strong; tier0 1 checks)\n")
        write(self.sdir(old), "meta.json", json.dumps(dict(self.meta(old), status="closed", closed="2026-11-09 10:05:00", approval="pending")))
        rc, so, se = self.run_tool("brain_sleep.py", "--dry-run", "--no-gym")
        digest = open(os.path.join(self.root, json.loads(so)["digest"]), encoding="utf-8").read()
        self.assertIn(f"session `{old}` (t; judge: pass)", digest)

    # ---- B5: a failed Tier-0 check does not spend a judge call ----
    def test_b5_tier0_failure_skips_the_other_vendor(self):
        marker = os.path.join(self.tmp.name, "judge-was-called")
        fake = os.path.join(self.tmp.name, "bin", "codex")
        verdict = {"overall": "pass", "verdicts": [{"requirement": "R1", "verdict": "pass", "evidence": "x", "severity": "none"}], "flaws": []}
        write(self.tmp.name, "bin/codex", "#!/bin/sh\nout=''\nwhile [ $# -gt 0 ]; do [ \"$1\" = \"-o\" ] && out=\"$2\"; shift; done\n"
              f"cat > /dev/null\ntouch '{marker}'\nprintf '%s' '{json.dumps(verdict)}' > \"$out\"\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        sid = self.new()
        d = self.sdir(sid)
        c = open(os.path.join(d, "contract.md"), encoding="utf-8").read()
        write(d, "contract.md", c.replace("<!-- - R1: cmd: <shell command that exits 0 when R1 is met> -->", "- R1: cmd: test -f /definitely/missing/file"))
        env = dict(self.env, BRAIN_CODEX_BIN=fake)
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, env=env)
        res = json.loads(so)
        self.assertEqual((res["overall"], res["tier2"], rc), ("fail", "skipped", 1), se)
        self.assertIn("R1", res["failed_checks"])
        self.assertFalse(os.path.exists(marker))
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--force-tier2", env=env)
        self.assertEqual((json.loads(so)["overall"], json.loads(so)["tier2"]), ("fail", "called"))
        self.assertTrue(os.path.exists(marker))

    # ---- B6: an old health check is not proof ----
    def test_b6_stale_judge_health_is_unverified(self):
        rc, so, se = self.py("import brain_judge as J, time\n"
                             "print(J.health_fresh('2020-01-01 10:00'), J.health_fresh(time.strftime('%Y-%m-%d %H:%M')), J.health_fresh(None))")
        self.assertEqual(so.split(), ["False", "True", "False"], se)

    # ---- B7: the maker's summaries are labelled as claims and come last ----
    def test_b7_packet_marks_the_makers_summaries_as_claims(self):
        sid = self.new()
        d = self.sdir(sid)
        write(d, "task-summary.md", SUMMARY.format(d="MAKER-SAYS-ALL-GOOD"))
        art = write(self.tmp.name, "out/result.txt", "deliverable text")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, "--dry-run")
        head = "## The maker's own summaries (claims to verify against the artifacts above; not evidence)"
        self.assertIn(head, so, se)
        self.assertLess(so.index("deliverable text"), so.index(head))
        self.assertLess(so.index(head), so.index("MAKER-SAYS-ALL-GOOD"))

    # ---- C1: a released lesson is routed; a candidate and a private one are not ----
    def test_c1_released_lessons_reach_the_router(self):
        les = lambda name, status, extra="": write(self.root, f"Brain System/lessons/{name}.md",
            f"---\ntitle: \"{name}\"\ntype: lesson\nstatus: {status}\n{extra}summary: recheck the turbine clearance before export\n---\n# {name}\nRecheck the turbine clearance before export.\n")
        les("lesson released", "released")
        les("lesson candidate", "candidate")
        les("lesson private", "released", "scope_class: personal\n")
        route = lambda scope: [n["title"] for n in json.loads(self.run_tool(
            "brain_route.py", "--query", "turbine clearance export", "--scope", scope, "--json")[1])["notes"]]
        self.assertEqual(route("engineering"), ["lesson released"])
        self.assertEqual(sorted(route("personal")), ["lesson private", "lesson released"])

    # ---- C2 (summary): an episode says what was delivered ----
    def test_c2_episode_summary_is_the_delivered_line(self):
        sid = self.fast("c2")
        rc, so, se = self.run_tool("brain_session.py", "close", "--session", sid, "--summary", "moved 12 notes into dated folders")
        ep = open(os.path.join(self.root, json.loads(so)["episode"]), encoding="utf-8").read()
        self.assertIn('summary: "moved 12 notes into dated folders"', ep)
        self.assertNotIn("— pending", ep)

    # ---- C2 (cap): episodes do not crowd out knowledge ----
    def test_c2_router_returns_at_most_two_episodes(self):
        for i in range(5):
            write(self.root, f"Brain System/history/episodes/ep{i}.md",
                  f"---\ntitle: \"Episode {i}\"\ntype: episode\nsummary: gearbox housing print run {i}\n---\n# Episode {i}\nGearbox housing print.\n")
        write(self.root, "Brain System/domains/engineering/Gearbox housing.md",
              "---\ntitle: Gearbox housing\ntype: knowledge\nsummary: gearbox housing print tolerances\n---\n# Gearbox housing\nPrint tolerances.\n")
        notes = json.loads(self.run_tool("brain_route.py", "--query", "gearbox housing print", "--scope", "engineering", "--json")[1])["notes"]
        self.assertEqual(len([n for n in notes if n["type"] == "episode"]), 2)
        self.assertIn("Gearbox housing", [n["title"] for n in notes])

    # ---- C3: the release takes the records of closed sessions with it ----
    def test_c3_release_paths_include_closed_session_records(self):
        closed = self.fast("c3")
        rc, so, se = self.run_tool("brain_session.py", "close", "--session", closed, "--summary", "done")
        still_open = self.new()
        rc, so, se = self.py("import json, brain_sleep as S\nprint(json.dumps(S.record_paths()))")
        paths = json.loads(so)
        self.assertIn(f"sessions/{closed}", paths, se)
        self.assertNotIn(f"sessions/{still_open}", paths)
        self.assertIn("Brain System/history/episodes", paths)

    # ---- C4: a brain session is charged only for its own time in the conversation ----
    def test_c4_tokens_are_counted_inside_the_session_window(self):
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"
        now = time.time()
        line = lambda i, t, out: json.dumps({"timestamp": iso(t), "message": {"id": f"m{i}", "usage": {"input_tokens": 100, "output_tokens": out}}})
        tr = write(self.tmp.name, "t.jsonl", "\n".join([line(1, now - 7200, 11), line(2, now - 3600, 22), line(3, now, 33)]) + "\n")
        rc, so, se = self.py("import json, token_meter as T\n"
                             f"print(json.dumps([T.claude([{tr!r}])[0]['output'], T.claude([{tr!r}], since={now - 5400}, until={now - 1800})[0]['output']]))")
        self.assertEqual(json.loads(so), [66, 22], se)
        sid = self.fast("c4")
        time.sleep(1.1)                                                      # timestamps have whole seconds: stay clear of the edge
        tr = write(self.tmp.name, "t.jsonl", "\n".join([line(1, now - 7200, 11), line(2, now - 3600, 22), line(3, time.time(), 33)]) + "\n")
        self.hook("end", {"session_id": "c4", "transcript_path": tr, "cwd": self.root})  # only the last line is this session's
        a = json.load(open(os.path.join(self.sdir(sid), "analysis.json"), encoding="utf-8"))
        self.assertEqual((a["tokens"]["output"], a["tokens"]["window"]), (33, "session"))
        self.new()                                                           # two sessions: the pilot report walks both
        rc, so, se = self.run_tool("pilot.py", "report")
        self.assertEqual(rc, 0, se)
        self.assertEqual(json.loads(so)["on"]["sessions"], 2)

    # ---- C5: a table-of-contents page is rewritten only when its content changes ----
    def test_c5_toc_pages_keep_their_date_when_nothing_changed(self):
        self.run_tool("brain_index.py")
        toc = os.path.join(self.root, "Brain System", "00-toc", "toc-home.md")
        text = open(toc, encoding="utf-8").read()
        write(self.root, "Brain System/00-toc/toc-home.md", text.replace(f"updated: {time.strftime('%Y-%m-%d')}", "updated: 2026-01-01"))
        rc, so, se = self.run_tool("brain_index.py")
        self.assertEqual(json.loads(so.strip().splitlines()[-1])["toc_changed"], 0, so + se)
        self.assertIn("updated: 2026-01-01", open(toc, encoding="utf-8").read())

    # ---- C6: a pointer written before the vault folder was renamed still finds its episode ----
    def test_c6_decide_follows_an_old_vault_pointer(self):
        sid = self.fast("c6")
        rc, so, se = self.run_tool("brain_session.py", "close", "--session", sid, "--summary", "done")
        rel = json.loads(so)["episode"]
        self.assertTrue(rel.startswith("Brain System/"), rel)
        write(self.sdir(sid), "meta.json", json.dumps(dict(self.meta(sid), episode="vault/" + rel[len("Brain System/"):])))
        rc, so, se = self.run_tool("brain_session.py", "decide", "--session", sid, "--approval", "rejected")
        self.assertEqual(rc, 0, se)
        self.assertIn("approval: rejected", open(os.path.join(self.root, rel), encoding="utf-8").read())

    # ---- D1: the always-on text stays inside its caps and names the version ----
    def test_d1_card_and_protocol_size_and_version(self):
        rc, so, se = self.run_tool("brain_start.py", "--agent", "claude", "--format", "text", "--cwd", self.root)
        self.assertIn('v3 "Fable Art"', so, se)
        self.assertIn("2 RETRIEVE  runs by itself", so)
        self.assertLess(len(so), 4057)                                       # the v2.1 card was 4,057 characters
        agents = open(os.path.join(REAL, "AGENTS.md"), encoding="utf-8").read()
        self.assertIn("v3 Fable Art", agents)
        self.assertLessEqual(len(agents), 6000)

    # ================= second pass: one test per sub-behaviour the judge found untested (round 3) =================
    def digest(self, *args):
        rc, so, se = self.run_tool("brain_sleep.py", "--no-gym", *(args or ("--dry-run",)))
        return open(os.path.join(self.root, json.loads(so)["digest"]), encoding="utf-8").read()

    def stamp(self, days_ago):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - days_ago * 86400))

    # ---- B1 (switch): BRAIN_NO_AUTOROUTE=1 turns the automatic retrieval off ----
    def test_b1_autoroute_can_be_switched_off(self):
        args = ("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "t", "--lane", "fast", "--request", "airflow simulation")
        self.assertIn("retrieval", json.loads(self.run_tool(*args)[1]))       # control: on by default (v2.1 has no retrieval at all)
        off = json.loads(self.run_tool(*args, env=dict(self.env, BRAIN_NO_AUTOROUTE="1"))[1])
        self.assertNotIn("retrieval", off)
        self.assertFalse([f for f in os.listdir(self.sdir(off["session"])) if f.startswith("retrieval-")])

    # ---- B2 (digest window): a recorded reason is shown for 7 days, not for ever ----
    def test_b2_digest_shows_close_reasons_for_seven_days_only(self):
        for name, days in (("20261101-000000-claude-aaaa", 30), ("20261109-000000-claude-bbbb", 1)):
            write(self.root, f"sessions/{name}/meta.json", json.dumps({"id": name, "title": name[-4:], "status": "closed", "approval": "approved",
                                                                        "closed": self.stamp(days), "no_judge": "reason-" + name[-4:]}))
        d = self.digest()
        self.assertIn("reason-bbbb", d)
        self.assertNotIn("reason-aaaa", d)

    # ---- B2 + B8 (chat surface): the MCP close still closes ----
    def test_b2_b8_mcp_close_from_a_chat_surface(self):
        call = lambda i, name, args: {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}
        init = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, {"jsonrpc": "2.0", "method": "notifications/initialized"}]
        run = lambda msgs: {d["id"]: d for d in map(json.loads, self.run_tool("brain_mcp.py", stdin="\n".join(json.dumps(m) for m in init + msgs) + "\n")[1].splitlines())}
        out = run([call(2, "brain_session_new", {"title": "chat task", "request": "write a short note", "lane": "standard", "requirements": ["a note exists — check: The owner reads it"]})])
        sid = json.loads(out[2]["result"]["content"][0]["text"])["session"]
        out = run([call(3, "brain_close", {"session": sid, "task_summary": "Wrote the note and read it back.", "brain_summary": "none"})])
        self.assertEqual(json.loads(out[3]["result"]["content"][0]["text"])["status"], "closed", out[3])
        self.assertIn("Chat/Cowork", self.meta(sid)["no_judge"])
        self.assertIn("Delivered: Wrote the note", open(os.path.join(self.sdir(sid), "task-summary.md"), encoding="utf-8").read())

    # ---- B3 (window): a skipped step from a month ago is not proposed again ----
    def test_b3_skipped_step_proposals_look_at_fourteen_days(self):
        for name, days in (("old1", 30), ("new1", 1)):
            write(self.root, f"sessions/{name}/analysis.json", json.dumps({"ended": self.stamp(days), "flow": {"lane": "standard", "missing_steps": ["judge"]}}))
        self.assertIn("Flow step skipped in 1 session(s): judge", self.digest())

    # ---- B4 (card): decisions and exceptions are counted apart ----
    def test_b4_card_counts_decisions_and_exceptions_apart(self):
        write(self.root, "state/sleep-last.json", json.dumps({"finished": "2026-11-10 10:00:00", "release": None, "decisions": 3, "exceptions": 1, "digest": "reports/d.md"}))
        rc, so, se = self.run_tool("brain_start.py", "--agent", "claude", "--format", "text", "--cwd", self.root)
        self.assertIn("waiting for the owner: 3 decision(s), 1 exception(s)", so, se)

    # ---- B6 (use): the card and the judge each report a stale health check ----
    def test_b6_card_reports_a_stale_health_check(self):
        write(self.root, "tools/judge-health.json", json.dumps({"checked": "2020-01-01 10:00", "judges": [{"cli": "codex", "status": "STRONG"}]}))
        rc, so, se = self.run_tool("brain_start.py", "--agent", "claude", "--format", "text", "--cwd", self.root)
        self.assertIn("your judge codex STRONG (STALE check, counts as unverified", so, se)

    def test_b6_judge_reports_a_stale_health_check(self):
        env = dict(self.env, BRAIN_JUDGE_HEALTH_DAYS="0")
        fake = os.path.join(self.tmp.name, "bin", "codex")
        verdict = {"overall": "pass", "verdicts": [{"requirement": "R1", "verdict": "pass", "evidence": "x", "severity": "none"}], "flaws": []}
        write(self.tmp.name, "bin/codex", "#!/bin/sh\nout=''\nwhile [ $# -gt 0 ]; do [ \"$1\" = \"-o\" ] && out=\"$2\"; shift; done\n"
              f"cat > /dev/null\nprintf '%s' '{json.dumps(verdict)}' > \"$out\"\n")
        os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
        sid = self.fast("b6")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, env=dict(env, BRAIN_CODEX_BIN=fake))
        self.assertEqual(json.loads(so)["strength"], "unverified (health check stale)", se)

    # ---- C1 (new lessons): a lesson keeps the scope class of the session it came from ----
    def test_c1_new_lesson_carries_its_sessions_scope(self):
        write(self.root, "sessions/s1/meta.json", json.dumps({"title": "private task", "scope_class": "personal", "project": "none"}))
        write(self.root, "queue/s1-lesson.md", "---\ntitle: x\ntype: lesson\nstatus: candidate\nsource: sessions/s1/\n---\nCheck the dates twice.\n")
        rc, so, se = self.run_tool("brain_sleep.py", "--no-gym")
        lesson = os.path.join(self.root, json.loads(so)["lessons"][0])
        self.assertIn("scope_class: personal", open(lesson, encoding="utf-8").read())

    # ---- C1 (budget): a released lesson is treated as a constraint card ----
    def test_c1_released_lesson_is_a_constraint_card(self):
        write(self.root, "Brain System/lessons/rule.md", "---\ntitle: \"turbine rule\"\ntype: lesson\nstatus: released\nsummary: recheck the turbine clearance before export\n---\n# turbine rule\nRecheck.\n")
        notes = json.loads(self.run_tool("brain_route.py", "--query", "turbine clearance export", "--scope", "engineering", "--json")[1])["notes"]
        self.assertEqual([(n["title"], n["constraint"]) for n in notes], [("turbine rule", True)])

    def hint(self, prompt, scope="engineering"):
        self.run_tool("brain_index.py")
        rc, so, se = self.py("import json, brain_hooks as H\n" + f"print(json.dumps([[n['title'], n['type']] for n in H.pick_notes({prompt!r}, {scope!r}, n=5, threshold=0)]))")
        return json.loads(so)

    # ---- C1 (hint): the per-message hint shows a released lesson and no candidate ----
    def test_c1_hint_shows_released_lessons_only(self):
        for name, status in (("lesson released", "released"), ("lesson candidate", "candidate")):
            write(self.root, f"Brain System/lessons/{name}.md", f"---\ntitle: \"{name}\"\ntype: lesson\nstatus: {status}\nsummary: recheck the turbine clearance before export\n---\n# {name}\nRecheck.\n")
        titles = [t for t, _ in self.hint("turbine clearance export")]
        self.assertIn("lesson released", titles)
        self.assertNotIn("lesson candidate", titles)

    # ---- C2 (hint): the per-message hint carries at most one episode ----
    def test_c2_hint_carries_at_most_one_episode(self):
        for i in range(3):
            write(self.root, f"Brain System/history/episodes/ep{i}.md", f"---\ntitle: \"Episode {i}\"\ntype: episode\nsummary: gearbox housing print run {i}\n---\n# Episode {i}\nGearbox housing print.\n")
        self.assertEqual(len([t for t, typ in self.hint("gearbox housing print") if typ == "episode"]), 1)

    # ---- C2 (frontmatter): an episode records the judge result ----
    def test_c2_episode_records_the_judge_result(self):
        sid = self.fast("c2j")
        rc, so, se = self.run_tool("brain_session.py", "close", "--session", sid, "--summary", "done")
        self.assertIn("\njudge: none\n", open(os.path.join(self.root, json.loads(so)["episode"]), encoding="utf-8").read())

    # ---- C3 (paths): the queue and the digests are part of the release too ----
    def test_c3_release_paths_include_queue_and_digests(self):
        write(self.root, "queue/x-lesson.md", "x\n")
        write(self.root, "reports/digest-2026-W46.md", "x\n")
        rc, so, se = self.py("import json, brain_sleep as S\nprint(json.dumps(S.record_paths()))")
        paths = json.loads(so)
        self.assertIn("queue", paths, se)
        self.assertIn("reports/digest-2026-W46.md", paths)

    # ---- C4 (Codex): a Codex running total is cut to the session's window ----
    def test_c4_codex_running_total_is_windowed(self):
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"
        now = time.time()
        ev = lambda t, i, o: json.dumps({"timestamp": iso(t), "payload": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": i, "cached_input_tokens": 0, "output_tokens": o, "total_tokens": i + o}}}})
        tr = write(self.tmp.name, "rollout-x.jsonl", "\n".join([ev(now - 7200, 100, 10), ev(now - 3600, 300, 30), ev(now, 600, 60)]) + "\n")
        rc, so, se = self.py("import json, token_meter as T\n" + f"r = T.codex([{tr!r}], since={now - 5400}, until={now - 1800})[0]\nprint(json.dumps([r['context_in'], r['output']]))")
        self.assertEqual(json.loads(so), [200, 20], se)

    # ---- C4 (corrections): The owner's messages are counted inside the session's window ----
    def test_c4_corrections_are_counted_inside_the_window(self):
        iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".000Z"
        now = time.time()
        msg = lambda t: json.dumps({"timestamp": iso(t), "type": "user", "message": {"content": "do it"}})
        tr = write(self.tmp.name, "u.jsonl", "\n".join([msg(now - 7200), msg(now - 3600), msg(now - 3500), msg(now)]) + "\n")
        rc, so, se = self.py("import json, pilot as P\n" + f"print(json.dumps([P.user_turns({tr!r}), P.user_turns({tr!r}, {now - 5400}, {now - 1800})]))")
        self.assertEqual(json.loads(so), [4, 2], se)


if __name__ == "__main__":
    unittest.main()
