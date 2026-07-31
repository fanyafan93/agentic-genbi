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
            run = store.get_run("run_analysis_1")

            self.assertIsNotNone(thread)
            assert thread is not None
            self.assertEqual(thread["thread"]["id"], "thread_1")
            self.assertEqual(thread["turns"][0]["id"], "turn_1")
            self.assertEqual(thread["runs"][0]["id"], "run_analysis_1")
            self.assertEqual([item["kind"] for item in thread["items"]], ["message", "sql"])
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


if __name__ == "__main__":
    unittest.main()
