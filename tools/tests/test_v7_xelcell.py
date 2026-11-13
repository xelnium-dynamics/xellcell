#!/usr/bin/env python3
"""
Regression suite for v7 "Xelcell": the fixes for the findings of judge round 4 (Argon), one test per finding.
 Q  judge: backticked / escaped quotes are paired correctly; a pass that rests only on quotes nobody can find is not a pass;
    an unreadable artifact is never advertised as sealed and never crashes the packet; the judge CLI timing out or not
    starting is an inconclusive round, not a crash.
 H  hooks: a skill shown earlier that fits again is named again with its path after REMIND_AFTER messages; a compaction
    makes the hooks offer the skills once more.
 C  close: brain_learn.py is the one place that queues lessons (one naming scheme); the old code is only the fallback.
 M  map: braces inside a multi-line template literal are not code; memo/forwardRef components; GLSL precision qualifiers.
 R  route_real: the session's own scope is used; the label sheet and its scoring.
 D  dream prints the calibrate alert; the installer migrates the old folder name; brain.py puts forwarded flags first.
"""
import json
import os
import stat
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_v6_clearwater import Base, write, read, TOOLS, REAL  # noqa: E402

sys.path.insert(0, TOOLS)
import brain_judge as BJ  # noqa: E402
import brain_map  # noqa: E402

SLOW_JUDGE = "#!/usr/bin/env python3\nimport time\ntime.sleep(5)\n"


class JudgeV7(Base):
    def test_q1_backticked_and_escaped_quotes_are_paired_correctly(self):
        ev = 'The file holds `{"overall": "pass", "verdicts": []}` and the test says "review_verdict downgrades a pass".'
        self.assertEqual(BJ.quoted(ev), ['{"overall": "pass", "verdicts": []}', "review_verdict downgrades a pass"])
        ev2 = 'It prints "he said \\"never guess\\" twice in the text" and then stops here for good measure.'
        self.assertEqual(BJ.quoted(ev2), ['he said "never guess" twice in the text'])
        self.assertEqual(BJ.quoted('a short "x" one and `y` are below the 20-character floor'), [])

    def test_q2_a_pass_resting_only_on_unfound_quotes_is_not_a_pass(self):
        contract = "## Hard requirements\n- R1: a — check: x\n- R2: b — check: y\n\n## Preferences\n"
        v, w = BJ.review_verdict({"overall": "pass", "flaws": [], "verdicts": [
            {"requirement": "R1", "verdict": "pass", "evidence": 'the log says "the turbine was validated against test data"', "severity": "none"},
            {"requirement": "R2", "verdict": "pass", "evidence": 'it says "all numbers carry SI units"', "severity": "none"}]},
            contract, "the packet says: all numbers carry SI units. nothing else")
        self.assertEqual([r["verdict"] for r in v["verdicts"]], ["inconclusive", "pass"])
        self.assertEqual(v["overall"], "inconclusive")
        self.assertIn("none of the quoted evidence is in the packet", v["verdicts"][0]["evidence"])
        # one found quote keeps the row a pass (the missing one is a warning): a judge may shorten a second quote
        v, w = BJ.review_verdict({"overall": "pass", "flaws": [], "verdicts": [
            {"requirement": "R1", "verdict": "pass", "evidence": '"all numbers carry SI units" and "something nobody wrote anywhere"', "severity": "none"},
            {"requirement": "R2", "verdict": "pass", "evidence": "no quote here", "severity": "none"}]}, contract, "all numbers carry SI units")
        self.assertEqual((v["overall"], len(w)), ("pass", 1))

    @unittest.skipIf(os.name == "nt", "Windows ignores chmod read bits, so a file cannot be made unreadable this way")
    def test_q3_an_unreadable_artifact_is_not_advertised_and_does_not_crash(self):
        sid = self.new()
        ok = write(self.root, "out/report.md", "# Report\nfine\n")
        locked = write(self.root, "out/locked.md", "# Locked\nsecret\n")
        os.chmod(locked, 0)
        try:
            for flag in ("--dry-run", "--preflight"):
                rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", ok, locked, flag)
                self.assertNotIn("Traceback", se, flag)
                self.assertNotIn("./artifacts/02-locked.md", so, flag)
            rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", ok, locked, "--dry-run")
            man = so[so.index("## 0 What you received"):so.index("## 1 Goal")]
            self.assertRegex(man, r"out/locked\.md \| artifact \| - \| UNREADABLE")
            self.assertRegex(man, r"out/report\.md \| artifact \| \d+ \| full")
        finally:
            os.chmod(locked, stat.S_IRUSR | stat.S_IWUSR)

    def test_q4_judge_cli_timeout_or_missing_is_an_inconclusive_round(self):
        sid = self.new()
        art = write(self.root, "out/report.md", "# Report\n")
        write(self.root, "judge/config.json", json.dumps({"timeout_s": 1}))
        exe = write(self.tmp.name, "bin/slow-codex", SLOW_JUDGE)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, env=dict(self.env, BRAIN_CODEX_BIN=exe))
        self.assertEqual((rc, json.loads(so)["overall"]), (2, "inconclusive"), se)
        self.assertIn("judge timed out after 1s", json.load(open(os.path.join(self.sdir(sid), "verdict-01.json")))["raw_tail"])
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, env=dict(self.env, BRAIN_CODEX_BIN="/nonexistent/codex"))
        self.assertEqual((rc, json.loads(so)["overall"]), (2, "inconclusive"), se)
        self.assertIn("judge CLI could not start", json.load(open(os.path.join(self.sdir(sid), "verdict-02.json")))["raw_tail"])

    def test_q5_brain_py_puts_the_forwarded_flag_first(self):
        sid = self.new()
        a1, a2 = write(self.root, "out/a.md", "# a\n"), write(self.root, "out/b.md", "# b\n")
        rc, so, se = self.run_tool("brain.py", "preflight", "--session", sid, "--artifacts", a1, a2)
        self.assertEqual(json.loads(so)["artifacts"], 2, se)          # both files are artifacts; --preflight was not swallowed
        self.assertEqual([f for f in os.listdir(self.sdir(sid)) if f.startswith("verdict-")], [])


