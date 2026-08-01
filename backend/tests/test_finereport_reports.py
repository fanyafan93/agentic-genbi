from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.api.exploration_api import create_app
from backend.exploration.run_service import ExplorationRunService


class FineReportReportsApiTest(unittest.TestCase):
    def test_lists_and_loads_aggregated_parsed_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resource_root = Path(temp_dir)
            parsed_root = resource_root / "finereport" / "解析"
            parsed_root.mkdir(parents=True)
            self._write_json(
                parsed_root / "预算管控.01_报表与数据集.json",
                {
                    "reports": [
                        {
                            "report": {
                                "name": "预算管控",
                                "source_cpt_path": "reports/预算管控.cpt",
                                "sheet_names": ["额度报表"],
                            },
                            "datasets": [
                                {
                                    "name": "ds",
                                    "type": "database_query",
                                    "fine_report_class": "DatabaseQuery",
                                    "connection_name": "fat_dm",
                                    "raw_sql": "select amount from dm.budget",
                                    "parameters": [{"name": "month"}],
                                    "embedded_row_count": 0,
                                }
                            ],
                        }
                    ]
                },
            )
            self._write_json(
                parsed_root / "预算管控.02_参数与交互.json",
                {
                    "reports": [
                        {
                            "report": {"name": "预算管控", "source_cpt_path": "reports/预算管控.cpt"},
                            "parameters": [],
                            "parameter_widgets": [
                                {
                                    "parameter": "month",
                                    "widget_class": "ComboBox",
                                    "label": "月份",
                                    "default_value": "2026-07",
                                    "dictionary": None,
                                }
                            ],
                            "conditional_rules": [
                                {"cell": "A2", "condition": "amount > 0", "action_class": "Style", "action": "highlight"}
                            ],
                        }
                    ]
                },
            )
            self._write_json(
                parsed_root / "预算管控.03_报表主体结构.json",
                {
                    "report": {"name": "预算管控", "source_cpt_path": "reports/预算管控.cpt"},
                    "sheets": [
                        {
                            "name": "额度报表",
                            "cells": [
                                {"cell": "A1", "row": 1, "column": "A", "rowspan": 1, "colspan": 2, "value": "预算"},
                                {
                                    "cell": "A2",
                                    "row": 2,
                                    "column": "A",
                                    "rowspan": 1,
                                    "colspan": 1,
                                    "formula": "=sum(A3)",
                                    "binding": {"dataset": "ds", "field": "amount"},
                                },
                            ],
                        }
                    ],
                },
            )

            with patch.dict("os.environ", {"GENBI_RESOURCE_LIBRARY_ROOT": str(resource_root)}, clear=False):
                client = TestClient(create_app(ExplorationRunService()))
                listed = client.get("/api/business-semantics/finereport/reports")

                self.assertEqual(listed.status_code, 200)
                report = listed.json()["reports"][0]
                self.assertEqual(report["name"], "预算管控")
                self.assertEqual(report["counts"]["datasets"], 1)
                self.assertEqual(report["counts"]["cells"], 2)
                self.assertEqual(report["status"], "complete")

                detail = client.get(f"/api/business-semantics/finereport/reports/{report['id']}")

                self.assertEqual(detail.status_code, 200)
                payload = detail.json()
                self.assertEqual(payload["report"]["sourceCptPath"], "reports/预算管控.cpt")
                self.assertEqual(payload["datasets"][0]["connection_name"], "fat_dm")
                self.assertEqual(payload["parameterWidgets"][0]["label"], "月份")
                self.assertEqual(payload["conditionalRules"][0]["cell"], "A2")
                self.assertEqual(payload["sheets"][0]["rowCount"], 2)
                self.assertEqual(payload["sheets"][0]["columnCount"], 2)
                self.assertEqual(payload["sheets"][0]["cells"][0]["colspan"], 2)
                self.assertEqual(payload["sheets"][0]["cells"][1]["columnIndex"], 1)
                self.assertEqual(payload["sheets"][0]["cells"][1]["binding"]["field"], "amount")

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
