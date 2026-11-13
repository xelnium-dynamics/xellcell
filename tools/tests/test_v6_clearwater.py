#!/usr/bin/env python3
"""
Regression suite for v6 "Clearwater" (the review of Hydro Brain v4/v5):
 J  judge brief: manifest of what the judge received (cuts, binaries, missing files named), requirement ledger, error
    list from the evidence log, previous-round findings, sealed copies, code review of the judge's own answer, preflight.
 T  typed-judge status: an uncalibrated threshold is "calibrate", not "rewrite the question".
 M  project map: outline / query / slice / who, incremental rebuild, self/ never mapped; brain_fetch --outline/--section.
 H  hooks: a reminder, a skill and a note are said once per conversation; machine messages get nothing; the session
    linker ignores commands that merely contain the words and ids of past sessions.
 R  router: one or two content words call a skill only on real evidence; bounded verb <-> -ing matching.
 C  capsule: every checkpoint refreshes it; after a compaction the start hook prints it instead of the whole card.
 L  memory: at most three queued lessons per session and no gap-as-lesson; whole-sentence reflections; bridges need a
    shared title/tag word; the idle agent never weaves links by itself; logs are not retrieval answers; digest cap.
 E  one entry point (brain.py) forwards arguments and exit codes.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

import brain_dream  # noqa: E402
import brain_judge as BJ  # noqa: E402
import brain_map  # noqa: E402
import hydro_skills as HS  # noqa: E402


def write(base, rel, content, mode="w"):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as fh:
        fh.write(content)
    return p


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


FAKE_JUDGE = '''#!/usr/bin/env python3
import json, os, sys
out = sys.argv[sys.argv.index("-o") + 1]
seen = sorted(os.listdir("artifacts")) if os.path.isdir("artifacts") else []
with open(os.environ["FAKE_PROBE"], "w") as fh:
    json.dump({"sealed": seen, "packet_head": open("packet.md").read()[:400]}, fh)
with open(out, "w") as fh:
    fh.write(os.environ["FAKE_VERDICT"])
'''


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "brain")
        self.vault = os.path.join(self.root, "Brain System")
        for d in ("sessions", "queue", "reports", "state/eval", "Brain System/system"):
            os.makedirs(os.path.join(self.root, d), exist_ok=True)
        self.skills = os.path.join(self.tmp.name, "skills")
        write(self.skills, "threejs-shaders/SKILL.md",
              "---\nname: threejs-shaders\ndescription: Custom Three.js GLSL vertex and fragment shaders and postprocessing\n---\nShader guide\n")
        roots = write(self.tmp.name, "roots.json", json.dumps([{"path": self.skills, "agent": "Claude, Codex", "kind": "brain-library", "autoload": "no"}]))
        self.env = dict(os.environ, BRAIN_ROOT=self.root, BRAIN_SKILL_ROOTS=roots, BRAIN_NO_SLEEP="1", BRAIN_NO_AUTOROUTE="1")
        for k in ("BRAIN_VAULT", "BRAIN_INDEX_DB", "BRAIN_OFF", "BRAIN_HOOK_VERBOSE"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, script, *args, stdin=None, env=None, cwd=None):
        p = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, script), *args], input=stdin, capture_output=True,
                           text=True, env=env or self.env, cwd=cwd or self.root)
        return p.returncode, p.stdout, p.stderr

    def py(self, code):
        p = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {TOOLS!r})\n" + code],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr[-600:])
        return p.stdout

    def sdir(self, sid):
        return os.path.join(self.root, "sessions", sid)

    def new(self, reqs=("- R1: the report exists — check: exists: out/report.md",), checks=(), request="Build the turbine report", extra=()):
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "Turbine report", *extra)
        self.assertEqual(rc, 0, se)
        sid = json.loads(so)["session"]
        cp = os.path.join(self.sdir(sid), "contract.md")
        c = read(cp).replace("<paste the owner's request exactly>", request).replace("- R1: … — check: …", "\n".join(reqs)).replace('- "…"', "- (none quoted)")
        if checks:
            c = c.replace("<!-- - R1: cmd: <shell command that exits 0 when R1 is met> -->", "\n".join(checks))
        write(self.sdir(sid), "contract.md", c)
        return sid

    def hook(self, mode, data, env=None, agent=None):
        rc, so, se = self.run_tool("brain_hooks.py", mode, *(("--agent", agent) if agent else ()), stdin=json.dumps(data), env=env)
        self.assertEqual(rc, 0, se)
        return json.loads(so)["hookSpecificOutput"] if so.strip() else {}

    def fake_judge(self, verdict):
        exe = write(self.tmp.name, "bin/fake-codex", FAKE_JUDGE)
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IEXEC)
        probe = os.path.join(self.tmp.name, "judge-probe.json")
        return dict(self.env, BRAIN_CODEX_BIN=exe, FAKE_PROBE=probe, FAKE_VERDICT=json.dumps(verdict)), probe


# ---------------------------------------------------------------- J: judge brief
class JudgeBrief(Base):
    def test_j1_brief_says_what_it_received_the_goal_and_the_errors(self):
        sid = self.new(reqs=("- R1: the report exists — check: exists: out/report.md", "- R2: the numbers carry units — check: read the table"),
                       checks=("- R1: exists: out/report.md",))
        d = self.sdir(sid)
        small = write(self.root, "out/report.md", "# Report\nThrust 12 kN at 9000 rpm.\n")
        big = write(self.root, "out/big.log", "HEAD-PROBE " + "x" * 300000 + " TAIL-PROBE")
        binary = write(self.root, "out/render.png", b"\x89PNG\r\n\x1a\n\xff\xfe\x00binary", mode="wb")
        ghost = os.path.join(self.root, "out", "never-made.stl")
        write(d, "evidence.jsonl", "\n".join(json.dumps(r) for r in [
            {"t": "2026-11-13 10:00:00", "tool": "Bash", "command": "npm run build", "stderr_tail": "Error: cannot resolve ./mesh.js", "stdout_tail": ""},
            {"t": "2026-11-13 10:01:00", "tool": "Bash", "command": "pytest -q", "stderr_tail": "", "stdout_tail": "1 FAILED"},
            {"t": "2026-11-13 10:02:00", "tool": "Bash", "command": "pytest -q", "stderr_tail": "", "stdout_tail": "3 passed"},
            {"t": "2026-11-13 10:03:00", "tool": "Bash", "command": "python3 brain_session.py checkpoint --note SECRET-MAKER-NOTE", "stderr_tail": "Traceback (most recent call last)", "stdout_tail": ""},
            {"t": "2026-11-13 10:04:00", "tool": "Edit", "file": small},
            {"t": "2026-11-13 10:05:00", "tool": "Edit", "file": os.path.join(self.root, "src", "solver.py")},
            {"t": "2026-11-13 10:06:00", "tool": "Write", "file": small, "warn": "scout_unread_original: edited a file a scout pointed to without reading it first"},
        ]) + "\n")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", small, big, binary, ghost, small, "--dry-run")
        self.assertEqual(rc, 0, se)
        for head in ("## 0 What you received (manifest", "## 1 Goal — the contract (frozen, verbatim)", "### Requirement ledger",
                     "## 2 Errors and risk signals", "## 3 What the session changed", "## 4 Lenses for scope", "## 5 Artifacts"):
            self.assertIn(head, so)
        self.assertLessEqual(len(so), BJ.MAX_PACKET + 300)
        # every input is accounted for: full, cut (with the characters named), binary, missing; the duplicate counts once
        man = so[so.index("## 0 What you received"):so.index("## 1 Goal")]
        self.assertEqual(man.count("out/report.md |"), 1)
        self.assertRegex(man, r"out/report\.md \| artifact \| \d+ \| full")
        self.assertRegex(man, r"out/big\.log \| artifact \| \d+ \| excerpt: \d+ of 300022 chars \(characters \d+–\d+ cut\); full file: \./artifacts/02-big\.log")
        self.assertRegex(man, r"render\.png \| artifact \| \d+ \| not inlined \(image/PDF\); open \./artifacts/03-render\.png")
        self.assertRegex(man, r"never-made\.stl \| artifact \| - \| MISSING")
        self.assertIn("NOT in this packet, by design", man)
        self.assertIn("HEAD-PROBE", so)
        self.assertIn("TAIL-PROBE", so)            # head AND tail of a cut file are shown
        self.assertIn("…[CUT: characters", so)
        # the goal: one ledger row per requirement with its Tier-0 state
        self.assertRegex(so, r"\| R1 \| the report exists \| exists: out/report\.md \| PASS \(exists\) \|")
        self.assertRegex(so, r"\| R2 \| the numbers carry units \| read the table \| no Tier-0 check")
        # the errors: the open one is listed, the rerun one is counted, the brain's own command (maker's note) is not shown
        err = so[so.index("## 2 Errors"):so.index("## 3 What the session changed")]
        self.assertIn("npm run build", err)
        self.assertIn("cannot resolve ./mesh.js", err)
        self.assertIn("1 other error result(s) were followed by a clean rerun", err)
        self.assertNotIn("SECRET-MAKER-NOTE", so)
        self.assertIn("scout_unread_original", err)
        # what changed: the edited file that was not submitted is named
        chg = so[so.index("## 3 What the session changed"):so.index("## 4 Lenses")]
        self.assertIn("2 file(s) edited; 1 of them submitted", chg)
        self.assertIn("src/solver.py", chg)

    def test_j2_sealed_copies_fix_list_previous_round_and_brief_file(self):
        sid = self.new(reqs=("- R1: the report exists — check: exists: out/report.md", "- R2: the numbers carry units — check: read the table"))
        d = self.sdir(sid)
        art = write(self.root, "out/report.md", "# Report\nThrust 12 at 9000.\n")
        img = write(self.root, "out/plot.png", b"\x89PNG\r\n\x1a\n\xff\x00", mode="wb")
        v1 = {"overall": "fail", "flaws": ["axis labels missing"], "inputs_missing": ["the solver log"], "unsupported_claims": ["validated against test data"],
              "verdicts": [{"requirement": "R1 the report exists", "verdict": "pass", "evidence": "`Thrust 12 at 9000.`", "severity": "none", "fix": ""},
                           {"requirement": "R2 units", "verdict": "fail", "evidence": "`Thrust 12 at 9000.` has no unit", "severity": "major", "fix": "write 12 kN at 9000 rpm"}]}
        env, probe = self.fake_judge(v1)
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, img, env=env)
        res = json.loads(so)
        self.assertEqual((rc, res["overall"]), (1, "fail"), se)
        self.assertEqual(json.load(open(probe))["sealed"], ["01-report.md", "02-plot.png", "SEALED.txt"])           # the judge could open the originals
        self.assertIn("Read section 0", json.load(open(probe))["packet_head"])
        self.assertEqual(res["fix_list"], [{"requirement": "R2 units", "verdict": "fail", "fix": "write 12 kN at 9000 rpm"}])
        self.assertEqual(res["inputs_missing"], ["the solver log"])
        self.assertEqual(res["unsupported_claims"], ["validated against test data"])
        self.assertTrue(os.path.exists(os.path.join(d, "judge-brief-01.md")))                        # what the judge saw is kept
        rec = json.load(open(os.path.join(d, "verdict-01.json")))
        self.assertEqual(rec["brief"]["file"], "judge-brief-01.md")
        self.assertEqual([m["shown"] for m in rec["brief"]["inputs"]][0], "full")
        # round 2 is told what round 1 found
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, "--dry-run")
        prev = so[so.index("### Previous judge round (verdict-01.json)"):so.index("## 3 What the session changed")]
        self.assertIn("R2 units → fail (major)", prev)
        self.assertIn("asked fix: write 12 kN at 9000 rpm", prev)
        self.assertIn("flaw: axis labels missing", prev)
        self.assertIn("unsupported claim: validated against test data", prev)

    def test_j3_the_judges_own_answer_is_checked_by_code(self):
        contract = "## Hard requirements\n- R1: a — check: x\n- R2: b — check: y\n\n## Preferences\n"
        v, w = BJ.review_verdict({"overall": "pass", "verdicts": [{"requirement": "R1", "verdict": "pass", "evidence": "ok", "severity": "none"}], "flaws": []}, contract, "packet")
        self.assertEqual(v["overall"], "inconclusive")                                               # R2 has no verdict: not a pass
        self.assertEqual([r["verdict"] for r in v["verdicts"]], ["pass", "not_checked"])
        self.assertIn("no verdict for: R2", w[0])
        v, w = BJ.review_verdict({"overall": "pass", "flaws": [], "verdicts": [
            {"requirement": "R1", "verdict": "pass", "evidence": "x", "severity": "none"},
            {"requirement": "R2", "verdict": "fail", "evidence": "x", "severity": "blocker"}]}, contract, "packet")
        self.assertEqual(v["overall"], "fail")
        for open_row in ("inconclusive", "not_checked", "fail"):                                     # a pass may not stand next to an open row
            v, w = BJ.review_verdict({"overall": "pass", "flaws": [], "verdicts": [
                {"requirement": "R1", "verdict": "pass", "evidence": "x", "severity": "none"},
                {"requirement": "R2", "verdict": open_row, "evidence": "x", "severity": "minor"}]}, contract, "packet")
            self.assertEqual(v["overall"], "inconclusive", open_row)
        v, w = BJ.review_verdict({"overall": "pass", "flaws": [], "verdicts": [                      # a quote from a sealed copy is real evidence
            {"requirement": "R1", "verdict": "pass", "evidence": 'the sealed file says "deep inside the long file, beyond the excerpt"', "severity": "none"},
            {"requirement": "R2", "verdict": "pass", "evidence": "ok", "severity": "none"}]},
            contract, "the packet shows only the head", corpus="... deep inside the long file, beyond the excerpt ...")
        self.assertEqual((v["overall"], w), ("pass", []))
        v, w = BJ.review_verdict({"overall": "pass", "flaws": [], "verdicts": [
            {"requirement": "R1", "verdict": "pass", "evidence": 'the file says "thrust is exactly 12 kN at 9000 rpm"', "severity": "none"},
            {"requirement": "R2", "verdict": "pass", "evidence": 'it says "all numbers carry SI units"', "severity": "none"}]},
            contract, "the packet says: all numbers   carry SI units. nothing else")
        self.assertEqual(v["overall"], "inconclusive")                                               # v7: a pass resting only on an invented quote is not a pass
        self.assertEqual([r["verdict"] for r in v["verdicts"]], ["inconclusive", "pass"])
        self.assertIn("R1", w[0])
        self.assertEqual(BJ.review_verdict(None, contract, ""), (None, []))
        # quotes are paired in order: the judge's own words between two quotes are not a quote (judge round 3, R5)
        ev = 'install-status.json reports "agent-brain" for all three live configuration targets and "/Users/x/Library/LaunchAgents/dream.plist": "not-installed".'
        self.assertEqual(BJ.quoted(ev), ["/Users/x/Library/LaunchAgents/dream.plist"])
        self.assertEqual(BJ.quoted("it says `a backticked passage of some length` and “a curly quoted passage here”"),
                         ["a backticked passage of some length", "a curly quoted passage here"])
        v, w = BJ.review_verdict({"overall": "pass", "flaws": [], "verdicts": [                      # one real quote does not cover an invented one
            {"requirement": "R1", "verdict": "pass", "evidence": '"all numbers carry SI units" and "the turbine was validated against test data"', "severity": "none"},
            {"requirement": "R2", "verdict": "pass", "evidence": "ok", "severity": "none"}]}, contract, "all numbers carry SI units")
        self.assertEqual(len(w), 1)
        self.assertIn("1 of 2 quote(s)", w[0])
        self.assertEqual(BJ.requirements(contract), [("R1", "a", "x"), ("R2", "b", "y")])

    def test_j4_preflight_costs_nothing_and_writes_no_verdict(self):
        sid = self.new(reqs=("- R1: the report exists — check: exists: out/report.md", "- R2: units — check: read"), checks=("- R1: exists: out/report.md",))
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--preflight")
        out = json.loads(so)
        self.assertEqual((rc, out["ready"], out["tier0_failed"]), (1, False, ["R1"]), se)            # the check fails before any model is asked
        self.assertEqual(out["requirements_without_tier0_check"], ["R2"])
        art = write(self.root, "out/report.md", "# Report\n")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, "--preflight")
        self.assertEqual((rc, json.loads(so)["ready"]), (0, True), se)
        self.assertEqual([f for f in os.listdir(self.sdir(sid)) if f.startswith(("verdict-", "judge"))], [])

    def test_j6_many_files_fit_the_cap_and_small_ones_stay_whole(self):
        # found by the first real judge round of v6 (18 files, long paths): the overhead of headings and manifest rows
        # pushed the packet over its cap, the tail (the maker's summaries) was cut and every input was flagged
        sid = self.new()
        deep = "out/" + "a-rather-long-folder-name/" * 3
        arts = [write(self.root, f"{deep}small-{i:02d}.txt", f"SMALL-{i:02d} " + "s" * 300) for i in range(16)]
        arts += [write(self.root, f"{deep}big-{i}.log", f"BIG-{i}-HEAD " + "b" * 60000 + f" BIG-{i}-TAIL") for i in range(3)]
        write(self.sdir(sid), "task-summary.md", "# Task summary\nDelivered: things\nVerified: R1\nLAST-LINE-OF-THE-CLAIMS\n")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", *arts, "--dry-run")
        self.assertEqual(rc, 0, se)
        self.assertLessEqual(len(so) + len(BJ.INSTRUCTION), BJ.MAX_PACKET + 10)
        self.assertNotIn("packet hit its size cap", so)
        self.assertNotIn("PACKET CUT", so)
        self.assertIn("LAST-LINE-OF-THE-CLAIMS", so)                  # the end of the packet is intact
        man = so[so.index("## 0 What you received"):so.index("## 1 Goal")]
        self.assertEqual(len([l for l in man.splitlines() if "small-" in l and l.rstrip().endswith("| full |")]), 16)
        self.assertEqual(len([l for l in man.splitlines() if "big-" in l and "excerpt:" in l]), 3)
        for i in range(3):
            self.assertIn(f"BIG-{i}-HEAD", so)
            self.assertIn(f"BIG-{i}-TAIL", so)

    def test_j7_manifest_never_advertises_a_copy_that_is_not_sealed(self):
        sid = self.new()
        small = write(self.root, "out/report.md", "# Report\nsmall\n")
        huge = write(self.root, "out/scan.bin", b"\xff\xfe" + b"\x00" * 4096, mode="wb")
        code = ("import brain_judge as J, json, sys, tempfile, os\n"
                "J.SEAL_FILE_MAX = 1024\n"                                                             # make the 4 KB file 'too large'
                f"arts = [{small!r}, {huge!r}]\n"
                "text, man = J.packet('## Hard requirements\\n- R1: a — check: x\\n', arts, [], d=None)\n"
                "tmp = tempfile.mkdtemp(); n = J.seal(tmp, arts)\n"
                "print(json.dumps({'man': man, 'n': n, 'files': sorted(os.listdir(os.path.join(tmp, 'artifacts'))), 'text': text}))")
        out = json.loads(self.py(code))
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["files"], ["01-report.md", "SEALED.txt"])
        big = next(m for m in out["man"] if m["path"].endswith("scan.bin"))
        self.assertIsNone(big["sealed"])
        self.assertIn("NOT SEALED", big["shown"])
        self.assertNotIn("./artifacts/02-scan.bin", out["text"])
        self.assertIn("answer not_checked for what depends on it", out["text"])

    def test_j9_a_failed_copy_is_taken_out_of_the_packet_and_export_writes_a_package(self):
        small = write(self.root, "out/report.md", "# Report\nsmall\n")
        other = write(self.root, "out/notes.md", "# Notes\nmore\n")
        code = ("import brain_judge as J, json, shutil, os\n"
                f"arts = [{small!r}, {other!r}]\n"
                "text, man = J.packet('## Hard requirements\\n- R1: a — check: x\\n', arts, [], d=None)\n"
                "real = shutil.copyfile\n"
                "def flaky(src, dst):\n"
                "    if src.endswith('notes.md'): raise OSError('disk says no')\n"
                "    return real(src, dst)\n"
                "shutil.copyfile = flaky\n"
                "tmp, text2, man2 = J.prepare(arts, text, man)\n"
                "print(json.dumps({'before': './artifacts/02-notes.md' in text, 'after': './artifacts/02-notes.md' in text2, 'kept': './artifacts/01-report.md' in text2,\n"
                "                  'man': man2, 'files': sorted(os.listdir(os.path.join(tmp, 'artifacts')))}))")
        out = json.loads(self.py(code))
        self.assertEqual((out["before"], out["after"], out["kept"]), (True, False, True))
        self.assertEqual(out["files"], ["01-report.md", "SEALED.txt"])
        bad = next(m for m in out["man"] if m["path"].endswith("notes.md"))
        self.assertIsNone(bad["sealed"])
        self.assertIn("NOT SEALED: the copy failed", bad["shown"])
        # --export: the same packet as files, for a judge that someone runs by hand
        sid = self.new()
        pkg = os.path.join(self.tmp.name, "package")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", small, other, "--export", pkg)
        self.assertEqual(rc, 0, se)
        self.assertEqual(sorted(os.listdir(pkg)), ["artifacts", "packet.md", "schema.json"])
        self.assertEqual(sorted(os.listdir(os.path.join(pkg, "artifacts"))), ["01-report.md", "02-notes.md", "SEALED.txt"])
        packet = read(os.path.join(pkg, "packet.md"))
        self.assertTrue(packet.startswith("You are a blind judge."))
        self.assertIn("## 0 What you received", packet)
        self.assertEqual([f for f in os.listdir(self.sdir(sid)) if f.startswith(("verdict-", "judge"))], [])   # no round is recorded
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", small, "--export", pkg)
        self.assertNotEqual(rc, 0)                                                        # never overwrites a package

    def test_j10_a_verdict_from_a_judge_run_by_hand_is_recorded_and_checked(self):
        sid = self.new(reqs=("- R1: the report exists — check: exists: out/report.md", "- R2: units — check: read"))
        art = write(self.root, "out/report.md", "# Report\nThrust 12 kN.\n")
        answer = write(self.tmp.name, "argon.txt", "Here is my verdict:\n" + json.dumps({"overall": "pass", "flaws": [], "inputs_missing": [], "unsupported_claims": [],
                       "verdicts": [{"requirement": "R1 the report exists", "verdict": "pass", "evidence": "`Thrust 12 kN.`", "severity": "none", "fix": ""}]}) + "\nThanks.")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, "--record", answer, "--judge-name", "Argon")
        res = json.loads(so)
        self.assertEqual((rc, res["overall"], res["judge"]), (2, "inconclusive", "argon"), se)     # R2 got no verdict: the hand-run judge is checked too
        rec = json.load(open(os.path.join(self.sdir(sid), "verdict-01.json")))
        self.assertEqual((rec["tier2"], rec["judge_vendor"]), ("recorded by hand", "argon"))
        self.assertIn("by hand", rec["judge_strength"])
        self.assertIn("round 1: inconclusive (judge argon", read(os.path.join(self.sdir(sid), "judge.md")))
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, "--record", answer, "--judge-name", "claude")
        self.assertIn("SAME VENDOR AS THE MAKER", json.load(open(os.path.join(self.sdir(sid), "verdict-02.json")))["judge_strength"])

    def test_j11_sealed_only_files_keep_the_documents_whole(self):
        sid = self.new()
        doc = write(self.root, "out/README.md", "# The document\n" + "d" * 30000 + "\nDOC-LAST-LINE\n")
        codes = [write(self.root, f"src/module_{i}.py", f"# CODE-{i}\n" + "c" * 60000) for i in range(4)]
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", doc, "--sealed-only", *codes, "--dry-run")
        self.assertEqual(rc, 0, se)
        man = so[so.index("## 0 What you received"):so.index("## 1 Goal")]
        self.assertRegex(man, r"out/README\.md \| artifact \| \d+ \| full \|")              # the document is whole ...
        self.assertIn("DOC-LAST-LINE", so)
        self.assertEqual(len([l for l in man.splitlines() if "module_" in l and "not inlined (sealed only); open ./artifacts/" in l]), 4)
        self.assertNotIn("CODE-0", so)                                                    # ... the code is not inlined ...
        pkg = os.path.join(self.tmp.name, "pkg")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", doc, "--sealed-only", *codes, "--export", pkg)
        self.assertEqual(rc, 0, se)
        self.assertEqual(len([f for f in os.listdir(os.path.join(pkg, "artifacts")) if f.endswith(".py")]), 4)   # ... and travels as a full copy
        without = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", doc, *codes, "--dry-run")[1]
        man2 = without[without.index("## 0 What you received"):without.index("## 1 Goal")]
        self.assertRegex(man2, r"out/README\.md \| artifact \| \d+ \| excerpt: ")           # inlined beside the code, the same document is cut

    def test_j12_tier0_timeout_is_a_fail_and_can_be_raised(self):
        sid = self.new(checks=("- R1: cmd: python3 -c \"import time; time.sleep(2)\"",))
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--preflight", env=dict(self.env, BRAIN_TIER0_TIMEOUT="1"))
        out = json.loads(so)
        self.assertEqual((rc, out["tier0_failed"]), (1, ["R1"]), se)
        self.assertIn("timed out after 1 seconds", out["fix_list"][0]["fix"])
        art = write(self.root, "out/report.md", "# Report\n")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, "--preflight", env=dict(self.env, BRAIN_TIER0_TIMEOUT="30"))
        self.assertEqual((rc, json.loads(so)["tier0_failed"]), (0, []), se)

    def test_j8_a_check_that_exits_zero_on_an_error_is_marked(self):
        sid = self.new(checks=("- R1: cmd: ! grep -q forbidden out/never-there.txt",))
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--dry-run")
        self.assertRegex(so, r"\| R1 \| the report exists \| exists: out/report\.md \| PASS\? \(cmd\) \|")
        self.assertIn("exit 0, but the output looks like an error", so)

    def test_j5_lenses_follow_the_scope_and_never_fail_the_real_file(self):
        lenses = json.load(open(os.path.join(REAL, "judge", "lenses.json"), encoding="utf-8"))
        for scope in ("engineering", "website", "brand", "research", "system", "general", "cv_official"):
            self.assertGreaterEqual(len(lenses[scope]), 3, scope)
        self.assertIn("never fail a requirement because of a lens", BJ.INSTRUCTION)


# ---------------------------------------------------------------- T: typed judge status
class TypedStatus(Base):
    def test_t1_uncalibrated_is_calibrate_not_rewrite(self):
        write(self.root, "judge/questions/REQ-MET.json", json.dumps({"id": "REQ-MET", "question": "Met?", "labels": ["yes", "no"], "state_fields": ["x"], "threshold": {"value": None}}))
        write(self.root, "judge/gold/owner/REQ-MET.jsonl", "".join(json.dumps({"state": {"x": i}, "label": "yes", "source": "owner"}) + "\n" for i in range(32)))
        row = {"question_id": "REQ-MET", "tier": 2, "escalated_from": 1, "tier1": {"runs": ["yes", "yes"], "accepted": False, "why_not": "cold start (fewer than 30 gold labels)"}}
        write(self.root, "judge/log.jsonl", "".join(json.dumps(row) + "\n" for _ in range(5)))
        rc, so, se = self.run_tool("judge_typed.py", "status")
        st = json.loads(so)
        q = st["questions"]["REQ-MET"]
        self.assertEqual((q["rewrite_alert"], q["uncalibrated_escalations"], q["escalated"]), (False, 5, 0), se)
        self.assertEqual(st["alerts"][0]["action"], "calibrate_threshold")
        # real disagreement still raises the rewrite alert
        bad = dict(row, tier1={"runs": ["yes", "no"], "accepted": False, "why_not": "runs disagree"})
        write(self.root, "judge/log.jsonl", "".join(json.dumps(bad) + "\n" for _ in range(5)))
        st = json.loads(self.run_tool("judge_typed.py", "status")[1])
        self.assertTrue(st["questions"]["REQ-MET"]["rewrite_alert"])
        self.assertEqual(st["alerts"][0]["action"], "rewrite_question_not_threshold")


# ---------------------------------------------------------------- M: project map
class ProjectMap(Base):
    def project(self):
        proj = os.path.join(self.tmp.name, "game")
        write(proj, "src/main.js", "\n".join(
            ["// Night scene entry", "import { Bloom } from './fx/bloom.js';", "const SETTINGS = {", "  fog: 0.2,", "};", ""]
            + ["function pad%d() { return %d; }" % (i, i) for i in range(40)]
            + ["export function updateWaterSurface(time) {", "  const amp = Math.sin(time);", "  if (amp > 0) { ripple(amp); }", "  return amp;", "}", "",
               "class PlayerController {", "  constructor(scene) {", "    this.scene = scene;", "  }", "  walkForward(dt) {", "    return dt * 2;", "  }", "}", ""]))
        write(proj, "src/fx/bloom.js", "export class Bloom {\n  render() {\n    return 1;\n  }\n}\n")
        write(proj, "tools/solver.py", '"""Airflow solver."""\nimport math\n\nLIMIT_VALUE = 3\n\n\nclass Mesh:\n    def refine(self, n):\n        return n * 2\n\n\ndef solve_pressure(mesh):\n    return math.pi\n')
        write(proj, "index.html", "<html><head><title>Night Garden</title>\n<style>\n.hud-panel {\n  color: red;\n}\n</style></head>\n<body>\n<canvas id=\"stage\"></canvas>\n<script>\nfunction bootGame() {\n  return 42;\n}\n</script>\n</body></html>\n")
        write(proj, "docs/notes.md", "---\nsummary: build notes\n---\n# Build\nintro\n## Lighting\nwarm evening\n## Export\nglb\n")
        write(proj, "node_modules/junk/index.js", "function shouldNeverBeMapped() {}\n")
        return proj

    def test_m1_query_outline_slice_who(self):
        proj = self.project()
        rc, so, se = self.run_tool("brain_map.py", "query", "water surface update", "--root", proj)
        self.assertEqual(rc, 0, se)
        self.assertRegex(so, r"src/main\.js:L47-L51  fn updateWaterSurface")
        self.assertNotIn("shouldNeverBeMapped", so)
        rc, so, se = self.run_tool("brain_map.py", "slice", os.path.join(proj, "src/main.js"), "--symbol", "updateWaterSurface")
        self.assertIn("export function updateWaterSurface(time)", so)
        self.assertIn("return amp;", so)
        self.assertNotIn("pad3()", so)                                # the symbol, not the file
        self.assertLess(len(so), 500)
        rc, so, se = self.run_tool("brain_map.py", "outline", os.path.join(proj, "index.html"))
        for want in ("block <style>", "css .hud-panel", "el canvas#stage", "block <script>", "fn bootGame", "Night Garden"):
            self.assertIn(want, so)
        self.assertRegex(so, r"L10-L12  fn bootGame")                # line numbers inside an inline script are file lines
        rc, so, se = self.run_tool("brain_map.py", "outline", os.path.join(proj, "tools/solver.py"))
        for want in ("class Mesh", "method refine", "fn solve_pressure", "const LIMIT_VALUE", "Airflow solver."):
            self.assertIn(want, so)
        rc, so, se = self.run_tool("brain_map.py", "who", "Bloom", "--root", proj)
        self.assertRegex(so, r"defined: src/fx/bloom\.js:L1-L5  class Bloom")
        self.assertRegex(so, r"used: src/main\.js  1x at L2")
        rc, so, se = self.run_tool("brain_map.py", "query", "walk", "--root", proj)
        self.assertRegex(so, r"method walkForward  \(in PlayerController\)")

    def test_m4_glsl_css_and_json_files(self):
        proj = os.path.join(self.tmp.name, "kit")
        write(proj, "water.frag", "uniform float uTime;\nvarying vec2 vUv;\n\nfloat wave(vec2 p) {\n  return sin(p.x + uTime);\n}\n\nvoid main() {\n  gl_FragColor = vec4(wave(vUv));\n}\n")
        write(proj, "site.css", ":root {\n  --ink: #0b2f5a;\n}\n\n.hero-title {\n  color: var(--ink);\n}\n\n@media (max-width: 600px) {\n  .hero-title {\n    font-size: 2rem;\n  }\n}\n")
        write(proj, "tokens.json", '{\n  "palette": {\n    "navy": "#0b2f5a"\n  },\n  "spacing": [4, 8, 16]\n}\n')
        rc, so, se = self.run_tool("brain_map.py", "outline", os.path.join(proj, "water.frag"))
        for want in ("L1-L1  uniform uTime", "L2-L2  uniform vUv", "L4-L4  fn wave", "L8-L8  fn main"):
            self.assertIn(want, so)
        rc, so, se = self.run_tool("brain_map.py", "outline", os.path.join(proj, "site.css"))
        for want in ("L1-L3  css :root", "L5-L7  css .hero-title", "L9-L13  at-rule @media (max-width: 600px)"):
            self.assertIn(want, so)
        self.assertEqual(so.count("css .hero-title"), 1)                # the rule nested in @media is not a second top-level rule
        rc, so, se = self.run_tool("brain_map.py", "outline", os.path.join(proj, "tokens.json"))
        for want in ("L2-L2  key palette", "L5-L5  key spacing"):
            self.assertIn(want, so)
        self.assertNotIn("key navy", so)                                # top-level keys only
        rc, so, se = self.run_tool("brain_map.py", "query", "wave", "--root", proj)
        self.assertRegex(so, r"water\.frag:L4-L4  fn wave")
        rc, so, se = self.run_tool("brain_map.py", "slice", os.path.join(proj, "water.frag"), "--symbol", "wave")
        self.assertIn("return sin(p.x + uTime);", so)                    # a one-line definition is shown with its body

    def test_m2_incremental_and_private_shelf(self):
        proj = self.project()
        first = json.loads(self.run_tool("brain_map.py", "build", "--root", proj)[1])
        self.assertEqual((first["files"], first["parsed_now"]), (5, 5))
        again = json.loads(self.run_tool("brain_map.py", "build", "--root", proj)[1])
        self.assertEqual(again["parsed_now"], 0)                      # nothing changed: nothing is read again
        write(proj, "src/fx/bloom.js", "export class Bloom {\n  render() {\n    return 2;\n  }\n  resize() {}\n}\n")
        third = json.loads(self.run_tool("brain_map.py", "build", "--root", proj)[1])
        self.assertEqual(third["parsed_now"], 1)
        write(self.vault, "self/diary.md", "# Diary\nprivate\n")
        rc, so, se = self.run_tool("brain_map.py", "outline", os.path.join(self.vault, "self", "diary.md"))
        self.assertNotEqual(rc, 0)
        self.assertNotIn("private", so)
        rc, so, se = self.run_tool("brain_map.py", "query", "diary private", "--root", self.vault)
        self.assertNotIn("diary", so.split("\n", 1)[-1])              # walking the vault skips self/
        stats = json.loads(self.run_tool("brain_map.py", "stats", "--root", proj)[1])
        self.assertGreater(stats["tree_tokens"], 0)

    def test_m3_fetch_outline_and_section(self):
        sid = self.new()
        write(self.vault, "system/long-note.md", "---\ntitle: Long note\n---\n# Long note\nintro\n## Export rules\nalways glb\nwith draco\n## Lighting rules\nwarm\n")
        rc, so, se = self.run_tool("brain_fetch.py", "--session", sid, "Brain System/system/long-note.md", "--outline")
        self.assertEqual(rc, 0, se)
        self.assertRegex(so, r"L6-L8  Export rules")
        self.assertNotIn("always glb", so)
        rc, so, se = self.run_tool("brain_fetch.py", "--session", sid, "Brain System/system/long-note.md", "--section", "export")
        self.assertIn("always glb", so)
        self.assertNotIn("warm", so)
        rc, so, se = self.run_tool("brain_fetch.py", "--session", sid, "Brain System/system/long-note.md", "--section", "nope")
        self.assertEqual(rc, 4)


# ---------------------------------------------------------------- H: hooks
class QuietHooks(Base):
    def index(self):
        write(self.vault, "system/shader-card.md", "---\ntitle: Shader uniforms card\ntype: system\nsummary: glsl vertex shader uniforms for threejs water surface\n---\n# Shader uniforms card\nglsl vertex shader uniforms threejs water.\n")
        self.assertEqual(self.run_tool("brain_index.py")[0], 0)

    def test_h1_said_once_per_conversation(self):
        self.index()
        ask = {"session_id": "conv-A", "cwd": self.root, "prompt": "write a custom glsl vertex shader for the threejs water surface"}
        first = self.hook("prompt", ask)["additionalContext"]
        self.assertIn("no brain session is open", first)
        self.assertIn("threejs-shaders", first)
        self.assertEqual(self.hook("prompt", ask), {})                                   # same message again: nothing new to say
        other = self.hook("prompt", dict(ask, session_id="conv-B"))["additionalContext"]
        self.assertIn("threejs-shaders", other)                                          # another conversation is told
        loud = self.hook("prompt", ask, env=dict(self.env, BRAIN_HOOK_VERBOSE="1"))["additionalContext"]
        self.assertIn("threejs-shaders", loud)                                           # the old behaviour is one switch away

    def test_h5_skill_paths_under_the_brain_are_shortened_once(self):
        lib = os.path.join(self.root, "skills")
        write(lib, "threejs-shaders/SKILL.md", "---\nname: threejs-shaders\ndescription: Custom Three.js GLSL vertex and fragment shaders and postprocessing\n---\nShader guide\n")
        roots = write(self.tmp.name, "roots-in-brain.json", json.dumps([{"path": lib, "agent": "Claude, Codex", "kind": "brain-library", "autoload": "no"}]))
        env = dict(self.env, BRAIN_SKILL_ROOTS=roots)
        self.assertEqual(self.run_tool("brain_index.py", env=env)[0], 0)
        ctx = self.hook("prompt", {"session_id": "conv-S", "cwd": self.root, "prompt": "write a custom glsl vertex shader for the threejs water surface"}, env=env)["additionalContext"]
        self.assertEqual(ctx.count("($BRAIN = "), 1)                                      # the root is named once ...
        self.assertIn("· $BRAIN/skills/threejs-shaders/SKILL.md", ctx)                   # ... and each skill line uses the short form
        self.assertEqual(ctx.count(self.root.replace(os.path.expanduser("~"), "~") + "/skills/"), 0)

    def test_h6_a_short_nudge_every_fifteenth_message(self):
        csid = "conv-N"
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "t", "--lane", "fast", "--request", "tidy", "--check", "true")
        sid = json.loads(so)["session"]
        self.hook("post", {"session_id": csid, "tool_name": "Bash", "tool_input": {"command": "python3 -I brain_session.py new --agent claude"}, "tool_response": {"stdout": so, "stderr": ""}})
        said = [self.hook("prompt", {"session_id": csid, "cwd": self.root, "prompt": f"carry on with step {i}"}).get("additionalContext", "") for i in range(1, 31)]
        self.assertIn(f"brain session {sid} is open", said[0])                            # message 1: the full line, once
        self.assertEqual([i + 1 for i, s in enumerate(said) if s], [1, 15, 30])           # then silence, except a nudge on 15 and 30
        self.assertEqual(said[14], f"Agent Brain: session {sid} still open — checkpoint, judge, close.")
        self.assertLess(len(said[14]), len(said[0]) / 2)

    def test_h2_machine_messages_and_small_talk_get_nothing(self):
        self.index()
        self.hook("prompt", {"session_id": "conv-C", "cwd": self.root, "prompt": "hello"})
        for text in ("<task-notification><status>completed</status> glsl vertex shader threejs</task-notification>",
                     "[SYSTEM NOTIFICATION - NOT USER INPUT] background glsl vertex shader threejs job finished", "ok do it", "undo that"):
            self.assertEqual(self.hook("prompt", {"session_id": "conv-C", "cwd": self.root, "prompt": text}), {}, text)

    def test_h3_flow_line_returns_when_the_state_changes(self):
        csid = "conv-D"
        self.assertIn("no brain session is open", self.hook("prompt", {"session_id": csid, "cwd": self.root, "prompt": "plan the turbine work"})["additionalContext"])
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "t", "--lane", "fast", "--request", "tidy", "--check", "true")
        sid = json.loads(so)["session"]
        self.hook("post", {"session_id": csid, "tool_name": "Bash", "tool_input": {"command": "python3 -I brain.py new --agent claude"}, "tool_response": {"stdout": so, "stderr": ""}})
        now = self.hook("prompt", {"session_id": csid, "cwd": self.root, "prompt": "go on with the turbine work"})["additionalContext"]
        self.assertIn(f"brain session {sid} is open", now)
        self.assertEqual(self.hook("prompt", {"session_id": csid, "cwd": self.root, "prompt": "go on with the turbine work"}), {})

    def test_h4_linker_ignores_words_and_past_ids(self):
        rc, so, se = self.run_tool("brain_session.py", "new", "--agent", "claude", "--cwd", self.root, "--title", "mine", "--lane", "fast", "--request", "tidy", "--check", "true")
        mine = json.loads(so)["session"]
        self.hook("post", {"session_id": "conv-E", "tool_name": "Bash", "tool_input": {"command": "python3 -I brain_session.py new --agent claude"}, "tool_response": {"stdout": so, "stderr": ""}})
        links = lambda: json.load(open(os.path.join(self.root, "state", "live-links.json")))
        self.assertEqual(links()["conv-E"], mine)
        old = "20250101-000000-claude-abcd"
        write(self.root, f"sessions/{old}/meta.json", json.dumps({"id": old, "status": "closed"}))
        os.utime(os.path.join(self.root, "sessions", old, "meta.json"), (1, 1))
        # a script that only CONTAINS the words, printing a past session's id (this locked a real session on 2026-11-13)
        self.hook("post", {"session_id": "conv-E", "tool_name": "Bash",
                           "tool_input": {"command": "python3 - <<'EOF'\nprint('run brain_session.py new first')\nEOF"},
                           "tool_response": {"stdout": f"capsule of {old}", "stderr": ""}})
        self.assertEqual(links()["conv-E"], mine)
        # a real `new` whose output shows an OLD id (piped through something) does not link to it either
        self.hook("post", {"session_id": "conv-E", "tool_name": "Bash", "tool_input": {"command": "python3 -I brain_session.py new --agent claude | tail -1"},
                           "tool_response": {"stdout": old, "stderr": ""}})
        self.assertEqual(links()["conv-E"], mine)


# ---------------------------------------------------------------- R: router
class Router(unittest.TestCase):
    ROWS = [("blender-addon-development", "Build Blender add-ons with operators, panels and undo support", "/s/a/SKILL.md", "Claude, Codex", "brain-library", "no"),
            ("blender-character-rigging", "Armatures, weight painting and rigging for characters and mascots", "/s/b/SKILL.md", "Claude, Codex", "brain-library", "no"),
            ("code-review", "Review a diff for bugs and risky changes before merging", "/s/c/SKILL.md", "Claude, Codex", "brain-library", "no"),
            ("design-token", "Design tokens for colour, spacing and type in a design system", "/s/d/SKILL.md", "Claude, Codex", "brain-library", "no"),
            ("brand-naming", "Naming a brand, product or company: methods and checks", "/s/e/SKILL.md", "Claude, Codex", "brain-library", "no"),
            ("seo-audit", "Audit a site for SEO problems: crawl, meta, speed", "/s/f/SKILL.md", "Claude, Codex", "brain-library", "no")]

    def names(self, prompt):
        return [s["short"] for s in HS.rank_skills(prompt, self.ROWS, who="Claude")]

    def test_r1_talk_is_not_a_task(self):
        for talk in ("undo that", "show me the diff", "no, the other one", "is it done?", "ok do it"):
            self.assertEqual(self.names(talk), [], talk)

    def test_r2_short_tasks_still_find_their_skill(self):
        self.assertIn("seo-audit", self.names("audit my site for SEO problems"))
        self.assertIn("seo-audit", self.names("seo audit"))                              # two words, both in the name
        self.assertIn("blender-character-rigging", self.names("character rigging for the mascot so its arms can bend"))
        self.assertIn("brand-naming", self.names("pick a name for the brand of my company"))

    def test_r3_inflections_are_whole_words(self):
        self.assertTrue(HS.token_match("shader", {"shaders"}))
        self.assertTrue(HS.token_match("shaders", {"shader"}))
        self.assertTrue(HS.token_match("box", {"boxes"}))
        self.assertFalse(HS.token_match("close", {"closed"}))                            # the v4 collision stays closed
        self.assertFalse(HS.token_match("str", {"string"}))
        self.assertFalse(HS.token_match("rig", {"rigging"}))                             # the -ing rule was withdrawn (route_real.py: unverifiable churn)
        self.assertEqual(HS.variants("rig"), ["rigs", "riges"])

    def test_r4_holdout_sets_are_kept_apart(self):
        # the v6 holdout sets ship as evidence (they were written for the maintainers' skill library); none of their
        # prompts may be copied into the router or the hook
        code = (read(os.path.join(TOOLS, "hydro_skills.py")) + read(os.path.join(TOOLS, "brain_hooks.py"))).lower()
        hd = os.path.join(REAL, "versions", "v6-clearwater", "evidence", "holdouts")
        for name, n_pos in (("prompt-skills-holdout.json", 40), ("prompt-skills-holdout-2.json", 20)):
            hold = json.load(open(os.path.join(hd, name), encoding="utf-8"))
            self.assertGreaterEqual(len(hold["positive"]), n_pos)
            self.assertGreaterEqual(len(hold["negative"]), 20)
            copied = [p for p in hold["negative"] + [c["prompt"] for c in hold["positive"]]
                      if len(p.split()) >= 2 and p.lower().rstrip("?!.") in code]
            self.assertEqual(copied, [], name)

    def test_r5_holdout_report_runs_and_never_gates(self):
        with tempfile.TemporaryDirectory() as t:
            root = os.path.join(t, "brain")
            write(root, "Brain System/system/card.md", "---\ntitle: Card\ntype: system\n---\n# Card\nx\n")
            skills = os.path.join(t, "skills")
            write(skills, "invoice-checker/SKILL.md", "---\nname: invoice-checker\ndescription: Check invoices, VAT and ledger totals in spreadsheets\n---\nx\n")
            roots = write(t, "roots.json", json.dumps([{"path": skills, "agent": "Claude, Codex", "kind": "brain-library", "autoload": "no"}]))
            write(root, "state/eval/prompt-skills-holdout-mine.json", json.dumps({"positive": [{"prompt": "check the VAT totals on these invoices", "accept": ["invoice"]}],
                                                                                    "negative": ["thanks, that is all"]}))
            env = dict(os.environ, BRAIN_ROOT=root, BRAIN_SKILL_ROOTS=roots, BRAIN_NO_SLEEP="1")
            env.pop("BRAIN_VAULT", None); env.pop("BRAIN_INDEX_DB", None)
            p = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "route_eval.py"), "--holdout", "--json"], capture_output=True, text=True, env=env, cwd=root)
        self.assertEqual(p.returncode, 0, p.stderr[-300:])                               # exit 0 whatever the score: it reports, it does not gate
        sets = {r["set"]: r for r in json.loads(p.stdout)}
        self.assertEqual(sorted(sets), ["prompt-skills-holdout-mine"])                   # any state/eval/prompt-skills-holdout*.json you add
        r = sets["prompt-skills-holdout-mine"]
        self.assertEqual((r["gate"], r["found"] + len(r["misses"]), r["positives"]), ("none (reported only)", 1, 1))
        self.assertEqual(r["found"], 1)                                                  # an accountant's skill is found for an accountant's request


# ---------------------------------------------------------------- C: capsule
class RealTraffic(Base):
    def test_r6_router_on_marks_own_words_stores_no_message_text(self):
        write(self.vault, "system/card.md", "---\ntitle: Card\ntype: system\n---\n# Card\nx\n")
        self.assertEqual(self.run_tool("brain_index.py")[0], 0)
        def session(sid, scope, request, read=None, status="closed"):
            d = os.path.join(self.root, "sessions", sid)
            write(d, "meta.json", json.dumps({"id": sid, "status": status, "scope_class": scope}))
            write(d, "contract.md", f"---\nscope_class: {scope}\n---\n## Request (verbatim)\n{request}\n\n## Deliverables\n-\n")
            if read:
                write(d, "evidence.jsonl", json.dumps({"tool": "Read", "file": f"/x/skills/{read}/SKILL.md"}) + "\n")
        session("20261101-000001-claude-aaaa", "engineering", "write a custom glsl vertex shader for the threejs water surface", read="threejs-shaders")
        session("20261101-000002-claude-bbbb", "general", "tidy the notes folder and rename the files", read="some-other-skill")
        session("20261101-000003-claude-cccc", "personal", "PRIVATE-REQUEST glsl vertex shader threejs")
        session("20261101-000004-claude-dddd", "general", "OPEN-REQUEST glsl vertex shader threejs", status="open")
        tr = os.path.join(self.tmp.name, "tr")
        user = lambda text, **kw: json.dumps(dict({"type": "user", "message": {"content": text}}, **kw))
        write(tr, "-Users-me-game/a.jsonl", "\n".join([
            user("SECRET-SHORT-WORDS please"), user("glsl vertex shader threejs"), user("glsl vertex shader threejs"),
            user("this one is a much longer message that has more than four words in it"), user("<task-notification>x</task-notification>"),
            user("/model"), user("ok", isMeta=True),
            json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "content": "short result"}]}})]) + "\n")
        write(tr, "-private-tmp-brain-e2e/b.jsonl", user("harness glsl shader") + "\n")
        out_file = os.path.join(self.tmp.name, "real.json")
        rc, so, se = self.run_tool("route_real.py", "--transcripts", tr, "--out", out_file)
        self.assertEqual(rc, 0, se)
        res = json.load(open(out_file))
        s = res["summary"]
        self.assertEqual((s["requests"], s["sessions_with_a_real_skill_read"], s["read_skill_was_offered"]), (2, 2, 1))   # private and open sessions are skipped
        self.assertEqual((s["short_messages"], s["short_messages_that_get_a_skill_list"]), (2, 1))                       # deduplicated; machine, slash, meta, long, harness left out
        self.assertEqual(s["gate"], "none (reported only)")
        text = read(out_file) + so
        for secret in ("SECRET-SHORT-WORDS", "PRIVATE-REQUEST", "OPEN-REQUEST", "tidy the notes", "water surface"):
            self.assertNotIn(secret, text)                                                                                # ids, skill names, hashes, counts: never the words
        self.assertEqual(len(res["router_sha256"]), 64)


class Capsule(Base):
    def test_c1_checkpoint_refreshes_the_capsule_and_compaction_prints_it(self):
        sid = self.new(request="Build the turbine report with the airflow numbers")
        d = self.sdir(sid)
        self.hook("post", {"session_id": "conv-F", "tool_name": "Bash", "tool_input": {"command": "python3 -I brain_session.py new --agent claude"},
                           "tool_response": {"stdout": json.dumps({"session": sid}), "stderr": ""}})
        write(d, "evidence.jsonl", json.dumps({"t": "2026-11-13 10:00:00", "tool": "Edit", "file": os.path.join(self.root, "src", "solver.py")}) + "\n"
              + json.dumps({"t": "2026-11-13 10:01:00", "tool": "Bash", "command": "make sim", "stderr_tail": "Error: mesh diverged", "stdout_tail": ""}) + "\n")
        rc, so, se = self.run_tool("brain_session.py", "checkpoint", "--session", sid, "--note", "Mesh refined to 2 mm; solver converges in 400 steps")
        self.assertEqual(rc, 0, se)
        cap = read(os.path.join(d, "capsule.md"))
        for want in ("Goal: Build the turbine report", "R1 the report exists [open]", "Mesh refined to 2 mm", "src/solver.py×1", "Open error: `make sim` → Error: mesh diverged"):
            self.assertIn(want, cap)
        self.assertLess(len(cap), 2500)
        # after a compaction: the capsule, not the manual
        rc, so, se = self.run_tool("brain_start.py", "--agent", "claude", stdin=json.dumps({"session_id": "conv-F", "source": "compact", "cwd": self.root}))
        text = json.loads(so)["hookSpecificOutput"]["additionalContext"]
        self.assertIn(f"you are back in brain session {sid} (compact)", text)
        self.assertIn("Mesh refined to 2 mm", text)
        self.assertNotIn("FAST LANE", text)
        # an ordinary start still gets the card, inside its cap, with the one entry point
        rc, so, se = self.run_tool("brain_start.py", "--agent", "codex", stdin=json.dumps({"session_id": "conv-G", "source": "startup", "cwd": self.root}))
        card = json.loads(so)["hookSpecificOutput"]["additionalContext"]
        for want in ("readiness card", 'v3 "Fable Art"', "FAST LANE", "BRAIN = python3 -I", "map query", "preflight", "--agent codex"):
            self.assertIn(want, card)
        self.assertLess(len(card), 4057)

    def test_c2_the_judge_never_sees_the_capsule(self):
        sid = self.new()
        self.run_tool("brain_session.py", "checkpoint", "--session", sid, "--note", "SECRET-MAKER-REASONING")
        art = write(self.root, "out/report.md", "# Report\n")
        rc, so, se = self.run_tool("brain_judge.py", "--session", sid, "--artifacts", art, "--dry-run")
        self.assertNotIn("SECRET-MAKER-REASONING", so)


# ---------------------------------------------------------------- L: memory layers
class Memory(Base):
    def test_l1_queue_takes_proposed_lessons_only_and_at_most_three(self):
        sid = self.new(extra=("--project", "nova"))
        d = self.sdir(sid)
        write(d, "retrieval-log.jsonl", json.dumps({"mark": "missing", "what": "foil dieline template"}) + "\n")
        write(d, "task-summary.md", "# Task summary\n| Delivered | spec |\n| Verified (requirement → tier → evidence) | R1 → Tier 0 |\n\n## Gotchas\n- Kraft stock darkens red ink unless a white underbase is specified.\n")
        write(d, "brain-summary.md", "# Brain Summary\n| Field | Content |\n|---|---|\n| Proposed lesson | Always specify a white underbase under dark red on kraft. |\n\n## Lessons (candidate)\n"
              + "".join(f"- Candidate lesson number {i} about press proofs and separations.\n" for i in range(1, 7)))
        rc, so, se = self.run_tool("brain_learn.py", "--session", sid, "--no-index")
        res = json.loads(so)
        self.assertEqual(res["status"], "learned", se)
        queued = sorted(os.listdir(os.path.join(self.root, "queue")))
        self.assertEqual(len(queued), 3, queued)                                          # before v6: one file per bullet (8 for a real session)
        texts = "".join(read(os.path.join(self.root, "queue", f)) for f in queued)
        self.assertIn("white underbase under dark red", texts)                            # the proposed lesson comes first
        self.assertNotIn("Retrieval gap", texts)                                          # a gap is a gap report, not a lesson
        self.assertNotIn("Kraft stock darkens", texts)                                    # a gotcha stays in the ledger ...
        self.assertIn("Kraft stock darkens", read(os.path.join(self.vault, "history", "learnings", "nova.md")))
        self.assertGreaterEqual(res["insights_count"], 8)

    def test_l8_an_ordinary_word_is_not_a_used_skill(self):
        sid = self.new()
        d = self.sdir(sid)
        write(d, "retrieval-01.md", "# Route\n\n## Skills\n- **ship** (x) — ship a release\n- **start** (x) — start things\n- **brand-packaging** (x) — packaging\n- **figma** (x) — figma\n- **commit** (x) — commits\n")
        write(d, "task-summary.md", "# T\n| Delivered | We ship it on Friday and start the next round; the commit is in git. Followed brand-packaging for the pouch. |\n| Verified (requirement → tier → evidence) | R1 |\n")
        write(d, "brain-summary.md", "# B\n| Field | Content |\n|---|---|\n| Reused (notes, cards, skills) | the `figma` skill for the frames |\n| Proposed lesson | none |\n")
        res = json.loads(self.run_tool("brain_learn.py", "--session", sid, "--no-index")[1])
        self.assertEqual(res["skills_shown"], ["ship", "start", "brand-packaging", "figma", "commit"])
        self.assertEqual(sorted(res["skills_used"]), ["brand-packaging", "figma"])        # before v6: all five were "used"

    def test_l2_reflections_are_whole_sentences(self):
        long = ("We looked at many things first and none of them mattered for the result at all in the end. "
                "The root cause is that the index is rebuilt while the hook still reads it. I will add a lock next.")
        got = brain_dream._signal_sentences(long)
        self.assertTrue(got.startswith("The root cause is"))
        self.assertTrue(got.endswith("I will add a lock next."))
        self.assertEqual(brain_dream._signal_sentences("nothing notable here at all"), "")
        self.assertEqual(brain_dream._signal_sentences("root cause " + "x" * 400), "")     # no clean sentence: nothing, not a cut

    def test_l6_one_failed_command_is_not_a_lesson_a_recurring_one_is(self):
        tr = os.path.join(self.tmp.name, "transcripts")
        err = lambda text: json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": text}]}})
        think = json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking":
                 "We tried three things before lunch. The root cause is a stale lock file left by the indexer. " + "Then a very long tail follows. " * 20}]}})
        write(tr, "a.jsonl", "\n".join([err("Error: shader compile failed in water.frag line 12"), err("Error: only-once failure in solver step 9"), think]) + "\n")
        write(tr, "b.jsonl", err("Error: shader compile failed in water.frag line 40") + "\n")
        write(self.root, "state/analysis/hook-errors.log", "".join(f"2026-11-1{i} 01:08:34 ['pre'] error: bad character range z-a at position 6\n" for i in range(6)))
        rc, so, se = self.run_tool("brain_dream.py", "--once", "--transcript-roots", tr)
        self.assertEqual(rc, 0, se)
        refl = read(os.path.join(self.vault, "history", "learnings", "dream-reflections.md"))
        self.assertIn("type: log", refl)
        self.assertIn("(2x) Error: shader compile failed", refl)                           # the same signature twice: recorded with its count
        self.assertNotIn("only-once failure", refl)                                        # one failed command: an event, not a lesson
        self.assertIn("The root cause is a stale lock file left by the indexer.", refl)    # the whole sentence ...
        self.assertNotIn("Then a very long tail follows. Then a very long tail follows. Then", refl)   # ... not a 220-character cut
        self.assertEqual(refl.count("bad character range z-a"), 1)                         # six log lines, one reflection
        self.assertIn("hook error (6x in the log)", refl)

    def test_l7_digest_cost_line_reads_the_analysis_and_the_map_log(self):
        import time as _t
        now = _t.strftime("%Y-%m-%d %H:%M:%S")
        write(self.root, f"state/analysis/{_t.strftime('%Y-%m')}.jsonl", "".join(
            json.dumps({"ended": now, "brain_session": f"s{i}", "tokens": {"total": t}}) + "\n" for i, t in enumerate((1000, 5000, 90000))))
        write(self.root, "state/map-savings.jsonl", json.dumps({"t": now, "root": "/x", "cmd": "query", "answer_tokens": 200, "whole_file_tokens": 30000}) + "\n")
        out = self.py("import brain_sleep as S\nprint(S.token_week())")
        self.assertIn("3 analysed session(s) in 7 days, median 5,000 tokens, heaviest 90,000 (s2)", out)
        self.assertIn("project map: 1 call(s) answered in 200 tokens where the whole files hold 30,000", out)

    def test_l3_bridges_need_a_shared_title_or_tag_word(self):
        talk = "quarterly whisky tasting entirely delightful"
        mech = "escapement pinion ratio arbor wheelwork"
        write(self.vault, "concepts/gear-clock.md", f"---\ntitle: Gear clock\ntype: domain\ntags: [horology]\n---\n# Gear clock\n{mech} {talk}\n")
        write(self.vault, "concepts/cassette-player.md", f"---\ntitle: Cassette player\ntype: domain\ntags: [audio]\n---\n# Cassette player\n{talk} capstan\n")
        write(self.vault, "concepts/gear-train.md", f"---\ntitle: Gear train\ntype: domain\ntags: [horology]\n---\n# Gear train\n{mech} mainspring\n")
        for i, words in enumerate(("saffron pouch dieline varnish", "turbine airflow mesh solver", "padel court booking invoice",
                                   "typeface kerning ligature baseline", "invoice ledger vat receipt", "tram ticket platform timetable")):
            write(self.vault, f"concepts/filler-{i}.md", f"---\ntitle: Filler {i} {words.split()[0]}\ntype: domain\n---\n# Filler {i}\n{words} unrelated material here\n")
        out = json.loads(self.py("import json, brain_dream as D\nr = D._stage_weave_graph(20, False, False)\nprint(json.dumps(r))"))
        self.assertGreaterEqual(out["bridges_found"], 1)
        m = read(os.path.join(self.vault, "history", "learnings", "dream-map.md"))
        self.assertIn("type: log", m)
        self.assertNotIn("cassette-player", m)                                            # five shared body words, no shared topic: no bridge
        self.assertIn("[[concepts/gear-clock|Gear clock]] -> [[concepts/gear-train|Gear train]]", m)

    def test_l4_idle_agent_never_weaves_and_logs_are_not_answers(self):
        self.assertNotIn("--apply-links", brain_dream.launchd_plist_dict()["ProgramArguments"])
        write(self.vault, "history/dream-notes.md", "---\ntitle: Dream notes zymurgy\ntype: log\nsummary: zymurgy kraft ink journal\n---\n# Dream notes\nzymurgy kraft ink\n")
        write(self.vault, "system/ink-card.md", "---\ntitle: Ink card zymurgy\ntype: system\nsummary: zymurgy kraft ink rules\n---\n# Ink card\nzymurgy kraft ink\n")
        self.assertEqual(self.run_tool("brain_index.py")[0], 0)
        rc, so, se = self.run_tool("brain_route.py", "--query", "zymurgy kraft ink", "--scope", "system", "--json")
        paths = [n["path"] for n in json.loads(so)["notes"]]
        self.assertTrue(any("ink-card" in p for p in paths), paths)
        self.assertFalse(any("dream-notes" in p for p in paths), paths)

    def test_l5_digest_shows_the_strongest_lessons_and_counts_the_rest(self):
        for i in range(11):
            body = "- lesson: keep the mesh under 2 mm\n- cue: turbine\n- evidence: sessions/x/\n" if i == 10 else f"Plain candidate {i}.\n"
            write(self.vault, f"lessons/cand-{i:02d}.md", f"---\ntitle: \"cand {i}\"\ntype: lesson\nstatus: candidate\n---\n# cand {i}\n{body}")
        rc, so, se = self.run_tool("brain_sleep.py", "--dry-run", "--no-gym")
        self.assertEqual(rc, 0, se)
        dg = read(os.path.join(self.root, json.loads(so)["digest"]))
        boxes = [l for l in dg.splitlines() if "— lesson `" in l]
        self.assertEqual(len(boxes), 8)
        self.assertIn("cand-10.md", boxes[0])                                             # the structured lesson leads
        self.assertIn("3 more candidate lesson(s) wait behind the 8 shown", dg)
        self.assertIn("- cost:", dg)


# ---------------------------------------------------------------- E: one entry point
class EntryPoint(Base):
    def test_e1_brain_py_forwards_arguments_and_exit_codes(self):
        rc, so, se = self.run_tool("brain.py", "new", "--agent", "codex", "--cwd", self.root, "--title", "via entry")
        self.assertEqual(rc, 0, se)
        sid = json.loads(so)["session"]
        self.assertIn("-codex-", sid)
        rc, so, se = self.run_tool("brain.py", "lint", "--session", sid)
        self.assertEqual(rc, 1)                                                           # the unfilled template fails lint, through the wrapper too
        self.assertFalse(json.loads(so)["ok"])
        rc, so, se = self.run_tool("brain.py", "preflight", "--session", sid)
        self.assertEqual(rc, 1)
        self.assertIn("tier0_failed", so)
        rc, so, se = self.run_tool("brain.py", "nonsense")
        self.assertEqual(rc, 2)
        rc, so, se = self.run_tool("brain.py", "help")
        self.assertIn("one short entry point", so)


if __name__ == "__main__":
    unittest.main()