class HooksV7(Base):
    ASK = "write a custom glsl vertex shader for the threejs water surface"

    def index(self):
        write(self.vault, "system/card.md", "---\ntitle: Card\ntype: system\n---\n# Card\nx\n")
        self.assertEqual(self.run_tool("brain_index.py")[0], 0)

    def say(self, csid, text):
        return self.hook("prompt", {"session_id": csid, "cwd": self.root, "prompt": text}).get("additionalContext", "")

    def test_h7_a_skill_that_fits_again_is_named_again_with_its_path(self):
        self.index()
        first = self.say("conv-R", self.ASK)                                  # message 1: the full line
        self.assertIn("- threejs-shaders: ", first)
        self.assertEqual(self.say("conv-R", self.ASK), "")                    # message 2: just said, silence
        for i in range(3, 9):
            self.say("conv-R", f"carry on with step {i}")                     # messages 3-8: other work
        again = self.say("conv-R", self.ASK)                                  # message 9: eight messages later it fits again
        self.assertIn("Skills shown earlier that fit this message again", again)
        self.assertIn("threejs-shaders → ", again)
        self.assertIn("threejs-shaders/SKILL.md", again)                      # with the path, so it can be opened
        self.assertNotIn("- threejs-shaders: ", again)                        # one line, not the full description again
        self.assertLess(len(again), len(first))
        self.assertEqual(self.say("conv-R", self.ASK), "")                    # message 10: reminded a moment ago, silence

    def test_h8_after_a_compaction_the_skill_is_offered_in_full_again(self):
        self.index()
        csid = "conv-K"
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "t", "--lane", "fast", "--request", "tidy", "--check", "true")
        self.hook("post", {"session_id": csid, "tool_name": "Bash", "tool_input": {"command": "python3 -I brain_session.py new --agent claude"}, "tool_response": {"stdout": so, "stderr": ""}})
        self.assertIn("- threejs-shaders: ", self.say(csid, self.ASK))
        self.assertEqual(self.say(csid, self.ASK), "")
        rc, so, se = self.run_tool("brain_start.py", "--agent", "claude", stdin=json.dumps({"session_id": csid, "source": "compact", "cwd": self.root}))
        self.assertIn("you are back in brain session", so)
        back = self.say(csid, self.ASK)                                       # the summary dropped the hook's words: say them once more
        self.assertIn("- threejs-shaders: ", back)
        self.assertIn("brain session", back)


