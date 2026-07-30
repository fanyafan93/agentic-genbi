from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.analysis.asset_store import AnalysisAssetStore
from backend.analysis.run_service import AnalysisRunService
from backend.api.exploration_api import create_app
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_service import ExplorationRunService
from backend.exploration.run_trace_store import RunTraceStore


class AnalysisApiTest(unittest.TestCase):
    def test_analysis_run_api_returns_backend_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trace_store = RunTraceStore(root / "traces.jsonl")
            event_store = RunEventStore(root / "events.jsonl")
            app = create_app(
                ExplorationRunService(trace_store=trace_store, event_store=event_store),
                analysis_service=AnalysisRunService(trace_store=trace_store, event_store=event_store),
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

    def test_analysis_stream_api_returns_sse(self) -> None:
        app = create_app(ExplorationRunService(), analysis_service=AnalysisRunService())
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
            app = create_app(
                ExplorationRunService(trace_store=trace_store, event_store=event_store),
                analysis_service=AnalysisRunService(trace_store=trace_store, event_store=event_store),
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
        app = create_app(ExplorationRunService(), analysis_service=AnalysisRunService())
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
