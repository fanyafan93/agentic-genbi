from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.analysis.asset_store import AnalysisAssetStore
from backend.analysis.runner_contracts import AnalysisAgentRunResult
from backend.analysis.report_query_service import CHANNEL_SALES_QUERY_REF, ReportQueryResponse
from backend.analysis.run_service import AnalysisRunService
import backend.api.exploration_api as exploration_api
from backend.api.exploration_api import create_app
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_service import ExplorationRunService
from backend.exploration.run_trace_store import RunTraceStore
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
                    rows=[{"channel": "线上自营", "salesAmount": 100, "salesShare": 1}],
                    rowCount=1,
                    elapsedMs=12,
                    truncated=False,
                )

        app = create_app(ExplorationRunService(), analysis_service=AnalysisRunService(), report_query_service=QueryService())
        client = TestClient(app)

        response = client.post(
            f"/api/analysis/report-queries/{CHANNEL_SALES_QUERY_REF}",
            json={"filters": {"month": "2026-08", "brand": "all"}},
        )
        missing = client.post("/api/analysis/report-queries/browser-supplied-sql", json={"filters": {"month": "2026-08"}})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["rows"][0]["channel"], "线上自营")
        self.assertEqual(missing.status_code, 404)

    def test_codex_report_draft_becomes_report_item_without_leaking_json_to_message(self) -> None:
        class ReportDraftRunner:
            runtime_name = "openai-codex"

            def run(self, prompt: str) -> AnalysisAgentRunResult:
                return AnalysisAgentRunResult(
                    final_output=(
                        "我已整理出一份待验证的报告结构。\n"
                        "<interactive_report_draft>\n"
                        '{"title":"渠道销售分析","subtitle":"待数据查询验证","document":{"root":{"props":{}},"content":[],"zones":{}},'
                        '"filters":[],"queries":{},"chartSpecs":{},"gridSpecs":{}}\n'
                        "</interactive_report_draft>"
                    ),
                    raw_result_type="test",
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            events = AnalysisRunService(agent_runner=ReportDraftRunner(), thread_store=thread_store).run(
                __import__("backend.analysis.run_service", fromlist=["AnalysisRunRequest"]).AnalysisRunRequest(
                    question="分析渠道销售结构",
                    analysis_mode="quick",
                )
            )

            draft = next(event for event in events if event.type == "interactive_report.draft")
            message = next(event for event in events if event.type == "agent.message.created")
            thread_id = draft.payload["source"]["threadId"]
            saved = thread_store.get_thread(thread_id)

            self.assertEqual(draft.payload["artifactType"], "interactive_report")
            self.assertEqual(draft.payload["source"]["runId"], draft.run_id)
            self.assertNotIn("interactive_report_draft", message.payload["content"])
            self.assertTrue(saved)
            self.assertIn("report", [item["kind"] for item in saved["items"]])

    def test_default_analysis_service_uses_postgres_thread_store_when_enabled(self) -> None:
        with patch.dict("os.environ", {"GENBI_PERSISTENCE": "postgres"}, clear=False):
            with patch.object(exploration_api, "build_postgres_thread_store") as build_thread_store:
                thread_store = ThreadStore(Path("unused-thread-store.jsonl"))
                build_thread_store.return_value = thread_store

                service = exploration_api.build_default_analysis_service(ExplorationRunService())

                self.assertIs(service.thread_store, thread_store)
                build_thread_store.assert_called_once()

    def test_default_analysis_service_uses_codex_runner_when_configured(self) -> None:
        with patch.dict("os.environ", {"GENBI_ANALYSIS_RUNTIME": "codex"}, clear=False):
            with patch.object(exploration_api.CodexSdkAnalysisRunner, "from_env") as from_env:
                runner = object()
                from_env.return_value = runner

                service = exploration_api.build_default_analysis_service(ExplorationRunService())

                self.assertIs(service.agent_runner, runner)
                from_env.assert_called_once()

    def test_analysis_run_api_returns_backend_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trace_store = RunTraceStore(root / "traces.jsonl")
            event_store = RunEventStore(root / "events.jsonl")
            thread_store = ThreadStore(root / "thread-store.jsonl")
            app = create_app(
                ExplorationRunService(trace_store=trace_store, event_store=event_store),
                analysis_service=AnalysisRunService(trace_store=trace_store, event_store=event_store, thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/tasks/runs",
                json={"question": "分析一下渠道销售占比", "analysis_mode": "quick"},
            )
            payload = response.json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["conversation_id"].startswith("conv_analysis_"))
            self.assertTrue(payload["latest_run_id"].startswith("run_analysis_"))
            self.assertEqual(payload["events_url"], f"/api/analysis/tasks/runs/{payload['latest_run_id']}/events")
            self.assertIn("analysis.problem.classified", [event["type"] for event in payload["events"]])
            self.assertIn(
                "reports/quick_report.html",
                [event["payload"]["path"] for event in payload["events"] if event["type"] == "artifact.created"],
            )

            thread = client.get(f"/api/analysis/threads/{payload['conversation_id']}")
            threads = client.get("/api/analysis/threads")
            run_detail = client.get(f"/api/analysis/tasks/runs/{payload['run_id']}")
            self.assertEqual(thread.status_code, 200)
            self.assertEqual(thread.json()["thread"]["id"], payload["conversation_id"])
            self.assertEqual(thread.json()["turns"][0]["threadId"], payload["conversation_id"])
            self.assertIn("sql", [item["kind"] for item in thread.json()["items"]])
            self.assertEqual(threads.status_code, 200)
            self.assertEqual(threads.json()["threads"][0]["id"], payload["conversation_id"])
            self.assertEqual(run_detail.status_code, 200)
            self.assertIsNone(run_detail.json()["run"])
            self.assertEqual(run_detail.json()["systemRun"]["run"]["id"], payload["run_id"])
            self.assertIn("artifact.created", [event["type"] for event in run_detail.json()["events"]])

    def test_analysis_stream_api_returns_sse(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                ExplorationRunService(),
                analysis_service=AnalysisRunService(thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/tasks/runs/stream",
                json={"question": "首购后 30 天复购率怎么算", "analysis_mode": "deep"},
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("event: run.created", response.text)
            self.assertIn("event: agent.question.requested", response.text)
            self.assertIn("首购和复购按会员 ID", response.text)


    def test_analysis_message_turn_preserves_conversation_and_updates_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trace_store = RunTraceStore(root / "traces.jsonl")
            event_store = RunEventStore(root / "events.jsonl")
            thread_store = ThreadStore(root / "thread-store.jsonl")
            app = create_app(
                ExplorationRunService(trace_store=trace_store, event_store=event_store),
                analysis_service=AnalysisRunService(trace_store=trace_store, event_store=event_store, thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post(
                "/api/analysis/tasks/runs",
                json={"question": "analysis first purchase repurchase", "analysis_mode": "quick"},
            )
            first_payload = first.json()
            conversation_id = first_payload["conversation_id"]

            second = client.post(
                "/api/analysis/tasks/runs",
                json={
                    "question": "continue from current asset and update sql report",
                    "conversation_id": conversation_id,
                    "analysis_mode": "quick",
                    "turn_kind": "message",
                },
            )
            second_payload = second.json()
            event_types = [event["type"] for event in second_payload["events"]]
            updated_paths = [event["payload"]["path"] for event in second_payload["events"] if event["type"] == "artifact.updated"]
            created = next(event for event in second_payload["events"] if event["type"] == "run.created")

            self.assertEqual(second.status_code, 200)
            self.assertEqual(second_payload["conversation_id"], conversation_id)
            self.assertEqual(created["payload"]["conversation_id"], conversation_id)
            self.assertEqual(created["payload"]["turn_kind"], "message")
            self.assertIn("agent.message.created", event_types)
            self.assertIn("reports/updated_report.html", updated_paths)
            self.assertIn("queries/revised_query.sql", updated_paths)

    def test_analysis_reply_turn_preserves_conversation_and_updates_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                ExplorationRunService(),
                analysis_service=AnalysisRunService(thread_store=thread_store),
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post(
                "/api/analysis/tasks/runs",
                json={"question": "define repurchase metric", "analysis_mode": "deep"},
            )
            first_payload = first.json()
            conversation_id = first_payload["conversation_id"]

            reply = client.post(
                "/api/analysis/tasks/runs",
                json={
                    "question": "member_id",
                    "conversation_id": conversation_id,
                    "analysis_mode": "deep",
                    "turn_kind": "reply",
                },
            )
            payload = reply.json()
            created = next(event for event in payload["events"] if event["type"] == "run.created")
            updated_paths = [event["payload"]["path"] for event in payload["events"] if event["type"] == "artifact.updated"]
            ask_events = [event for event in payload["events"] if event["type"] == "agent.question.requested"]

            self.assertEqual(reply.status_code, 200)
            self.assertEqual(payload["conversation_id"], conversation_id)
            self.assertEqual(created["payload"]["conversation_id"], conversation_id)
            self.assertEqual(created["payload"]["analysis_mode"], "deep")
            self.assertEqual(created["payload"]["turn_kind"], "reply")
            self.assertIn("reports/updated_report.html", updated_paths)
            self.assertIn("queries/revised_query.sql", updated_paths)
            self.assertEqual(ask_events, [])

    def test_analysis_asset_api_saves_lists_and_reopens_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_store = AnalysisAssetStore(Path(temp_dir) / "analysis-assets.jsonl")
            app = create_app(
                ExplorationRunService(),
                analysis_service=AnalysisRunService(),
                analysis_asset_store=asset_store,
            )
            client = TestClient(app)

            save_payload = {
                "assetId": "asset_mock_report",
                "artifactVersionId": "artifact_version_mock_report_v1",
                "sourceTaskId": "analysis_task_run_analysis_abc",
                "sourceTaskTitle": "first purchase repurchase",
                "sourceConversationId": "conv_analysis_abc",
                "sourceRunId": "run_analysis_abc",
                "assetType": "report",
                "title": "quick_report.html",
                "label": "report",
                "description": "reusable analysis report",
                "visibility": "team",
                "status": "saved",
                "latestVersion": "v1-draft",
                "fileId": "reports-quick-report-html",
                "saveReason": "user_confirmed",
                "reopenContext": {
                    "sourceTaskId": "analysis_task_run_analysis_abc",
                    "sourceConversationId": "conv_analysis_abc",
                    "sourceRunId": "run_analysis_abc",
                    "continuationPrompt": "continue from quick report",
                    "targetFileId": "reports-quick-report-html",
                },
            }

            saved = client.post("/api/analysis/assets", json=save_payload)
            listed = client.get("/api/analysis/assets", params={"source_task_id": "analysis_task_run_analysis_abc"})
            reopened = client.post("/api/analysis/assets/asset_mock_report/reopen")

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["asset"]["assetId"], "asset_mock_report")
            self.assertEqual(saved.json()["asset"]["metadata"]["saveReason"], "user_confirmed")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()["assets"]), 1)
            self.assertEqual(listed.json()["assets"][0]["sourceConversationId"], "conv_analysis_abc")
            self.assertEqual(reopened.status_code, 200)
            self.assertEqual(reopened.json()["context"]["targetFileId"], "reports-quick-report-html")
            self.assertEqual(reopened.json()["artifactVersionId"], "artifact_version_mock_report_v1")


if __name__ == "__main__":
    unittest.main()
