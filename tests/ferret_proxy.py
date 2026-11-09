"""Offline Ferret integration and authentication boundary regression tests."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gateway'))
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from gateway import (
    FERRET_READ_TOOLS, FERRET_WRITE_TOOLS, ExplicitToolBoundary,
    build_server, create_ferret_proxy, ferret_settings,
)

URL = 'https://ferret.example.invalid/mcp'
FERRET_ENV = ('FERRET_MCP_URL', 'FERRET_MCP_TOKEN', 'FERRET_WRITE_TOOLS')


class FerretTests(unittest.TestCase):
    def test_optional_by_default(self):
        with patch.dict(os.environ, {key: '' for key in FERRET_ENV}):
            self.assertIsNone(ferret_settings())

    def test_read_only_by_default(self):
        with patch.dict(os.environ, {'FERRET_MCP_URL': URL, 'FERRET_MCP_TOKEN': 'test-secret',
                                     'FERRET_WRITE_TOOLS': ''}):
            url, token, tools = ferret_settings()
            self.assertEqual((url, token), (URL, 'test-secret'))
            self.assertEqual(tools, FERRET_READ_TOOLS)
            self.assertNotIn('remove', tools)
            self.assertNotIn('create_item', tools)

    def test_write_tools_only_by_explicit_name(self):
        with patch.dict(os.environ, {'FERRET_MCP_URL': URL, 'FERRET_MCP_TOKEN': 'test-secret',
                                     'FERRET_WRITE_TOOLS': 'create_item,update_item'}):
            tools = ferret_settings()[2]
            self.assertEqual(tools - FERRET_READ_TOOLS, {'create_item', 'update_item'})
        for invalid in ('remove', '*', 'unknown_new_tool', 'create_item,remove'):
            with patch.dict(os.environ, {'FERRET_MCP_URL': URL, 'FERRET_MCP_TOKEN': 'test-secret',
                                         'FERRET_WRITE_TOOLS': invalid}):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    ferret_settings()
        self.assertNotIn('remove', FERRET_WRITE_TOOLS)

    def test_bad_config_fails_closed(self):
        cases = [
            {'FERRET_MCP_URL': URL, 'FERRET_MCP_TOKEN': ''},
            {'FERRET_MCP_URL': '', 'FERRET_MCP_TOKEN': 'secret'},
            {'FERRET_MCP_URL': '', 'FERRET_MCP_TOKEN': '', 'FERRET_WRITE_TOOLS': 'create_item'},
            {'FERRET_MCP_URL': 'http://ferret.example.invalid/mcp', 'FERRET_MCP_TOKEN': 'secret'},
            {'FERRET_MCP_URL': 'https://u:p@ferret.example.invalid/mcp', 'FERRET_MCP_TOKEN': 'secret'},
            {'FERRET_MCP_URL': URL + '?token=secret', 'FERRET_MCP_TOKEN': 'secret'},
            {'FERRET_MCP_URL': URL, 'FERRET_MCP_TOKEN': 'Bearer secret'},
            {'FERRET_MCP_URL': URL, 'FERRET_MCP_TOKEN': 'secret\nOther: value'},
        ]
        for config in cases:
            with self.subTest(config={k: v for k, v in config.items() if k != 'FERRET_MCP_TOKEN'}):
                with patch.dict(os.environ, {key: '' for key in FERRET_ENV} | config):
                    with self.assertRaises(ValueError):
                        ferret_settings()

    def test_bearer_header_stays_on_backend(self):
        with patch('gateway.StreamableHttpTransport') as transport, \
             patch('gateway.ProxyClient') as client, \
             patch('gateway.create_proxy') as factory:
            create_ferret_proxy(URL, 'synthetic-secret')
            transport.assert_called_once_with(
                URL, headers={'Authorization': 'Bearer synthetic-secret'})
            client.assert_called_once_with(
                transport.return_value, forward_incoming_headers=False)
            factory.assert_called_once_with(
                client.return_value, name='Ferret Inventar', mask_error_details=True)

    def test_explicit_tool_boundary(self):
        async def check():
            guard = ExplicitToolBoundary({'ferret_search_inventory'})
            for name in ('ferret_search_inventory',):
                fn = AsyncMock(return_value={'ok': True})
                result = await guard.on_call_tool(
                    SimpleNamespace(message=SimpleNamespace(name=name)), fn)
                self.assertEqual(result, {'ok': True})
                fn.assert_awaited_once()
            for name in ('ferret_create_item', 'ferret_remove',
                         'ferret_unknown', 'attach_document'):
                with self.subTest(tool=name), self.assertRaises(ToolError):
                    await guard.on_call_tool(
                        SimpleNamespace(message=SimpleNamespace(name=name)), AsyncMock())
        asyncio.run(check())

    def test_mount_exposes_only_reviewed_tools(self):
        # A synthetic, in-process backend keeps CI independent of Ferret and secrets.
        fake = FastMCP('Synthetic Ferret', mask_error_details=True)

        @fake.tool()
        def search_inventory(query: str) -> dict:
            return {'items': [], 'query': query}

        @fake.tool()
        def create_item(name: str) -> dict:
            return {'created': name}

        with tempfile.TemporaryDirectory() as state:
            runtime = {
                'MCP_PUBLIC_URL': 'https://mcp.example.invalid',
                'OAUTH_CLIENT_ID': 'synthetic-client',
                'OAUTH_CLIENT_SECRET': 'synthetic-secret',
                'OAUTH_ALLOWED_SUBJECTS': '12345',
                'OAUTH_SIGNING_KEY': 's' * 64,
                'PANGOLIN_ORIGIN_SECRET': 'o' * 64,
                'HOMEBOX_URL': 'http://127.0.0.1:1',
                'HOMEBOX_TOKEN': 'synthetic',
                'HOMEBOX_PUBLIC_URL': 'https://inventory.example.invalid',
                'XDG_DATA_HOME': state,
                'FERRET_MCP_URL': URL,
                'FERRET_MCP_TOKEN': 'fake-key',
            }
            for enabled_writes, expected_write in [('', False), ('create_item', True)]:
                with self.subTest(writes=enabled_writes):
                    with patch.dict(os.environ, runtime | {'FERRET_WRITE_TOOLS': enabled_writes}), \
                         patch('gateway.create_ferret_proxy', return_value=fake):
                        server, _ = build_server()
                        names = {tool.name for tool in asyncio.run(server.list_tools())}
                        self.assertIn('ferret_search_inventory', names)
                        self.assertEqual('ferret_create_item' in names, expected_write)
                        self.assertNotIn('ferret_remove', names)


if __name__ == '__main__':
    unittest.main()
