from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.api.analysis_api import create_app
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.system_management.mcp_registry import (
    McpRegistry,
    McpSecretCipher,
    MemoryMcpServerRepository,
)


class McpManagementApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = McpRegistry(
            repository=MemoryMcpServerRepository(),
            cipher=McpSecretCipher("unit-test-master-key"),
        )
        self.environment = patch.dict(
            "os.environ",
            {"GENBI_SYSTEM_API_TOKEN": "internal-system-token"},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.client = TestClient(
            create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                mcp_registry=self.registry,
            )
        )
        self.headers = {
            "X-GenBI-System-Token": "internal-system-token",
            "X-GenBI-Actor-Id": "admin-1",
        }

    def test_admin_gateway_can_create_list_and_reveal_external_secret(self) -> None:
        created = self.client.post(
            "/api/system/mcp/servers",
            headers=self.headers,
            json={
                "name": "external_api",
                "displayName": "External API",
                "transport": "streamable_http",
                "url": "https://mcp.example.test/mcp",
                "bearerTokenEnvVar": "EXTERNAL_MCP_TOKEN",
                "bearerToken": "plain-http-token",
                "enabled": True,
            },
        )

        self.assertEqual(created.status_code, 201)
        self.assertNotIn("plain-http-token", created.text)

        listed = self.client.get(
            "/api/system/mcp/servers",
            headers=self.headers,
        )
        self.assertEqual(
            [server["category"] for server in listed.json()["servers"]],
            ["system", "external"],
        )
        self.assertNotIn("plain-http-token", listed.text)

        revealed = self.client.get(
            "/api/system/mcp/servers/external_api/secrets",
            headers=self.headers,
        )
        self.assertEqual(revealed.status_code, 200)
        self.assertEqual(
            revealed.json(),
            {"secrets": {"EXTERNAL_MCP_TOKEN": "plain-http-token"}},
        )

    def test_server_name_cannot_be_changed(self) -> None:
        self.client.post(
            "/api/system/mcp/servers",
            headers=self.headers,
            json={
                "name": "external_api",
                "transport": "streamable_http",
                "url": "https://mcp.example.test/mcp",
            },
        )

        response = self.client.patch(
            "/api/system/mcp/servers/external_api",
            headers=self.headers,
            json={"name": "renamed_api"},
        )

        self.assertEqual(response.status_code, 409)

    def test_system_server_can_be_disabled_but_not_deleted(self) -> None:
        disabled = self.client.patch(
            "/api/system/mcp/servers/GenBI_report",
            headers=self.headers,
            json={"enabled": False},
        )
        deleted = self.client.delete(
            "/api/system/mcp/servers/GenBI_report",
            headers=self.headers,
        )

        self.assertEqual(disabled.status_code, 200)
        self.assertFalse(disabled.json()["server"]["enabled"])
        self.assertEqual(deleted.status_code, 409)

    def test_mutations_require_internal_system_token(self) -> None:
        response = self.client.post(
            "/api/system/mcp/servers",
            json={
                "name": "external_api",
                "transport": "streamable_http",
                "url": "https://mcp.example.test/mcp",
            },
        )

        self.assertEqual(response.status_code, 401)

    def test_connection_test_discovers_and_persists_tools(self) -> None:
        script = "\n".join(
            [
                "import json,sys",
                "for line in sys.stdin:",
                " request=json.loads(line)",
                " if request.get('method') == 'initialize':",
                "  print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'protocolVersion':'2024-11-05','capabilities':{},'serverInfo':{'name':'fixture','version':'1'}}}), flush=True)",
                " elif request.get('method') == 'tools/list':",
                "  print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'tools':[{'name':'fixture_query','description':'Fixture'}]}}), flush=True)",
            ]
        )
        self.client.post(
            "/api/system/mcp/servers",
            headers=self.headers,
            json={
                "name": "fixture",
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-u", "-c", script],
            },
        )

        tested = self.client.post(
            "/api/system/mcp/servers/fixture/test",
            headers=self.headers,
        )
        listed = self.client.get(
            "/api/system/mcp/servers",
            headers=self.headers,
        )

        self.assertEqual(tested.status_code, 200)
        self.assertTrue(tested.json()["ok"])
        external = next(
            server
            for server in listed.json()["servers"]
            if server["name"] == "fixture"
        )
        self.assertEqual(
            [tool["name"] for tool in external["tools"]],
            ["fixture_query"],
        )


if __name__ == "__main__":
    unittest.main()
