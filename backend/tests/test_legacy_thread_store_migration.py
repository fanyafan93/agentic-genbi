from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from runpy import run_path

from backend.harness.codex_projection_store import CodexProjectionStore
from backend.harness.session_catalog import SessionCatalog

migrate_legacy_thread_store = run_path(
    str(Path(__file__).resolve().parents[2] / "scripts" / "migrate_legacy_thread_store.py")
)["migrate_legacy_thread_store"]


class LegacyThreadStoreMigrationTest(unittest.TestCase):
    def test_migrates_legacy_jsonl_into_session_and_projection_stores_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "thread-store.jsonl"
            legacy_path.write_text(
                "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in [
                        {
                            "record_type": "thread",
                            "payload": {
                                "id": "conv_1",
                                "productKind": "analysis_task",
                                "title": None,
                                "userId": None,
                                "status": "failed",
                                "createdAt": "2026-08-03T01:00:00+00:00",
                                "updatedAt": "2026-08-03T01:10:00+00:00",
                                "metadata": {"domain": "analysis_task", "tenant_id": "default"},
                                "tenantId": None,
                                "workspaceId": "workspace_a",
                                "codexThreadId": "codex_thread_1",
                            },
                        },
                        {
                            "record_type": "turn",
                            "payload": {
                                "id": "turn_1",
                                "threadId": "conv_1",
                                "inputKind": "start",
                                "question": "old question",
                                "status": "failed",
                                "createdAt": "2026-08-03T01:00:00+00:00",
                                "updatedAt": "2026-08-03T01:10:00+00:00",
                                "metadata": {"thread_id": "conv_1"},
                                "codexThreadId": "codex_thread_1",
                                "codexTurnId": "codex_turn_1",
                            },
                        },
                        {
                            "record_type": "codex_item_projection",
                            "payload": {
                                "codexItemId": "item_1",
                                "codexThreadId": "codex_thread_1",
                                "codexTurnId": "codex_turn_1",
                                "itemType": "agentMessage",
                                "status": "completed",
                                "payload": {"content": "answer"},
                                "createdAt": "2026-08-03T01:01:00+00:00",
                                "completedAt": "2026-08-03T01:02:00+00:00",
                                "genbiThreadId": "conv_1",
                                "genbiTurnId": "turn_1",
                            },
                        },
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            catalog = SessionCatalog(path=Path(temp_dir) / "sessions.jsonl")
            projections = CodexProjectionStore(path=Path(temp_dir) / "projections.jsonl")

            first = migrate_legacy_thread_store(
                legacy_path,
                session_catalog=catalog,
                projection_store=projections,
                dry_run=False,
            )
            second = migrate_legacy_thread_store(
                legacy_path,
                session_catalog=catalog,
                projection_store=projections,
                dry_run=False,
            )

            self.assertEqual(first.read_threads, 1)
            self.assertEqual(first.read_turns, 1)
            self.assertEqual(first.read_items, 1)
            self.assertEqual(second.read_threads, 1)
            self.assertEqual(len(catalog.list_sessions(limit=10)), 1)
            self.assertEqual(len(projections.list_turns("conv_1")), 1)
            self.assertEqual(len(projections.list_items(session_id="conv_1", turn_id="turn_1")), 2)

            session = catalog.get_session("conv_1")
            assert session is not None
            self.assertEqual(session.title, "old question")
            self.assertEqual(session.status, "active")
            self.assertEqual(session.codexSessionId, "conv_1")
            self.assertEqual(session.metadata["legacy_codex_session_id"], "codex_thread_1")
            self.assertEqual(session.tenantId, "default")
            self.assertEqual(session.workspaceId, "workspace_a")

            turn = projections.get_turn("conv_1", "turn_1")
            assert turn is not None
            self.assertEqual(turn.codexSessionId, "conv_1")
            self.assertEqual(turn.codexTurnId, "turn_1")
            self.assertEqual(turn.metadata["legacy_codex_session_id"], "codex_thread_1")
            self.assertEqual(turn.metadata["legacy_codex_turn_id"], "codex_turn_1")

            items = projections.list_items(session_id="conv_1", turn_id="turn_1")
            user_items = [item for item in items if item.itemType == "userMessage"]
            self.assertEqual(len(user_items), 1)
            self.assertEqual(user_items[0].codexItemId, "legacy_user_turn_1")
            self.assertEqual(user_items[0].payload["content"], "old question")
