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

    def test_create_interactive_report_unwraps_mcp_item_rows(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {
                    "title": "渠道销售",
                    "summary": "基于聚合结果。",
                    "rows": {"item": [{"vchannel_name": "屈臣氏", "sales_amt": 100}, {"vchannel_name": "松鼠单体加盟", "sales_amt": 80}]},
                    "threadId": "thread_1",
                    "turnId": "turn_1",
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn("\"ok\": true", text)
        payload = json.loads(text)
        rows = payload["interactive_report"]["datasets"]["channel_sales"]["rows"]
        self.assertEqual(rows[0]["vchannel_name"], "屈臣氏")
        self.assertEqual(rows[1]["sales_amt"], 80)

    def test_validate_interactive_report_unwraps_nested_item_specs(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "validate_interactive_report",
                "arguments": {
                    "artifact": {
                        "id": "report_wrapped",
                        "title": "渠道销售",
                        "subtitle": "Top 渠道",
                        "artifactType": "interactive_report",
                        "renderer": "puck",
                        "ownerId": "codex-agent",
                        "source": {"threadId": "thread_1", "turnId": "turn_1"},
                        "document": {"root": {"props": {"title": "渠道销售"}}, "content": []},
                        "filters": [],
                        "queries": {"q1": {"datasetId": "d1", "filterBindings": []}},
                        "datasets": {"d1": {"rows": {"item": {"item": [{"channel": "A", "sales": 1}]}}}},
                        "chartSpecs": {"c1": {"id": "c1", "datasetId": "d1", "type": "bar", "xField": "channel", "series": {"item": [{"field": "sales", "label": "销售额"}]}}},
                        "gridSpecs": {"g1": {"id": "g1", "datasetId": "d1", "columns": {"item": [{"field": "channel", "label": "渠道"}]}, "pageSize": 10}},
                    }
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn("\"ok\": true", text)

    def test_create_interactive_report_parses_powershell_row_strings(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {
                    "title": "渠道销售",
                    "summary": "基于聚合结果。",
                    "rows": {"item": ["@{vchannel_name=PriceTag; sales_amt=45.0; sales_share=0.2978}"]},
                    "threadId": "thread_1",
                    "turnId": "turn_1",
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn("\"ok\": true", text)
        payload = json.loads(text)
        row = payload["interactive_report"]["datasets"]["channel_sales"]["rows"][0]
        self.assertEqual(row["vchannel_name"], "PriceTag")
        self.assertEqual(row["sales_amt"], 45.0)

    def test_create_interactive_report_compiles_top_level_arguments_when_artifact_is_empty(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {
                    "title": "物料类型销售分析",
                    "summary": "基于已查证的物料类型聚合结果。",
                    "sourceDescription": "本轮 SQL 聚合结果",
                    "rows": [
                        {"$text": "\t{\"物料类型\":\"单刀\",\"客户数\":309,\"记录数\":315,\"实付金额\":46337.15}"},
                        {"$text": "\t{\"物料类型\":\"刀芯\",\"客户数\":317,\"记录数\":418,\"实付金额\":26149.89}"},
                    ],
                    "artifact": {},
                    "threadId": "thread_1",
                    "turnId": "turn_1",
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        payload = json.loads(text)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "validated")
        self.assertEqual(payload["interactive_report"]["artifactType"], "interactive_report")

    def test_validate_interactive_report_recovers_wrapped_series_json_strings(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "validate_interactive_report",
                "arguments": {
                    "artifact": {
                        "id": "report_series_wrapped",
                        "title": "渠道销售",
                        "subtitle": "Top 渠道",
                        "artifactType": "interactive_report",
                        "schemaVersion": "1.0",
                        "renderer": "puck",
                        "ownerId": "codex-agent",
                        "source": {"threadId": "thread_1", "turnId": "turn_1"},
                        "document": {
                            "root": {"props": {"title": "渠道销售"}},
                            "zones": "",
                            "content": {"item": {"type": "ChartBlock", "props": {"id": "chart_1", "queryRef": "q1", "chartSpecRef": "c1"}}},
                        },
                        "filters": "",
                        "queries": {"q1": {"datasetId": "d1", "filterBindings": ""}},
                        "datasets": {"d1": {"rows": {"item": {"item": [{"sale_date": "a", "sales_amt": 1}, {"sale_date": "b", "sales_amt": 2}]}}}},
                        "chartSpecs": {
                            "c1": {
                                "id": "c1",
                                "datasetId": "d1",
                                "type": "bar",
                                "xField": "sale_date",
                                "series": {"item": {"item": ['{"field":"sales_amt","label":"销售额"}']}},
                            }
                        },
                        "gridSpecs": {
                            "g1": {
                                "id": "g1",
                                "datasetId": "d1",
                                "columns": {"item": {"item": ['{"field":"sale_date","label":"日期"}', '{"field":"sales_amt","label":"销售额"}']}},
                                "pageSize": "10",
                            }
                        },
                    }
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn("\"ok\": true", text)


if __name__ == "__main__":
    unittest.main()
