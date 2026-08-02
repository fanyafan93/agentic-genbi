from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.runner_contracts import AnalysisAgentResult, AnalysisAgentRunnerEvent
from backend.analysis.turn_service import AnalysisTurnRequest, AnalysisTurnService, AnalysisThreadService, classify_analysis_problem
from backend.harness.thread_store import ThreadStore


class _CodexThreadRecordingRunner:
    runtime_name = "openai-codex"

    def __init__(self) -> None:
        self.contexts: list[dict] = []

    def stream(self, prompt: str, *, context: dict):
        self.contexts.append(dict(context))
        codex_thread_id = context.get("codex_thread_id") or "codex_thread_created"
        yield AnalysisAgentRunnerEvent(
            type="turn/started",
            payload={
                "runtime": "openai-codex",
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_created",
                "resumed": bool(context.get("codex_thread_id")),
            },
        )
        yield AnalysisAgentResult(final_output="Codex ok", raw_result_type="FakeCodex", events=[])


class AnalysisTurnServiceTest(unittest.TestCase):
    def test_analysis_without_runner_fails_without_synthetic_items_or_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = AnalysisTurnService(thread_store=ThreadStore(Path(temp_dir) / "thread-store.jsonl"))
            events = service.run(
                AnalysisTurnRequest(
                    question="analyze channel sales",
                    conversation_id="conv_analysis_test",
                )
            )

            event_types = [event.type for event in events]
            self.assertIn("turn/started", event_types)
            self.assertIn("turn/completed", event_types)
            self.assertNotIn("item/completed", event_types)
            self.assertFalse(any(event.type.startswith("genbi/artifact/") for event in events))
            completed = next(event for event in events if event.type == "turn/completed")
            self.assertEqual(completed.payload["status"], "failed")
            self.assertEqual(completed.payload["error"], "analysis_agent_runner_not_configured")

            first = next(event for event in events if event.type == "turn/started")
            self.assertEqual(first.turn_id, first.payload["turn_id"])
            self.assertEqual(first.payload["thread_id"], "conv_analysis_test")
            self.assertTrue(str(first.payload["turn_id"]).startswith("analysis_turn_"))
            self.assertEqual(first.payload["item_kind"], "message")

            thread = service.thread_store.get_thread("conv_analysis_test")  # type: ignore[union-attr]
            self.assertIsNotNone(thread)
            assert thread is not None
            self.assertEqual(thread["thread"]["productKind"], "analysis_task")
            self.assertEqual(thread["turns"][0]["inputKind"], "start")
            self.assertNotIn("runs", thread)
            self.assertNotIn("sql", [item["kind"] for item in thread["items"]])

    def test_thread_service_submits_turn_with_thread_turn_contract(self) -> None:
        service = AnalysisThreadService()
        submission = service.submit_turn(
            AnalysisTurnRequest(
                question="channel sales share",
                conversation_id="analysis_thread_1",
                turn_kind="message",
            )
        )
        events = list(service.stream_turn_events(submission.turn_id))

        self.assertEqual(submission.thread_id, "analysis_thread_1")
        self.assertTrue(submission.turn_id.startswith("analysis_turn_"))
        self.assertEqual(events[0].turn_id, submission.turn_id)
        self.assertEqual(events[0].payload["thread_id"], submission.thread_id)
        self.assertEqual(events[0].payload["turn_id"], submission.turn_id)

    def test_missing_turn_uses_turn_error(self) -> None:
        service = AnalysisThreadService()
        events = list(service.stream_turn_events("missing_turn"))

        self.assertEqual(events[0].type, "turn/completed")
        self.assertEqual(events[0].payload["status"], "failed")
        self.assertEqual(events[0].payload["error"], "turn_not_found")
        self.assertEqual(len([event for event in events if event.type == "turn/completed"]), 1)

    def test_async_turn_missing_uses_turn_error(self) -> None:
        async def collect():
            service = AnalysisThreadService()
            events = []
            async for event in service.astream_turn_events("missing_turn"):
                events.append(event)
            return events

        events = asyncio.run(collect())

        self.assertEqual(events[0].type, "turn/completed")
        self.assertEqual(events[0].payload["status"], "failed")
        self.assertEqual(events[0].payload["error"], "turn_not_found")
        self.assertEqual(len([event for event in events if event.type == "turn/completed"]), 1)

    def test_analysis_does_not_emit_synthetic_plan_or_question_events(self) -> None:
        events = AnalysisTurnService().run(
            AnalysisTurnRequest(
                question="first purchase 30d repurchase definition",
                conversation_id="conv_analysis_deep",
            )
        )

        allowed_prefixes = ("turn/", "item/", "genbi/")
        self.assertTrue(all(event.type.startswith(allowed_prefixes) for event in events))
        self.assertFalse(any(event.type == "item/completed" and event.payload.get("codex_item_type") == "agentQuestion" for event in events))

    def test_problem_classifier_recognizes_metric_diagnosis(self) -> None:
        classification = classify_analysis_problem("East region GMV drop reason")

        self.assertEqual(classification.type, "metric_diagnosis")
        self.assertEqual(classification.label, "metric diagnosis")

    def test_codex_thread_id_is_persisted_and_restored_for_followup_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runner = _CodexThreadRecordingRunner()
            service = AnalysisTurnService(agent_runner=runner, thread_store=thread_store)

            first = service.run(
                AnalysisTurnRequest(
                    question="first analysis question",
                    conversation_id="thread_codex_resume",
                )
            )
            second = service.run(
                AnalysisTurnRequest(
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
            self.assertIn("genbi_turn_id", runner.contexts[0])
            self.assertIsNone(runner.contexts[0]["codex_thread_id"])
            self.assertEqual(runner.contexts[1]["codex_thread_id"], "codex_thread_created")
            self.assertFalse(next(event for event in first if event.type == "turn/started" and event.payload.get("eventSource") == "codex").payload["resumed"])
            self.assertTrue(next(event for event in second if event.type == "turn/started" and event.payload.get("eventSource") == "codex").payload["resumed"])


if __name__ == "__main__":
    unittest.main()