class CloseV7(Base):
    def summaries(self, sid):
        d = self.sdir(sid)
        write(d, "task-summary.md", "# Task summary\n| Delivered | the spec |\n| Verified (requirement → tier → evidence) | R1 → Tier 0 |\n")
        write(d, "brain-summary.md", "# Brain Summary\n| Field | Content |\n|---|---|\n| Proposed lesson | Always specify a white underbase under dark red on kraft. |\n"
              "| Lesson cue (when it applies) | printing on kraft |\n\n## Lessons\n- Second lesson about press proofs and separations here.\n- Third lesson about varnish and drying times here.\n- Fourth lesson that must not be queued at all.\n")

    def test_c3_one_place_queues_lessons_with_one_naming_scheme(self):
        sid = self.new()
        self.summaries(sid)
        rc, so, se = self.run_tool("brain_session.py", "close", "--session", sid, "--no-judge", "unit test")
        res = json.loads(so)
        self.assertEqual((rc, res["status"]), (0, "closed"), se)
        files = sorted(os.listdir(os.path.join(self.root, "queue")))
        self.assertEqual(files, [f"{sid}-lesson-02.md", f"{sid}-lesson-03.md", f"{sid}-lesson.md"])
        self.assertEqual(res["queued"], f"queue/{sid}-lesson.md")
        first = read(os.path.join(self.root, "queue", f"{sid}-lesson.md"))
        self.assertIn("white underbase under dark red", first)
        self.assertIn("- cue: printing on kraft", first)                       # brain_learn's structured form, not the v3 one-liner
        self.assertNotIn("Fourth lesson", "".join(read(os.path.join(self.root, "queue", f)) for f in files))

    def test_c4_the_old_queue_code_runs_only_when_brain_learn_fails(self):
        sid = self.new()
        self.summaries(sid)
        code = ("import argparse, json, brain_session as S, brain_learn as L\n"
                "def boom(*a, **k): raise RuntimeError('learn is down')\n"
                "L.learn_session = boom\n"
                f"a = argparse.Namespace(session={sid!r}, approval='pending', project=None, summary=None, force_claims=False, no_judge='unit test', unresolved=None)\n"
                "S.cmd_close(a)\n")
        out = json.loads(self.py(code).strip().splitlines()[-1])
        self.assertEqual(out["status"], "closed")
        self.assertIn("RuntimeError", out["learn"]["error"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.root, "queue"))), [f"{sid}-lesson.md"])    # the proposed lesson is not lost
        self.assertIn("white underbase", read(os.path.join(self.root, "queue", f"{sid}-lesson.md")))


class MapV7(Base):
    def test_m5_braces_inside_a_template_literal_are_not_code(self):
        src = "\n".join([
            "export function makeWater() {",                 # 1
            "  const frag = `",                              # 2
            "    void main() {",                             # 3
            "      if (x > 0.0) { discard; }",               # 4
            "    }",                                         # 5   (inside the literal: not the end of makeWater)
            "    float wave(vec2 p) {",                      # 6
            "  `;",                                          # 7   an unbalanced brace inside the literal
            "  return frag;",                                # 8
            "}",                                             # 9   the real end
            "",
            "export function after() {",                     # 11
            "  return 1;",
            "}"])                                            # 13
        syms = {s[1]: (s[2], s[3]) for s in brain_map.parse_js(src)[0]}
        self.assertEqual(syms["makeWater"], (1, 9))
        self.assertEqual(syms["after"], (11, 13))
        self.assertNotIn("wave", syms)                       # GLSL inside a string is not a JS symbol

    def test_m6_wrapped_components_and_glsl_precision(self):
        js = "export const Card = React.memo(function Card(props) {\n  return null;\n});\nconst Input = forwardRef((p, ref) => {\n  return null;\n});\nconst Box = styled.div`\n  color: red;\n`;\n"
        names = {s[1]: s[0] for s in brain_map.parse_js(js)[0]}
        for want in ("Card", "Input", "Box"):
            self.assertEqual(names.get(want), "fn", want)
        glsl = "uniform highp float uTime;\nhighp float wave(vec2 p) {\n  return 1.0;\n}\nvoid main() {\n}\n"
        got = [(s[0], s[1]) for s in brain_map.parse_glsl(glsl)[0]]
        self.assertEqual(got, [("uniform", "uTime"), ("fn", "wave"), ("fn", "main")])


