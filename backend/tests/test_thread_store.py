from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.exploration.run_service import ExplorationRunEvent
from backend.harness.thread_store import ThreadStore


class ThreadStoreTest(unittest.TestCase):
    def test_store_saves_thread_turn_run_and_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            events = [
                ExplorationRunEvent(
                    type="run.created",
                    run_id="run_analysis_1",
                    payload={
                        "thread_id": "thread_1",
                        "turn_id": "turn_1",
                        "run_id": "run_analysis_1",
                        "question": "分析 GMV",
                        "item_id": "item_1",
                        "item_kind": "message",
                    },
                ),
                ExplorationRunEvent(
                    type="artifact.created",
                    run_id="run_analysis_1",
                    payload={
                        "thread_id": "thread_1",
                        "turn_id": "turn_1",
                        "run_id": "run_analysis_1",
                        "path": "queries/query.sql",
                        "kind": "sql",
                        "item_id": "item_2",
                        "item_kind": "sql",
                    },
                ),
                ExplorationRunEvent(type="run.completed", run_id="run_analysis_1", payload={"status": "completed"}),
            ]

            store.save_run(
                thread_id="thread_1",
                turn_id="turn_1",
                run_id="run_analysis_1",
                question="分析 GMV",
                input_kind="start",
                product_kind="analysis_task",
                user_id="user_1",
                events=events,
                metadata={"analysis_mode": "quick"},
            )

            thread = store.get_thread("thread_1")
            turn = store.get_turn("thread_1", "turn_1")
            run = store.get_run("run_analysis_1")

            self.assertIsNotNone(thread)
            assert thread is not None
            self.assertIsNotNone(turn)
            assert turn is not None
            self.assertEqual(thread["thread"]["id"], "thread_1")
            self.assertEqual(thread["turns"][0]["id"], "turn_1")
            self.assertEqual(thread["runs"][0]["id"], "run_analysis_1")
            self.assertEqual([item["kind"] for item in thread["items"]], ["message", "sql"])
            self.assertEqual(turn["turn"]["id"], "turn_1")
            self.assertEqual(turn["executionAttempts"][0]["id"], "run_analysis_1")
            self.assertEqual([item["kind"] for item in turn["items"]], ["message", "sql"])
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run["run"]["itemCount"], 2)

    def test_store_reads_runtime_thread_id_from_thread_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")

            store.save_run(
                thread_id="thread_1",
                turn_id="turn_1",
                run_id="run_1",
                question="resume test",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[ExplorationRunEvent(type="run.completed", run_id="run_1", payload={"status": "completed"})],
                metadata={
                    "codex_thread_id": "codex_1",
                    "runtime_threads": {"openai-codex": "codex_1"},
                },
            )

            self.assertEqual(store.get_thread_metadata("thread_1")["codex_thread_id"], "codex_1")
            self.assertEqual(store.get_runtime_thread_id("thread_1", "openai-codex"), "codex_1")
            self.assertEqual(store.get_analysis_thread_mapping("thread_1")["codexThreadId"], "codex_1")  # type: ignore[index]

    def test_store_promotes_genbi_thread_mapping_fields_from_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")

            store.save_run(
                thread_id="analysis_thread_1",
                turn_id="turn_1",
                run_id="run_1",
                question="mapping test",
                input_kind="start",
                product_kind="analysis_task",
                user_id="user_1",
                events=[ExplorationRunEvent(type="run.completed", run_id="run_1", payload={"status": "completed"})],
                metadata={
                    "tenant_id": "tenant_1",
                    "workspace_id": "workspace_1",
                    "runtime_threads": {"openai-codex": "codex_thread_1"},
                },
            )

            mapping = store.get_analysis_thread_mapping("analysis_thread_1")
            metadata = store.get_thread_metadata("analysis_thread_1")
            runtime_thread_id = store.get_runtime_thread_id("analysis_thread_1", "openai-codex")

        self.assertIsNotNone(mapping)
        assert mapping is not None
        self.assertEqual(mapping["id"], "analysis_thread_1")
        self.assertEqual(mapping["tenantId"], "tenant_1")
        self.assertEqual(mapping["userId"], "user_1")
        self.assertEqual(mapping["workspaceId"], "workspace_1")
        self.assertEqual(mapping["codexThreadId"], "codex_thread_1")
        self.assertEqual(metadata["codex_thread_id"], "codex_thread_1")
        self.assertEqual(runtime_thread_id, "codex_thread_1")

    def test_store_projects_codex_items_by_codex_item_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            events = [
                ExplorationRunEvent(
                    type="agent.message.delta",
                    run_id="run_1",
                    payload={
                        "codex_method": "item/agentMessage/delta",
                        "codex_thread_id": "codex_thread_1",
                        "codex_turn_id": "codex_turn_1",
                        "codex_item_id": "codex_item_1",
                        "delta": "第一段",
                    },
                ),
                ExplorationRunEvent(
                    type="agent.runner.raw",
                    run_id="run_1",
                    payload={
                        "phase": "agent_message.completed",
                        "codex_method": "item/completed",
                        "codex_thread_id": "codex_thread_1",
                        "codex_turn_id": "codex_turn_1",
                        "codex_item_id": "codex_item_1",
                        "codex_item_type": "agentMessage",
                        "content": "完整 Codex 输出",
                    },
                ),
                ExplorationRunEvent(type="run.completed", run_id="run_1", payload={"status": "completed"}),
            ]

            saved = store.save_run(
                thread_id="thread_1",
                turn_id="turn_1",
                run_id="run_1",
                question="分析 GMV",
                input_kind="start",
                product_kind="analysis_task",
                user_id="user_1",
                events=events,
                metadata={"codex_thread_id": "codex_thread_1"},
            )

            thread = store.get_thread("thread_1")
            run = store.get_run("run_1")

            self.assertEqual(saved["codexItemProjections"][0]["codexItemId"], "codex_item_1")
            self.assertIsNotNone(thread)
            self.assertIsNotNone(run)
            assert thread is not None
            assert run is not None
            self.assertEqual(len(thread["codexItemProjections"]), 1)
            self.assertEqual(len(run["codexItemProjections"]), 1)
            projection = thread["codexItemProjections"][0]
            self.assertEqual(projection["codexThreadId"], "codex_thread_1")
            self.assertEqual(projection["codexTurnId"], "codex_turn_1")
            self.assertEqual(thread["turns"][0]["codexThreadId"], "codex_thread_1")
            self.assertEqual(thread["turns"][0]["codexTurnId"], "codex_turn_1")
            self.assertEqual(projection["itemType"], "agentMessage")
            self.assertEqual(projection["status"], "completed")
            self.assertEqual(projection["payload"]["content"], "完整 Codex 输出")


if __name__ == "__main__":
    unittest.main()
