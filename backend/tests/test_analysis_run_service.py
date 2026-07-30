from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.run_service import AnalysisRunRequest, AnalysisRunService, classify_analysis_problem
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_trace_store import RunTraceStore


class AnalysisRunServiceTest(unittest.TestCase):
    def test_quick_analysis_emits_assets_and_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = AnalysisRunService(
                trace_store=RunTraceStore(root / "traces.jsonl"),
                event_store=RunEventStore(root / "events.jsonl"),
            )
            events = service.run(
                AnalysisRunRequest(
                    question="分析一下渠道销售占比",
                    conversation_id="conv_analysis_test",
                    analysis_mode="quick",
                )
            )

            event_types = [event.type for event in events]
            artifact_paths = [event.payload["path"] for event in events if event.type == "artifact.created"]

            self.assertIn("run.created", event_types)
            self.assertIn("analysis.problem.classified", event_types)
            self.assertIn("analysis.retrieval.plan", event_types)
            self.assertIn("agent.message.created", event_types)
            self.assertIn("run.completed", event_types)
            self.assertIn("reports/quick_report.html", artifact_paths)
            self.assertIn("queries/quick_candidate.sql", artifact_paths)

            traces = service.trace_store.list_traces()
            self.assertEqual(len(traces), 1)
            self.assertEqual(traces[0].metadata["domain"], "analysis_task")
            self.assertEqual(traces[0].metadata["analysis_mode"], "quick")

    def test_deep_analysis_requests_business_clarification(self) -> None:
        service = AnalysisRunService()
        events = service.run(
            AnalysisRunRequest(
                question="首购后 30 天复购率怎么算",
                conversation_id="conv_analysis_deep",
                analysis_mode="deep",
            )
        )

        plan = next(event for event in events if event.type == "analysis.retrieval.plan")
        question = next(event for event in events if event.type == "agent.question.requested")

        labels = [item["label"] for item in plan.payload["items"]]
        self.assertIn("FineReport 报表级语义模型", labels)
        self.assertIn("金蝶数据字典语义模型", labels)
        self.assertIn("ETL / Hop 血缘语义模型", labels)
        self.assertIn("首购和复购按会员 ID", question.payload["question"])

    def test_problem_classifier_recognizes_metric_diagnosis(self) -> None:
        classification = classify_analysis_problem("华东 GMV 下滑原因")

        self.assertEqual(classification.type, "metric_diagnosis")
        self.assertEqual(classification.label, "异常归因")


if __name__ == "__main__":
    unittest.main()

