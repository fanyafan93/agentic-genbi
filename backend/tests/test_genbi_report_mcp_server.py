from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.mcp_servers.genbi_report_server import _handle


def _ok_artifact() -> dict:
    return {
        "id": "report_1",
        "title": "渠道销售",
        "subtitle": "Top 渠道",
        "artifactType": "interactive_report",
        "renderer": "puck",
        "ownerId": "user_1",
        "document": {"root": {"props": {"title": "渠道销售"}}, "content": []},
        "filters": [],
        "queries": {"q1": {"datasetId": "d1", "filterBindings": []}},
        "datasets": {"d1": {"rows": [{"channel": "A", "sales": 1}]}},
        "chartSpecs": {
            "c1": {
                "id": "c1",
                "datasetId": "d1",
                "type": "bar",
                "xField": "channel",
                "title": "Sales by channel",
                "series": [{"field": "sales", "label": "Sales", "format": "currency"}],
            },
        },
        "gridSpecs": {
            "g1": {
                "id": "g1",
                "datasetId": "d1",
                "columns": [{"field": "channel", "label": "Channel"}],
                "pageSize": 10,
            },
        },
    }


class GenbiReportMcpServerTest(unittest.TestCase):
    def test_lists_create_interactive_report_tool(self) -> None:
        # The schema now requires only ``artifact``. Thread / Turn /
        # Item IDs are no longer accepted from the agent: the
        # projection layer injects them. The legacy ``sourceTable``
        # shortcut is gone.
        response = _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        tool_names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(tool_names, ["create_interactive_report", "validate_interactive_report"])
        create_schema = response["result"]["tools"][0]["inputSchema"]
        self.assertEqual(create_schema["required"], ["artifact"])
        self.assertEqual(list(create_schema["properties"].keys()), ["artifact"])
        self.assertFalse(create_schema.get("additionalProperties", True))

    def test_create_interactive_report_requires_artifact_field(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {
                    "title": "direct fields are not allowed",
                    "summary": "no more title/summary shortcut",
                    "rows": [],
                },
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"ok": false', text)
        self.assertIn('"status": "validation_failed"', text)
        # The validation error specifically names the artifact field.
        self.assertIn('"path": "artifact"', text)

    def test_create_interactive_report_rejects_thread_id_in_artifact(self) -> None:
        # The agent must not supply ``threadId`` / ``turnId`` /
        # ``codex_*_id`` fields. GenBI Runtime injects source
        # identity; the agent was creating fake lineage.
        bad = _ok_artifact()
        bad["source"] = {"threadId": "codex_thread_pending", "turnId": "codex_turn_pending"}
        response = _handle({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {"artifact": bad},
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"ok": false', text)
        self.assertIn('"forbidden_field"', text)
        self.assertIn("Runtime", text)

    def test_create_interactive_report_rejects_top_level_thread_id(self) -> None:
        # ``codex_thread_id`` etc. inside the artifact are equally
        # forbidden; the runtime injection is the only path.
        bad = _ok_artifact()
        bad["codex_thread_id"] = "codex_thread_pending"
        response = _handle({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {"artifact": bad},
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"forbidden_field"', text)

    def test_create_interactive_report_accepts_valid_artifact(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {"artifact": _ok_artifact()},
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"ok": true', text)
        payload = json.loads(text)
        self.assertEqual(payload["interactive_report"]["id"], "report_1")
        self.assertEqual(payload["interactive_report"]["artifactType"], "interactive_report")

    def test_create_interactive_report_reports_validation_errors(self) -> None:
        bad = _ok_artifact()
        # Force a series field that does not exist in the dataset.
        bad["chartSpecs"]["c1"]["series"] = [{"field": "missing", "label": "Sales"}]
        response = _handle({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {"artifact": bad},
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"ok": false', text)
        self.assertIn('"chartSpecs.c1.series.0.field"', text)
        self.assertIn("missing", text)

    def test_create_interactive_report_does_not_rewrite_fields(self) -> None:
        # The previous "best fit" xField / series-field / grid-column
        # rewriting is gone. An invalid field stays invalid.
        bad = _ok_artifact()
        bad["chartSpecs"]["c1"]["xField"] = "channel"
        bad["chartSpecs"]["c1"]["series"] = [{"field": "sales_amt", "label": "Sales"}]
        bad["datasets"]["d1"]["rows"] = [{"vchannel_name": "A", "sales": 1}]
        response = _handle({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {"artifact": bad},
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"ok": false', text)
        # We must see the literal error path, not a silent rewrite to
        # ``vchannel_name`` / ``sales_amt``.
        self.assertIn('"missing_field"', text)

    def test_create_interactive_report_unwraps_item_wrapped_rows(self) -> None:
        # PowerShell/MCP adapters sometimes serialize large payloads
        # inside ``{ "item": ... }`` shells. We unwrap that shape but
        # we do not perform any other field inference.
        wrapped = _ok_artifact()
        wrapped["datasets"]["d1"]["rows"] = {"item": [{"channel": "A", "sales": 1}]}
        response = _handle({
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {"artifact": wrapped},
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"ok": true', text)
        payload = json.loads(text)
        rows = payload["interactive_report"]["datasets"]["d1"]["rows"]
        self.assertEqual(rows, [{"channel": "A", "sales": 1}])

    def test_create_interactive_report_does_not_coerce_powershell_strings(self) -> None:
        # We no longer parse PowerShell ``@{}`` strings into dicts.
        # Incomplete inputs are rejected, not coerced.
        bad = _ok_artifact()
        bad["datasets"]["d1"]["rows"] = {"item": ["@{channel=A; sales=1}"]}
        response = _handle({
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "create_interactive_report",
                "arguments": {"artifact": bad},
            },
        })

        text = response["result"]["content"][0]["text"]
        # The PowerShell string never got coerced; the artifact's
        # rows still contain a string and the contract validates
        # ``datasets.<id>.rows`` are object records. The validation
        # must surface a clear error instead of silently rebuilding
        # the dataset.
        self.assertIn('"ok": false', text)
        self.assertIn('"empty_dataset"', text)

    def test_validate_interactive_report_returns_errors_for_invalid_artifact(self) -> None:
        bad = _ok_artifact()
        bad["chartSpecs"]["c1"]["series"] = [{"field": "missing", "label": "Sales"}]
        response = _handle({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "validate_interactive_report",
                "arguments": {"artifact": bad},
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"ok": false', text)
        self.assertIn('"status": "validation_failed"', text)
        # ``validate`` does not echo the artifact on failure.
        self.assertNotIn('"interactive_report"', text)

    def test_validate_interactive_report_echoes_clean_artifact(self) -> None:
        response = _handle({
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "validate_interactive_report",
                "arguments": {"artifact": _ok_artifact()},
            },
        })

        text = response["result"]["content"][0]["text"]
        self.assertIn('"ok": true', text)
        payload = json.loads(text)
        self.assertEqual(payload["interactive_report"]["id"], "report_1")


if __name__ == "__main__":
    unittest.main()
