from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.events import AgentEvent
from backend.harness.thread_store import ThreadStore


class ThreadStoreTest(unittest.TestCase):
    def test_create_thread_saves_waiting_thread_without_turns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")

            created = store.create_thread(
                thread_id="codex_thread_report",
                product_kind="analysis_task",
                title="渠道日报 新分析",
                user_id="user_1",
                status="waiting_for_question",
                codex_thread_id="codex_thread_report",
                metadata={"source_report_id": "report_1"},
            )
            detail = store.get_thread("codex_thread_report")

            self.assertEqual(created["thread"]["status"], "waiting_for_question")
            self.assertEqual(created["turns"], [])
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail["thread"]["title"], "渠道日报 新分析")
            self.assertEqual(detail["thread"]["metadata"]["source_report_id"], "report_1")
            self.assertEqual(detail["turns"], [])

    def test_store_saves_thread_turn_and_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            events = [
                AgentEvent(
                    type="turn/started",
                    turn_id="codex_turn_1",
                    payload={
                        "thread_id": "codex_thread_1",
                        "turn_id": "codex_turn_1",
                        "question": "analyze GMV",
                        "item_id": "item_1",
                        "item_kind": "message",
                    },
                ),
                AgentEvent(
                    type="genbi/artifact/created",
                    turn_id="codex_turn_1",
                    payload={
                        "thread_id": "codex_thread_1",
                        "turn_id": "codex_turn_1",
                        "path": "queries/query.sql",
                        "kind": "sql",
                        "item_id": "item_2",
                        "item_kind": "sql",
                    },
                ),
                AgentEvent(type="turn/completed", turn_id="codex_turn_1", payload={"status": "completed"}),
            ]

            store.save_turn(
                thread_id="codex_thread_1",
                turn_id="codex_turn_1",
                question="analyze GMV",
                input_kind="start",
                product_kind="analysis_task",
                user_id="user_1",
                events=events,
                metadata={"analysis_scope": "controlled"},
            )

            thread = store.get_thread("codex_thread_1")
            turn = store.get_turn("codex_thread_1", "codex_turn_1")
            turn_events = store.get_turn_events("codex_turn_1")

            self.assertIsNotNone(thread)
            assert thread is not None
            self.assertIsNotNone(turn)
            assert turn is not None
            self.assertEqual(thread["thread"]["id"], "codex_thread_1")
            self.assertEqual(thread["thread"]["title"], "analyze GMV")
            self.assertEqual(thread["turns"][0]["id"], "codex_turn_1")
            self.assertNotIn("runs", thread)
            self.assertEqual([item["kind"] for item in thread["items"]], ["message", "sql"])
            self.assertEqual(turn["turn"]["id"], "codex_turn_1")
            self.assertNotIn("executionAttempts", turn)
            self.assertEqual([item["kind"] for item in turn["items"]], ["message", "sql"])
            self.assertEqual([event["type"] for event in turn_events], ["turn/started", "genbi/artifact/created"])

    def test_store_reads_runtime_thread_id_from_thread_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")

            store.save_turn(
                thread_id="codex_thread_resume",
                turn_id="codex_turn_resume",
                question="resume test",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[AgentEvent(type="turn/completed", turn_id="codex_turn_resume", payload={"status": "completed"})],
                metadata={
                    "codex_thread_id": "codex_thread_resume",
                    "runtime_threads": {"openai-codex": "codex_thread_resume"},
                },
            )

            self.assertEqual(store.get_thread_metadata("codex_thread_resume")["codex_thread_id"], "codex_thread_resume")
            self.assertEqual(store.get_runtime_thread_id("codex_thread_resume", "openai-codex"), "codex_thread_resume")

    def test_store_promotes_analysis_task_fields_from_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")

            store.save_turn(
                thread_id="codex_thread_promote",
                turn_id="codex_turn_promote",
                question="mapping test",
                input_kind="start",
                product_kind="analysis_task",
                user_id="user_1",
                events=[AgentEvent(type="turn/completed", turn_id="codex_turn_promote", payload={"status": "completed"})],
                metadata={
                    "tenant_id": "tenant_1",
                    "workspace_id": "workspace_1",
                    "runtime_threads": {"openai-codex": "codex_thread_promote"},
                },
            )

            mapping = store.get_analysis_thread_mapping("codex_thread_promote")
            metadata = store.get_thread_metadata("codex_thread_promote")
            runtime_thread_id = store.get_runtime_thread_id("codex_thread_promote", "openai-codex")

        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping["id"], "codex_thread_promote")
        self.assertEqual(mapping["tenantId"], "tenant_1")
        self.assertEqual(mapping["userId"], "user_1")
        self.assertEqual(mapping["workspaceId"], "workspace_1")
        self.assertEqual(mapping["codexThreadId"], "codex_thread_promote")
        self.assertEqual(metadata["codex_thread_id"], "codex_thread_promote")
        self.assertEqual(runtime_thread_id, "codex_thread_promote")

    def test_store_projects_codex_items_by_codex_item_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            events = [
                AgentEvent(
                    type="item/agentMessage/delta",
                    turn_id="codex_turn_1",
                    payload={
                        "codex_method": "item/agentMessage/delta",
                        "codex_thread_id": "codex_thread_1",
                        "codex_turn_id": "codex_turn_1",
                        "codex_item_id": "codex_item_1",
                        "delta": "first part",
                    },
                ),
                AgentEvent(
                    type="item/completed",
                    turn_id="codex_turn_1",
                    payload={
                        "codex_method": "item/completed",
                        "codex_thread_id": "codex_thread_1",
                        "codex_turn_id": "codex_turn_1",
                        "codex_item_id": "codex_item_1",
                        "codex_item_type": "agentMessage",
                        "content": "complete Codex output",
                    },
                ),
                AgentEvent(type="turn/completed", turn_id="codex_turn_1", payload={"status": "completed"}),
            ]

            saved = store.save_turn(
                thread_id="codex_thread_1",
                turn_id="codex_turn_1",
                question="analyze GMV",
                input_kind="start",
                product_kind="analysis_task",
                user_id="user_1",
                events=events,
                metadata={"codex_thread_id": "codex_thread_1"},
            )

            thread = store.get_thread("codex_thread_1")

            self.assertEqual(saved["codexItemProjections"][0]["codexItemId"], "codex_item_1")
            self.assertIsNotNone(thread)
            assert thread is not None
            self.assertEqual(len(thread["codexItemProjections"]), 1)
            projection = thread["codexItemProjections"][0]
            self.assertEqual(projection["codexThreadId"], "codex_thread_1")
            self.assertEqual(projection["codexTurnId"], "codex_turn_1")
            self.assertEqual(thread["turns"][0]["codexThreadId"], "codex_thread_1")
            self.assertEqual(thread["turns"][0]["codexTurnId"], "codex_turn_1")
            self.assertEqual(projection["itemType"], "agentMessage")
            self.assertEqual(projection["status"], "completed")
            self.assertEqual(projection["payload"]["content"], "complete Codex output")

    def test_delete_thread_removes_thread_turn_items_and_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            store.save_turn(
                thread_id="codex_thread_delete",
                turn_id="codex_turn_delete",
                question="delete me",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[
                    AgentEvent(
                        type="item/completed",
                        turn_id="codex_turn_delete",
                        payload={
                            "codex_method": "item/completed",
                            "codex_item_type": "agentMessage",
                            "codex_item_id": "codex_item_delete",
                            "item_id": "item_delete",
                            "item_kind": "message",
                            "content": "done",
                        },
                    ),
                ],
                metadata={},
            )

            self.assertTrue(store.delete_thread("codex_thread_delete", product_kind="analysis_task"))

            self.assertIsNone(store.get_thread("codex_thread_delete"))
            self.assertIsNone(store.get_turn("codex_thread_delete", "codex_turn_delete"))
            self.assertEqual(store.get_turn_events("codex_turn_delete"), [])
            self.assertFalse(store.delete_thread("codex_thread_delete", product_kind="analysis_task"))


if __name__ == "__main__":
    unittest.main()
