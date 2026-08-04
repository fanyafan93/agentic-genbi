"""Health endpoint contract.

The backend MUST refuse to start when Postgres is unavailable.
The ``/health`` endpoint MUST report ``503 unhealthy`` when any
configured store cannot answer a real query. We do not silently
fall back to a degraded mode.
"""

from __future__ import annotations

import unittest

from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.tests.auth_test_client import build_test_app


class HealthEndpointTest(unittest.TestCase):
    def test_health_returns_ok_when_stores_respond(self) -> None:
        # The default ``build_test_app`` wires empty in-memory stores
        # that respond to ``list_threads`` / ``list_assets`` /
        # ``list_reports`` / ``list_knowledge``. Health must report ok.
        app = build_test_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("checks", body)
        self.assertEqual(body["checks"]["thread_store"], "ok")
        self.assertEqual(body["checks"]["analysis_asset_store"], "ok")
        self.assertEqual(body["checks"]["interactive_report_store"], "ok")
        self.assertEqual(body["checks"]["knowledge_store"], "ok")

    def test_health_returns_503_when_a_store_fails(self) -> None:
        # A store that always raises a real error must surface as
        # ``unhealthy`` (HTTP 503). We never degrade silently; the
        # readiness probe is the operator's signal to roll back the
        # deploy.
        class _FailingThreadStore:
            def list_threads(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                raise RuntimeError("database connection refused")

        app = build_test_app(
            analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
            thread_store=_FailingThreadStore(),  # type: ignore[arg-type]
        )
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body["status"], "unhealthy")
        self.assertIn("RuntimeError", body["checks"]["thread_store"])
        # Other stores still report ok; the failure is per-store.
        self.assertEqual(body["checks"]["analysis_asset_store"], "ok")


if __name__ == "__main__":
    unittest.main()
