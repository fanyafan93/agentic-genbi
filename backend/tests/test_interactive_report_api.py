from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.analysis.interactive_report_store import InteractiveReportStore
from backend.api.analysis_api import create_app
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime


def _report_payload(
    *,
    document_title: str = "Channel Sales Share",
    source_thread_id: str | None = "conv_analysis_123",
    source_turn_id: str | None = "turn_analysis_123",
    origin_type: str | None = None,
) -> dict:
    payload = {
        "id": "report_channel_sales",
        "title": "Channel Sales Share Analysis",
        "subtitle": "Compare sales, share, and growth by channel",
        "artifactType": "interactive_report",
        "renderer": "puck",
        "document": {"content": [{"type": "MarkdownBlock", "props": {"content": document_title}}], "root": {"props": {}}},
        "filters": [{"id": "month", "label": "Month", "defaultValue": "2026-08", "options": [{"label": "2026-08", "value": "2026-08"}]}],
        "queries": {"channel-sales-query": {"datasetId": "channel_sales", "filterBindings": ["month"]}},
        "chartSpecs": {"channel-sales-chart": {"id": "channel-sales-chart", "datasetId": "channel_sales", "type": "bar"}},
        "gridSpecs": {"channel-sales-grid": {"id": "channel-sales-grid", "datasetId": "channel_sales", "columns": []}},
        "datasets": {"channel_sales": {"rows": [{"channel": "direct", "salesAmount": 1000}]}},
        "ownerId": "user_jason",
    }
    if origin_type is not None:
        payload["originType"] = origin_type
    if source_thread_id is not None and source_turn_id is not None:
        payload["source"] = {"threadId": source_thread_id, "turnId": source_turn_id}
    return payload


class InteractiveReportApiTest(unittest.TestCase):
    def test_saves_lists_opens_and_overwrites_current_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.jsonl")
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
            )
            client = TestClient(app)

            created = client.post("/api/analysis/reports", json=_report_payload())
            updated = client.post(
                "/api/analysis/reports",
                json=_report_payload(document_title="Channel Sales Share revised", source_turn_id="turn_analysis_456"),
            )
            listed = client.get("/api/analysis/reports", params={"owner_id": "user_jason"})
            latest = client.get("/api/analysis/reports/report_channel_sales")
            versions = client.get("/api/analysis/reports/report_channel_sales/versions")

            self.assertEqual(created.status_code, 200)
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(listed.status_code, 200)
            self.assertNotIn("latestVersion", listed.json()["reports"][0])
            self.assertEqual(latest.json()["report"]["document"]["content"][0]["props"]["content"], "Channel Sales Share revised")
            self.assertEqual(latest.json()["report"]["datasets"]["channel_sales"]["rows"][0]["salesAmount"], 1000)
            self.assertEqual(latest.json()["report"]["sourceTurnId"], "turn_analysis_456")
            self.assertEqual(latest.json()["report"]["originType"], "codex")
            self.assertEqual(versions.status_code, 404)

    def test_saves_seed_report_without_session_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.jsonl")
            app = create_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled(), interactive_report_store=report_store)
            client = TestClient(app)

            created = client.post(
                "/api/analysis/reports",
                json=_report_payload(source_thread_id=None, source_turn_id=None, origin_type="seed"),
            )

            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["report"]["originType"], "seed")
            self.assertNotIn("sourceThreadId", created.json()["report"])
            self.assertNotIn("sourceTurnId", created.json()["report"])

    def test_migrates_only_latest_legacy_report_version_into_report_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "interactive-reports.json"
            report = _report_payload()
            report_summary = {
                key: value
                for key, value in report.items()
                if key not in {"document", "filters", "queries", "chartSpecs", "gridSpecs", "datasets", "source", "originType"}
            }
            report_summary.update(
                {
                    "sourceThreadId": "conv_analysis_123",
                    "sourceTurnId": "turn_analysis_456",
                    "latestVersion": 2,
                    "createdAt": "2026-08-01T00:00:00+00:00",
                    "updatedAt": "2026-08-02T00:00:00+00:00",
                }
            )
            version_one = {
                "reportId": report["id"],
                "version": 1,
                "sourceThreadId": "conv_analysis_123",
                "sourceTurnId": "turn_analysis_123",
                "document": {"content": [{"type": "MarkdownBlock", "props": {"content": "old"}}], "root": {"props": {}}},
                "filters": report["filters"],
                "queries": report["queries"],
                "chartSpecs": report["chartSpecs"],
                "gridSpecs": report["gridSpecs"],
                "datasets": report["datasets"],
                "createdAt": "2026-08-01T00:00:00+00:00",
            }
            version_two = {
                **version_one,
                "version": 2,
                "sourceTurnId": "turn_analysis_456",
                "document": {"content": [{"type": "MarkdownBlock", "props": {"content": "latest"}}], "root": {"props": {}}},
                "createdAt": "2026-08-02T00:00:00+00:00",
            }
            store_path.write_text(
                json.dumps({"reports": [report_summary], "versions": [version_one, version_two], "shares": []}),
                encoding="utf-8",
            )

            migrated = InteractiveReportStore(store_path).get_report(report["id"])

            self.assertIsNotNone(migrated)
            self.assertEqual(migrated.document["content"][0]["props"]["content"], "latest")
            persisted = json.loads(store_path.read_text(encoding="utf-8"))
            self.assertNotIn("versions", persisted)
            self.assertNotIn("latestVersion", persisted["reports"][0])


if __name__ == "__main__":
    unittest.main()

