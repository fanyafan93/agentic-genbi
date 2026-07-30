from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.asset_store import AnalysisAssetReopenContext, AnalysisAssetStore


class AnalysisAssetStoreTest(unittest.TestCase):
    def test_save_list_and_reopen_asset_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalysisAssetStore(Path(temp_dir) / "assets.jsonl")
            context = AnalysisAssetReopenContext(
                sourceTaskId="analysis_task_run_123",
                sourceConversationId="conv_analysis_123",
                sourceRunId="run_analysis_123",
                continuationPrompt="continue from report",
                targetFileId="reports-quick-report-html",
            )

            record = store.save_asset(
                asset_id="asset_report",
                artifact_version_id="artifact_version_report_v1",
                source_task_id="analysis_task_run_123",
                source_task_title="first purchase repurchase",
                source_conversation_id="conv_analysis_123",
                source_run_id="run_analysis_123",
                asset_type="report",
                title="quick_report.html",
                label="report",
                description="reusable analysis report",
                visibility="team",
                status="saved",
                latest_version="v1-draft",
                file_id="reports-quick-report-html",
                reopen_context=context,
                metadata={"saveReason": "user_confirmed"},
            )

            self.assertEqual(record.assetId, "asset_report")
            self.assertEqual(record.sourceConversationId, "conv_analysis_123")
            self.assertEqual(record.reopenContext.targetFileId, "reports-quick-report-html")
            self.assertEqual(store.list_assets(source_task_id="analysis_task_run_123")[0].assetId, "asset_report")
            self.assertEqual(store.list_assets(q="repurchase")[0].assetId, "asset_report")

            reopened = store.reopen_asset("asset_report")
            self.assertIsNotNone(reopened)
            self.assertEqual(reopened["context"]["sourceConversationId"], "conv_analysis_123")
            self.assertEqual(reopened["artifactVersionId"], "artifact_version_report_v1")

    def test_save_asset_upserts_by_asset_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalysisAssetStore(Path(temp_dir) / "assets.jsonl")
            context = AnalysisAssetReopenContext(
                sourceTaskId="analysis_task_1",
                sourceConversationId="conv_analysis_1",
                sourceRunId="run_analysis_1",
                continuationPrompt="continue",
            )

            store.save_asset(
                asset_id="asset_sql",
                artifact_version_id="artifact_version_sql_v1",
                source_task_id="analysis_task_1",
                source_task_title="task",
                source_conversation_id="conv_analysis_1",
                source_run_id="run_analysis_1",
                asset_type="sql",
                title="candidate.sql",
                label="sql",
                description="candidate query",
                visibility="team",
                status="saved",
                latest_version="v1-draft",
                reopen_context=context,
            )
            updated = store.save_asset(
                asset_id="asset_sql",
                artifact_version_id="artifact_version_sql_v2",
                source_task_id="analysis_task_1",
                source_task_title="task",
                source_conversation_id="conv_analysis_1",
                source_run_id="run_analysis_2",
                asset_type="sql",
                title="candidate.sql",
                label="sql",
                description="revised query",
                visibility="team",
                status="reusable",
                latest_version="v2",
                reopen_context=AnalysisAssetReopenContext(
                    sourceTaskId="analysis_task_1",
                    sourceConversationId="conv_analysis_1",
                    sourceRunId="run_analysis_2",
                    continuationPrompt="continue from revised query",
                ),
            )

            records = store.list_assets()
            self.assertEqual(len(records), 1)
            self.assertEqual(updated.artifactVersionId, "artifact_version_sql_v2")
            self.assertEqual(records[0].status, "reusable")
            self.assertEqual(records[0].sourceRunId, "run_analysis_2")


if __name__ == "__main__":
    unittest.main()
