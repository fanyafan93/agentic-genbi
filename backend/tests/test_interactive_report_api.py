from __future__ import annotations

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
    expected_version: int | None = None,
    document_title: str = "Channel Sales Share",
    source_turn_id: str = "turn_analysis_123",
) -> dict:
    source = {"threadId": "conv_analysis_123", "turnId": source_turn_id}
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
        "source": source,
        "ownerId": "user_jason",
    }
    if expected_version is not None:
        payload["expectedVersion"] = expected_version
    return payload


class InteractiveReportApiTest(unittest.TestCase):
    def test_saves_lists_opens_and_preserves_report_versions(self) -> None:
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
                json=_report_payload(expected_version=1, document_title="Channel Sales Share revised", source_turn_id="turn_analysis_456"),
            )
            listed = client.get("/api/analysis/reports", params={"owner_id": "user_jason"})
            latest = client.get("/api/analysis/reports/report_channel_sales")
            version_one = client.get("/api/analysis/reports/report_channel_sales/versions/1")
            versions = client.get("/api/analysis/reports/report_channel_sales/versions")

            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["version"]["version"], 1)
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["version"]["version"], 2)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()["reports"][0]["latestVersion"], 2)
            self.assertEqual(latest.json()["version"]["document"]["content"][0]["props"]["content"], "Channel Sales Share revised")
            self.assertEqual(latest.json()["version"]["datasets"]["channel_sales"]["rows"][0]["salesAmount"], 1000)
            self.assertEqual(version_one.json()["version"]["document"]["content"][0]["props"]["content"], "Channel Sales Share")
            self.assertEqual(version_one.json()["version"]["sourceTurnId"], "turn_analysis_123")
            self.assertEqual(latest.json()["version"]["sourceTurnId"], "turn_analysis_456")
            self.assertEqual([item["version"] for item in versions.json()["versions"]], [2, 1])

    def test_saves_report_with_turn_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.jsonl")
            app = create_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled(), interactive_report_store=report_store)
            client = TestClient(app)

            created = client.post("/api/analysis/reports", json=_report_payload(source_turn_id="turn_report_only"))

            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["version"]["sourceTurnId"], "turn_report_only")

    def test_rejects_stale_report_version_saves(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.jsonl")
            app = create_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled(), interactive_report_store=report_store)
            client = TestClient(app)

            client.post("/api/analysis/reports", json=_report_payload())
            stale = client.post("/api/analysis/reports", json=_report_payload(expected_version=0))

            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["detail"], "interactive_report_version_conflict")


if __name__ == "__main__":
    unittest.main()

