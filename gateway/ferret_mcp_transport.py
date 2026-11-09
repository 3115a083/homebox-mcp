"""Ferret MCP transport adapter for the one-shot Homebox migration.

The reverse proxy may expose /mcp with an API key while protecting /api/v1
with a separate login. This adapter uses *only* Ferret's MCP endpoint for
all destination reads and writes. No inventory data or image bytes are logged.

The small request() adapter provides the exact response shapes consumed by
migrate_to_ferret.py, so the metadata and photo safety checks are shared.
"""
from __future__ import annotations

import base64
import json
import re

import httpx


_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


class FerretMCP:
    def __init__(self, url: str, token: str, *, transport=None):
        parts = httpx.URL(url.strip())
        if (parts.scheme != "https" or not parts.host or parts.userinfo or
                parts.query or parts.fragment or not parts.path.endswith("/mcp")):
            raise ValueError("FERRET_MCP_URL must be an HTTPS URL ending in /mcp")
        self.url = str(parts)
        self.key = token
        self.client = httpx.Client(
            timeout=120,
            follow_redirects=False,
            transport=transport,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-11-25",
            },
        )
        self.sequence = 0
        self.session = None

    def __enter__(self):
        try:
            self._initialize()
        except Exception:
            self.client.close()
            raise
        return self

    def __exit__(self, _type, _value, _tb):
        self.client.close()

    def _post(self, payload: dict):
        headers = {"Mcp-Session-Id": self.session} if self.session else None
        r = self.client.post(self.url, json=payload, headers=headers)
        r.raise_for_status()
        new_session = r.headers.get("mcp-session-id")
        if new_session:
            if self.session and self.session != new_session:
                raise ValueError("Ferret MCP session unexpectedly changed")
            self.session = new_session
        if r.status_code == 202 or not r.content:
            return None
        if "text/event-stream" in r.headers.get("content-type", ""):
            messages = []
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    try:
                        messages.append(json.loads(line[5:].strip()))
                    except json.JSONDecodeError:
                        continue
            if not messages:
                raise ValueError("Ferret MCP returned no JSON event")
            for message in messages:
                if "result" in message or "error" in message:
                    return message
            raise ValueError("Ferret MCP SSE has no RPC response")
        return r.json()

    def _initialize(self):
        self.sequence += 1
        init = self._post({
            "jsonrpc": "2.0", "id": self.sequence, "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "homebox-ferret-migration", "version": "1"},
            },
        })
        if not isinstance(init, dict) or not isinstance(init.get("result"), dict):
            raise ValueError("Ferret MCP initialization failed")
        accepted = init["result"].get("protocolVersion")
        if accepted not in ("2025-11-25", "2026-07-28"):
            raise ValueError("Unsupported Ferret MCP protocol")
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def available_tools(self) -> frozenset[str]:
        """Read the server-advertised tool list before any migration writes."""
        names = set()
        cursor = None
        for _ in range(20):
            self.sequence += 1
            args = {"cursor": cursor} if cursor else {}
            envelope = self._post({
                "jsonrpc": "2.0", "id": self.sequence,
                "method": "tools/list", "params": args,
            })
            if not isinstance(envelope, dict) or not isinstance(envelope.get("result"), dict):
                raise ValueError("Could not inspect Ferret MCP tool permissions")
            result = envelope["result"]
            if not isinstance(result.get("tools"), list):
                raise ValueError("Unexpected Ferret MCP tool list")
            for tool in result["tools"]:
                if isinstance(tool, dict) and isinstance(tool.get("name"), str):
                    names.add(tool["name"])
            next_cursor = result.get("nextCursor")
            if not next_cursor:
                return frozenset(names)
            if next_cursor == cursor:
                raise ValueError("Ferret MCP tool pagination stalled")
            cursor = next_cursor
        raise ValueError("Ferret MCP tool list exceeded pagination limit")

    def call(self, name: str, arguments: dict | None = None):
        self.sequence += 1
        envelope = self._post({
            "jsonrpc": "2.0", "id": self.sequence,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        })
        if not isinstance(envelope, dict):
            raise ValueError("Empty MCP tool response for " + name)
        if envelope.get("error"):
            raise ValueError("Ferret MCP protocol error for " + name)
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise ValueError("Malformed Ferret MCP tool response for " + name)
        if result.get("isError"):
            texts = [c.get("text", "") for c in result.get("content") or [] if c.get("type") == "text"]
            # Error responses sometimes contain input echoes. Avoid logging raw
            # values, images or secrets from the upstream server.
            raise ValueError("Ferret rejected MCP tool: " + name)
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return structured
        texts = [c.get("text") for c in result.get("content") or []
                 if c.get("type") == "text" and isinstance(c.get("text"), str)]
        if len(texts) != 1:
            raise ValueError("Unexpected Ferret MCP content for " + name)
        try:
            value = json.loads(texts[0])
        except json.JSONDecodeError:
            raise ValueError("Non-JSON Ferret MCP result for " + name) from None
        if not isinstance(value, dict):
            raise ValueError("Unexpected Ferret MCP result type for " + name)
        return value

    def request(self, method: str, path: str, **kwargs):
        """Mimic only the Ferret REST operations the migration needs."""
        if method == "GET" and path == "me":
            # Authenticated read: unlike /api/v1/me, this works behind an MCP-
            # only reverse-proxy rule. Fails clearly before any write.
            self.call("list_locations")
            result = {"verified": True}
        elif method == "GET" and path == "items":
            params = kwargs.get("params") or {}
            found = self.call("list_items", {
                "limit": params.get("limit", 200),
                "offset": params.get("offset", 0),
            })
            result = {"data": found.get("items", []), "total": found.get("total", 0)}
        elif method == "GET" and path == "categories":
            result = {"data": self.call("list_categories").get("categories", [])}
        elif method == "POST" and path == "categories":
            body = kwargs["json"]
            result = self.call("save_category", {
                "name": body["name"],
                "parentId": body.get("parentId"),
            })
        elif method == "GET" and path == "locations/tree":
            result = self.call("list_locations")
        elif method == "POST" and path == "locations":
            body = kwargs["json"]
            result = self.call("save_location", {
                "name": body["name"],
                "parentId": body.get("parentId"),
                "propertyId": body["propertyId"],
            })
        elif method == "POST" and path == "items":
            result = self.call("create_item", kwargs["json"])
        else:
            m = re.fullmatch(r"items/([a-zA-Z0-9_-]+)/attachments", path)
            if not m or not _SAFE_ID.fullmatch(m.group(1)):
                raise ValueError("Unsupported Ferret operation")
            item_id = m.group(1)
            if method == "GET":
                item = self.call("get_item", {"id": item_id})
                result = {"data": [{"filename": a.get("filename"), "id": a.get("id")}
                                   for a in item.get("attachments", [])]}
            elif method == "POST":
                filename, raw, _mime = kwargs["files"]["file"]
                if not isinstance(raw, bytes):
                    raise ValueError("Expected original photo bytes")
                # Only this adapter converts the existing photo-only payload to
                # base64; it never accepts document types from the caller.
                if kwargs.get("data", {}).get("kind") != "photo":
                    raise ValueError("Non-photo upload was refused")
                result = self.call("add_photo", {
                    "itemId": item_id,
                    "kind": "photo",
                    "filename": filename,
                    "data": base64.b64encode(raw).decode("ascii"),
                })
                result = {"id": result.get("attachment")}
            else:
                raise ValueError("Unsupported Ferret operation")
        # Use an ordinary httpx response so the original request() helper,
        # status handling and validation remain unchanged.
        req = httpx.Request(method, self.url)
        return httpx.Response(200, request=req, json=result)
