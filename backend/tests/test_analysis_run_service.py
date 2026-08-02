from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.runner_contracts import AnalysisAgentRunResult
from backend.analysis.run_service import AnalysisRunRequest, AnalysisRunService, AnalysisThreadService, classify_analysis_problem
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_service import ExplorationRunEvent
from backend.exploration.run_trace_store import RunTraceStore
from backend.harness.thread_store import ThreadStore


class _CodexThreadRecordingRunner:
    runtime_name = "openai-codex"

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def stream(self, prompt: str, *, context: dict):
        self.contexts.append(dict(context))
        codex_thread_id = context.get("codex_thread_id") or "codex_thread_created"
        yield ExplorationRunEvent(
            type="agent.runner.raw",
            run_id=str(context.get("execution_attempt_id") or context.get("genbi_run_id") or "run_test"),
            payload={
                "runtime": "openai-codex",
                "phase": "thread.opened",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_created",
                "resumed": bool(context.get("codex_thread_id")),
            },
        )
        yield AnalysisAgentRunResult(final_output="Codex ok", raw_result_type="FakeCodex", events=[])


class AnalysisRunServiceTest(unittest.TestCase):
    def test_analysis_emits_assets_and_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = AnalysisRunService(
                trace_store=RunTraceStore(root / "traces.jsonl"),
                event_store=RunEventStore(root / "events.jsonl"),
                thread_store=ThreadStore(root / "thread-store.jsonl"),
            )
            events = service.run(
                AnalysisRunRequest(
                    question="分析一下渠道销售占比",
                    conversation_id="conv_analysis_test",
                )
            )

            event_types = [event.type for event in events]
            artifact_paths = [event.payload["path"] for event in events if event.type == "artifact.created"]

            self.assertIn("turn/started", event_types)
            self.assertIn("analysis.problem.classified", event_types)
            self.assertIn("analysis.retrieval.plan", event_types)
            self.assertIn("agent.message.created", event_types)
            self.assertIn("item/completed", event_types)
            self.assertIn("genbi/artifact/created", event_types)
            self.assertIn("turn/completed", event_types)
            self.assertNotIn("run.created", event_types)
            self.assertNotIn("run.completed", event_types)
            self.assertIn("reports/analysis_report.html", artifact_paths)
            self.assertIn("queries/candidate.sql", artifact_paths)
            first = next(event for event in events if event.type == "turn/started")
            self.assertEqual(first.payload["thread_id"], "conv_analysis_test")
            self.assertTrue(str(first.payload["turn_id"]).startswith("analysis_turn_"))
            self.assertNotIn(first.payload["run_id"].removeprefix("run_"), first.payload["turn_id"])
            self.assertEqual(first.payload["item_kind"], "message")
            self.assertTrue(str(first.payload["item_id"]).startswith("item_analysis_"))
            artifact = next(event for event in events if event.payload.get("path") == "queries/candidate.sql")
            self.assertEqual(artifact.payload["item_kind"], "sql")
            self.assertEqual(artifact.payload["thread_id"], "conv_analysis_test")
            self.assertEqual(artifact.payload["turn_id"], first.payload["turn_id"])

            self.assertEqual(service.trace_store.list_traces(), [])
            self.assertEqual(service.event_store.list_events(events[0].run_id), [])

            thread = service.thread_store.get_thread("conv_analysis_test")
            self.assertIsNotNone(thread)
            assert thread is not None
            self.assertEqual(thread["thread"]["productKind"], "analysis_task")
            self.assertEqual(thread["turns"][0]["inputKind"], "start")
            self.assertEqual(thread["runs"][0]["id"], events[0].run_id)
            self.assertIn("sql", [item["kind"] for item in thread["items"]])

    def test_thread_service_submits_turn_with_execution_attempt_compatibility(self) -> None:
        service = AnalysisThreadService()
        submission = service.submit_turn(AnalysisRunRequest(
            question="渠道销售占比",
            conversation_id="analysis_thread_1",
            turn_kind="message",
        ))
        events = list(service.stream_turn_events(submission.execution_attempt_id))

        self.assertEqual(submission.thread_id, "analysis_thread_1")
        self.assertTrue(submission.turn_id.startswith("analysis_turn_"))
        self.assertTrue(submission.execution_attempt_id.startswith("run_analysis_"))
        self.assertEqual(events[0].run_id, submission.execution_attempt_id)
        self.assertEqual(events[0].payload["thread_id"], submission.thread_id)
        self.assertEqual(events[0].payload["turn_id"], submission.turn_id)

    def test_run_named_methods_remain_compatibility_shims(self) -> None:
        service = AnalysisThreadService()
        execution_attempt_id = service.create_run(AnalysisRunRequest(question="渠道销售占比"))
        events = list(service.stream_run_events(execution_attempt_id))

        self.assertTrue(execution_attempt_id.startswith("run_analysis_"))
        self.assertEqual(events[0].run_id, execution_attempt_id)
        self.assertIn("turn_id", events[0].payload)

    def test_missing_turn_attempt_uses_new_error_with_run_compatibility(self) -> None:
        service = AnalysisThreadService()
        turn_events = list(service.stream_turn_events("missing_attempt"))
        run_events = list(service.stream_run_events("missing_attempt"))

        self.assertEqual(turn_events[0].payload["error"], "execution_attempt_not_found")
        self.assertEqual(run_events[0].payload["error"], "run_not_found")

    def test_async_turn_missing_attempt_uses_execution_attempt_error(self) -> None:
        import asyncio

        async def collect() -> list[ExplorationRunEvent]:
            service = AnalysisThreadService()
            events = []
            async for event in service.astream_turn_events("missing_attempt"):
                events.append(event)
            return events

        events = asyncio.run(collect())

        self.assertEqual(events[0].payload["error"], "execution_attempt_not_found")

    def test_analysis_uses_full_semantic_plan_without_mode_switch(self) -> None:
        service = AnalysisRunService()
        events = service.run(
            AnalysisRunRequest(
                question="首购后 30 天复购率怎么算",
                conversation_id="conv_analysis_deep",
            )
        )

        plan = next(event for event in events if event.type == "analysis.retrieval.plan")

        labels = [item["label"] for item in plan.payload["items"]]
        self.assertIn("FineReport 报表级语义模型", labels)
        self.assertIn("金蝶数据字典语义模型", labels)
        self.assertIn("ETL / Hop 血缘语义模型", labels)
        self.assertNotIn("agent.question.requested", [event.type for event in events])

    def test_problem_classifier_recognizes_metric_diagnosis(self) -> None:
        classification = classify_analysis_problem("华东 GMV 下滑原因")

        self.assertEqual(classification.type, "metric_diagnosis")
        self.assertEqual(classification.label, "异常归因")


    def test_codex_thread_id_is_persisted_and_restored_for_followup_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runner = _CodexThreadRecordingRunner()
            service = AnalysisRunService(agent_runner=runner, thread_store=thread_store)

            first = service.run(
                AnalysisRunRequest(
                    question="first analysis question",
                    conversation_id="thread_codex_resume",
                )
            )
            second = service.run(
                AnalysisRunRequest(
                    question="continue this analysis",
                    conversation_id="thread_codex_resume",
                    turn_kind="message",
                )
            )

            thread = thread_store.get_thread("thread_codex_resume")

            self.assertIsNotNone(thread)
            assert thread is not None
            self.assertEqual(thread["thread"]["metadata"]["codex_thread_id"], "codex_thread_created")
            self.assertEqual(thread["turns"][0]["codexTurnId"], "codex_turn_created")
            self.assertTrue(runner.contexts[0]["execution_attempt_id"].startswith("run_analysis_"))
            self.assertIsNone(runner.contexts[0]["codex_thread_id"])
            self.assertEqual(runner.contexts[1]["codex_thread_id"], "codex_thread_created")
            self.assertFalse(next(event for event in first if event.payload.get("phase") == "thread.opened").payload["resumed"])
            self.assertTrue(next(event for event in second if event.payload.get("phase") == "thread.opened").payload["resumed"])


if __name__ == "__main__":
    unittest.main()

