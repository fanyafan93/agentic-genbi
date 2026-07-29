from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.exploration.run_service import ExplorationRunEvent, ExplorationRunRequest, ExplorationRunService
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_trace_store import RunTraceStore, build_run_trace


class RunTraceStoreTest(unittest.TestCase):
    def test_build_trace_summarizes_events_usage_and_cost(self) -> None:
        events = [
            ExplorationRunEvent(type="run.created", run_id="run_1", payload={"question": "q"}),
            ExplorationRunEvent(type="agent.title.generated", run_id="run_1", payload={"title": "首购复购"}),
            ExplorationRunEvent(type="tool.call.started", run_id="run_1", payload={"tool": "search_resources"}),
            ExplorationRunEvent(type="agent.message.created", run_id="run_1", payload={"content": "ok"}),
            ExplorationRunEvent(
                type="agent.runner.raw",
                run_id="run_1",
                payload={"usage": {"input_tokens": 1000, "output_tokens": 500, "total_tokens": 1500}},
            ),
            ExplorationRunEvent(type="run.completed", run_id="run_1", payload={"status": "completed"}),
        ]

        with patch.dict(
            os.environ,
            {"GENBI_MODEL_INPUT_USD_PER_1M": "2", "GENBI_MODEL_OUTPUT_USD_PER_1M": "8"},
            clear=False,
        ):
            trace = build_run_trace(
                run_id="run_1",
                request=ExplorationRunRequest(question="首购后 30 天复购率", conversation_id="conv_1", user_id="user_1"),
                events=events,
            )

        self.assertEqual(trace.title, "首购复购")
        self.assertEqual(trace.status, "completed")
        self.assertEqual(trace.tool_call_count, 1)
        self.assertEqual(trace.agent_message_count, 1)
        self.assertEqual(trace.token_usage.total_tokens, 1500)
        self.assertEqual(trace.cost.total_usd, 0.006)

    def test_store_saves_and_lists_recent_traces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            events = [
                ExplorationRunEvent(type="run.created", run_id="run_1", payload={"question": "q"}),
                ExplorationRunEvent(type="run.completed", run_id="run_1", payload={"status": "completed"}),
            ]

            record = store.save_trace(
                run_id="run_1",
                request=ExplorationRunRequest(question="q"),
                events=events,
            )

            records = store.list_traces()
            self.assertEqual(records[0].run_id, record.run_id)
            self.assertEqual(store.get_trace("run_1").status, "completed")
            self.assertIsNone(store.get_trace("missing"))
            self.assertEqual(store.clear_traces(), 1)
            self.assertEqual(store.list_traces(), [])

    def test_store_lists_conversation_run_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            root_events = [
                ExplorationRunEvent(type="run.created", run_id="run_root", payload={"question": "库存是怎么取数的"}),
                ExplorationRunEvent(type="run.completed", run_id="run_root", payload={"status": "completed"}),
            ]
            child_events = [
                ExplorationRunEvent(type="run.created", run_id="run_child", payload={"question": "那仓库范围呢"}),
                ExplorationRunEvent(type="run.completed", run_id="run_child", payload={"status": "completed"}),
            ]

            store.save_trace(run_id="run_root", request=ExplorationRunRequest(question="库存是怎么取数的"), events=root_events)
            store.save_trace(
                run_id="run_child",
                request=ExplorationRunRequest(question="那仓库范围呢", conversation_id="run_root"),
                events=child_events,
                metadata={"continuation_of": "run_root"},
            )

            self.assertEqual(store.list_conversation_run_ids("run_root"), ["run_root", "run_child"])

    def test_run_service_persists_trace_when_store_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            service = ExplorationRunService(trace_store=store)

            events = list(service.stream_events(ExplorationRunRequest(question="库存周转异常 SKU"), run_id="run_trace"))
            trace = store.get_trace("run_trace")

            self.assertEqual(events[-1].type, "run.failed")
            self.assertIsNotNone(trace)
            self.assertEqual(trace.run_id, "run_trace")
            self.assertEqual(trace.status, "failed")

    def test_run_service_persists_events_when_store_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            event_store = RunEventStore(Path(temp_dir) / "run-events.jsonl")
            service = ExplorationRunService(event_store=event_store)

            events = list(service.stream_events(ExplorationRunRequest(question="复购率"), run_id="run_events"))
            restored = event_store.list_events("run_events")

            self.assertEqual([event.type for event in restored], [event.type for event in events])
            self.assertEqual(restored[0].payload["question"], "复购率")
            self.assertEqual(event_store.clear_events(), len(events))


if __name__ == "__main__":
    unittest.main()
