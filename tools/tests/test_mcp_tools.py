"""MCP server: every one of the 10 tools is called over stdio in a throwaway brain, and every tool
declares all four annotation hints. Run: bash tools/test_all.sh"""
import json, unittest

from test_live_tools import Brain

HINTS = {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
READ_ONLY = {"brain_card", "brain_route", "brain_skills", "brain_find_skills", "brain_read"}


class McpToolTests(Brain):
    def rpc(self, *calls):
        msgs = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}]
        msgs += [{"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": n, "arguments": a}}
                 for i, (n, a) in enumerate(calls, 1)]
        rc, so, se = self.run_tool("brain_mcp.py", stdin="\n".join(json.dumps(m) for m in msgs) + "\n")
        self.assertEqual(rc, 0, se)
        out = {d["id"]: d for d in map(json.loads, so.splitlines())}
        return [out[i]["result"] for i in range(1, len(calls) + 1)]

    def text(self, result):
        self.assertNotIn("error", result)
        return result["content"][0]["text"]

    def test_annotations_on_every_tool(self):
        rc, so, se = self.run_tool("brain_mcp.py", stdin=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
        tools = json.loads(so)["result"]["tools"]
        self.assertEqual(len(tools), 10)
        for t in tools:
            a = t["annotations"]
            self.assertEqual(set(a), HINTS, t["name"])
            self.assertTrue(all(isinstance(v, bool) for v in a.values()), t["name"])
            self.assertEqual(a["readOnlyHint"], t["name"] in READ_ONLY, t["name"])
            self.assertFalse(a["destructiveHint"], t["name"])
            self.assertFalse(a["openWorldHint"], t["name"])

    def test_read_tools(self):
        card, route, skills, find, read = self.rpc(
            ("brain_card", {}),
            ("brain_route", {"query": "airflow wind tunnel"}),
            ("brain_skills", {"request": "export blender models for airflow"}),
            ("brain_find_skills", {"request": "export blender models for airflow"}),
            ("brain_read", {"path": "Brain System/domains/engineering/Airflow basics.md"}))
        self.assertIn("brain_session.py", self.text(card))
        self.assertIn("Airflow basics", self.text(route))
        self.assertIn("blender-export", self.text(skills))
        self.assertIn("blender-export", self.text(find))
        self.assertIn("CFD airflow", self.text(read))

    def test_session_tools(self):
        new, = self.rpc(("brain_session_new", {"title": "mcp test", "request": "write a short note", "lane": "fast"}))
        sid = json.loads(self.text(new))["session"]
        cp, close, learn, dream = self.rpc(
            ("brain_checkpoint", {"session": sid, "note": "note written"}),
            ("brain_close", {"session": sid, "task_summary": "Wrote the note and read it back.", "brain_summary": "none"}),
            ("brain_learn_session", {"session": sid}),
            ("brain_dream", {"mode": "status"}))
        self.assertEqual(json.loads(self.text(cp))["checkpoint"], 1)
        self.assertEqual(json.loads(self.text(close))["status"], "closed")
        self.assertFalse(learn.get("isError"), learn)
        self.assertFalse(dream.get("isError"), dream)


if __name__ == "__main__":
    unittest.main()
