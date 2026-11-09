"""Offline integration tests for direct Ferret MCP migration and photo uploads."""
import base64
import json
import os
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gateway"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import migrate_to_ferret as m
from ferret_mcp_transport import FerretMCP
from ferret_migration import MockInventory


class McpServerFake:
    def __init__(self, inventory):
        self.db = inventory
        self.calls = []
        self.mcp_only = True

    def __call__(self, req):
        assert req.url.path == "/mcp", "REST API must never be used"
        assert req.headers.get("authorization") == "Bearer ferret-token"
        assert "text/event-stream" in req.headers.get("accept", "")
        payload = json.loads(req.content)
        method = payload["method"]
        if method == "initialize":
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": payload["id"], "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {}, "serverInfo": {"name": "test-ferret", "version": "1"},
                },
            }, headers={"Mcp-Session-Id": "test-session"})
        assert req.headers.get("mcp-session-id") == "test-session"
        if method == "notifications/initialized":
            return httpx.Response(202, content=b"")
        assert method == "tools/call"
        name, args = payload["params"]["name"], payload["params"]["arguments"]
        self.calls.append(name)
        db = self.db
        if name == "list_locations":
            result = {"properties": [{"id": "property1", "name": "Test",
                                      "locations": db.locations}]}
        elif name == "list_categories":
            result = {"categories": db.cats, "tags": [], "templates": []}
        elif name == "list_items":
            start = args.get("offset", 0)
            result = {"total": len(db.dest), "offset": start,
                      "items": db.dest[start:start + args.get("limit", 50)]}
        elif name == "save_category":
            new = {"id": f"category-{len(db.cats)}", "name": args["name"],
                   "children": [], "path": args["name"]}
            db.cats.append(new)
            result = new
        elif name == "save_location":
            result = {"id": f"loc-{len(db.locations)}",
                      "name": args["name"], "children": []}
            parent = next((r for r in db.locations if r["id"] == args.get("parentId")), None)
            (parent["children"] if parent else db.locations).append(result)
        elif name == "create_item":
            result = dict(args)
            result["id"] = "ferret-" + str(len(db.dest) + 1)
            db.dest.append(result)
        elif name == "get_item":
            matching = [x for x in db.dest if x["id"] == args["id"]]
            if not matching:
                return self._return(payload, error=True)
            result = dict(matching[0])
            result["attachments"] = db.attachments.get(result["id"], [])
        elif name == "add_photo":
            assert args["kind"] == "photo"
            assert args["filename"].startswith("homebox-")
            assert args["filename"].endswith((".jpg", ".png", ".webp", ".gif"))
            photo = base64.b64decode(args["data"], validate=True)
            assert m.extension_for(photo) is not None
            arr = db.attachments.setdefault(args["itemId"], [])
            row = {"id": f"file-{len(arr) + 1}", "filename": args["filename"]}
            arr.append(row)
            result = {"attachment": row["id"], "kind": "photo"}
        else:
            raise AssertionError("Unexpected tool: " + name)
        return self._return(payload, result)

    @staticmethod
    def _return(payload, result=None, error=False):
        answer = {"jsonrpc": "2.0", "id": payload["id"],
                  "result": {"content": [{"type": "text", "text": json.dumps(result or {})}],
                             "isError": error}}
        return httpx.Response(200, json=answer)


class Tests(unittest.TestCase):
    def test_mcp_only_dryrun_and_upload_rerun(self):
        db = MockInventory()
        server = McpServerFake(db)
        hb, _unused = db.clients()
        with hb, FerretMCP("https://example.invalid/mcp", "ferret-token",
                           transport=httpx.MockTransport(server)) as f:
            dry, errors = m.migrate(hb, f)
            self.assertFalse(errors)
            self.assertEqual(dry["would_create"], 2)
            self.assertNotIn("create_item", server.calls)
            counts, errors = m.migrate(hb, f, apply=True)
            self.assertFalse(errors, errors)
            self.assertEqual(counts["created"], 2)
            self.assertEqual(counts["uploaded_photos"], 2)
            self.assertEqual(len(db.dest), 2)
            again, errors = m.migrate(hb, f, apply=True)
            self.assertFalse(errors, errors)
            self.assertEqual(again["already_imported"], 2)
            self.assertEqual(again["already_uploaded_photos"], 2)
            self.assertEqual(len(db.dest), 2)
        self.assertEqual(server.calls.count("add_photo"), 2)
        self.assertEqual(server.calls.count("create_item"), 2)
        self.assertNotIn("add_item_from_photo", server.calls)
        self.assertEqual(len([x for x in db.events if x[0] == "POST"]), 0)

    def test_mcp_tool_error_is_rejected(self):
        db = MockInventory()
        server = McpServerFake(db)
        with FerretMCP("https://example.invalid/mcp", "ferret-token",
                       transport=httpx.MockTransport(server)) as f:
            with self.assertRaisesRegex(ValueError, "Ferret rejected"):
                f.call("get_item", {"id": "missing"})

    def test_does_not_accept_insecure_endpoint(self):
        for bad in ["http://localhost/mcp", "https://example.invalid/api/v1",
                    "https://x/mcp?token=secret", "https://user:secret@x/mcp"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                FerretMCP(bad, "ferret-token")


if __name__ == "__main__":
    unittest.main()
