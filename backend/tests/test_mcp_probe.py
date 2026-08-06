from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_mcp_config import CodexMcpServer
from backend.system_management.mcp_probe import probe_mcp_server


class McpProbeTest(unittest.TestCase):
    def test_stdio_probe_initializes_and_discovers_tools(self) -> None:
        script = "\n".join(
            [
                "import json,sys",
                "for line in sys.stdin:",
                " request=json.loads(line)",
                " if request.get('method') == 'initialize':",
                "  print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'fixture','version':'1'}}}), flush=True)",
                " elif request.get('method') == 'tools/list':",
                "  print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'tools':[{'name':'fixture_query','description':'Run a fixture query'}]}}), flush=True)",
            ]
        )
        server = CodexMcpServer(
            name="fixture",
            command=sys.executable,
            args=["-u", "-c", script],
        )

        result = probe_mcp_server(server, timeout_seconds=5)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(
            result["tools"],
            [
                {
                    "name": "fixture_query",
                    "description": "Run a fixture query",
                    "permission": "tool.external",
                    "trusted": False,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
