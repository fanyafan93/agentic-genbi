from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.analysis.asset_store import AnalysisAssetStore
from backend.analysis.interactive_report_store import InteractiveReportStore
import backend.api.analysis_api as analysis_api
from backend.api.analysis_api import create_app
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.events import AgentEvent
from backend.harness.thread_store import ThreadStore
from backend.business_semantics.knowledge_store import KnowledgeStore


class _FakeCodexRuntime:
    runtime_name = "openai-codex"

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def stream(self, question: str, *, context: dict):
        self.contexts.append(dict(context))
        yield from self._events(context)

    async def async_stream(self, question: str, *, context: dict):
        self.contexts.append(dict(context))
        for event in self._events(context):
            yield event

    def _events(self, context: dict):
        codex_thread_id = context.get("codex_thread_id") or "codex_thread_created"
        yield AgentEvent(
            type="turn/started",
            turn_id="codex_turn_created",
            payload={
                "eventSource": "codex",
                "runtime": "openai-codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_created",
            },
        )
        yield AgentEvent(
            type="item/agentMessage/delta",
            turn_id="codex_turn_created",
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_created",
                "codex_item_id": "codex_item_msg",
                "codex_item_type": "agentMessage",
                "delta": "hello",
            },
        )
        yield AgentEvent(
            type="item/completed",
            turn_id="codex_turn_created",
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_created",
                "codex_item_id": "codex_item_msg",
                "codex_item_type": "agentMessage",
                "content": "Codex answer",
            },
        )
        yield AgentEvent(
            type="turn/completed",
            turn_id="codex_turn_created",
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_created",
                "status": "completed",
            },
        )


class _AsyncOnlyRuntime:
    runtime_name = "openai-codex"

    def stream(self, question: str, *, context: dict):
        raise RuntimeError("sync stream must not be used from the create path")

    async def async_stream(self, question: str, *, context: dict):
        yield AgentEvent(
            type="turn/completed",
            turn_id="codex_turn_async",
            payload={
                "eventSource": "codex",
                "codex_thread_id": context.get("codex_thread_id") or "codex_thread_async",
                "codex_turn_id": "codex_turn_async",
                "status": "completed",
            },
        )


