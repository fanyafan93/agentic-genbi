from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.mcp_servers.genbi_report_server import _handle


class GenbiReportMcpServerTest(unittest.TestCase):
    def test_lists_create_interactive_report_tool(self) -> None:
        response = _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        tool_names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(tool_names, ["create_interactive_report", "validate_interactive_report"])
        self.assertEqual(response["result"]["tools"][0]["name"], "create_interactive_report")
        schema = response["result"]["tools"][0]["inputSchema"]
        self.assertNotIn("sourceTable", schema["required"])
        self.assertNotIn("default", schema["properties"]["sourceTable"])

    def test_create_interactive_report_returns_artifact_payload(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {
                    "title": "渠道销售占比分析",
                    "summary": "直营渠道贡献最高。",
                    "sourceTable": "dm.dm_channel_mtsg_sale_total",
                    "rows": [{"channel": "线上直营", "salesAmount": 1000}],
                    "threadId": "thread_1",
                    "turnId": "turn_1",
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn("\"ok\": true", text)
        self.assertIn("\"artifactType\": \"interactive_report\"", text)
        self.assertIn("dm.dm_channel_mtsg_sale_total", text)
        payload = json.loads(text)
        block_ids = [block["props"].get("id") for block in payload["interactive_report"]["document"]["content"]]
        self.assertEqual(len(block_ids), len(set(block_ids)))
        self.assertTrue(all(block_ids))

    def test_create_interactive_report_can_use_generic_source_description(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {
                    "title": "经营看板",
                    "summary": "基于已查证聚合结果生成。",
                    "sourceDescription": "本轮 SQL 聚合结果",
                    "rows": [{"metric": "GMV", "value": 1000}],
                    "threadId": "thread_1",
                    "turnId": "turn_1",
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn("\"artifactType\": \"interactive_report\"", text)
        self.assertIn("本轮 SQL 聚合结果", text)
        self.assertNotIn("dm.dm_channel_mtsg_sale_total", text)

    def test_validate_interactive_report_reports_missing_chart_field(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "validate_interactive_report",
                "arguments": {
                    "artifact": {
                        "id": "report_bad",
                        "title": "坏图表",
                        "subtitle": "字段不存在",
                        "artifactType": "interactive_report",
                        "renderer": "puck",
                        "ownerId": "codex-agent",
                        "source": {"threadId": "thread_1", "turnId": "turn_1"},
                        "document": {"root": {"props": {"title": "坏图表"}}, "content": []},
                        "filters": [],
                        "queries": {"q1": {"datasetId": "d1", "filterBindings": []}},
                        "datasets": {"d1": {"rows": [{"channel": "A", "sales_amt": 100}]}},
                        "chartSpecs": {"c1": {"id": "c1", "datasetId": "d1", "type": "bar", "xField": "channel", "series": [{"field": "missing", "label": "销售额"}]}},
                        "gridSpecs": {"g1": {"id": "g1", "datasetId": "d1", "columns": [{"field": "channel", "label": "渠道"}], "pageSize": 10}},
                    }
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn("\"ok\": false", text)
        self.assertIn("chartSpecs.c1.series.0.field", text)
        self.assertIn("missing", text)

    def test_create_interactive_report_normalizes_legacy_chart_fields(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {
                    "artifact": {
                        "id": "report_normalized",
                        "title": "渠道销售",
                        "subtitle": "Top 渠道",
                        "artifactType": "interactive_report",
                        "renderer": "puck",
                        "ownerId": "codex-agent",
                        "source": {"threadId": "thread_1", "turnId": "turn_1"},
                        "document": {"root": {"props": {"title": "渠道销售"}}, "content": []},
                        "filters": [],
                        "queries": {"q1": {"datasetId": "d1", "filterBindings": []}},
                        "datasets": {"d1": {"rows": [{"vchannel_name": "屈臣氏", "sales_amt": 100}]}},
                        "chartSpecs": {"c1": {"id": "c1", "datasetId": "d1", "type": "bar", "xField": "channel", "series": [{"field": "salesAmount", "label": "销售额"}]}},
                        "gridSpecs": {"g1": {"id": "g1", "datasetId": "d1", "columns": [{"field": "vchannel_name", "label": "渠道"}], "pageSize": 10}},
                    }
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn("\"ok\": true", text)
        self.assertIn("\"xField\": \"vchannel_name\"", text)
        self.assertIn("\"field\": \"sales_amt\"", text)


if __name__ == "__main__":
    unittest.main()
