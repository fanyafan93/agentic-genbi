from __future__ import annotations

import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.analysis.asset_store import AnalysisAssetStore
from backend.analysis.runner_contracts import AnalysisAgentResult
from backend.analysis.report_query_service import CHANNEL_SALES_QUERY_REF, ReportQueryResponse
from backend.analysis.turn_service import AnalysisTurnRequest, AnalysisTurnService
import backend.api.analysis_api as analysis_api
from backend.api.analysis_api import create_app
from backend.harness.thread_store import ThreadStore


class AnalysisApiTest(unittest.TestCase):
    def test_report_query_api_only_accepts_server_owned_query_ref(self) -> None:
        class QueryService:
            def run(self, query_ref: str, filters: dict[str, object], *, audit_context: dict[str, object] | None = None) -> ReportQueryResponse:
                if query_ref != CHANNEL_SALES_QUERY_REF:
                    from backend.analysis.report_query_service import ReportQueryNotFound

                    raise ReportQueryNotFound("report_query_not_found")
                return ReportQueryResponse(
                    queryRef=query_ref,
                    filters={"month": str(filters["month"])},
                    columns=["channel", "salesAmount", "salesShare"],
                    rows=[{"channel": "绾夸笂鑷惀", "salesAmount": 100, "salesShare": 1}],
                    rowCount=1,
                    elapsedMs=12,
                    truncated=False,
                )

        app = create_app(analysis_service=AnalysisTurnService(), report_query_service=QueryService())
        client = TestClient(app)

        response = client.post(
            f"/api/analysis/report-queries/{CHANNEL_SALES_QUERY_REF}",
            json={"filters": {"month": "2026-08", "brand": "all"}},
        )
        missing = client.post("/api/analysis/report-queries/browser-supplied-sql", json={"filters": {"month": "2026-08"}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"][0]["channel"], "绾夸笂鑷惀")
        self.assertEqual(missing.status_code, 404)

    def test_codex_report_draft_becomes_report_item_without_leaking_json_to_message(self) -> None:
        class ReportDraftRunner:
            runtime_name = "openai-codex"

            def run(self, prompt: str) -> AnalysisAgentResult:
                return AnalysisAgentResult(
                    final_output=(
                        "鎴戝凡鏁寸悊鍑轰竴浠藉緟楠岃瘉鐨勬姤鍛婄粨鏋勩€俓n"
                        "<interactive_report_draft>\n"
                        '{"title":"channel sales analysis","subtitle":"pending validation","document":{"root":{"props":{}},"content":[],"zones":{}},'
                        '"filters":[],"queries":{},"chartSpecs":{},"gridSpecs":{}}\n'
                        "</interactive_report_draft>"
                    ),
                    raw_result_type="test",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            events = AnalysisTurnService(agent_runner=ReportDraftRunner(), thread_store=thread_store).run(
                AnalysisTurnRequest(question="analyze channel sales")
            )

            draft = next(event for event in events if event.type == "genbi/artifact/updated" and event.payload.get("artifactType") == "interactive_report")
            message = next(event for event in events if event.type == "item/completed" and event.payload.get("codex_item_type") == "agentMessage")
            thread_id = draft.payload["source"]["threadId"]
            saved = thread_store.get_thread(thread_id)

            self.assertEqual(draft.payload["artifactType"], "interactive_report")
            self.assertEqual(draft.payload["source"]["turnId"], draft.turn_id)
            self.assertNotIn("interactive_report_draft", message.payload["content"])
            self.assertTrue(saved)
            self.assertIn("report", [item["kind"] for item in saved["items"]])

    def test_default_analysis_service_uses_postgres_thread_store_when_enabled(self) -> None:
        with patch.dict("os.environ", {"GENBI_PERSISTENCE": "postgres"}, clear=False):
            with patch.object(analysis_api, "build_postgres_thread_store") as build_thread_store:
                thread_store = ThreadStore(Path("unused-thread-store.jsonl"))
                build_thread_store.return_value = thread_store

                service = analysis_api.build_default_analysis_service()

                self.assertIs(service.thread_store, thread_store)
                build_thread_store.assert_called_once()

    def test_default_analysis_service_uses_codex_runner_when_configured(self) -> None:
        with patch.dict("os.environ", {"GENBI_ANALYSIS_RUNTIME": "codex"}, clear=False):
            with patch.object(analysis_api.CodexSdkAnalysisRunner, "from_env") as from_env:
                runner = object()
                from_env.return_value = runner

                service = analysis_api.build_default_analysis_service()

                self.assertIs(service.agent_runner, runner)
                from_env.assert_called_once()

    def test_analysis_thread_turn_api_returns_backend_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thread_store = ThreadStore(root / "thread-store.jsonl")
            app = create_app(
                analysis_service=AnalysisTurnService(thread_store=thread_store),
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
            self.assertEqual(payload["events_url"], f"/api/analysis/threads/{payload['thread_id']}/turns/{payload['turn_id']}")
            self.assertIn(
                "reports/analysis_report.html",
                [event["payload"]["path"] for event in payload["events"] if event["type"] == "genbi/artifact/created"],
            )

            thread = client.get(f"/api/analysis/threads/{payload['conversation_id']}")
            threads = client.get("/api/analysis/threads")
            turn_detail = client.get(f"/api/analysis/threads/{payload['thread_id']}/turns/{payload['turn_id']}")
            self.assertEqual(thread.status_code, 200)
            self.assertEqual(thread.json()["thread"]["id"], payload["conversation_id"])
            self.assertEqual(thread.json()["turns"][0]["threadId"], payload["conversation_id"])
            self.assertIn("sql", [item["kind"] for item in thread.json()["items"]])
            self.assertEqual(threads.status_code, 200)
            self.assertEqual(threads.json()["threads"][0]["id"], payload["conversation_id"])
            self.assertEqual(turn_detail.status_code, 200)
            self.assertEqual(turn_detail.json()["turn"]["id"], payload["turn_id"])
            self.assertNotIn("executionAttempts", turn_detail.json())

    def test_analysis_thread_turn_create_api_uses_thread_turn_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_service=AnalysisTurnService(thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post(
                "/api/analysis/threads/turns",
                json={"question": "channel sales share"},
            )
            thread_id = first.json()["thread_id"]
            second = client.post(
                f"/api/analysis/threads/{thread_id}/turns",
                json={"question": "continue with growth source", "turn_kind": "message"},
            )

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.json()["conversation_id"], thread_id)
            self.assertEqual(second.json()["thread_id"], thread_id)
            self.assertTrue(first.json()["turn_id"].startswith("analysis_turn_"))
            self.assertTrue(second.json()["turn_id"].startswith("analysis_turn_"))
            self.assertEqual(
                second.json()["events_url"],
                f"/api/analysis/threads/{thread_id}/turns/{second.json()['turn_id']}",
            )

    def test_analysis_stream_api_returns_sse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_service=AnalysisTurnService(thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/threads/turns/stream",
                json={"question": "first purchase 30d repurchase"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("event: turn/started", response.text)
            self.assertIn("event: item/completed", response.text)
            self.assertIn("event: turn/completed", response.text)

    def test_analysis_thread_turn_stream_api_preserves_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_service=AnalysisTurnService(thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post(
                "/api/analysis/threads/turns/stream",
                json={"question": "first purchase 30d repurchase"},
            )
            conversation_id = _event_payload_value(first.text, "conversation_id")
            first_turn_id = _event_payload_value(first.text, "turn_id")
            second = client.post(
                f"/api/analysis/threads/{conversation_id}/turns/stream",
                json={"question": "缁х画鏇存柊鎶ュ憡", "turn_kind": "message"},
            )
            second_turn_id = _event_payload_value(second.text, "turn_id")
            thread = client.get(f"/api/analysis/threads/{conversation_id}")
            first_turn = client.get(f"/api/analysis/threads/{conversation_id}/turns/{first_turn_id}")
            second_turn = client.get(f"/api/analysis/threads/{conversation_id}/turns/{second_turn_id}")

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertIsNotNone(conversation_id)
            self.assertIsNotNone(first_turn_id)
            self.assertIsNotNone(second_turn_id)
            self.assertIn("event: turn/started", first.text)
            self.assertIn("event: turn/completed", second.text)
            self.assertEqual(thread.status_code, 200)
            self.assertEqual(thread.json()["thread"]["id"], conversation_id)
            self.assertEqual(len(thread.json()["turns"]), 2)
            self.assertEqual(thread.json()["turns"][1]["inputKind"], "message")
            self.assertEqual(first_turn.status_code, 200)
            self.assertEqual(second_turn.status_code, 200)
            self.assertEqual(first_turn.json()["turn"]["id"], first_turn_id)
            self.assertEqual(second_turn.json()["turn"]["id"], second_turn_id)
            self.assertNotIn("executionAttempts", second_turn.json())
            self.assertIn("codexItemProjections", second_turn.json())


    def test_analysis_message_turn_preserves_conversation_and_updates_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            thread_store = ThreadStore(root / "thread-store.jsonl")
            app = create_app(
                analysis_service=AnalysisTurnService(thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post(
                "/api/analysis/threads/turns",
                json={"question": "analysis first purchase repurchase"},
            )
            first_payload = first.json()
            conversation_id = first_payload["conversation_id"]

            second = client.post(
                f"/api/analysis/threads/{conversation_id}/turns",
                json={
                    "question": "continue from current asset and update sql report",
                    "turn_kind": "message",
                },
            )
            second_payload = second.json()
            event_types = [event["type"] for event in second_payload["events"]]
            updated_paths = [event["payload"]["path"] for event in second_payload["events"] if event["type"] == "genbi/artifact/updated"]
            created = next(event for event in second_payload["events"] if event["type"] == "turn/started")

            self.assertEqual(second.status_code, 200)
            self.assertEqual(second_payload["conversation_id"], conversation_id)
            self.assertEqual(created["payload"]["conversation_id"], conversation_id)
            self.assertEqual(created["payload"]["turn_kind"], "message")
            self.assertIn("item/completed", event_types)
            self.assertIn("reports/updated_report.html", updated_paths)
            self.assertIn("queries/revised_query.sql", updated_paths)

    def test_analysis_reply_turn_preserves_conversation_and_updates_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_service=AnalysisTurnService(thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post(
                "/api/analysis/threads/turns",
                json={"question": "define repurchase metric"},
            )
            first_payload = first.json()
            conversation_id = first_payload["conversation_id"]

            reply = client.post(
                f"/api/analysis/threads/{conversation_id}/turns",
                json={
                    "question": "member_id",
                    "turn_kind": "reply",
                },
            )
            payload = reply.json()
            created = next(event for event in payload["events"] if event["type"] == "turn/started")
            updated_paths = [event["payload"]["path"] for event in payload["events"] if event["type"] == "genbi/artifact/updated"]
            ask_events = [event for event in payload["events"] if event["type"] == "item/completed" and event["payload"].get("codex_item_type") == "agentQuestion"]

            self.assertEqual(reply.status_code, 200)
            self.assertEqual(payload["conversation_id"], conversation_id)
            self.assertEqual(created["payload"]["conversation_id"], conversation_id)
            self.assertEqual(created["payload"]["turn_kind"], "reply")
            self.assertIn("reports/updated_report.html", updated_paths)
            self.assertIn("queries/revised_query.sql", updated_paths)
            self.assertEqual(ask_events, [])

    def test_analysis_asset_api_saves_lists_and_reopens_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_store = AnalysisAssetStore(Path(temp_dir) / "analysis-assets.jsonl")
            app = create_app(
                analysis_service=AnalysisTurnService(),
                analysis_asset_store=asset_store,
            )
            client = TestClient(app)

            save_payload = {
                "assetId": "asset_mock_report",
                "artifactVersionId": "artifact_version_mock_report_v1",
                "sourceTaskId": "analysis_task_run_analysis_abc",
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
                    "sourceTaskId": "analysis_task_run_analysis_abc",
                    "sourceConversationId": "conv_analysis_abc",
                    "continuationPrompt": "continue from analysis report",
                    "targetFileId": "reports-analysis-report-html",
                    "sourceCodexThreadId": "codex_thread_abc",
                    "sourceCodexTurnId": "codex_turn_abc",
                    "sourceCodexItemId": "codex_item_report",
                },
            }

            saved = client.post("/api/analysis/assets", json=save_payload)
            listed = client.get("/api/analysis/assets", params={"source_task_id": "analysis_task_run_analysis_abc"})
            lineage = client.get("/api/analysis/artifact-lineage", params={"codex_item_id": "codex_item_report"})
            asset_lineage = client.get("/api/analysis/assets/asset_mock_report/lineage")
            reopened = client.post("/api/analysis/assets/asset_mock_report/reopen")

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["asset"]["assetId"], "asset_mock_report")
            self.assertEqual(saved.json()["asset"]["sourceCodexThreadId"], "codex_thread_abc")
            self.assertEqual(saved.json()["asset"]["sourceCodexTurnId"], "codex_turn_abc")
            self.assertEqual(saved.json()["asset"]["sourceCodexItemId"], "codex_item_report")
            self.assertEqual(saved.json()["asset"]["metadata"]["saveReason"], "user_confirmed")
            self.assertEqual(saved.json()["asset"]["metadata"]["codex_lineage"]["codexItemId"], "codex_item_report")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()["assets"]), 1)
            self.assertEqual(listed.json()["assets"][0]["sourceConversationId"], "conv_analysis_abc")
            self.assertEqual(listed.json()["assets"][0]["sourceCodexItemId"], "codex_item_report")
            self.assertEqual(lineage.status_code, 200)
            self.assertEqual(lineage.json()["lineage"][0]["assetId"], "asset_mock_report")
            self.assertEqual(lineage.json()["lineage"][0]["codexItemId"], "codex_item_report")
            self.assertEqual(asset_lineage.status_code, 200)
            self.assertEqual(asset_lineage.json()["lineage"]["artifactId"], "asset_mock_report")
            self.assertEqual(asset_lineage.json()["lineage"]["artifactVersionId"], "artifact_version_mock_report_v1")
            self.assertEqual(asset_lineage.json()["lineage"]["codexThreadId"], "codex_thread_abc")
            self.assertEqual(reopened.status_code, 200)
            self.assertEqual(reopened.json()["context"]["targetFileId"], "reports-analysis-report-html")
            self.assertEqual(reopened.json()["context"]["sourceCodexItemId"], "codex_item_report")
            self.assertEqual(reopened.json()["artifactVersionId"], "artifact_version_mock_report_v1")

    def test_analysis_asset_api_accepts_codex_lineage_without_run_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_store = AnalysisAssetStore(Path(temp_dir) / "analysis-assets.jsonl")
            app = create_app(
                analysis_service=AnalysisTurnService(),
                analysis_asset_store=asset_store,
            )
            client = TestClient(app)

            save_payload = {
                "assetId": "asset_codex_lineage_report",
                "artifactVersionId": "artifact_version_codex_lineage_report_v1",
                "sourceTaskId": "analysis_task_codex",
                "sourceTaskTitle": "codex lineage first",
                "sourceConversationId": "conv_analysis_codex",
                "sourceCodexThreadId": "codex_thread_lineage",
                "sourceCodexTurnId": "codex_turn_lineage",
                "sourceCodexItemId": "codex_item_lineage",
                "assetType": "report",
                "title": "analysis_report.html",
                "visibility": "team",
                "reopenContext": {
                    "sourceTaskId": "analysis_task_codex",
                    "sourceConversationId": "conv_analysis_codex",
                    "sourceCodexThreadId": "codex_thread_lineage",
                    "sourceCodexTurnId": "codex_turn_lineage",
                    "sourceCodexItemId": "codex_item_lineage",
                    "continuationPrompt": "continue from analysis report",
                },
            }

            saved = client.post("/api/analysis/assets", json=save_payload)

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["asset"]["sourceCodexThreadId"], "codex_thread_lineage")
            self.assertEqual(saved.json()["asset"]["sourceCodexTurnId"], "codex_turn_lineage")
            self.assertEqual(saved.json()["asset"]["sourceCodexItemId"], "codex_item_lineage")


def _event_payload_value(sse_text: str, key: str) -> object | None:
    for line in sse_text.splitlines():
        if not line.startswith("data:"):
            continue
        event = json.loads(line.removeprefix("data:").strip())
        payload = dict(event.get("payload") or {})
        if key in payload:
            return payload[key]
    return None


if __name__ == "__main__":
    unittest.main()