class AnalysisApiTest(unittest.IsolatedAsyncioTestCase):
    def test_default_analysis_runtime_uses_codex_runtime_when_configured(self) -> None:
        with patch.dict("os.environ", {"GENBI_ANALYSIS_RUNTIME": "codex"}, clear=False):
            with patch.object(analysis_api.CodexSdkAnalysisRuntime, "from_env") as from_env:
                runtime = object()
                from_env.return_value = runtime

                service = analysis_api.build_default_analysis_runtime()

                self.assertIs(service, runtime)
                from_env.assert_called_once()

    def test_create_app_uses_postgres_thread_store_when_enabled(self) -> None:
        with patch.dict("os.environ", {"GENBI_PERSISTENCE": "postgres"}, clear=False):
            with patch.object(analysis_api, "build_postgres_thread_store") as build_thread_store:
                thread_store = ThreadStore(Path("unused-thread-store.jsonl"))
                build_thread_store.return_value = thread_store

                app = create_app(
                    knowledge_store=KnowledgeStore(),
                    analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                    analysis_asset_store=AnalysisAssetStore(Path("unused-assets.jsonl")),
                    interactive_report_store=InteractiveReportStore(Path("unused-reports.jsonl")),
                )

                self.assertIsNotNone(app)
                build_thread_store.assert_called_once()

    def test_analysis_thread_turn_api_streams_codex_events_and_persists_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/threads/turns",
                json={"question": "analyze channel sales share"},
            )
            payload = response.json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["conversation_id"].startswith("conv_analysis_"))
            self.assertEqual(payload["thread_id"], payload["conversation_id"])
            self.assertTrue(payload["turn_id"].startswith("analysis_turn_"))
            self.assertEqual([event["type"] for event in payload["events"]], ["turn/started", "item/agentMessage/delta", "item/completed", "turn/completed"])
            self.assertTrue(all(event["payload"]["eventSource"] == "codex" for event in payload["events"]))

            thread = client.get(f"/api/analysis/threads/{payload['conversation_id']}")
            turn_detail = client.get(f"/api/analysis/threads/{payload['thread_id']}/turns/{payload['turn_id']}")

            self.assertEqual(thread.status_code, 200)
            self.assertEqual(thread.json()["thread"]["id"], payload["conversation_id"])
            self.assertEqual(thread.json()["thread"]["codexThreadId"], "codex_thread_created")
            self.assertEqual(thread.json()["turns"][0]["codexTurnId"], "codex_turn_created")
            self.assertEqual(turn_detail.status_code, 200)
            self.assertEqual(turn_detail.json()["turn"]["id"], payload["turn_id"])
            self.assertNotIn("executionAttempts", turn_detail.json())
            self.assertEqual(turn_detail.json()["codexItemProjections"][0]["codexItemId"], "codex_item_msg")

    async def test_create_analysis_turn_payload_uses_async_runtime_inside_running_event_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            body = SimpleNamespace(
                question="async create path",
                user_id=None,
                turn_kind="start",
                metadata={},
            )

            payload = await analysis_api._create_analysis_turn_payload(
                _AsyncOnlyRuntime(),  # type: ignore[arg-type]
                thread_store,
                body,
                conversation_id="thread_async_create",
            )

            self.assertEqual(payload["thread_id"], "thread_async_create")
            self.assertEqual(payload["events"][0]["type"], "turn/completed")
            self.assertEqual(thread_store.get_thread("thread_async_create")["thread"]["codexThreadId"], "codex_thread_async")  # type: ignore[index]

    def test_analysis_thread_turn_stream_api_preserves_codex_thread_for_followup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post(
                "/api/analysis/threads/turns/stream",
                json={"question": "first purchase 30d repurchase"},
            )
            conversation_id = _event_payload_value(first.text, "codex_thread_id")
            genbi_thread_id = _thread_id_from_store(thread_store)
            second = client.post(
                f"/api/analysis/threads/{genbi_thread_id}/turns/stream",
                json={"question": "continue analysis", "turn_kind": "message"},
            )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertIn("event: item/agentMessage/delta", first.text)
            self.assertIn("event: turn/completed", second.text)
            self.assertEqual(runtime.contexts[1]["codex_thread_id"], "codex_thread_created")

    def test_disabled_runtime_fails_explicitly_without_fabricated_content(self) -> None:
        app = create_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
        client = TestClient(app)

        response = client.post("/api/analysis/threads/turns", json={"question": "analyze channel sales"})
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["events"], [event for event in payload["events"] if event["type"] == "turn/completed"])
        self.assertEqual(payload["events"][0]["payload"]["error"], "codex_runtime_not_configured")

    def test_analysis_asset_api_saves_lists_and_reopens_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_store = AnalysisAssetStore(Path(temp_dir) / "analysis-assets.jsonl")
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                analysis_asset_store=asset_store,
            )
            client = TestClient(app)

            save_payload = {
                "assetId": "asset_mock_report",
                "artifactVersionId": "artifact_version_mock_report_v1",
                "sourceTaskId": "analysis_task_codex",
                "sourceTaskTitle": "first purchase repurchase",
                "sourceConversationId": "conv_analysis_abc",
                "sourceCodexThreadId": "codex_thread_abc",
                "sourceCodexTurnId": "codex_turn_abc",
                "sourceCodexItemId": "codex_item_report",
                "assetType": "report",
                "title": "analysis_report.html",
                "label": "report",
                "description": "reusable analysis report",
                "visibility": "team",
                "status": "saved",
                "latestVersion": "v1-draft",
                "fileId": "reports-analysis-report-html",
                "saveReason": "user_confirmed",
                "reopenContext": {
                    "sourceTaskId": "analysis_task_codex",
                    "sourceConversationId": "conv_analysis_abc",
                    "continuationPrompt": "continue from analysis report",
                    "targetFileId": "reports-analysis-report-html",
                    "sourceCodexThreadId": "codex_thread_abc",
                    "sourceCodexTurnId": "codex_turn_abc",
                    "sourceCodexItemId": "codex_item_report",
                },
            }

            saved = client.post("/api/analysis/assets", json=save_payload)
            listed = client.get("/api/analysis/assets", params={"source_task_id": "analysis_task_codex"})
            lineage = client.get("/api/analysis/artifact-lineage", params={"codex_item_id": "codex_item_report"})
            asset_lineage = client.get("/api/analysis/assets/asset_mock_report/lineage")
            reopened = client.post("/api/analysis/assets/asset_mock_report/reopen")

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["asset"]["sourceCodexThreadId"], "codex_thread_abc")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()["assets"]), 1)
            self.assertEqual(lineage.json()["lineage"][0]["assetId"], "asset_mock_report")
            self.assertEqual(asset_lineage.json()["lineage"]["artifactId"], "asset_mock_report")
            self.assertEqual(asset_lineage.json()["lineage"]["artifactVersionId"], "artifact_version_mock_report_v1")
            self.assertEqual(reopened.json()["context"]["sourceCodexItemId"], "codex_item_report")


def _event_payload_value(sse_text: str, key: str) -> object | None:
    for line in sse_text.splitlines():
        if not line.startswith("data:"):
            continue
        event = json.loads(line.removeprefix("data:").strip())
        payload = dict(event.get("payload") or {})
        if key in payload:
            return payload[key]
    return None


def _thread_id_from_store(thread_store: ThreadStore) -> str:
    threads = thread_store.list_threads(product_kind="analysis_task")
    assert threads
    return str(threads[0]["id"])


if __name__ == "__main__":
    unittest.main()
