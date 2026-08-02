from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.runner_contracts import (
    AnalysisAgentResult,
    AnalysisAgentRunnerEvent,
    build_analysis_runner_prompt,
)
from backend.analysis.turn_service import AnalysisTurnRequest, AnalysisTurnService


class AnalysisAgentRunnerTest(unittest.TestCase):
    def test_analysis_service_forwards_sync_agent_runner_events(self) -> None:
        class FakeRunner:
            def stream(self, prompt: str):
                yield AnalysisAgentRunnerEvent(
                    type="item/agentMessage/delta",
                    payload={"delta": "Real ", "codex_item_type": "agentMessage", "codex_method": "item/agentMessage/delta"},
                )
                yield AnalysisAgentResult(final_output="Real Codex Runner output", raw_result_type="FakeResult")

        service = AnalysisTurnService(agent_runner=FakeRunner())
        events = service.run(
            AnalysisTurnRequest(
                question="Analyze channel sales share",
                conversation_id="conv_analysis_runner",
            )
        )

        self.assertIn("item/agentMessage/delta", [event.type for event in events])
        message = next(event for event in events if event.type == "item/completed" and event.payload.get("codex_item_type") == "agentMessage")
        self.assertEqual(message.payload["content"], "Real Codex Runner output")

    def test_analysis_service_does_not_complete_failed_agent_runner(self) -> None:
        class BrokenRunner:
            def stream(self, prompt: str):
                raise RuntimeError("runner exploded")

        service = AnalysisTurnService(agent_runner=BrokenRunner())
        events = service.run(
            AnalysisTurnRequest(
                question="Analyze channel sales share",
                conversation_id="conv_analysis_runner_failed",
            )
        )

        event_types = [event.type for event in events]
        terminal_events = [event for event in events if event.type == "turn/completed"]
        self.assertEqual(len(terminal_events), 1)
        self.assertEqual(terminal_events[0].payload["status"], "failed")
        self.assertEqual(terminal_events[0].payload["error"], "analysis_agent_runner_failed")

    def test_analysis_service_does_not_duplicate_codex_completed_event(self) -> None:
        class CodexRunner:
            runtime_name = "openai-codex"

            def stream(self, prompt: str):
                yield AnalysisAgentRunnerEvent(
                    type="turn/completed",
                    payload={
                        "eventSource": "codex",
                        "codex_method": "turn/completed",
                        "status": "completed",
                    },
                )
                yield AnalysisAgentResult(final_output="Codex output", raw_result_type="FakeResult")

        service = AnalysisTurnService(agent_runner=CodexRunner())
        events = service.run(AnalysisTurnRequest(question="Analyze channel sales share"))

        completed_events = [event for event in events if event.type == "turn/completed"]
        self.assertEqual(len(completed_events), 1)
        self.assertEqual(completed_events[0].payload["eventSource"], "codex")

    def test_analysis_service_does_not_invent_skill_asset_after_agent_runner(self) -> None:
        class FakeRunner:
            def stream(self, prompt: str):
                yield AnalysisAgentResult(final_output="Skill draft", raw_result_type="FakeResult")

        service = AnalysisTurnService(agent_runner=FakeRunner())
        events = service.run(
            AnalysisTurnRequest(
                question="Turn this analysis into skill.md",
                conversation_id="conv_analysis_skill_runner",
                turn_kind="message",
            )
        )

        artifact_paths = [event.payload["path"] for event in events if event.type == "genbi/artifact/created"]
        self.assertNotIn("skills/analysis_skill.md", artifact_paths)

    def test_reusable_report_and_sql_request_does_not_become_skill_asset(self) -> None:
        class FakeRunner:
            def stream(self, prompt: str):
                yield AnalysisAgentResult(final_output="Report and SQL draft", raw_result_type="FakeResult")

        service = AnalysisTurnService(agent_runner=FakeRunner())
        events = service.run(
            AnalysisTurnRequest(
                question="Generate reusable analysis report and SQL assets",
                conversation_id="conv_analysis_reusable_assets_runner",
            )
        )

        artifact_paths = [event.payload["path"] for event in events if event.type == "genbi/artifact/created"]
        self.assertNotIn("skills/analysis_skill.md", artifact_paths)

    def test_analysis_service_forwards_async_agent_runner_events(self) -> None:
        class FakeRunner:
            async def async_stream(self, prompt: str):
                yield AnalysisAgentRunnerEvent(
                    type="item/agentMessage/delta",
                    payload={"delta": "Async ", "codex_item_type": "agentMessage", "codex_method": "item/agentMessage/delta"},
                )
                yield AnalysisAgentResult(final_output="Async Codex Runner output", raw_result_type="FakeStreamedResult")

        async def collect_events() -> list:
            service = AnalysisTurnService(agent_runner=FakeRunner())
            events = []
            async for event in service.astream_events(
                AnalysisTurnRequest(
                    question="How to calculate 30 day repeat purchase rate?",
                    conversation_id="conv_analysis_runner_async",
                )
            ):
                events.append(event)
            return events

        events = asyncio.run(collect_events())

        self.assertIn("item/agentMessage/delta", [event.type for event in events])
        message = next(event for event in events if event.type == "item/completed" and event.payload.get("codex_item_type") == "agentMessage")
        self.assertEqual(message.payload["content"], "Async Codex Runner output")

    def test_submitted_turn_stream_uses_async_runner_without_falling_back_to_sync(self) -> None:
        class AsyncOnlyRunner:
            async def async_stream(self, prompt: str):
                yield AnalysisAgentResult(final_output="SSE async output", raw_result_type="AsyncOnlyResult")

        async def collect_events() -> list:
            service = AnalysisTurnService(agent_runner=AsyncOnlyRunner())
            submission = service.submit_turn(
                AnalysisTurnRequest(
                    question="Stream this turn through the async runner",
                    conversation_id="conv_analysis_submitted_async",
                )
            )
            events = []
            async for event in service.astream_turn_events(submission.turn_id):
                events.append(event)
            return events

        events = asyncio.run(collect_events())

        message = next(event for event in events if event.type == "item/completed" and event.payload.get("codex_item_type") == "agentMessage")
        self.assertEqual(message.payload["content"], "SSE async output")
        self.assertFalse(any(event.type == "turn/completed" and event.payload.get("status") == "failed" for event in events))

    def test_analysis_runner_prompt_names_models_and_problem_type(self) -> None:
        prompt = build_analysis_runner_prompt(
            question="How to calculate 30 day repeat purchase rate?",
            problem_label="Metric definition",
            semantic_model_labels=["FineReport semantic model", "Verified business knowledge"],
        )

        self.assertIn("Metric definition", prompt)
        self.assertIn("FineReport semantic model", prompt)
        self.assertNotIn("interactive_report_draft", prompt)


if __name__ == "__main__":
    unittest.main()
