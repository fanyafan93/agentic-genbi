from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.runner_contracts import build_analysis_runner_prompt
from backend.analysis.turn_service import AnalysisTurnService
from backend.api.analysis_api import create_app


class RemovedLegacyAnalysisSurfaceTest(unittest.TestCase):
    def test_legacy_resource_and_report_query_routes_are_not_registered(self) -> None:
        app = create_app(analysis_service=AnalysisTurnService())
        route_paths = {route.path for route in app.routes}

        self.assertFalse(any(path.startswith("/api/resources") for path in route_paths))
        self.assertFalse(any(path.startswith("/api/analysis/report-queries") for path in route_paths))

    def test_analysis_prompt_does_not_request_text_embedded_report_payloads(self) -> None:
        prompt = build_analysis_runner_prompt(
            question="分析渠道销售",
            problem_label="业务分析",
            semantic_model_labels=["FineReport 语义案例"],
        )

        self.assertNotIn("interactive_report_draft", prompt)
        self.assertNotIn("JSON 必须包含", prompt)


if __name__ == "__main__":
    unittest.main()
