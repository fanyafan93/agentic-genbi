from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.runner_contracts import AnalysisAgentRunResult, build_analysis_runner_prompt, extract_interactive_report_draft, sanitize_interactive_report_context
from backend.analysis.run_service import AnalysisRunRequest, AnalysisRunService
from backend.analysis.report_query_service import CHANNEL_SALES_QUERY_REF
from backend.exploration.agent_runner import ExplorationAgentRunnerEvent


class AnalysisAgentRunnerTest(unittest.TestCase):
    def test_analysis_service_forwards_sync_agent_runner_events(self) -> None:
        class FakeRunner:
            def stream(self, prompt: str):
                yield ExplorationAgentRunnerEvent(type="agent.runner.raw", payload={"prompt_mentions_mode": "分析模式" in prompt})
                yield AnalysisAgentRunResult(final_output="真实 Codex Runner 输出", raw_result_type="FakeResult")

        service = AnalysisRunService(agent_runner=FakeRunner())
        events = service.run(
                AnalysisRunRequest(
                    question="分析一下渠道销售占比",
                    conversation_id="conv_analysis_runner",
                )
        )

        self.assertIn("agent.runner.started", [event.type for event in events])
        self.assertIn("agent.runner.completed", [event.type for event in events])
        self.assertIn("agent.runner.raw", [event.type for event in events])
        prompt_event = next(event for event in events if event.type == "agent.prompt.created")
        self.assertIn("用户问题：分析一下渠道销售占比", prompt_event.payload["prompt"])
        message = next(event for event in events if event.type == "agent.message.created")
        self.assertEqual(message.payload["content"], "真实 Codex Runner 输出")
        artifact_paths = [event.payload["path"] for event in events if event.type == "artifact.created"]
        self.assertIn("reports/analysis_report.html", artifact_paths)
        self.assertIn("queries/candidate.sql", artifact_paths)

    def test_analysis_service_does_not_complete_failed_agent_runner(self) -> None:
        class BrokenRunner:
            def stream(self, prompt: str):
                raise RuntimeError("runner exploded")

        service = AnalysisRunService(agent_runner=BrokenRunner())
        events = service.run(
                AnalysisRunRequest(
                    question="分析一下渠道销售占比",
                    conversation_id="conv_analysis_runner_failed",
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
                )
        )

        artifact_paths = [event.payload["path"] for event in events if event.type == "artifact.created"]
        self.assertIn("reports/analysis_report.html", artifact_paths)
        self.assertIn("queries/candidate.sql", artifact_paths)
        self.assertNotIn("skills/analysis_skill.md", artifact_paths)

    def test_analysis_service_forwards_async_agent_runner_events(self) -> None:
        class FakeRunner:
            async def async_stream(self, prompt: str):
                yield ExplorationAgentRunnerEvent(type="agent.runner.raw", payload={"prompt_mentions_mode": "分析模式" in prompt})
                yield AnalysisAgentRunResult(final_output="异步 Codex Runner 输出", raw_result_type="FakeStreamedResult")

        async def collect_events() -> list:
            service = AnalysisRunService(agent_runner=FakeRunner())
            events = []
            async for event in service.astream_events(
                AnalysisRunRequest(
                    question="首购后 30 天复购率怎么算",
                    conversation_id="conv_analysis_runner_async",
                )
            ):
                events.append(event)
            return events

        events = asyncio.run(collect_events())

        self.assertIn("agent.runner.started", [event.type for event in events])
        self.assertIn("agent.runner.completed", [event.type for event in events])
        self.assertIn("agent.runner.raw", [event.type for event in events])
        prompt_event = next(event for event in events if event.type == "agent.prompt.created")
        self.assertIn("用户问题：首购后 30 天复购率怎么算", prompt_event.payload["prompt"])
        message = next(event for event in events if event.type == "agent.message.created")
        self.assertEqual(message.payload["content"], "异步 Codex Runner 输出")

    def test_analysis_runner_prompt_names_models_and_problem_type(self) -> None:
        prompt = build_analysis_runner_prompt(
            question="首购后 30 天复购率怎么算",
            problem_label="指标口径",
            semantic_model_labels=["FineReport 报表级语义模型", "知识库已确认业务经验"],
        )

        self.assertNotIn("分析模式", prompt)
        self.assertIn("指标口径", prompt)
        self.assertIn("FineReport 报表级语义模型", prompt)
        self.assertIn("finereport-operation-management-channel-sales", prompt)
        self.assertIn("salesAmount", prompt)

    def test_report_draft_rejects_unregistered_query_reference(self) -> None:
        message, draft = extract_interactive_report_draft(
            "报告结构如下\n"
            "<interactive_report_draft>"
            '{"title":"测试","subtitle":"测试","document":{"root":{},"content":[],"zones":{}},'
            '"filters":[],"queries":{"unregistered-query":{"datasetId":"anything","filterBindings":[]}},'
            '"chartSpecs":{},"gridSpecs":{}}'
            "</interactive_report_draft>"
        )

        self.assertIsNone(draft)
        self.assertIn("unregistered-query", message)

    def test_report_draft_keeps_registered_content_when_model_adds_unknown_query(self) -> None:
        message, draft = extract_interactive_report_draft(
            "报告结构如下\n"
            "<interactive_report_draft>"
            '{"title":"测试","subtitle":"测试","document":{"root":{},"content":[{"type":"ChartBlock","props":{"queryRef":"finereport-operation-management-channel-sales","chartSpecRef":"channel-chart"}},{"type":"ChartBlock","props":{"queryRef":"unregistered-platform","chartSpecRef":"platform-chart"}}],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"},"unregistered-platform":{"datasetId":"platform-sales"}},'
            '"chartSpecs":{"channel-chart":{"datasetId":"channel-sales"},"platform-chart":{"datasetId":"platform-sales"}},"gridSpecs":{}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "报告结构如下")
        self.assertIsNotNone(draft)
        self.assertEqual(set(draft["queries"]), {CHANNEL_SALES_QUERY_REF})
        self.assertEqual(set(draft["chartSpecs"]), {"channel-chart"})
        self.assertEqual(len(draft["document"]["content"]), 1)

    def test_report_draft_accepts_model_markdown_with_unescaped_newlines(self) -> None:
        message, draft = extract_interactive_report_draft(
            "已更新报告\n"
            "<interactive_report_draft>"
            '{"title":"测试","subtitle":"测试","document":{"root":{},"content":[{"type":"MarkdownBlock","props":{"content":"第一行\n第二行"}}],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},"chartSpecs":{},"gridSpecs":{}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "已更新报告")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["document"]["content"][0]["props"]["content"], "第一行\n第二行")

    def test_report_draft_accepts_accidental_trailing_closing_brace(self) -> None:
        message, draft = extract_interactive_report_draft(
            "已更新报告\n"
            "<interactive_report_draft>"
            '{"title":"测试","subtitle":"测试","document":{"root":{},"content":[],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "已更新报告")
        self.assertIsNotNone(draft)

    def test_report_draft_accepts_missing_outer_closing_brace(self) -> None:
        message, draft = extract_interactive_report_draft(
            "已更新报告\n"
            "<interactive_report_draft>"
            '{"title":"测试","subtitle":"测试","document":{"root":{},"content":[],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "已更新报告")
        self.assertIsNotNone(draft)

    def test_report_draft_lifts_model_nested_report_fields(self) -> None:
        message, draft = extract_interactive_report_draft(
            "已更新报告\n"
            "<interactive_report_draft>"
            '{"title":"测试","subtitle":"测试","document":{"root":{"root":{},"content":[],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "已更新报告")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["document"], {"root": {}, "content": [], "zones": {}})
        self.assertIn("finereport-operation-management-channel-sales", draft["queries"])

    def test_report_draft_wraps_flattened_puck_root_props(self) -> None:
        message, draft = extract_interactive_report_draft(
            "已更新报告\n"
            "<interactive_report_draft>"
            '{"title":"测试","subtitle":"测试","document":{"props":{"title":"测试"},"content":[],"zones":{}},'
            '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
            '"chartSpecs":{},"gridSpecs":{}}'
            "</interactive_report_draft>"
        )

        self.assertEqual(message, "已更新报告")
        self.assertEqual(draft["document"]["root"], {"props": {"title": "测试"}})

    def test_authorized_report_context_is_bounded_and_requires_registered_query(self) -> None:
        report = {
            "id": "report_channel_sales",
            "title": "渠道销售结构",
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
            question="按区域拆开",
            problem_label="经营复盘",
            semantic_model_labels=[],
            current_report_context=context,
        )

        self.assertIsNotNone(context)
        self.assertEqual(context["id"], "report_channel_sales")
        self.assertNotIn("source", context)
        self.assertIn("当前基线", prompt)
        self.assertIn("渠道销售结构", prompt)
        report["queries"] = {"not-registered": {}}
        self.assertIsNone(sanitize_interactive_report_context(report))

    def test_report_context_is_not_controlled_by_data_egress_authorization(self) -> None:
        report = {
            "id": "report_channel_sales",
            "title": "渠道销售结构",
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
                yield AnalysisAgentRunResult(final_output="更新后的报告", raw_result_type="FakeResult")

        runner = FakeRunner()
        service = AnalysisRunService(agent_runner=runner)
        service.run(AnalysisRunRequest(question="按区域拆开", metadata={"interactive_report_context": report}))
        self.assertIn("渠道销售结构", runner.prompt)

        service.run(
            AnalysisRunRequest(
                question="按区域拆开",
                metadata={"data_egress_authorized": True, "interactive_report_context": report},
            )
        )
        self.assertIn("渠道销售结构", runner.prompt)

    def test_continuation_draft_keeps_current_report_id(self) -> None:
        report = {
            "id": "report_channel_sales",
            "title": "渠道销售结构",
            "subtitle": "2026-05",
            "document": {"root": {}, "content": [], "zones": {}},
            "filters": [],
            "queries": {CHANNEL_SALES_QUERY_REF: {"datasetId": "channel-sales"}},
            "chartSpecs": {},
            "gridSpecs": {},
        }

        class FakeRunner:
            def stream(self, prompt: str):
                yield AnalysisAgentRunResult(
                    final_output=(
                        "已更新\n<interactive_report_draft>"
                        '{"title":"渠道销售结构","subtitle":"已更新","document":{"root":{},"content":[],"zones":{}},'
                        '"filters":[],"queries":{"finereport-operation-management-channel-sales":{"datasetId":"channel-sales"}},'
                        '"chartSpecs":{},"gridSpecs":{}}'
                        "</interactive_report_draft>"
                    ),
                    raw_result_type="FakeResult",
                )

        events = AnalysisRunService(agent_runner=FakeRunner()).run(
            AnalysisRunRequest(question="补充说明", metadata={"interactive_report_context": report})
        )
        draft = next(event.payload for event in events if event.type == "interactive_report.draft")
        self.assertEqual(draft["id"], "report_channel_sales")

    def test_legacy_data_egress_authorization_is_ignored(self) -> None:
        test_case = self

        class QueryService:
            def run(self, query_ref: str, filters: dict[str, object], *, audit_context: dict[str, object] | None = None) -> ReportQueryResponse:
                test_case.fail("Legacy data egress metadata must not trigger report query snapshots.")

        class FakeRunner:
            def stream(self, prompt: str):
                self.prompt = prompt
                yield AnalysisAgentRunResult(final_output="基于快照的结论", raw_result_type="FakeResult")

        runner = FakeRunner()
        events = AnalysisRunService(agent_runner=runner, report_query_service=QueryService()).run(
            AnalysisRunRequest(
                question="请分析 2026-05 渠道销售占比",
                metadata={"data_egress_authorized": True},
            )
        )

        self.assertNotIn('"salesAmount":100', runner.prompt)
        self.assertNotIn("本轮必须在回复末尾输出完整的 <interactive_report_draft>", runner.prompt)
        self.assertNotIn("agent.evidence.available", [event.type for event in events])

    def test_legacy_finereport_semantic_context_authorization_is_ignored(self) -> None:
        class SemanticRepository:
            def __init__(self) -> None:
                self.calls = 0

            def build_agent_semantic_context(self) -> dict[str, object]:
                self.calls += 1
                return {
                    "kind": "finereport_report_semantics",
                    "reports": [{"id": "finereport_safe", "name": "预算管控", "datasets": [], "bindings": []}],
                }

        class FakeRunner:
            def stream(self, prompt: str):
                self.prompt = prompt
                yield AnalysisAgentRunResult(final_output="已读取报表语义", raw_result_type="FakeResult")

        repository = SemanticRepository()
        runner = FakeRunner()
        service = AnalysisRunService(agent_runner=runner, finereport_repository=repository)  # type: ignore[arg-type]

        service.run(AnalysisRunRequest(question="分析预算", metadata={"data_egress_authorized": True}))
        self.assertEqual(repository.calls, 0)
        self.assertNotIn("finereport_safe", runner.prompt)

        events = service.run(AnalysisRunRequest(question="分析预算", metadata={"semantic_context_egress_authorized": True}))
        self.assertEqual(repository.calls, 0)
        self.assertNotIn("finereport_safe", runner.prompt)
        self.assertNotIn("agent.evidence.available", [event.type for event in events])

    def test_legacy_region_snapshot_request_does_not_rewrite_report(self) -> None:
        test_case = self

        class QueryService:
            def run(self, query_ref: str, filters: dict[str, object], *, audit_context: dict[str, object] | None = None) -> ReportQueryResponse:
                test_case.fail("Legacy data egress metadata must not trigger region snapshots.")

        class FakeRunner:
            def stream(self, prompt: str):
                self.prompt = prompt
                yield AnalysisAgentRunResult(final_output="区域拆分", raw_result_type="FakeResult")

        runner = FakeRunner()
        report_context = {
            "id": "report_channel_sales",
            "title": "渠道销售结构",
            "subtitle": "2026-05",
            "document": {
                "root": {},
                "content": [
                    {"type": "ChartBlock", "props": {"chartSpecRef": "channel-sales-chart", "queryRef": CHANNEL_SALES_QUERY_REF}},
                    {"type": "GridBlock", "props": {"gridSpecRef": "channel-sales-grid", "queryRef": CHANNEL_SALES_QUERY_REF}},
                ],
                "zones": {},
            },
            "filters": [],
            "queries": {CHANNEL_SALES_QUERY_REF: {"datasetId": "channel-sales"}},
            "chartSpecs": {},
            "gridSpecs": {},
        }
        AnalysisRunService(agent_runner=runner, report_query_service=QueryService()).run(
            AnalysisRunRequest(
                question="请按区域拆开 2026-05 渠道销售",
                metadata={"data_egress_authorized": True, "interactive_report_context": report_context},
            )
        )
        self.assertNotIn('"region":"华东"', runner.prompt)
        self.assertIn("渠道销售结构", runner.prompt)


if __name__ == "__main__":
    unittest.main()