class RealV7(Base):
    def make(self):
        write(self.vault, "system/card.md", "---\ntitle: Card\ntype: system\n---\n# Card\nx\n")
        self.assertEqual(self.run_tool("brain_index.py")[0], 0)
        for sid, scope, req in (("20261101-000001-claude-aaaa", "brand", "write a custom glsl vertex shader for the threejs water surface"),
                                ("20261101-000002-claude-bbbb", "general", "write a custom glsl fragment shader for threejs postprocessing"),
                                ("20261101-000003-claude-cccc", "general", "tidy the notes folder and rename the files")):
            d = os.path.join(self.root, "sessions", sid)
            write(d, "meta.json", json.dumps({"id": sid, "status": "closed", "scope_class": scope}))
            write(d, "contract.md", f"---\nscope_class: {scope}\n---\n## Request (verbatim)\n{req}\n\n## Deliverables\n-\n")
        tr = os.path.join(self.tmp.name, "tr")
        user = lambda text: json.dumps({"type": "user", "message": {"content": text}})
        write(tr, "-Users-me-game/a.jsonl", user("glsl vertex shader threejs") + "\n" + user("sounds fine") + "\n")
        return tr

    def test_r7_the_sessions_own_scope_is_used(self):
        tr = self.make()
        out_file = os.path.join(self.tmp.name, "real.json")
        rc, so, se = self.run_tool("route_real.py", "--transcripts", tr, "--out", out_file)
        self.assertEqual(rc, 0, se)
        res = json.load(open(out_file))
        rows = {r["session"][-4:]: r for r in res["requests"]}
        self.assertEqual((rows["aaaa"]["scope"], rows["bbbb"]["scope"]), ("brand", "general"))
        for r in res["requests"]:
            self.assertIn("offered_general", r)
            self.assertNotIn("text", r)                                           # the result file still holds no words
        self.assertIn("requests_whose_scope_changes_the_offer", res["summary"])
        code = ("import route_real as R\ncalls = []\nreal = R.H.pick_skills\n"
                "def spy(text, **k):\n    calls.append(k.get('scope'))\n    return real(text, **k)\n"
                "R.H.pick_skills = spy\n"
                f"R.requests({os.path.join(self.root, 'sessions')!r})\nprint(sorted(set(calls)))")
        self.assertEqual(self.py(code).strip(), "['brand', 'general']")           # the brand session was routed as brand

    def test_r8_label_sheet_and_its_scoring(self):
        tr = self.make()
        sheet = os.path.join(self.root, "reports", "route-labels.md")
        rc, so, se = self.run_tool("route_real.py", "--transcripts", tr, "--sheet", sheet)
        self.assertEqual((rc, json.loads(so)["requests"], json.loads(so)["short_messages"]), (0, 3, 2), se)
        text = read(sheet)
        self.assertIn("> write a custom glsl vertex shader for the threejs water surface", text)   # the owner's own words, locally
        self.assertIn("- [ ] threejs-shaders", text)
        # the owner ticks: session aaaa -> the shader skill is right; session cccc -> nothing fits, and names a missing skill;
        # short messages: the shader one is a task, "sounds fine" is talk. Session bbbb is left untouched (skipped).
        a, b = text.index("### 20261101-000001-claude-aaaa"), text.index("### 20261101-000002-claude-bbbb")
        text = text[:a] + text[a:b].replace("- [ ] threejs-shaders", "- [x] threejs-shaders") + text[b:]
        c = text.index("### 20261101-000003-claude-cccc")
        text = text[:c] + text[c:].replace("- [ ] none of these fit", "- [x] none of these fit", 1).replace("- missing: ", "- missing: file-organizer", 1)
        lines = []
        for line in text.splitlines():
            if "glsl vertex shader threejs" in line and line.startswith("- [ ] task"):
                line = line.replace("- [ ] task", "- [x] task", 1)
            if "sounds fine" in line:
                line = line.replace("[ ] talk", "[x] talk", 1)
            lines.append(line)
        write(self.root, "reports/route-labels.md", "\n".join(lines) + "\n")
        rc, so, se = self.run_tool("route_real.py", "--transcripts", tr, "--labels", sheet)
        res = json.loads(so)
        self.assertEqual(rc, 0, se)
        self.assertEqual((res["labelled_requests"], res["requests_with_a_right_skill_offered"], res["requests_where_nothing_offered_fits"],
                          res["skills_named_as_missing"]), (2, 1, 1, 1))
        self.assertEqual((res["short_messages_marked_task"], res["task_that_got_nothing"], res["short_messages_marked_talk"],
                          res["talk_that_got_a_skill_list"]), (1, 0, 1, 0))
        self.assertNotIn("water surface", so)                                     # counts only
        self.assertIn("reports/route-labels", read(os.path.join(REAL, ".gitignore")))


