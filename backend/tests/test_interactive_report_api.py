from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.analysis.interactive_report_store import InteractiveReportStore
from backend.analysis.run_service import AnalysisRunService
from backend.api.exploration_api import create_app
from backend.exploration.run_service import ExplorationRunService


def _report_payload(
    *,
    expected_version: int | None = None,
    document_title: str = "渠道销售占比",
    source_run_id: str = "run_analysis_123",
    include_run_id: bool = True,
) -> dict:
    source = {"threadId": "conv_analysis_123", "turnId": "turn_analysis_123", "executionAttemptId": source_run_id}
    if include_run_id:
        source["runId"] = source_run_id
    payload = {
        "id": "report_channel_sales",
        "title": "渠道销售占比分析",
        "subtitle": "按渠道查看销售额、占比与增长",
        "artifactType": "interactive_report",
        "renderer": "puck",
        "document": {"content": [{"type": "MarkdownBlock", "props": {"content": document_title}}], "root": {"props": {}}},
        "filters": [{"id": "month", "label": "月份", "defaultValue": "2026-08", "options": [{"label": "2026-08", "value": "2026-08"}]}],
        "queries": {"channel-sales-query": {"datasetId": "channel_sales", "filterBindings": ["month"]}},
        "chartSpecs": {"channel-sales-chart": {"id": "channel-sales-chart", "datasetId": "channel_sales", "type": "bar"}},
        "gridSpecs": {"channel-sales-grid": {"id": "channel-sales-grid", "datasetId": "channel_sales", "columns": []}},
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
                ExplorationRunService(),
                analysis_service=AnalysisRunService(),
                interactive_report_store=report_store,
            )
            client = TestClient(app)

            created = client.post("/api/analysis/reports", json=_report_payload())
            updated = client.post(
                "/api/analysis/reports",
                json=_report_payload(expected_version=1, document_title="渠道销售占比（已修订）", source_run_id="run_analysis_456"),
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
            self.assertEqual(latest.json()["version"]["document"]["content"][0]["props"]["content"], "渠道销售占比（已修订）")
            self.assertEqual(version_one.json()["version"]["document"]["content"][0]["props"]["content"], "渠道销售占比")
            self.assertEqual(version_one.json()["version"]["sourceRunId"], "run_analysis_123")
            self.assertEqual(version_one.json()["version"]["sourceExecutionAttemptId"], "run_analysis_123")
            self.assertEqual(latest.json()["version"]["sourceRunId"], "run_analysis_456")
            self.assertEqual([item["version"] for item in versions.json()["versions"]], [2, 1])

    def test_saves_report_with_execution_attempt_without_run_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.jsonl")
            app = create_app(ExplorationRunService(), analysis_service=AnalysisRunService(), interactive_report_store=report_store)
            client = TestClient(app)

            created = client.post("/api/analysis/reports", json=_report_payload(source_run_id="attempt_report_only", include_run_id=False))

            self.assertEqual(created.status_code, 200)
            self.assertEqual(created.json()["version"]["sourceExecutionAttemptId"], "attempt_report_only")
            self.assertEqual(created.json()["version"]["sourceRunId"], "attempt_report_only")

    def test_rejects_stale_report_version_saves(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.jsonl")
            app = create_app(ExplorationRunService(), analysis_service=AnalysisRunService(), interactive_report_store=report_store)
            client = TestClient(app)

            client.post("/api/analysis/reports", json=_report_payload())
            stale = client.post("/api/analysis/reports", json=_report_payload(expected_version=0))

            self.assertEqual(stale.status_code, 409)
            self.assertEqual(stale.json()["detail"], "interactive_report_version_conflict")


if __name__ == "__main__":
    unittest.main()
