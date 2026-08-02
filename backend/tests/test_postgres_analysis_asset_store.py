from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.asset_store import AnalysisAssetReopenContext
from backend.persistence import postgres_stores
from backend.persistence.postgres_stores import PostgresAnalysisAssetStore


class _Result:
    def __init__(self, rows: list[dict] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict]:
        return self._rows


class _Transaction:
    def __enter__(self) -> "_Transaction":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.assets: dict[str, dict] = {}
        self.lineage: dict[str, dict] = {}

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction()

    def execute(self, sql: str, params: dict | None = None) -> _Result:
        params = {key: _unwrap_jsonb(value) for key, value in (params or {}).items()}
        compact_sql = " ".join(sql.split()).lower()
        if compact_sql.startswith("create ") or compact_sql.startswith("alter ") or compact_sql.startswith("update "):
            return _Result()
        if "insert into analysis_assets" in compact_sql:
            self.assets[str(params["asset_id"])] = dict(params)
            return _Result(rowcount=1)
        if "insert into analysis_artifact_lineage" in compact_sql:
            self.lineage[str(params["artifact_id"])] = dict(params)
            return _Result(rowcount=1)
        if "select * from analysis_assets where asset_id" in compact_sql:
            row = self.assets.get(str(params["asset_id"]))
            return _Result([row] if row else [])
        if "select * from analysis_artifact_lineage" in compact_sql:
            rows = list(self.lineage.values())
            if params.get("codex_item_id"):
                rows = [row for row in rows if row.get("codex_item_id") == params["codex_item_id"]]
            if params.get("artifact_id"):
                rows = [row for row in rows if row.get("artifact_id") == params["artifact_id"]]
            return _Result(rows[: int(params.get("limit") or 50)])
        if compact_sql.startswith("delete from analysis_assets"):
            count = len(self.assets)
            self.assets.clear()
            self.lineage.clear()
            return _Result(rowcount=count)
        return _Result()


def _unwrap_jsonb(value: object) -> object:
    return getattr(value, "obj", value)


class PostgresAnalysisAssetStoreTest(unittest.TestCase):
    def test_saves_assets_and_queries_lineage_without_run_lookup(self) -> None:
        fake_conn = _FakeConnection()
        with (
            patch.object(postgres_stores, "_connect", return_value=fake_conn),
            patch.object(postgres_stores, "_jsonb", side_effect=lambda value: value),
        ):
            store = PostgresAnalysisAssetStore("postgresql://example/genbi")
            record = store.save_asset(
                asset_id="asset_report",
                artifact_version_id="artifact_version_report_v1",
                source_task_id="analysis_task_1",
                source_task_title="channel sales",
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
                file_id="reports-analysis-report-html",
                reopen_context=AnalysisAssetReopenContext(
                    sourceTaskId="analysis_task_1",
                    sourceConversationId="conv_analysis_1",
                    continuationPrompt="continue from report",
                    targetFileId="reports-analysis-report-html",
                    sourceCodexThreadId="codex_thread_1",
                    sourceCodexTurnId="codex_turn_1",
                    sourceCodexItemId="codex_item_1",
                ),
            )

            lineage = store.list_artifact_lineage(codex_item_id="codex_item_1")
            by_asset = store.get_asset("asset_report")

        self.assertEqual(record.metadata["codex_lineage"]["codexItemId"], "codex_item_1")
        self.assertIsNotNone(by_asset)
        assert by_asset is not None
        self.assertEqual(by_asset.sourceCodexItemId, "codex_item_1")
        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0].assetId, "asset_report")
        self.assertEqual(lineage[0].artifactId, "asset_report")
        self.assertEqual(lineage[0].artifactVersionId, "artifact_version_report_v1")
        self.assertEqual(lineage[0].codexItemId, "codex_item_1")


if __name__ == "__main__":
    unittest.main()
