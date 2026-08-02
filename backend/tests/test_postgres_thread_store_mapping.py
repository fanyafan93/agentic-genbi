from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.thread_store import ThreadRecord, TurnRecord
from backend.persistence import postgres_stores


class PostgresThreadStoreMappingTest(unittest.TestCase):
    def test_thread_params_include_explicit_analysis_thread_mapping(self) -> None:
        record = ThreadRecord(
            id="analysis_thread_1",
            productKind="analysis_task",
            title="渠道销售占比分析",
            tenantId="tenant_1",
            userId="user_1",
            workspaceId="workspace_1",
            codexThreadId="codex_thread_1",
            status="completed",
            createdAt="2026-08-02T10:00:00Z",
            updatedAt="2026-08-02T10:01:00Z",
            metadata={"codex_thread_id": "codex_thread_1"},
        )

        with patch.object(postgres_stores, "_jsonb", side_effect=lambda value: value):
            params = postgres_stores._thread_params(record)

        self.assertEqual(params["tenant_id"], "tenant_1")
        self.assertEqual(params["user_id"], "user_1")
        self.assertEqual(params["workspace_id"], "workspace_1")
        self.assertEqual(params["codex_thread_id"], "codex_thread_1")

    def test_thread_record_from_row_preserves_explicit_mapping_fields(self) -> None:
        record = postgres_stores._thread_record_from_row(
            {
                "id": "analysis_thread_1",
                "product_kind": "analysis_task",
                "title": "渠道销售占比分析",
                "tenant_id": "tenant_1",
                "user_id": "user_1",
                "workspace_id": "workspace_1",
                "codex_thread_id": "codex_thread_1",
                "status": "completed",
                "created_at": "2026-08-02T10:00:00Z",
                "updated_at": "2026-08-02T10:01:00Z",
                "metadata": {},
            }
        )

        self.assertEqual(record.tenantId, "tenant_1")
        self.assertEqual(record.userId, "user_1")
        self.assertEqual(record.workspaceId, "workspace_1")
        self.assertEqual(record.codexThreadId, "codex_thread_1")

    def test_turn_params_and_row_preserve_codex_turn_index(self) -> None:
        turn = TurnRecord(
            id="analysis_turn_1",
            threadId="analysis_thread_1",
            inputKind="message",
            question="继续分析",
            status="completed",
            createdAt="2026-08-02T10:00:00Z",
            updatedAt="2026-08-02T10:01:00Z",
            codexThreadId="codex_thread_1",
            codexTurnId="codex_turn_1",
            metadata={"codex_turn_id": "codex_turn_1"},
        )

        with patch.object(postgres_stores, "_jsonb", side_effect=lambda value: value):
            params = postgres_stores._turn_params(turn)
        row_record = postgres_stores._turn_record_from_row(
            {
                "id": "analysis_turn_1",
                "thread_id": "analysis_thread_1",
                "input_kind": "message",
                "question": "继续分析",
                "status": "completed",
                "created_at": "2026-08-02T10:00:00Z",
                "updated_at": "2026-08-02T10:01:00Z",
                "codex_thread_id": "codex_thread_1",
                "codex_turn_id": "codex_turn_1",
                "metadata": {},
            }
        )

        self.assertEqual(params["codex_thread_id"], "codex_thread_1")
        self.assertEqual(params["codex_turn_id"], "codex_turn_1")
        self.assertEqual(row_record.codexThreadId, "codex_thread_1")
        self.assertEqual(row_record.codexTurnId, "codex_turn_1")


if __name__ == "__main__":
    unittest.main()
