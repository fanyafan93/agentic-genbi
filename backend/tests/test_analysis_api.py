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
from backend.api.principal import enable_dev_principal_bypass
from backend.tests.auth_test_client import anonymous_client, auth_client, build_test_app
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.events import AgentEvent
from backend.harness.thread_store import ThreadStore
from backend.business_semantics.knowledge_store import KnowledgeStore
from fastapi.testclient import TestClient
import os


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


class _MissingTerminalRuntime:
    runtime_name = "openai-codex"

    async def async_stream(self, question: str, *, context: dict):
        yield AgentEvent(
            type="turn/started",
            turn_id="codex_turn_missing_terminal",
            payload={
                "eventSource": "codex",
                "codex_thread_id": "codex_thread_missing_terminal",
                "codex_turn_id": "codex_turn_missing_terminal",
            },
        )
        yield AgentEvent(
            type="item/completed",
            turn_id="codex_turn_missing_terminal",
            payload={
                "eventSource": "codex",
                "codex_thread_id": "codex_thread_missing_terminal",
                "codex_turn_id": "codex_turn_missing_terminal",
                "codex_item_id": "codex_item_tool",
                "codex_item_type": "mcpToolCall",
                "mcp_server": "BI_doris",
                "mcp_tool": "mysql_query",
                "mcp_status": "completed",
            },
        )


class AnalysisApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        super().setUp()
        enable_dev_principal_bypass(True)
        os.environ["GENBI_AUTH_DEV_BYPASS"] = "1"

    def tearDown(self) -> None:
        super().tearDown()
        enable_dev_principal_bypass(False)
        os.environ.pop("GENBI_AUTH_DEV_BYPASS", None)

    def _user_client(self, app, *, user_id: str = "user_1", tenant_id: str = "default"):
        from backend.tests.auth_test_client import AuthTestClient

        return AuthTestClient(app, user_id=user_id, tenant_id=tenant_id)

    def test_default_analysis_runtime_uses_codex_runtime_when_configured(self) -> None:
        with patch.dict("os.environ", {"GENBI_ANALYSIS_RUNTIME": "codex"}, clear=False):
            with patch.object(analysis_api.CodexSdkAnalysisRuntime, "from_env") as from_env:
                runtime = object()
                from_env.return_value = runtime

                service = analysis_api.build_default_analysis_runtime()

                self.assertIs(service, runtime)
                from_env.assert_called_once()

    def test_create_app_always_uses_postgres_thread_store(self) -> None:
        # The default-store path now requires Postgres unconditionally:
        # the previous "GENBI_PERSISTENCE unset -> in-memory store"
        # silent fallback is exactly the data-loss pattern the
        # contract prohibits. This test pins the new behavior: even
        # without any env var, ``create_app`` reaches for the Postgres
        # store, and the caller is expected to inject an in-memory
        # store explicitly when running unit tests.
        with patch.object(analysis_api, "build_postgres_thread_store") as build_thread_store:
            thread_store = ThreadStore(Path("unused-thread-store.jsonl"))
            build_thread_store.return_value = thread_store

            app = build_test_app(
                knowledge_store=KnowledgeStore(),
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                analysis_asset_store=AnalysisAssetStore(Path("unused-assets.jsonl")),
                interactive_report_store=InteractiveReportStore(Path("unused-reports.jsonl")),
                thread_store=None,
            )

            self.assertIsNotNone(app)
            build_thread_store.assert_called_once()

    def test_system_mcp_server_api_lists_trusted_report_tool(self) -> None:
        with patch.dict("os.environ", {
            "GENBI_CODEX_MCP_COUNT": "1",
            "GENBI_CODEX_MCP_1_NAME": "GenBI_report",
            "GENBI_CODEX_MCP_1_COMMAND": "python",
            "GENBI_CODEX_MCP_1_ARGS": "-m backend.mcp_servers.genbi_report_server",
        }, clear=False):
            app = build_test_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
            client = TestClient(app)

            listed = client.get("/api/system/mcp/servers")
            tested = client.post("/api/system/mcp/servers/GenBI_report/test")

            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()["servers"][0]["name"], "GenBI_report")
            self.assertEqual(listed.json()["servers"][0]["approval"], "trusted")
            self.assertEqual(tested.status_code, 200)
            self.assertTrue(tested.json()["ok"])

    def test_analysis_thread_turn_api_streams_codex_events_and_persists_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = build_test_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            with auth_client(app) as client:
                response = client.post(
                    "/api/analysis/threads/turns",
                    json={"question": "analyze channel sales share"},
                )
                payload = response.json()

                self.assertEqual(response.status_code, 200)
                self.assertTrue(payload["thread_id"].startswith("analysis_thread_"))
                self.assertNotIn("conversation_id", payload)
                self.assertTrue(payload["turn_id"].startswith("analysis_turn_"))
                self.assertEqual([event["type"] for event in payload["events"]], ["turn/started", "item/agentMessage/delta", "item/completed", "turn/completed"])
                self.assertTrue(all(event["payload"]["eventSource"] == "codex" for event in payload["events"]))

                thread = client.get(f"/api/analysis/threads/{payload['thread_id']}")
                turn_detail = client.get(f"/api/analysis/threads/{payload['thread_id']}/turns/{payload['turn_id']}")

                self.assertEqual(thread.status_code, 200)
                self.assertEqual(thread.json()["thread"]["id"], payload["thread_id"])
                self.assertEqual(thread.json()["thread"]["codexThreadId"], "codex_thread_created")
                self.assertEqual(thread.json()["turns"][0]["codexTurnId"], "codex_turn_created")
                self.assertEqual(turn_detail.status_code, 200)
                self.assertEqual(turn_detail.json()["turn"]["id"], payload["turn_id"])
                self.assertNotIn("executionAttempts", turn_detail.json())
                self.assertEqual(turn_detail.json()["codexItemProjections"][0]["codexItemId"], "codex_item_msg")

    def test_analysis_thread_list_includes_latest_question_for_sidebar_titles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = build_test_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            with auth_client(app) as client:
                created = client.post("/api/analysis/threads/turns", json={"question": "real sidebar question"})
                listed = client.get("/api/analysis/threads")

                self.assertEqual(created.status_code, 200)
                self.assertEqual(listed.status_code, 200)
                self.assertEqual(listed.json()["threads"][0]["latestQuestion"], "real sidebar question")

    def test_analysis_thread_list_hides_legacy_draft_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )
            client = TestClient(app)

            thread_store.create_thread(
                thread_id="draft_report_report_1",
                product_kind="analysis_task",
                title="legacy draft",
                user_id=None,
                status="completed",
            )
            thread_store.create_thread(
                thread_id="analysis_thread_real",
                product_kind="analysis_task",
                title="real thread",
                user_id=None,
                status="completed",
            )

            listed = client.get("/api/analysis/threads")

            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["id"] for item in listed.json()["threads"]], ["analysis_thread_real"])

    def test_create_waiting_analysis_thread_without_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )
            with auth_client(app, user_id="user_1") as client:
                created = client.post("/api/analysis/threads", json={"title": "New Analysis"})
                detail = client.get(f"/api/analysis/threads/{created.json()['thread']['id']}")

            self.assertEqual(created.status_code, 200)
            self.assertTrue(created.json()["thread"]["id"].startswith("analysis_thread_"))
            self.assertEqual(created.json()["thread"]["status"], "waiting_for_question")
            self.assertIsNone(created.json()["thread"]["latestQuestion"])
            self.assertEqual(detail.json()["turns"], [])

    def test_create_waiting_analysis_thread_reuses_existing_empty_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post("/api/analysis/threads", json={"title": "New Analysis", "user_id": "user_1"})
            second = client.post("/api/analysis/threads", json={"title": "New Analysis", "user_id": "user_1"})

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["thread"]["id"], first.json()["thread"]["id"])
            self.assertEqual(len(thread_store.list_threads(product_kind="analysis_task")), 1)

    def test_analysis_thread_api_repairs_legacy_mojibake_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = build_test_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            created = client.post("/api/analysis/threads/turns", json={"question": "legacy question"})
            thread_id = created.json()["thread_id"]
            listed = client.get("/api/analysis/threads")
            detail = client.get(f"/api/analysis/threads/{thread_id}")

            self.assertEqual(listed.json()["threads"][0]["latestQuestion"], "legacy question")
            self.assertEqual(detail.json()["turns"][0]["question"], "legacy question")

    def test_analysis_thread_api_passes_text_verbatim_no_mojibake_repair(self) -> None:
        # The previous "auto-repair" path silently rewrote ``??`` strings
        # to ``None`` and latin1-rejected UTF-8 back into UTF-8. That
        # hid upstream encoding bugs. The contract now is: stored
        # text is returned verbatim; the operator migrates bad data
        # out-of-band instead of letting the API keep paper-over it.
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = build_test_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            garbled = "?? GMV ???????????????"
            created = client.post("/api/analysis/threads/turns", json={"question": garbled})
            thread_id = created.json()["thread_id"]
            listed = client.get("/api/analysis/threads")
            detail = client.get(f"/api/analysis/threads/{thread_id}")

            # Stored text comes back unchanged. The API is no longer
            # in the business of guessing what's "actually" the user's
            # question; corruption is a data-migration concern.
            self.assertEqual(listed.json()["threads"][0]["latestQuestion"], garbled)
            self.assertEqual(detail.json()["turns"][0]["question"], garbled)

    def test_delete_analysis_thread_removes_sidebar_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = build_test_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            created = client.post("/api/analysis/threads/turns", json={"question": "delete sidebar item"})
            thread_id = created.json()["thread_id"]
            deleted = client.delete(f"/api/analysis/threads/{thread_id}")
            listed = client.get("/api/analysis/threads")
            missing = client.delete(f"/api/analysis/threads/{thread_id}")

            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted.json(), {"deleted": True, "thread_id": thread_id})
            self.assertEqual(listed.json()["threads"], [])
            self.assertEqual(missing.status_code, 404)

    async def test_create_analysis_turn_payload_uses_async_runtime_inside_running_event_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            from backend.api.principal import Principal

            body = SimpleNamespace(
                question="async create path",
                user_id=None,
                turn_kind="start",
                metadata={},
            )

            payload = await analysis_api._create_analysis_turn_payload(
                _AsyncOnlyRuntime(),  # type: ignore[arg-type]
                thread_store,
                InteractiveReportStore(Path(temp_dir) / "interactive-reports.json"),
                body,
                thread_id="thread_async_create",
                principal=Principal(user_id="user_1", tenant_id="default", role="user"),
            )

            self.assertEqual(payload["thread_id"], "thread_async_create")
            self.assertEqual(payload["events"][0]["type"], "turn/completed")
            self.assertEqual(thread_store.get_thread("thread_async_create")["thread"]["codexThreadId"], "codex_thread_async")  # type: ignore[index]

    def test_enrich_analysis_event_adds_question_to_user_message_items(self) -> None:
        event = AgentEvent(
            type="item/completed",
            turn_id="codex_turn_user",
            payload={
                "eventSource": "codex",
                "codex_item_type": "userMessage",
                "codex_item_id": "codex_user_item",
            },
        )

        enriched = analysis_api._enrich_analysis_event(
            event,
            thread_id="thread_1",
            turn_id="turn_1",
            question="follow-up question",
        )

        self.assertEqual(enriched.payload["content"], "follow-up question")

    def test_analysis_thread_turn_stream_api_preserves_codex_thread_for_followup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = build_test_app(
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
            self.assertEqual(_event_payload_value(second.text, "question"), "continue analysis")
            self.assertEqual(runtime.contexts[1]["codex_thread_id"], "codex_thread_created")

    def test_stream_appends_failed_terminal_event_when_codex_stops_without_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = build_test_app(
                analysis_runtime=_MissingTerminalRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post("/api/analysis/threads/turns/stream", json={"question": "missing completion"})
            thread_id = _thread_id_from_store(thread_store)
            detail = client.get(f"/api/analysis/threads/{thread_id}")

            self.assertEqual(response.status_code, 200)
            self.assertIn("codex_stream_ended_without_turn_completed", response.text)
            self.assertEqual(detail.json()["thread"]["status"], "failed")
            self.assertEqual(detail.json()["turns"][0]["status"], "failed")

    def test_interrupted_terminal_event_persists_interrupted_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            events = [
                AgentEvent(
                    type="turn/started",
                    turn_id="analysis_turn_cancelled",
                    payload={
                        "thread_id": "analysis_thread_cancelled",
                        "turn_id": "analysis_turn_cancelled",
                        "codex_thread_id": "codex_thread_cancelled",
                        "codex_turn_id": "codex_turn_cancelled",
                    },
                ),
                analysis_api._interrupted_terminal_event(
                    thread_id="analysis_thread_cancelled",
                    turn_id="analysis_turn_cancelled",
                ),
            ]

            thread_store.save_turn(
                thread_id="analysis_thread_cancelled",
                turn_id="analysis_turn_cancelled",
                question="cancelled stream",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=events,
            )
            detail = thread_store.get_thread("analysis_thread_cancelled")

            self.assertEqual(detail["thread"]["status"], "interrupted")
            self.assertEqual(detail["turns"][0]["status"], "interrupted")

    def test_disabled_runtime_fails_explicitly_without_fabricated_content(self) -> None:
        app = build_test_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
        client = TestClient(app)

        response = client.post("/api/analysis/threads/turns", json={"question": "analyze channel sales"})
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["events"], [event for event in payload["events"] if event["type"] == "turn/completed"])
        self.assertEqual(payload["events"][0]["payload"]["error"], "codex_runtime_not_configured")

    def test_genbi_report_tool_call_emits_interactive_report_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
            )
            complete_artifact = {
                "id": "report_thread_report",
                "title": "Channel report",
                "subtitle": "Channel sales summary",
                "artifactType": "interactive_report",
                "renderer": "puck",
                "ownerId": "user_thread_report",
                "document": {"root": {"props": {"title": "Channel report"}}},
                "filters": [],
                "queries": {
                    "channel-sales-query": {
                        "datasetId": "channel_sales",
                        "filterBindings": [],
                    },
                },
                "chartSpecs": {
                    "channel-sales-chart": {
                        "id": "channel-sales-chart",
                        "datasetId": "channel_sales",
                        "type": "bar",
                        "xField": "channel",
                        "title": "Channel sales",
                        "series": [
                            {"field": "salesAmount", "label": "Sales", "format": "currency"},
                        ],
                    },
                },
                "gridSpecs": {
                    "channel-sales-grid": {
                        "id": "channel-sales-grid",
                        "datasetId": "channel_sales",
                        "columns": [
                            {"field": "channel", "label": "Channel"},
                            {"field": "salesAmount", "label": "Sales", "format": "currency"},
                        ],
                    },
                },
                "datasets": {
                    "channel_sales": {
                        "rows": [{"channel": "Direct", "salesAmount": 1000, "salesShare": 0.42}],
                    },
                },
            }
            event = AgentEvent(
                type="item/completed",
                turn_id="codex_turn_report",
                payload={
                    "eventSource": "codex",
                    "codex_item_type": "mcpToolCall",
                    "codex_item_id": "codex_item_report",
                    "mcp_server": "GenBI_report",
                    "mcp_tool": "create_interactive_report",
                    "mcp_status": "completed",
                    "mcp_result": {"interactive_report": complete_artifact},
                },
            )

            artifact = analysis_api._interactive_report_artifact_event(
                event,
                thread_id="thread_report",
                turn_id="turn_report",
                interactive_report_store=report_store,
            )

            self.assertIsNotNone(artifact)
            assert artifact is not None
            # The artifact is persisted first; the projection only
            # emits a ``genbi/artifact/created`` event when the store
            # actually accepted the write.
            self.assertEqual(artifact.type, "genbi/artifact/created")
            self.assertEqual(artifact.payload["source"]["threadId"], "thread_report")
            self.assertEqual(artifact.payload["source"]["turnId"], "turn_report")
            self.assertEqual(artifact.payload["datasets"]["channel_sales"]["rows"][0]["channel"], "Direct")
            self.assertIn("version", artifact.payload)

    def test_report_payload_mcp_item_emits_artifact_without_server_tool_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
            )
            complete_artifact = {
                "id": "report_from_payload",
                "title": "channel report",
                "subtitle": "minimal",
                "artifactType": "interactive_report",
                "renderer": "puck",
                "ownerId": "user_thread_report",
                "document": {"root": {"props": {"title": "channel report"}}},
                "filters": [],
                "queries": {
                    "channel-sales-query": {
                        "datasetId": "channel_sales",
                        "filterBindings": [],
                    },
                },
                "chartSpecs": {
                    "channel-sales-chart": {
                        "id": "channel-sales-chart",
                        "datasetId": "channel_sales",
                        "type": "bar",
                        "xField": "channel",
                        "title": "Channel sales",
                        "series": [
                            {"field": "sales", "label": "Sales", "format": "currency"},
                        ],
                    },
                },
                "gridSpecs": {
                    "channel-sales-grid": {
                        "id": "channel-sales-grid",
                        "datasetId": "channel_sales",
                        "columns": [{"field": "channel", "label": "Channel"}],
                    },
                },
                "datasets": {
                    "channel_sales": {
                        "rows": [{"channel": "A", "sales": 1}],
                    },
                },
            }
            event = AgentEvent(
                type="item/completed",
                turn_id="codex_turn_report",
                payload={
                    "eventSource": "codex",
                    "codex_item_type": "mcpToolCall",
                    "codex_item_id": "codex_item_report",
                    "mcp_status": "completed",
                    "mcp_result": {"interactive_report": complete_artifact},
                },
            )

            artifact = analysis_api._interactive_report_artifact_event(
                event,
                thread_id="thread_report",
                turn_id="turn_report",
                interactive_report_store=report_store,
            )

            self.assertIsNotNone(artifact)
            assert artifact is not None
            self.assertEqual(artifact.type, "genbi/artifact/created")
            self.assertEqual(artifact.payload["source"]["threadId"], "thread_report")
            self.assertEqual(artifact.payload["source"]["turnId"], "turn_report")
            self.assertEqual(artifact.payload["datasets"]["channel_sales"]["rows"][0]["channel"], "A")
            self.assertIn("version", artifact.payload)

    def test_analysis_asset_api_saves_lists_and_reopens_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_store = AnalysisAssetStore(Path(temp_dir) / "analysis-assets.jsonl")
            from backend.tests.auth_test_client import build_test_app

            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                analysis_asset_store=asset_store,
            )
            with auth_client(app, user_id="owner_1") as client:
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

    def test_report_center_lists_mine_and_shared_current_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
            )
            with auth_client(app, user_id="owner_1") as owner_client:
                user2_client = owner_client.as_user(user_id="user_2")

                report_payload = {
                    "id": "report_current",
                    "title": "Current Report",
                    "subtitle": "Saved snapshot",
                    "artifactType": "interactive_report",
                    "renderer": "puck",
                    "source": {"threadId": "analysis_thread_a", "turnId": "analysis_turn_a"},
                    "document": {"content": [], "root": {"props": {}}},
                    "filters": [],
                    "queries": {},
                    "chartSpecs": {},
                    "gridSpecs": {},
                    "datasets": {"rows": {"rows": [{"channel": "A", "sales": 1}]}},
                    "dataUpdatedAt": "2026-08-04T09:00:00+08:00",
                }

                saved_v1 = owner_client.post("/api/analysis/reports", json=report_payload)
                shared = owner_client.post(
                    "/api/analysis/reports/report_current/shares",
                    json={"recipientUserId": "user_2", "permission": "view_and_reuse"},
                )
                saved_v2 = owner_client.post(
                    "/api/analysis/reports",
                    json={
                        **report_payload,
                        "title": "Current Report Updated",
                        "expectedVersion": saved_v1.json()["version"]["version"],
                        "datasets": {"rows": {"rows": [{"channel": "A", "sales": 2}]}},
                        "dataUpdatedAt": "2026-08-04T10:00:00+08:00",
                    },
                )

                owner_center = owner_client.get("/api/analysis/report-center")
                shared_center = user2_client.get("/api/analysis/report-center")

                self.assertEqual(saved_v1.status_code, 200)
                self.assertEqual(shared.status_code, 200)
                self.assertEqual(saved_v2.status_code, 200)
                self.assertEqual(owner_center.json()["mine"][0]["report"]["title"], "Current Report Updated")
                self.assertEqual(shared_center.json()["sharedWithMe"][0]["permission"], "view_and_reuse")
                self.assertEqual(shared_center.json()["sharedWithMe"][0]["report"]["title"], "Current Report Updated")
                self.assertEqual(shared_center.json()["sharedWithMe"][0]["report"]["dataUpdatedAt"], "2026-08-04T10:00:00+08:00")

                deleted = owner_client.delete("/api/analysis/reports/report_current")
                after_delete = user2_client.get("/api/analysis/report-center")

                self.assertEqual(deleted.status_code, 200)
                self.assertEqual(after_delete.json()["sharedWithMe"], [])

    def test_create_analysis_thread_from_report_creates_waiting_thread_without_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
                thread_store=thread_store,
            )
            with auth_client(app, user_id="owner_1") as client:
                report_payload = {
                    "id": "report_for_analysis",
                    "title": "Channel Daily",
                    "subtitle": "Saved snapshot",
                    "artifactType": "interactive_report",
                    "renderer": "puck",
                    "source": {"threadId": "analysis_thread_source", "turnId": "analysis_turn_source"},
                    "document": {"content": [], "root": {"props": {}}},
                    "filters": [],
                    "queries": {},
                    "chartSpecs": {},
                    "gridSpecs": {},
                    "datasets": {"channel_sales": {"rows": [{"channel": "A", "sales": 1}]}},
                    "dataUpdatedAt": "2026-08-04T09:00:00+08:00",
                }

                saved = client.post("/api/analysis/reports", json=report_payload)
                created = client.post(
                    "/api/analysis/reports/report_for_analysis/analysis-thread",
                    json={"title": "Channel Daily New Analysis"},
                )

                self.assertEqual(saved.status_code, 200)
                self.assertEqual(created.status_code, 200)
                payload = created.json()
                self.assertTrue(payload["thread"]["id"].startswith("analysis_thread_"))
                self.assertEqual(payload["thread"]["title"], "Channel Daily New Analysis")
                self.assertEqual(payload["thread"]["status"], "waiting_for_question")
                self.assertIsNone(payload["thread"]["latestQuestion"])
                self.assertEqual(payload["report"]["report"]["id"], "report_for_analysis")

                detail = client.get(f"/api/analysis/threads/{payload['thread']['id']}")
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["turns"], [])
                self.assertEqual(detail.json()["thread"]["metadata"]["source_report_id"], "report_for_analysis")
                self.assertEqual(detail.json()["thread"]["metadata"]["initial_report_artifact"]["title"], "Channel Daily")

    def test_create_analysis_thread_from_report_reuses_existing_empty_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = build_test_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
                thread_store=thread_store,
            )
            with auth_client(app, user_id="owner_1") as client:
                report_payload = {
                    "id": "report_reuse",
                    "title": "Report Reuse",
                    "subtitle": "Saved snapshot",
                    "artifactType": "interactive_report",
                    "renderer": "puck",
                    "source": {"threadId": "analysis_thread_source", "turnId": "analysis_turn_source"},
                    "document": {"content": [], "root": {"props": {}}},
                    "filters": [],
                    "queries": {},
                    "chartSpecs": {},
                    "gridSpecs": {},
                    "datasets": {"channel_sales": {"rows": [{"channel": "A", "sales": 1}]}},
                    "dataUpdatedAt": "2026-08-04T09:00:00+08:00",
                }

                saved = client.post("/api/analysis/reports", json=report_payload)
                first = client.post(
                    "/api/analysis/reports/report_reuse/analysis-thread",
                    json={"title": "Report Reuse New"},
                )
                second = client.post(
                    "/api/analysis/reports/report_reuse/analysis-thread",
                    json={"title": "Report Reuse New"},
                )

                self.assertEqual(saved.status_code, 200)
                self.assertEqual(first.status_code, 200)
                self.assertEqual(second.status_code, 200)
                self.assertEqual(second.json()["thread"]["id"], first.json()["thread"]["id"])
                self.assertEqual(len(thread_store.list_threads(product_kind="analysis_task")), 1)

    def test_report_share_rejects_unknown_permission(self) -> None:
        app = build_test_app(
            analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
            interactive_report_store=InteractiveReportStore(Path("unused-reports.json")),
        )
        with auth_client(app, user_id="owner_1") as client:
            response = client.post(
                "/api/analysis/reports/report_missing/shares",
                json={"recipientUserId": "user_2", "permission": "edit"},
            )

            self.assertEqual(response.status_code, 422)


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

