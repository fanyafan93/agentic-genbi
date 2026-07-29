from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.exploration.run_service import (
    ExplorationRunRequest,
    ExplorationRunService,
    extract_search_keywords,
    generate_exploration_title,
)
from backend.exploration.agent_runner import ExplorationAgentRunResult, ExplorationAgentRunnerEvent
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_trace_store import RunTraceStore
from resource_library.indexer import ResourceIndexer
from resource_library.inspector import inspect_index
from resource_library.tools import ResourceLibrary


class ExplorationRunServiceTest(unittest.TestCase):
    def test_generate_title_from_business_question(self) -> None:
        title = generate_exploration_title("首购后 30 天复购率现在应该怎么计算？先看看公司里有没有已有实现。")

        self.assertEqual(title, "首购后 30 天复购率")

    def test_extract_keywords_keeps_full_question_first(self) -> None:
        keywords = extract_search_keywords("首购后 30 天复购率")

        self.assertEqual(keywords[0], "首购后 30 天复购率")
        self.assertIn("复购率", keywords)

    def test_missing_agent_runner_fails_instead_of_local_fallback(self) -> None:
        service = ExplorationRunService()

        events = list(service.stream_events(ExplorationRunRequest(question="你能干什么"), run_id="run_help"))

        event_types = [event.type for event in events]
        self.assertNotIn("agent.message.created", event_types)
        self.assertIn("agent.runner.failed", event_types)
        self.assertEqual(events[-1].type, "run.failed")
        self.assertEqual(events[-1].payload["error"], "agent_runner_not_configured")

    def test_run_stream_requires_agent_runner_instead_of_local_resource_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            index_path = root / "resources.json"
            summary_path = root / "summaries.json"
            (root / "首购后30天复购率.sql").write_text("select member_id from dm.rebuy_30d;", encoding="utf-8")
            ResourceIndexer(root).write(index_path)
            inspect_index(index_path, summary_path)

            service = ExplorationRunService(
                resource_library=ResourceLibrary(index_path=index_path, summary_path=summary_path),
                db_tools=None,
            )
            events = list(
                service.stream_events(
                    ExplorationRunRequest(question="首购后 30 天复购率现在应该怎么计算？"),
                    run_id="run_test",
                )
            )

            event_types = [event.type for event in events]
            self.assertEqual(event_types[0], "run.created")
            self.assertIn("agent.title.generated", event_types)
            self.assertNotIn("agent.evidence.available", event_types)
            self.assertNotIn("agent.question.requested", event_types)
            self.assertIn("agent.runner.failed", event_types)
            self.assertEqual(events[-1].type, "run.failed")
            self.assertEqual(events[-1].payload["error"], "agent_runner_not_configured")

    def test_event_serializes_as_sse(self) -> None:
        service = ExplorationRunService()
        event = next(service.stream_events(ExplorationRunRequest(question="库存周转异常 SKU"), run_id="run_sse"))
        text = event.to_sse()

        self.assertTrue(text.startswith("event: run.created\n"))
        payload = json.loads(text.split("data: ", 1)[1])
        self.assertEqual(payload["run_id"], "run_sse")

    def test_create_run_allows_streaming_by_run_id(self) -> None:
        service = ExplorationRunService()
        run_id = service.create_run(ExplorationRunRequest(question="渠道销售占比"))

        events = list(service.stream_run_events(run_id))

        self.assertEqual(events[0].type, "run.created")
        self.assertEqual(events[0].run_id, run_id)

    def test_missing_run_id_returns_failed_event(self) -> None:
        service = ExplorationRunService()

        events = list(service.stream_run_events("run_missing"))

        self.assertEqual(events[0].type, "run.failed")
        self.assertEqual(events[0].payload["error"], "run_not_found")

    def test_agent_runner_path_emits_final_output(self) -> None:
        class FakeRunner:
            def run(self, question: str) -> ExplorationAgentRunResult:
                return ExplorationAgentRunResult(final_output=f"已完成：{question}", raw_result_type="FakeRunResult")

        service = ExplorationRunService(agent_runner=FakeRunner())

        events = list(service.stream_events(ExplorationRunRequest(question="渠道销售占比"), run_id="run_agent"))

        self.assertIn("agent.runner.started", [event.type for event in events])
        self.assertIn("agent.runner.completed", [event.type for event in events])
        self.assertEqual(events[-1].type, "run.completed")
        self.assertEqual(events[-1].payload["status"], "completed")

    def test_continuation_run_passes_history_context_to_agent_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            captured_questions = []

            class FakeRunner:
                def run(self, question: str) -> ExplorationAgentRunResult:
                    captured_questions.append(question)
                    return ExplorationAgentRunResult(final_output=f"回复：{question}", raw_result_type="FakeRunResult")

            trace_store = RunTraceStore(Path(temp_dir) / "run-traces.jsonl")
            event_store = RunEventStore(Path(temp_dir) / "run-events.jsonl")
            service = ExplorationRunService(
                agent_runner=FakeRunner(),
                trace_store=trace_store,
                event_store=event_store,
            )

            list(service.stream_events(ExplorationRunRequest(question="库存是怎么取数的"), run_id="run_root"))
            list(
                service.stream_events(
                    ExplorationRunRequest(
                        question="那仓库范围呢",
                        conversation_id="run_root",
                        metadata={"continuation_of": "run_root"},
                    ),
                    run_id="run_child",
                )
            )

            self.assertEqual(captured_questions[0], "库存是怎么取数的")
            self.assertIn("已有对话", captured_questions[1])
            self.assertIn("用户：库存是怎么取数的", captured_questions[1])
            self.assertIn("本轮用户追问", captured_questions[1])
            self.assertIn("那仓库范围呢", captured_questions[1])
            self.assertNotIn("用户新的补充", captured_questions[1])

    def test_agent_message_events_normalize_legacy_agent_self_name(self) -> None:
        class FakeRunner:
            def run(self, question: str) -> ExplorationAgentRunResult:
                return ExplorationAgentRunResult(final_output="我是数据探索 Agent。", raw_result_type="FakeRunResult")

        service = ExplorationRunService(agent_runner=FakeRunner())

        events = list(service.stream_events(ExplorationRunRequest(question="库存口径"), run_id="run_identity"))
        message_bodies = [event.payload["content"] for event in events if event.type == "agent.message.created"]

        self.assertNotIn("我是数据探索 Agent。", message_bodies)
        self.assertIn("我是知识探索 Agent。", message_bodies)

    def test_agent_runner_error_fails_run(self) -> None:
        class FakeRunner:
            def run(self, question: str) -> ExplorationAgentRunResult:
                raise RuntimeError("no key")

        service = ExplorationRunService(agent_runner=FakeRunner())

        events = list(service.stream_events(ExplorationRunRequest(question="渠道销售占比"), run_id="run_agent"))

        self.assertEqual(events[-1].type, "run.failed")
        self.assertEqual(events[-1].payload["error"], "agent_runner_failed")

    def test_agent_runner_stream_events_are_forwarded(self) -> None:
        class FakeRunner:
            def stream(self, question: str):
                yield ExplorationAgentRunnerEvent(
                    type="tool.call.started",
                    payload={"tool": "search_resources", "call_id": "call_1"},
                )
                yield ExplorationAgentRunnerEvent(
                    type="tool.call.completed",
                    payload={"tool": "search_resources", "call_id": "call_1", "output": "ok"},
                )
                yield ExplorationAgentRunResult(final_output="最终结论", raw_result_type="FakeStreaming")

        service = ExplorationRunService(agent_runner=FakeRunner())

        events = list(service.stream_events(ExplorationRunRequest(question="复购率"), run_id="run_streaming"))

        self.assertIn("tool.call.started", [event.type for event in events])
        self.assertIn("tool.call.completed", [event.type for event in events])
        self.assertEqual(events[-2].payload["content"], "最终结论")
        self.assertEqual(events[-1].type, "run.completed")

    def test_agent_runner_async_stream_events_are_forwarded_before_final_output(self) -> None:
        class FakeRunner:
            async def async_stream(self, question: str):
                yield ExplorationAgentRunnerEvent(
                    type="tool.call.started",
                    payload={"tool": "search_resources", "call_id": "call_async"},
                )
                await asyncio.sleep(0)
                yield ExplorationAgentRunnerEvent(
                    type="tool.call.completed",
                    payload={"tool": "search_resources", "call_id": "call_async", "output": "ok"},
                )
                yield ExplorationAgentRunResult(final_output="异步最终结论", raw_result_type="FakeAsyncStreaming")

        async def collect_events() -> list:
            service = ExplorationRunService(agent_runner=FakeRunner())
            return [
                event
                async for event in service.astream_events(
                    ExplorationRunRequest(question="复购率"),
                    run_id="run_async_streaming",
                )
            ]

        events = asyncio.run(collect_events())
        event_types = [event.type for event in events]

        self.assertLess(event_types.index("tool.call.started"), event_types.index("tool.call.completed"))
        self.assertLess(event_types.index("tool.call.completed"), event_types.index("agent.runner.completed"))
        self.assertEqual(events[-2].payload["content"], "异步最终结论")
        self.assertEqual(events[-1].type, "run.completed")

    def test_async_stream_by_run_id_returns_failed_event_for_missing_run(self) -> None:
        async def collect_events() -> list:
            service = ExplorationRunService()
            return [event async for event in service.astream_run_events("run_missing")]

        events = asyncio.run(collect_events())

        self.assertEqual(events[0].type, "run.failed")
        self.assertEqual(events[0].payload["error"], "run_not_found")


if __name__ == "__main__":
    unittest.main()
