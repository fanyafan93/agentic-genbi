from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.tests.auth_test_client import build_test_app


class RemovedLegacyAnalysisSurfaceTest(unittest.TestCase):
    def test_legacy_resource_and_report_query_routes_are_not_registered(self) -> None:
        app = build_test_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
        route_paths = {route.path for route in app.routes}

        self.assertFalse(any(path.startswith("/api/resources") for path in route_paths))
        self.assertFalse(any(path.startswith("/api/analysis/report-queries") for path in route_paths))

    def test_genbi_no_longer_defines_custom_turn_or_runner_or_prompt_layers(self) -> None:
        backend_root = Path(__file__).resolve().parents[1]

        self.assertIsNone(importlib.util.find_spec("backend.analysis.runner_contracts"))
        self.assertFalse(backend_root.joinpath("analysis", "turn_service.py").exists())


if __name__ == "__main__":
    unittest.main()
