from __future__ import annotations

import io
import json
import unittest
import urllib.error

from backend.system_management.model_connections import ModelRuntimeConnection
from backend.system_management.model_probe import probe_model_connection


class FakeResponse:
    status = 200
    headers = {"content-type": "application/json"}

    def read(self, _: int = -1) -> bytes:
        return json.dumps(
            {
                "id": "resp_test",
                "status": "completed",
                "model": "test-model",
            }
        ).encode("utf-8")

    def close(self) -> None:
        return None


class ModelConnectionProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = ModelRuntimeConnection(
            name="test",
            display_name="Test",
            provider_type="openai_compatible",
            model="test-model",
            base_url="https://models.example.test/v1",
            api_key="plain-model-key",
        )

    def test_probe_calls_responses_endpoint_without_exposing_key(self) -> None:
        captured: dict[str, object] = {}

        def opener(
            request: object,
            *,
            timeout: float,
        ) -> FakeResponse:
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        result = probe_model_connection(
            self.connection,
            opener=opener,
            timeout_seconds=7,
        )

        request = captured["request"]
        self.assertEqual(request.full_url, "https://models.example.test/v1/responses")
        self.assertEqual(request.get_header("Authorization"), "Bearer plain-model-key")
        self.assertEqual(
            json.loads(request.data.decode("utf-8"))["model"],
            "test-model",
        )
        self.assertEqual(captured["timeout"], 7)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ready")
        self.assertNotIn("plain-model-key", str(result))

    def test_probe_sanitizes_upstream_authentication_errors(self) -> None:
        def opener(
            _: object,
            *,
            timeout: float,
        ) -> FakeResponse:
            del timeout
            raise urllib.error.HTTPError(
                "https://models.example.test/v1/responses",
                401,
                "Unauthorized",
                {},
                io.BytesIO(b'{"error":"plain-model-key invalid"}'),
            )

        result = probe_model_connection(self.connection, opener=opener)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("401", result["message"])
        self.assertNotIn("plain-model-key", str(result))

    def test_probe_reports_timeout_without_upstream_details(self) -> None:
        def opener(
            _: object,
            *,
            timeout: float,
        ) -> FakeResponse:
            del timeout
            raise TimeoutError("request containing plain-model-key timed out")

        result = probe_model_connection(self.connection, opener=opener)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["message"], "连接超时")
        self.assertNotIn("plain-model-key", str(result))


if __name__ == "__main__":
    unittest.main()