class MiscV7(Base):
    def test_d1_dream_prints_the_calibrate_alert(self):
        write(self.root, "judge/questions/REQ-MET.json", json.dumps({"id": "REQ-MET", "question": "Met?", "labels": ["yes", "no"], "state_fields": ["x"], "threshold": {"value": None}}))
        write(self.root, "judge/gold/owner/REQ-MET.jsonl", "".join(json.dumps({"state": {"x": i}, "label": "yes", "source": "owner"}) + "\n" for i in range(32)))
        row = {"question_id": "REQ-MET", "tier": 2, "escalated_from": 1, "tier1": {"runs": ["yes", "yes"], "accepted": False, "why_not": "cold start (fewer than 30 gold labels)"}}
        write(self.root, "judge/log.jsonl", "".join(json.dumps(row) + "\n" for _ in range(5)))
        empty = os.path.join(self.tmp.name, "no-transcripts")
        os.makedirs(empty)
        rc, so, se = self.run_tool("brain_dream.py", "--once", "--transcript-roots", empty)
        self.assertEqual(rc, 0, se)
        gaps = read(os.path.join(self.vault, "capabilities", "dream-skill-gaps.md"))
        self.assertRegex(gaps, r"- Typed judge alert `REQ-MET`: 32 gold labels exist but no threshold is live .* -> calibrate_threshold")

    def test_d3_telemetry_is_rebuilt_from_the_records_with_the_current_rule(self):
        for sid, summary, read_skill in (("20261101-000001-claude-aaaa", "We ship it on Friday.", "threejs-patterns"),
                                         ("20261101-000002-claude-bbbb", "Followed threejs-patterns for the scene.", None)):
            d = os.path.join(self.root, "sessions", sid)
            write(d, "meta.json", json.dumps({"id": sid, "status": "closed"}))
            write(d, "retrieval-01.md", "# Route\n\n## Skills\n- **ship** (x) — ship\n- **threejs-patterns** (x) — patterns\n")
            write(d, "task-summary.md", f"# T\n| Delivered | {summary} |\n")
            if read_skill:
                write(d, "evidence.jsonl", json.dumps({"tool": "Read", "file": f"/x/skills/{read_skill}/SKILL.md"}) + "\n")
        write(self.root, "state/skill-telemetry.json", json.dumps({"processed_sessions": ["old"], "skills": {"ship": {"shown": 13, "used": 13}}}))
        rc, so, se = self.run_tool("brain_learn.py", "--rebuild-telemetry")
        res = json.loads(so)
        self.assertEqual((rc, res["rebuilt_from_sessions"], res["used"]), (0, 2, {"threejs-patterns": 2}), se)   # the read and the named use count; "ship" in prose does not
        tel = json.load(open(os.path.join(self.root, "state", "skill-telemetry.json")))
        self.assertEqual((tel["skills"]["ship"]["shown"], tel["skills"]["ship"]["used"]), (2, 0))
        kept = [f for f in os.listdir(os.path.join(self.root, "state")) if f.startswith("skill-telemetry.before-rebuild-")]
        self.assertEqual(len(kept), 1)                                                    # the old file is kept, not deleted

    def test_d4_a_calibration_that_tier1_lost_is_not_reported_as_missing(self):
        import datetime
        later = (datetime.date.today() + datetime.timedelta(days=20)).isoformat()
        t = {"value": None, "labels_used": 39, "set_on": "2026-11-14", "expires_on": later, "rule": "cold_start_escalate_all",
             "tier1_lower_bound": 0.597, "tier2_accuracy": 0.718}
        write(self.root, "judge/questions/REQ-MET.json", json.dumps({"id": "REQ-MET", "question": "Met?", "labels": ["yes", "no"], "state_fields": ["x"], "threshold": t}))
        write(self.root, "judge/gold/owner/REQ-MET.jsonl", "".join(json.dumps({"state": {"x": i}, "label": "yes", "source": "owner"}) + "\n" for i in range(39)))
        row = {"question_id": "REQ-MET", "tier": 2, "escalated_from": 1, "tier1": {"runs": ["yes", "yes"], "accepted": False, "why_not": "x"}}
        write(self.root, "judge/log.jsonl", "".join(json.dumps(row) + "\n" for _ in range(5)))
        st = json.loads(self.run_tool("judge_typed.py", "status")[1])
        self.assertEqual(st["alerts"], [])                                                # no "run calibrate" after it was run
        self.assertIn("Tier 1 too weak (lower bound 0.597 vs Tier 2 0.718)", st["questions"]["REQ-MET"]["status"])
        t["expires_on"] = "2020-01-01"                                                    # once it expires, the alert comes back
        write(self.root, "judge/questions/REQ-MET.json", json.dumps({"id": "REQ-MET", "question": "Met?", "labels": ["yes", "no"], "state_fields": ["x"], "threshold": t}))
        self.assertEqual(json.loads(self.run_tool("judge_typed.py", "status")[1])["alerts"][0]["action"], "calibrate_threshold")

    def test_d5_tokens_means_design_tokens_only_next_to_a_design_word(self):
        out = self.py("import hydro_skills as HS, json\n"
                      "rows = [('design-token', 'Design tokens for colour, spacing and type in a design system', '/s/a/SKILL.md', 'Claude, Codex', 'brain-library', 'no'),\n"
                      "        ('studio-tokens', 'Turn a design direction into one tokens file', '/s/b/SKILL.md', 'Claude, Codex', 'brain-library', 'no')]\n"
                      "f = lambda q: [s['short'] for s in HS.rank_skills(q, rows, who='Claude')]\n"
                      "print(json.dumps([f('how many tokens did we use so far?'), f('codex still eats tons of tokens in each session'),\n"
                      "                  f('set up design tokens and dark mode colours for the UI')]))")
        usage1, usage2, design = json.loads(out)
        self.assertEqual((usage1, usage2), ([], []))                                     # AI usage: no design-token skills
        self.assertIn("design-token", design)                                             # design tokens: still found

    def test_d2_installer_migrates_the_old_folder_name_but_never_its_own(self):
        out = self.py("import hydro_install as I, json\n"
                      "print(json.dumps({'root': I.HYDRO_ROOT, 'pats': list(I.AGENT_BRAIN_PATTERNS),\n"
                      "                  'moved': I._replace_roots('python3 -I \"~/Desktop/HYDRO BRAIN/tools/brain_hooks.py\" pre')}))")
        d = json.loads(out)
        self.assertIn("~/Desktop/HYDRO BRAIN", d["pats"])
        self.assertNotIn(d["root"], d["pats"])
        self.assertEqual(d["moved"], f'python3 -I "{d["root"]}/tools/brain_hooks.py" pre')


if __name__ == "__main__":
    unittest.main()
