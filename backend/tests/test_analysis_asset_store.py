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
                continuationPrompt="continue from report",
                targetFileId="reports-quick-report-html",
                sourceCodexThreadId="codex_thread_123",
                sourceCodexTurnId="codex_turn_123",
                sourceCodexItemId="codex_item_report",
            )

            record = store.save_asset(
                asset_id="asset_report",
                artifact_version_id="artifact_version_report_v1",
                source_task_id="analysis_task_run_123",
                source_task_title="first purchase repurchase",
                source_conversation_id="conv_analysis_123",
                source_codex_thread_id="codex_thread_123",
                source_codex_turn_id="codex_turn_123",
                source_codex_item_id="codex_item_report",
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
            self.assertEqual(record.sourceCodexThreadId, "codex_thread_123")
            self.assertEqual(record.sourceCodexTurnId, "codex_turn_123")
            self.assertEqual(record.sourceCodexItemId, "codex_item_report")
            self.assertEqual(record.metadata["codex_lineage"]["codexItemId"], "codex_item_report")
            self.assertEqual(record.reopenContext.targetFileId, "reports-quick-report-html")
            self.assertEqual(store.list_assets(source_task_id="analysis_task_run_123")[0].assetId, "asset_report")
            self.assertEqual(store.list_assets(q="repurchase")[0].assetId, "asset_report")

            reopened = store.reopen_asset("asset_report")
            self.assertIsNotNone(reopened)
            self.assertEqual(reopened["context"]["sourceConversationId"], "conv_analysis_123")
            self.assertEqual(reopened["context"]["sourceCodexItemId"], "codex_item_report")
            self.assertEqual(reopened["artifactVersionId"], "artifact_version_report_v1")

            lineage = store.list_artifact_lineage(codex_item_id="codex_item_report")
            self.assertEqual(len(lineage), 1)
            self.assertEqual(lineage[0].assetId, "asset_report")
            self.assertEqual(lineage[0].artifactId, "asset_report")
            self.assertEqual(lineage[0].artifactVersionId, "artifact_version_report_v1")
            self.assertEqual(lineage[0].codexThreadId, "codex_thread_123")
            self.assertEqual(lineage[0].codexTurnId, "codex_turn_123")
            self.assertEqual(lineage[0].codexItemId, "codex_item_report")

    def test_save_asset_upserts_by_asset_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalysisAssetStore(Path(temp_dir) / "assets.jsonl")
            context = AnalysisAssetReopenContext(
                sourceTaskId="analysis_task_1",
                sourceConversationId="conv_analysis_1",
                continuationPrompt="continue",
            )

            store.save_asset(
                asset_id="asset_sql",
                artifact_version_id="artifact_version_sql_v1",
                source_task_id="analysis_task_1",
                source_task_title="task",
                source_conversation_id="conv_analysis_1",
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
                    continuationPrompt="continue from revised query",
                ),
            )

            records = store.list_assets()
            self.assertEqual(len(records), 1)
            self.assertEqual(updated.artifactVersionId, "artifact_version_sql_v2")
            self.assertEqual(records[0].status, "reusable")

    def test_save_asset_uses_codex_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = AnalysisAssetStore(Path(temp_dir) / "assets.jsonl")
            context = AnalysisAssetReopenContext(
                sourceTaskId="analysis_task_1",
                sourceConversationId="conv_analysis_1",
                continuationPrompt="continue",
                sourceCodexThreadId="codex_thread_1",
                sourceCodexTurnId="codex_turn_1",
                sourceCodexItemId="codex_item_1",
            )

            record = store.save_asset(
                asset_id="asset_report",
                artifact_version_id="artifact_version_report_v1",
                source_task_id="analysis_task_1",
                source_task_title="task",
                source_conversation_id="conv_analysis_1",
                source_codex_thread_id="codex_thread_1",
                source_codex_turn_id="codex_turn_1",
                source_codex_item_id="codex_item_1",
                asset_type="report",
                title="analysis_report.html",
                label="report",
                description="saved report",
                visibility="team",
                status="saved",
                latest_version="v1-draft",
                reopen_context=context,
            )

            self.assertEqual(record.sourceCodexThreadId, "codex_thread_1")
            self.assertEqual(record.sourceCodexTurnId, "codex_turn_1")
            self.assertEqual(record.sourceCodexItemId, "codex_item_1")


if __name__ == "__main__":
    unittest.main()
