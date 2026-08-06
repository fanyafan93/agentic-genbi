from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.api.analysis_api import create_app
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.reports.build_context import ReportToolExecutionRegistry
from backend.system_management.mcp_registry import McpSecretCipher
from backend.system_management.model_connections import (
    MemoryModelConnectionRepository,
    ModelConnectionRegistry,
)


class StubModelConnectionRegistry:
    def list(self) -> list[dict[str, object]]:
        return []


class ModelConnectionManagementApiContractTest(unittest.TestCase):
    def test_backend_registers_model_connection_management_routes(self) -> None:
        client = TestClient(
            create_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
        )

        paths = client.get("/openapi.json").json()["paths"]

        self.assertIn("/api/system/model-connections", paths)
        self.assertIn(
            "/api/system/model-connections/{connection_name}",
            paths,
        )
        self.assertIn(
            "/api/system/model-connections/{connection_name}/secret",
            paths,
        )
        self.assertIn(
            "/api/system/model-connections/{connection_name}/test",
            paths,
        )
        self.assertIn(
            "/api/system/model-connections/{connection_name}/default",
            paths,
        )
        self.assertIn(
            "/api/codex-minimax/{connection_name}/v1/responses",
            paths,
        )

    def test_backend_lists_connections_from_the_managed_registry(self) -> None:
        with patch.dict(
            "os.environ",
            {"GENBI_SYSTEM_API_TOKEN": "internal-system-token"},
            clear=False,
        ):
            client = TestClient(
                create_app(
                    analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                    model_connection_registry=StubModelConnectionRegistry(),
                )
            )

            response = client.get(
                "/api/system/model-connections",
                headers={"X-GenBI-System-Token": "internal-system-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"connections": []})


class ModelConnectionManagementApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ModelConnectionRegistry(
            repository=MemoryModelConnectionRepository(),
            cipher=McpSecretCipher("unit-test-master-key"),
        )
        self.report_registry = ReportToolExecutionRegistry(
            secret=b"test-report-secret"
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
                model_connection_registry=self.registry,
                report_tool_execution_registry=self.report_registry,
            )
        )
        self.headers = {
            "X-GenBI-System-Token": "internal-system-token",
            "X-GenBI-Actor-Id": "admin-1",
        }

    def _create(self, name: str = "minimax") -> None:
        response = self.client.post(
            "/api/system/model-connections",
            headers=self.headers,
            json={
                "name": name,
                "displayName": "MiniMax",
                "providerType": "minimax",
                "model": "MiniMax-M3",
                "baseUrl": "https://api.minimaxi.com/v1",
                "apiKey": "plain-model-key",
                "enabled": True,
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_admin_gateway_can_create_list_and_reveal_api_key(self) -> None:
        self._create()

        listed = self.client.get(
            "/api/system/model-connections",
            headers=self.headers,
        )
        revealed = self.client.get(
            "/api/system/model-connections/minimax/secret",
            headers=self.headers,
        )

        self.assertEqual(listed.status_code, 200)
        self.assertNotIn("plain-model-key", listed.text)
        self.assertTrue(listed.json()["connections"][0]["isDefault"])
        self.assertEqual(revealed.status_code, 200)
        self.assertEqual(revealed.json(), {"apiKey": "plain-model-key"})
        self.assertEqual(revealed.headers["cache-control"], "no-store")

    def test_default_connection_cannot_be_disabled_or_deleted(self) -> None:
        self._create()

        disabled = self.client.patch(
            "/api/system/model-connections/minimax",
            headers=self.headers,
            json={"enabled": False},
        )
        deleted = self.client.delete(
            "/api/system/model-connections/minimax",
            headers=self.headers,
        )

        self.assertEqual(disabled.status_code, 409)
        self.assertEqual(deleted.status_code, 409)

    def test_connection_test_records_a_sanitized_result(self) -> None:
        self._create()
        with patch(
            "backend.api.analysis_api.probe_model_connection",
            return_value={
                "ok": True,
                "status": "ready",
                "message": "连接成功",
                "latencyMs": 12,
            },
        ):
            tested = self.client.post(
                "/api/system/model-connections/minimax/test",
                headers=self.headers,
            )
        listed = self.client.get(
            "/api/system/model-connections",
            headers=self.headers,
        )

        self.assertEqual(tested.status_code, 200)
        self.assertTrue(tested.json()["ok"])
        self.assertEqual(
            listed.json()["connections"][0]["status"],
            "ready",
        )
        self.assertNotIn("plain-model-key", tested.text)

    def test_mutations_require_the_internal_system_token(self) -> None:
        response = self.client.post(
            "/api/system/model-connections",
            json={
                "name": "minimax",
                "displayName": "MiniMax",
                "providerType": "minimax",
                "model": "MiniMax-M3",
                "baseUrl": "https://api.minimaxi.com/v1",
                "apiKey": "plain-model-key",
                "enabled": True,
            },
        )

        self.assertEqual(response.status_code, 401)

    def test_secret_endpoint_fails_closed_when_internal_token_is_unconfigured(
        self,
    ) -> None:
        self._create()
        with patch.dict(
            "os.environ",
            {"GENBI_SYSTEM_API_TOKEN": ""},
            clear=False,
        ):
            response = self.client.get(
                "/api/system/model-connections/minimax/secret",
            )

        self.assertEqual(response.status_code, 503)

    def test_minimax_adapter_uses_the_named_managed_connection(self) -> None:
        self._create()
        with patch(
            "backend.api.analysis_api.proxy_minimax_response",
            return_value=(
                200,
                {"content-type": "application/json"},
                b'{"id":"response-1"}',
            ),
        ) as proxy:
            response = self.client.post(
                "/api/codex-minimax/minimax/v1/responses",
                headers={"Authorization": "Bearer plain-model-key"},
                json={
                    "model": "MiniMax-M3",
                    "input": "ping",
                    "stream": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        proxy.assert_called_once()
        self.assertEqual(
            proxy.call_args.kwargs["upstream_base_url"],
            "https://api.minimaxi.com/v1",
        )
        self.assertEqual(
            proxy.call_args.kwargs["upstream_api_key"],
            "plain-model-key",
        )

    def test_scoped_managed_minimax_adapter_uses_execution_guard(
        self,
    ) -> None:
        self._create()
        token = self.report_registry.reserve(owner_id="user-1")
        execution_id = self.report_registry.execution_id(token)
        self.report_registry.record_successful_report_mutation(
            token,
            "start_report_build",
        )
        with patch(
            "backend.api.analysis_api.proxy_minimax_response",
            return_value=(
                200,
                {"content-type": "application/json"},
                b'{"id":"response-1"}',
            ),
        ):
            for _ in range(3):
                response = self.client.post(
                    (
                        "/api/codex-minimax/minimax/v1/executions/"
                        f"{execution_id}/responses"
                    ),
                    headers={
                        "Authorization": "Bearer plain-model-key"
                    },
                    json={
                        "model": "MiniMax-M3",
                        "stream": False,
                    },
                )
                self.assertEqual(response.status_code, 200)

            blocked = self.client.post(
                (
                    "/api/codex-minimax/minimax/v1/executions/"
                    f"{execution_id}/responses"
                ),
                headers={
                    "Authorization": "Bearer plain-model-key"
                },
                json={"model": "MiniMax-M3", "stream": False},
            )

        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(
            blocked.json()["error"]["code"],
            "report_build_no_progress",
        )

    def test_minimax_adapter_rejects_a_key_that_does_not_match(self) -> None:
        self._create()

        response = self.client.post(
            "/api/codex-minimax/minimax/v1/responses",
            headers={"Authorization": "Bearer wrong-key"},
            json={"model": "MiniMax-M3", "input": "ping"},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
