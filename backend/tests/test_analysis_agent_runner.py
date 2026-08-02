from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.report_query_service import CHANNEL_SALES_QUERY_REF
from backend.analysis.runner_contracts import (
    AnalysisAgentResult,
    AnalysisAgentRunnerEvent,
    build_analysis_runner_prompt,
    extract_interactive_report_draft,
    sanitize_interactive_report_context,
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
        self.assertIn("turn/failed", event_types)
        self.assertNotIn("turn/completed", event_types)

    def test_analysis_service_emits_skill_asset_after_agent_runner(self) -> None:
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
        self.assertIn("skills/analysis_skill.md", artifact_paths)

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

    def test_analysis_runner_prompt_names_models_and_problem_type(self) -> None:
        prompt = build_analysis_runner_prompt(
            question="How to calculate 30 day repeat purchase rate?",
            problem_label="Metric definition",
            semantic_model_labels=["FineReport semantic model", "Verified business knowledge"],
        )

        self.assertIn("Metric definition", prompt)
        self.assertIn("FineReport semantic model", prompt)
        self.assertIn("finereport-operation-management-channel-sales", prompt)
        self.assertIn("salesAmount", prompt)

    def test_report_draft_rejects_unregistered_query_reference(self) -> None:
        message, draft = extract_interactive_report_draft(
            "Report structure below\n"
            "<interactive_report_draft>"
            '{"title":"Test","subtitle":"Test","document":{"root":{},"content":[]},"filters":[],'
            '"queries":{"unregistered-query":{"datasetId":"anything","filterBindings":[]}},'
            '"chartSpecs":{},"gridSpecs":{}}'
            "</interactive_report_draft>"
        )

        self.assertIsNone(draft)
        self.assertIn("unregistered-query", message)

    def test_report_draft_keeps_registered_content_when_model_adds_unknown_query(self) -> None:
        message, draft = extract_interactive_report_draft(
            "Report structure below\n"
            "<interactive_report_draft>"
            '{"title":"Test","subtitle":"Test","document":{"root":{},"content":['
            '{"type":"ChartBlock","props":{"queryRef":"finereport-operation-management-channel-sales","chartSpecRef":"channel-chart"}},'
            '{"type":"ChartBlock","props":{"queryRef":"unregistered-platform","chartSpecRef":"platform-chart"}}],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"},'
            '"unregistered-platform":{"datasetId":"platform-sales"}},'
            '"chartSpecs":{"channel-chart":{"datasetId":"channel-sales"},"platform-chart":{"datasetId":"platform-sales"}},'
            '"gridSpecs":{}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "Report structure below")
        self.assertIsNotNone(draft)
        self.assertEqual(set(draft["queries"]), {CHANNEL_SALES_QUERY_REF})
        self.assertEqual(set(draft["chartSpecs"]), {"channel-chart"})
        self.assertEqual(len(draft["document"]["content"]), 1)

    def test_report_draft_accepts_model_markdown_with_unescaped_newlines(self) -> None:
        message, draft = extract_interactive_report_draft(
            "Updated report\n"
            "<interactive_report_draft>"
            '{"title":"Test","subtitle":"Test","document":{"root":{},"content":[{"type":"MarkdownBlock","props":{"content":"line one\nline two"}}],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "Updated report")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["document"]["content"][0]["props"]["content"], "line one\nline two")

    def test_report_draft_accepts_accidental_trailing_closing_brace(self) -> None:
        message, draft = extract_interactive_report_draft(
            "Updated report\n"
            "<interactive_report_draft>"
            '{"title":"Test","subtitle":"Test","document":{"root":{},"content":[],"zones":{}},"filters":[],'
            '"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "Updated report")
        self.assertIsNotNone(draft)

    def test_report_draft_accepts_missing_outer_closing_brace(self) -> None:
        message, draft = extract_interactive_report_draft(
            "Updated report\n"
            "<interactive_report_draft>"
            '{"title":"Test","subtitle":"Test","document":{"root":{},"content":[],"zones":{}},"filters":[],'
            '"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "Updated report")
        self.assertIsNotNone(draft)

    def test_report_draft_lifts_model_nested_report_fields(self) -> None:
        message, draft = extract_interactive_report_draft(
            "Updated report\n"
            "<interactive_report_draft>"
            '{"title":"Test","subtitle":"Test","document":{"root":{"root":{},"content":[],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "Updated report")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["document"], {"root": {}, "content": [], "zones": {}})
        self.assertIn("finereport-operation-management-channel-sales", draft["queries"])

    def test_report_draft_wraps_flattened_puck_root_props(self) -> None:
        message, draft = extract_interactive_report_draft(
            "Updated report\n"
            "<interactive_report_draft>"
            '{"title":"Test","subtitle":"Test","document":{"props":{"title":"Test"},"content":[],"zones":{}},"filters":[],'
            '"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "Updated report")
        self.assertEqual(draft["document"]["root"], {"props": {"title": "Test"}})

    def test_authorized_report_context_is_bounded_and_requires_registered_query(self) -> None:
        report = {
            "id": "report_channel_sales",
            "title": "Channel Sales Result",
            "subtitle": "2026-05",
            "document": {"root": {}, "content": [], "zones": {}},
            "filters": [],
            "queries": {"finereport-operation-management-channel-sales": {"datasetId": "channel-sales"}},
            "chartSpecs": {},
            "gridSpecs": {},
            "source": {"threadId": "ignored"},
        }
        context = sanitize_interactive_report_context(report)
        prompt = build_analysis_runner_prompt(
            question="Break down by region",
            problem_label="Business review",
            semantic_model_labels=[],
            current_report_context=context,
        )

        self.assertIsNotNone(context)
        self.assertEqual(context["id"], "report_channel_sales")
        self.assertNotIn("source", context)
        self.assertIn("Channel Sales Result", prompt)
        report["queries"] = {"not-registered": {}}
        self.assertIsNone(sanitize_interactive_report_context(report))

    def test_report_context_is_not_controlled_by_data_egress_authorization(self) -> None:
        report = {
            "id": "report_channel_sales",
            "title": "Channel Sales Result",
            "subtitle": "2026-05",
            "document": {"root": {}, "content": [], "zones": {}},
            "filters": [],
            "queries": {"finereport-operation-management-channel-sales": {"datasetId": "channel-sales"}},
            "chartSpecs": {},
            "gridSpecs": {},
        }

        class FakeRunner:
            def stream(self, prompt: str):
                self.prompt = prompt
                yield AnalysisAgentResult(final_output="Updated report", raw_result_type="FakeResult")

        runner = FakeRunner()
        service = AnalysisTurnService(agent_runner=runner)
        service.run(AnalysisTurnRequest(question="Break down by region", metadata={"interactive_report_context": report}))
        self.assertIn("Channel Sales Result", runner.prompt)

        service.run(
            AnalysisTurnRequest(
                question="Break down by region",
                metadata={"data_egress_authorized": True, "interactive_report_context": report},
            )
        )
        self.assertIn("Channel Sales Result", runner.prompt)


if __name__ == "__main__":
    unittest.main()
