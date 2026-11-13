"""Tests for the Agent Brain v2 tools. Run: bash tools/test_all.sh (stdlib unittest, synthetic fixtures)."""
import csv, hashlib, json, os, subprocess, sys, tempfile, unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(script, *args):
    p = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, script), *args], capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def write(root, rel, text, crlf=False):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\n", "\r\n") if crlf else text)
    return p


def tree_hash(root):
    h = hashlib.sha256()
    for d, dirs, fs in os.walk(root):
        dirs.sort()
        for f in sorted(fs):
            p = os.path.join(d, f)
            h.update(os.path.relpath(p, root).encode())
            if os.path.islink(p):
                h.update(os.readlink(p).encode())
            else:
                with open(p, "rb") as fh:
                    h.update(fh.read())
    return h.hexdigest()


def jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f]


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = os.path.join(self.tmp.name, "vault")
        self.out = os.path.join(self.tmp.name, "out")
        v = self.v
        write(v, "Note.md", "---\ntitle: Note\n---\n# Note\nbody text here\n")
        write(v, "Folder/My Note.md", "# My Note\n## Heading\nline ^blk1\n")
        write(v, "Folder/sub.md", "sub\n")
        write(v, "image.png", "png")
        write(v, "Dup/Dup.md", "one\n"); write(v, "Dup2/Dup.md", "two\n")
        write(v, "Aliased.md", "---\naliases: [Alias Name]\n---\nx\n")
        write(v, "σημείωση.md", "# σημείωση\nκείμενο\n", crlf=True)
        write(v, "Untitled.md", ""); write(v, "123.md", "same body twice here"); write(v, "ab.md", "same body twice here")
        write(v, ".obsidian/app.json", "{}"); write(v, ".trash/old.md", "[[Missing2]]")
        os.symlink(os.path.join(v, "Note.md"), os.path.join(v, "link.md"))
        os.symlink(os.path.join(v, "Folder"), os.path.join(v, "linkdir"))
        abs_inside = os.path.join(os.path.realpath(v), "Note.md")
        write(v, "a.md", "\n".join([
            "# Local", "[[Note|alias]] [[Folder/My Note#Heading]] [[#Local]] ![[image.png]]",
            "[x](Folder/My%20Note.md) [y](<Folder/My Note.md>) [[Folder/My Note#^blk1]]",
            "[[Folder]] [[Missing]] [z](Gone.md) [[Wrong/Note]] [[Note#No Such Heading]]",
            "[[Dup]] [[Alias Name]] [[σημείωση]]", f"[abs](<{abs_inside}>) [out](</etc/hosts>)",
            "```", "[[InFence]]", "```", "`[[InInline]]`", ""]))
        self.before = tree_hash(v)

    def tearDown(self):
        self.tmp.cleanup()

    def scan(self):
        rc, so, se = run("vault_scan.py", "--vault", self.v, "--out", self.out)
        self.assertEqual(rc, 0, se)
        return {(l["source"], l["target"]): l for l in jsonl(os.path.join(self.out, "links.jsonl"))}

    def test_resolution_and_v2_fixes(self):
        L = self.scan()
        st = lambda t: L[("a.md", t)]["status"]
        for t in ["Note", "Folder/My Note#Heading", "image.png", "Folder/My%20Note.md", "Folder/My Note.md",
                  "Folder/My Note#^blk1", "σημείωση"]:
            self.assertEqual(st(t), "resolved", t)
        self.assertEqual(st("#Local"), "self")
        self.assertEqual(st("Folder"), "unresolved")
        self.assertEqual(st("Missing"), "unresolved")
        self.assertEqual(st("Gone.md"), "unresolved")                       # fix 60: md link checked
        self.assertEqual(st("Wrong/Note"), "unresolved")                    # fix 58: no silent fallback
        self.assertIn("Note.md", L[("a.md", "Wrong/Note")]["suggest"])
        self.assertEqual(st("Note#No Such Heading"), "bad_fragment")        # fix 59
        self.assertEqual(st("Dup"), "ambiguous")
        self.assertEqual(st("Alias Name"), "alias_only")
        self.assertEqual(L[("a.md", os.path.join(os.path.realpath(self.v), "Note.md"))]["status"], "resolved")
        self.assertEqual(st("/etc/hosts"), "outside_vault")
        self.assertNotIn(("a.md", "InFence"), L)
        self.assertNotIn(("a.md", "InInline"), L)
        with open(os.path.join(self.out, "ghosts.csv"), encoding="utf-8") as f:
            ghosts = {r["target"]: r for r in csv.DictReader(f)}
        self.assertIn("Gone.md", ghosts)                                    # fix 60: counted as ghost
        self.assertIn("mdlink:1", ghosts["Gone.md"]["kinds"])
        self.assertNotIn("Missing2", ghosts)                                # .trash skipped
        self.assertEqual(self.before, tree_hash(self.v))                    # read-only proof

    def test_flags_symlinks_duplicates(self):
        self.scan()
        notes = {n["path"]: n for n in jsonl(os.path.join(self.out, "notes.jsonl"))}
        self.assertIn("empty", notes["Untitled.md"]["flags"])
        self.assertIn("untitled_or_generic", notes["Untitled.md"]["flags"])
        self.assertIn("numeric_title", notes["123.md"]["flags"])
        self.assertIn("very_short_title", notes["ab.md"]["flags"])
        self.assertNotIn("link.md", notes)
        with open(os.path.join(self.out, "report.md"), encoding="utf-8") as f:
            rep = f.read()
        self.assertIn("| Symlinks skipped | 2 |", rep)
        self.assertIn("Exact duplicate contents | 1 groups", rep)

    def test_unreadable_note_does_not_crash(self):                         # fix 57
        p = write(self.v, "locked.md", "secret")
        os.chmod(p, 0)
        try:
            if os.access(p, os.R_OK):
                self.skipTest("running with privileges that ignore file modes")
            self.scan()
            notes = {n["path"]: n for n in jsonl(os.path.join(self.out, "notes.jsonl"))}
            self.assertIn("unreadable", notes["locked.md"]["flags"])
        finally:
            os.chmod(p, 0o644)

    def test_refuses_out_inside_vault(self):
        rc, _, _ = run("vault_scan.py", "--vault", self.v, "--out", os.path.join(self.v, "scan"))
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.before, tree_hash(self.v))


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.src, self.dst = os.path.join(t, "src"), os.path.join(t, "raw", "vault")
        write(self.src, "a.md", "A"); write(self.src, "d/b.md", "B"); write(self.src, ".obsidian/x.json", "{}")
        os.symlink(os.path.join(self.src, "a.md"), os.path.join(self.src, "ln.md"))
        self.m1 = os.path.join(t, "raw", "manifests", "m1.json")
        self.src_hash = tree_hash(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def test_copy_rerun_conflict_verify(self):
        rc, so, se = run("snapshot.py", "copy", "--src", self.src, "--dest", self.dst, "--manifest", self.m1)
        self.assertEqual(rc, 0, se)
        tot = json.loads(so)
        self.assertEqual((tot["copied"], tot["symlinks"]), (2, 1))
        self.assertFalse(os.path.exists(os.path.join(self.dst, ".obsidian")))
        self.assertFalse(os.path.lexists(os.path.join(self.dst, "ln.md")))
        rc, so, _ = run("snapshot.py", "copy", "--src", self.src, "--dest", self.dst, "--manifest", self.m1)
        self.assertNotEqual(rc, 0)                                          # manifest never overwritten
        m2 = self.m1.replace("m1", "m2")
        rc, so, _ = run("snapshot.py", "copy", "--src", self.src, "--dest", self.dst, "--manifest", m2)
        self.assertEqual((rc, json.loads(so)["already_identical"], json.loads(so)["copied"]), (0, 2, 0))
        write(self.src, "a.md", "A changed")
        rc, so, _ = run("snapshot.py", "copy", "--src", self.src, "--dest", self.dst, "--manifest", self.m1.replace("m1", "m3"))
        self.assertEqual(rc, 2)                                             # conflict reported
        with open(os.path.join(self.dst, "a.md")) as f:
            self.assertEqual(f.read(), "A")                                 # and never overwritten
        rc, _, _ = run("snapshot.py", "verify", "--manifest", self.m1)
        self.assertEqual(rc, 0)
        write(self.dst, "d/b.md", "tampered")
        rc, so, _ = run("snapshot.py", "verify", "--manifest", self.m1)
        self.assertEqual((rc, json.loads(so)["problems"]), (2, 1))


NOTE = """---
title: Big
---
# Title
Intro line one
intro line two (lazy continuation)

- item one
  continued item one
- item two
  - nested item
1. numbered
- [ ] task item

| a | b |
|---|---|
| 1 | 2 |

> [!note] Callout
> second callout line

```python
# not a heading
- not a list
```

Setext Title
============
***
Final paragraph με ελληνικό κείμενο
"""


class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = os.path.join(self.tmp.name, "v")
        write(self.v, "big.md", NOTE)
        write(self.v, "crlf.md", "# H\r\n\r\n- x shared bullet text here\r\n")
        write(self.v, "other.md", "- x shared bullet text here\n")
        self.before = tree_hash(self.v)

    def tearDown(self):
        self.tmp.cleanup()

    def seg(self, out="o"):
        o = os.path.join(self.tmp.name, out)
        rc, so, se = run("segment.py", "--vault", self.v, "--out", o)
        self.assertEqual(rc, 0, se + so)
        return o, [b for b in jsonl(os.path.join(o, "blocks.jsonl"))]

    def test_every_line_covered_and_kinds(self):
        o, blocks = self.seg()
        notes = {n["path"]: n for n in jsonl(os.path.join(o, "segment_notes.jsonl"))}
        self.assertTrue(all(n["coverage_ok"] for n in notes.values()))
        big = [b for b in blocks if b["path"] == "big.md"]
        kinds = [b["kind"] for b in big]
        self.assertEqual(kinds, ["frontmatter", "heading", "paragraph", "list_item", "list_item", "list_item",
                                 "list_item", "list_item", "table", "quote", "code", "heading", "rule", "paragraph"])
        first_item = big[3]
        self.assertEqual((first_item["line_start"], first_item["line_end"]), (8, 9))   # continuation attached
        self.assertEqual(big[2]["heading_path"], ["Title"])
        self.assertEqual(self.before, tree_hash(self.v))

    def test_ids_stable_and_duplicates(self):
        _, b1 = self.seg("o1")
        with open(os.path.join(self.v, "big.md"), encoding="utf-8") as f:
            txt = f.read()
        write(self.v, "big.md", txt.replace("# Title\n", "# Title\nA new unrelated line.\n\n"))
        _, b2 = self.seg("o2")
        ids1 = {b["block_id"] for b in b1 if b["path"] == "big.md"}
        ids2 = {b["block_id"] for b in b2 if b["path"] == "big.md"}
        self.assertEqual(len(ids2 - ids1), 1)                               # only the new block is new
        with open(os.path.join(self.tmp.name, "o1", "duplicates.csv"), encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertTrue(any("crlf.md" in r["locations"] and "other.md" in r["locations"] for r in rows))


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.blocks = os.path.join(t, "blocks.jsonl")
        with open(self.blocks, "w") as f:
            for i, (s, e) in enumerate([(1, 2), (3, 3), (4, 6)]):
                f.write(json.dumps({"block_id": f"b{i}", "path": "n.md", "line_start": s, "line_end": e}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, rows):
        p = os.path.join(self.tmp.name, "plan.csv")
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["block_id", "action", "target", "reason"])
            w.writerows(rows)
        return run("coverage_check.py", "--blocks", self.blocks, "--plan", p)

    def test_cases(self):
        good = [["b0", "place", "projects/x.md", ""], ["b1", "duplicate_of", "b0", ""], ["b2", "raw_only", "", "obsolete"]]
        rc, so, _ = self.check(good)
        self.assertEqual((rc, json.loads(so.splitlines()[0])["accounted_pct"]), (0, 100.0))
        self.assertEqual(self.check(good[:2])[0], 1)                                        # missing block
        self.assertEqual(self.check(good + [good[0]])[0], 1)                                # listed twice
        self.assertEqual(self.check(good + [["zz", "place", "a.md", ""]])[0], 1)            # unknown id
        self.assertEqual(self.check([good[0], good[1], ["b2", "raw_only", "", ""]])[0], 1)  # no reason
        self.assertEqual(self.check([["b0", "raw_only", "", "x"], ["b1", "duplicate_of", "b0", ""], good[2]])[0], 1)
        self.assertEqual(self.check([good[0], ["b1", "place", "other/x.md", ""], good[2]])[0], 1)  # ambiguous name
        self.assertEqual(self.check([["b0", "place", "../x.md", ""], good[1], good[2]])[0], 1)     # escapes vault


class TokenMeterTests(unittest.TestCase):
    def test_claude_dedupe_and_codex_last_total(self):
        with tempfile.TemporaryDirectory() as t:
            c = os.path.join(t, "s.jsonl")
            u = {"input_tokens": 10, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 50, "output_tokens": 5}
            with open(c, "w") as f:
                for _ in range(3):  # same message on three lines -> counted once
                    f.write(json.dumps({"message": {"id": "m1", "usage": u}}) + "\n")
                f.write(json.dumps({"isSidechain": True, "message": {"id": "m2", "usage": u}}) + "\n")
            rc, so, _ = run("token_meter.py", "claude", c)
            s = json.loads(so.splitlines()[0])
            self.assertEqual((s["turns"], s["context_in"], s["boot_context"], s["sidechain_turns"]), (2, 320, 160, 1))
            x = os.path.join(t, "rollout.jsonl")
            with open(x, "w") as f:
                for n in (100, 250):
                    f.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {
                        "input_tokens": n, "cached_input_tokens": 1, "cache_write_input_tokens": 0, "output_tokens": 2,
                        "reasoning_output_tokens": 1, "total_tokens": n + 2}}}}) + "\n")
            rc, so, _ = run("token_meter.py", "codex", x)
            self.assertEqual(json.loads(so.splitlines()[0])["total"], 252)


