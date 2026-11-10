"""Compare the live authenticated Ferret MCP tools with our reviewed gateway policy.

Read-only: only MCP initialize and tools/list are issued. Never prints tokens,
URLs, environment, tool schemas, tool responses, inventory, or remote errors.
"""
from __future__ import annotations

import json
import os
import sys

from ferret_mcp_transport import FerretMCP
from gateway import (
    FERRET_READ_TOOLS, FERRET_WRITE_TOOLS, FERRET_DESTRUCTIVE_TOOLS,
    ferret_settings,
)


def capability_report(advertised: frozenset[str], enabled: frozenset[str]) -> dict:
    """Pure summary; expose only tool names, never private MCP descriptions."""
    reviewed = FERRET_READ_TOOLS | FERRET_WRITE_TOOLS | FERRET_DESTRUCTIVE_TOOLS
    return {
        "upstream_tools": len(advertised),
        "reviewed_available": len(advertised & reviewed),
        "read_tools": sorted(advertised & FERRET_READ_TOOLS),
        "enabled_write_tools": sorted(advertised & FERRET_WRITE_TOOLS & enabled),
        "disabled_write_tools": sorted(advertised & FERRET_WRITE_TOOLS - enabled),
        "enabled_destructive_tools": sorted(advertised & FERRET_DESTRUCTIVE_TOOLS & enabled),
        "disabled_destructive_tools": sorted(advertised & FERRET_DESTRUCTIVE_TOOLS - enabled),
        "unsupported_upstream_tools": sorted(advertised - reviewed),
        "gateway_enabled_tools_not_offered_by_ferret": sorted(enabled - advertised),
        "legacy_maintenance_api": "add_maintenance" in advertised,
        "modern_maintenance_api": "save_maintenance" in advertised,
        "category_write_offered": bool(advertised & {"save_category"}),
        "location_write_offered": bool(advertised & {"save_location", "create_location"}),
    }


def main() -> int:
    try:
        settings = ferret_settings()
        if settings is None:
            print("Ferret MCP is not configured.", file=sys.stderr)
            return 1
        url, token, enabled = settings
        with FerretMCP(url, token) as connection:
            advertised = connection.available_tools()
        print(json.dumps(capability_report(advertised, frozenset(enabled)),
                         sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as e:
        # Avoid upstream exception messages, which might contain private data.
        print("Ferret MCP capability audit failed: " + type(e).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
