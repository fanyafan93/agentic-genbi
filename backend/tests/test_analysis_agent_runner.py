from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.runner_contracts import AnalysisAgentRunResult, build_analysis_runner_prompt
from backend.analysis.run_service import AnalysisRunRequest, AnalysisRunService
from backend.exploration.agent_runner import ExplorationAgentRunnerEvent


class AnalysisAgentRunnerTest(unittest.TestCase):
    def test_analysis_service_forwards_sync_agent_runner_events(self) -> None:
        class FakeRunner:
            def stream(self, prompt: str):
                yield ExplorationAgentRunnerEvent(type="agent.runner.raw", payload={"prompt_has_mode": "快速分析" in prompt})
                yield AnalysisAgentRunResult(final_output="真实 Codex Runner 输出", raw_result_type="FakeResult")

        service = AnalysisRunService(agent_runner=FakeRunner())
        events = service.run(
            AnalysisRunRequest(
                question="分析一下渠道销售占比",
                conversation_id="conv_analysis_runner",
                analysis_mode="quick",
            )
        )

        self.assertIn("agent.runner.started", [event.type for event in events])
        self.assertIn("agent.runner.completed", [event.type for event in events])
        self.assertIn("agent.runner.raw", [event.type for event in events])
        message = next(event for event in events if event.type == "agent.message.created")
        self.assertEqual(message.payload["content"], "真实 Codex Runner 输出")
        artifact_paths = [event.payload["path"] for event in events if event.type == "artifact.created"]
        self.assertIn("reports/quick_report.html", artifact_paths)
        self.assertIn("queries/quick_candidate.sql", artifact_paths)

    def test_analysis_service_does_not_complete_failed_agent_runner(self) -> None:
        class BrokenRunner:
            def stream(self, prompt: str):
                raise RuntimeError("runner exploded")

        service = AnalysisRunService(agent_runner=BrokenRunner())
        events = service.run(
            AnalysisRunRequest(
                question="分析一下渠道销售占比",
                conversation_id="conv_analysis_runner_failed",
                analysis_mode="quick",
            )
        )

        event_types = [event.type for event in events]
        self.assertIn("agent.runner.failed", event_types)
        self.assertIn("run.failed", event_types)
        self.assertNotIn("run.completed", event_types)

    def test_analysis_service_emits_skill_asset_after_agent_runner(self) -> None:
        class FakeRunner:
            def stream(self, prompt: str):
                yield AnalysisAgentRunResult(final_output="Skill 草稿说明", raw_result_type="FakeResult")

        service = AnalysisRunService(agent_runner=FakeRunner())
        events = service.run(
            AnalysisRunRequest(
                question="把这次分析沉淀成 skill.md",
                conversation_id="conv_analysis_skill_runner",
                analysis_mode="quick",
                turn_kind="message",
            )
        )

        artifact_paths = [event.payload["path"] for event in events if event.type == "artifact.created"]
        self.assertIn("skills/analysis_skill.md", artifact_paths)

    def test_reusable_report_and_sql_request_does_not_become_skill_asset(self) -> None:
        class FakeRunner:
            def stream(self, prompt: str):
                yield AnalysisAgentRunResult(final_output="报告和 SQL 初稿", raw_result_type="FakeResult")

        service = AnalysisRunService(agent_runner=FakeRunner())
        events = service.run(
            AnalysisRunRequest(
                question="生成可复用的分析报告和SQL资产",
                conversation_id="conv_analysis_reusable_assets_runner",
                analysis_mode="quick",
            )
        )

        artifact_paths = [event.payload["path"] for event in events if event.type == "artifact.created"]
        self.assertIn("reports/quick_report.html", artifact_paths)
        self.assertIn("queries/quick_candidate.sql", artifact_paths)
        self.assertNotIn("skills/analysis_skill.md", artifact_paths)

    def test_analysis_service_forwards_async_agent_runner_events(self) -> None:
        class FakeRunner:
            async def async_stream(self, prompt: str):
                yield ExplorationAgentRunnerEvent(type="agent.runner.raw", payload={"prompt_has_deep": "深度分析" in prompt})
                yield AnalysisAgentRunResult(final_output="异步 Codex Runner 输出", raw_result_type="FakeStreamedResult")

        async def collect_events() -> list:
            service = AnalysisRunService(agent_runner=FakeRunner())
            events = []
            async for event in service.astream_events(
                AnalysisRunRequest(
                    question="首购后 30 天复购率怎么算",
                    conversation_id="conv_analysis_runner_async",
                    analysis_mode="deep",
                )
            ):
                events.append(event)
            return events

        events = asyncio.run(collect_events())

        self.assertIn("agent.runner.started", [event.type for event in events])
        self.assertIn("agent.runner.completed", [event.type for event in events])
        self.assertIn("agent.runner.raw", [event.type for event in events])
        message = next(event for event in events if event.type == "agent.message.created")
        self.assertEqual(message.payload["content"], "异步 Codex Runner 输出")

    def test_analysis_runner_prompt_names_mode_models_and_problem_type(self) -> None:
        prompt = build_analysis_runner_prompt(
            question="首购后 30 天复购率怎么算",
            analysis_mode="deep",
            problem_label="指标口径",
            semantic_model_labels=["FineReport 报表级语义模型", "知识库已确认业务经验"],
        )

        self.assertIn("深度分析", prompt)
        self.assertIn("指标口径", prompt)
        self.assertIn("FineReport 报表级语义模型", prompt)


if __name__ == "__main__":
    unittest.main()