class BrainLibraryTests(unittest.TestCase):
    def test_brain_skill_library_is_on_demand_and_indexed(self):
        sys.path.insert(0, TOOLS)
        import brain_index as BI
        lib = [r for r in BI.DEFAULT_ROOTS if r.get("kind") == "brain-library"]
        self.assertEqual(len(lib), 1)
        self.assertEqual(lib[0]["autoload"], "no")
        self.assertEqual(lib[0]["path"], os.path.join(os.path.dirname(TOOLS), "skills"))
        with tempfile.TemporaryDirectory() as t:
            write(t, "skills/demo-cad/SKILL.md", "---\nname: demo-cad\ndescription: Blender test skill\n---\n# x\n")
            roots = write(t, "roots.json", json.dumps([dict(lib[0], path=os.path.join(t, "skills"))]))
            old = os.environ.get("BRAIN_SKILL_ROOTS")
            os.environ["BRAIN_SKILL_ROOTS"] = roots
            try:
                rows = BI.collect_skills()
            finally:
                os.environ.pop("BRAIN_SKILL_ROOTS") if old is None else os.environ.__setitem__("BRAIN_SKILL_ROOTS", old)
            self.assertEqual([(r["name"], r["kind"], r["autoload"]) for r in rows], [("demo-cad", "brain-library", "no")])


if __name__ == "__main__":
    unittest.main()
