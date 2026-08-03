from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness import genbi_mcp_server


class _FakeDownstream:
    """In-memory replacement for ``DownstreamClient`` used by tests."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any] | None]] = []
        self.notifies: list[tuple[str, dict[str, Any] | None]] = []
        self._next_response: dict[str, Any] | None = None
        self._next_error: Exception | None = None
        self.closed = False
        self.running = True

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.requests.append((method, params))
        if self._next_error is not None:
            err, self._next_error = self._next_error, None
            raise err
        assert self._next_response is not None, f"no response queued for {method}"
        response, self._next_response = self._next_response, None
        return response

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self.notifies.append((method, params))

    def close(self) -> None:
        self.closed = True
        self.running = False

    def queue_response(self, response: dict[str, Any]) -> None:
        self._next_response = response

    def queue_error(self, exc: Exception) -> None:
        self._next_error = exc


class _LineReader:
    """Iterate over JSONL text frames like stdin."""

    def __init__(self, frames: list[dict[str, Any]]) -> None:
        self._lines = [json.dumps(frame) for frame in frames]

    def __iter__(self) -> "iter[str]":
        return iter(self._lines)


class GenbiMcpServerTest(unittest.TestCase):
    def test_initialize_negotiates_with_downstream(self) -> None:
        fake = _FakeDownstream()
        fake.queue_response(
            {
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                },
            }
        )
        server = genbi_mcp_server.GenbiMcpServer(fake)
        stdout = io.StringIO()
        frames = [
            {
                "jsonrpc": "2.0",
                "id": "init-1",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test"},
                },
            }
        ]
        server.run(_LineReader(frames), stdout)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(fake.requests[0][0], "initialize")
        self.assertEqual(fake.notifies[0][0], "notifications/initialized")
        responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], "init-1")
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2024-11-05")

    def test_tools_list_advertises_aliased_tool(self) -> None:
        fake = _FakeDownstream()
        server = genbi_mcp_server.GenbiMcpServer(fake)
        stdout = io.StringIO()
        frames = [{"jsonrpc": "2.0", "id": "list-1", "method": "tools/list"}]
        server.run(_LineReader(frames), stdout)
        responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(len(responses), 1)
        tools = responses[0]["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "mysql_query")
        self.assertEqual(tools[0]["inputSchema"]["required"], ["sql"])

    def test_tools_call_forwards_to_downstream_with_stripped_name(self) -> None:
        fake = _FakeDownstream()
        fake.queue_response(
            {
                "id": 99,
                "result": {
                    "content": [
                        {"type": "text", "text": "row 1 | 100.0"},
                        {"type": "text", "text": "row 2 | 200.0"},
                    ],
                    "isError": False,
                },
            }
        )
        server = genbi_mcp_server.GenbiMcpServer(fake)
        stdout = io.StringIO()
        frames = [
            {
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {
                    "name": "mcp__BI_doris__mysql_query",
                    "arguments": {"sql": "SELECT 1"},
                },
            }
        ]
        server.run(_LineReader(frames), stdout)
        self.assertEqual(len(fake.requests), 1)
        forwarded_method, forwarded_params = fake.requests[0]
        self.assertEqual(forwarded_method, "tools/call")
        self.assertEqual(forwarded_params["name"], "mysql_query")
        self.assertEqual(forwarded_params["arguments"], {"sql": "SELECT 1"})
        responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(responses[0]["id"], "call-1")
        self.assertFalse(responses[0]["result"]["isError"])

    def test_tools_call_accepts_double_prefixed_name(self) -> None:
        """Codex 0.146.0 emits the upstream server prefix on top of whatever
        tool name we registered. The alias must still strip it cleanly so the
        downstream @benborla29 server receives the bare ``mysql_query`` name.
        """
        fake = _FakeDownstream()
        fake.queue_response(
            {
                "id": 12,
                "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
            }
        )
        server = genbi_mcp_server.GenbiMcpServer(fake)
        stdout = io.StringIO()
        frames = [
            {
                "jsonrpc": "2.0",
                "id": "call-1",
                "method": "tools/call",
                "params": {
                    "name": "mcp__BI_doris__mcp__BI_doris__mysql_query",
                    "arguments": {"sql": "SELECT 1"},
                },
            }
        ]
        server.run(_LineReader(frames), stdout)
        forwarded_method, forwarded_params = fake.requests[0]
        self.assertEqual(forwarded_method, "tools/call")
        self.assertEqual(forwarded_params["name"], "mysql_query")

    def test_tools_call_returns_error_for_unknown_tool(self) -> None:
        fake = _FakeDownstream()
        server = genbi_mcp_server.GenbiMcpServer(fake)
        stdout = io.StringIO()
        frames = [
            {
                "jsonrpc": "2.0",
                "id": "call-2",
                "method": "tools/call",
                "params": {"name": "mcp__BI_doris__some_other_tool", "arguments": {}},
            }
        ]
        server.run(_LineReader(frames), stdout)
        responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(responses[0]["error"]["code"], -32601)
        self.assertIn("unsupported call", responses[0]["error"]["message"])
        # The downstream was NOT consulted for an unknown tool.
        self.assertEqual(len(fake.requests), 0)

    def test_tools_call_surfaces_downstream_errors(self) -> None:
        fake = _FakeDownstream()
        fake.queue_error(RuntimeError("connection closed"))
        server = genbi_mcp_server.GenbiMcpServer(fake)
        stdout = io.StringIO()
        frames = [
            {
                "jsonrpc": "2.0",
                "id": "call-3",
                "method": "tools/call",
                "params": {
                    "name": "mcp__BI_doris__mysql_query",
                    "arguments": {"sql": "SELECT 1"},
                },
            }
        ]
        server.run(_LineReader(frames), stdout)
        responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(responses[0]["error"]["code"], -32603)
        self.assertIn("downstream error", responses[0]["error"]["message"])

    def test_unrelated_server_prefix_is_not_stripped(self) -> None:
        # A request targeting a different server should not be silently
        # routed to downstream. We refuse it explicitly.
        fake = _FakeDownstream()
        server = genbi_mcp_server.GenbiMcpServer(fake)
        stdout = io.StringIO()
        frames = [
            {
                "jsonrpc": "2.0",
                "id": "call-4",
                "method": "tools/call",
                "params": {"name": "mcp__some_other_server__mysql_query", "arguments": {}},
            }
        ]
        server.run(_LineReader(frames), stdout)
        responses = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(responses[0]["error"]["code"], -32601)
        self.assertEqual(len(fake.requests), 0)

    def test_strip_prefix_helper(self) -> None:
        self.assertEqual(
            genbi_mcp_server._strip_server_prefix("mcp__BI_doris__mysql_query"),
            "mysql_query",
        )
        self.assertEqual(
            genbi_mcp_server._strip_server_prefix("mysql_query"),
            "mysql_query",
        )

    def test_resolve_downstream_env_uses_prefixed_keys(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                "GENBI_MCP_DOWNSTREAM_ENV_MYSQL_HOST": "8.134.63.30",
                "GENBI_MCP_DOWNSTREAM_ENV_MYSQL_USER": "readonly_user",
                "OTHER_VAR": "ignored",
            },
            clear=True,
        ):
            env = genbi_mcp_server._resolve_downstream_env()
        self.assertEqual(env, {"MYSQL_HOST": "8.134.63.30", "MYSQL_USER": "readonly_user"})


if __name__ == "__main__":
    unittest.main()