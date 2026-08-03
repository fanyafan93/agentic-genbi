from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.mcp_servers.genbi_report_server import _handle


class GenbiReportMcpServerTest(unittest.TestCase):
    def test_lists_create_interactive_report_tool(self) -> None:
        response = _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

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
        self.assertIn("\"artifactType\": \"interactive_report\"", text)
        self.assertIn("dm.dm_channel_mtsg_sale_total", text)

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


if __name__ == "__main__":
    unittest.main()
