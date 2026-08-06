from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.mcp_servers.genbi_report_server import _handle
from backend.reports.build_service import REPORT_BUILD_TOOL_NAMES
from backend.tests.test_report_store import report_config


def _call_tool(
    name: str,
    arguments: dict,
    *,
    invoke=None,
) -> dict:
    response = _handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        invoke=invoke,
    )
    assert response is not None
    return json.loads(response["result"]["content"][0]["text"])


def test_lists_exactly_nine_progressive_report_tools() -> None:
    response = _handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response is not None

    tools = response["result"]["tools"]
    assert [tool["name"] for tool in tools] == list(
        REPORT_BUILD_TOOL_NAMES
    )
    forbidden = {
        "owner_id",
        "ownerId",
        "session_id",
        "sessionId",
        "turn_id",
        "turnId",
        "tenant_id",
        "workspace_id",
        "roles",
    }
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["additionalProperties"] is False
        assert forbidden.isdisjoint(schema["properties"])


def test_table_tool_describes_opt_in_excel_export_columns() -> None:
    response = _handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response is not None
    table_tool = next(
        tool
        for tool in response["result"]["tools"]
        if tool["name"] == "upsert_report_table"
    )

    table_schema = table_tool["inputSchema"]["properties"]["table"]
    export_schema = table_schema["properties"]["exportColumns"]

    assert export_schema["type"] == "array"
    assert export_schema["minItems"] == 1
    assert export_schema["items"]["required"] == ["field", "title"]
    assert export_schema["items"]["properties"]["type"]["enum"] == [
        "text",
        "number",
        "date",
        "datetime",
        "boolean",
    ]


def test_query_tool_describes_parameter_binding_contract() -> None:
    response = _handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response is not None
    query_tool = next(
        tool
        for tool in response["result"]["tools"]
        if tool["name"] == "upsert_report_query"
    )

    parameters_schema = query_tool["inputSchema"]["properties"][
        "query"
    ]["properties"]["parameters"]
    binding_schema = parameters_schema["additionalProperties"]

    assert parameters_schema["type"] == "object"
    assert binding_schema["type"] == "object"
    assert binding_schema["required"] == ["filterId", "type"]
    assert binding_schema["additionalProperties"] is False
    assert binding_schema["properties"]["type"]["enum"] == [
        "string",
        "string[]",
        "date",
        "number",
        "boolean",
    ]
    assert binding_schema["properties"]["valueIndex"] == {
        "type": "integer",
        "minimum": 0,
    }


def test_layout_tool_describes_required_props_for_every_block() -> None:
    response = _handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response is not None
    layout_tool = next(
        tool
        for tool in response["result"]["tools"]
        if tool["name"] == "set_report_layout"
    )

    block_variants = layout_tool["inputSchema"]["properties"][
        "layout"
    ]["properties"]["content"]["items"]["oneOf"]
    required_props = {
        variant["properties"]["type"]["enum"][0]: set(
            variant["properties"]["props"]["required"]
        )
        for variant in block_variants
    }

    assert required_props == {
        "FilterBlock": {"id", "filterIds"},
        "ChartBlock": {"id", "chartId"},
        "TableBlock": {"id", "tableId"},
        "SectionBlock": {"id", "title"},
        "MarkdownBlock": {"id", "content"},
    }


def test_progressive_tool_forwards_only_its_small_arguments() -> None:
    calls: list[tuple[str, dict]] = []

    payload = _call_tool(
        "upsert_report_chart",
        {
            "build_id": "build-1",
            "chart_id": "sales-chart",
            "chart": {
                "queryId": "sales-query",
                "option": {"series": [{"type": "bar"}]},
            },
        },
        invoke=lambda name, arguments: (
            calls.append((name, arguments)) or {"ok": True}
        ),
    )

    assert payload == {"ok": True}
    assert calls == [
        (
            "upsert_report_chart",
            {
                "build_id": "build-1",
                "chart_id": "sales-chart",
                "chart": {
                    "queryId": "sales-query",
                    "option": {"series": [{"type": "bar"}]},
                },
            },
        )
    ]


def test_create_report_returns_validated_direct_report() -> None:
    payload = _call_tool("create_report", {"report": report_config()})

    assert payload["ok"] is True
    assert payload["action"] == "create"
    assert payload["reportId"].startswith("report_")
    assert payload["report"] == report_config()
    assert "artifactType" not in payload["report"]
    assert "datasets" not in payload["report"]
    assert "ownerId" not in payload["report"]
    assert "turnId" not in payload["report"]


def test_create_report_accepts_complete_json_string() -> None:
    report = report_config()

    payload = _call_tool(
        "create_report",
        {
            "report_json": json.dumps(
                report,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        },
    )

    assert payload["ok"] is True
    assert payload["report"] == report


def test_create_report_rejects_ambiguous_report_inputs() -> None:
    report = report_config()

    payload = _call_tool(
        "create_report",
        {
            "report": report,
            "report_json": json.dumps(report, ensure_ascii=False),
        },
    )

    assert payload["ok"] is False
    assert payload["error"]["path"] == "report"


def test_update_report_uses_caller_selected_id_and_full_report() -> None:
    payload = _call_tool(
        "update_report",
        {
            "report_id": "report_existing",
            "report": report_config("修改后的报表"),
        },
    )

    assert payload == {
        "ok": True,
        "action": "update",
        "reportId": "report_existing",
        "report": report_config("修改后的报表"),
    }


def test_invalid_report_returns_tool_error_without_partial_payload() -> None:
    invalid = report_config()
    invalid["queries"]["sales-query"]["sql"] = "DELETE FROM sales"

    response = _call_tool("create_report", {"report": invalid})

    assert response["ok"] is False
    assert response["status"] == "validation_failed"
    assert response["error"]["path"] == "queries.sales-query.sql"
    assert "report" not in response


def test_model_cannot_supply_owner_or_turn() -> None:
    with_owner = {**report_config(), "ownerId": "model-owner"}
    with_turn = {**report_config(), "turnId": "model-turn"}

    owner_response = _call_tool("create_report", {"report": with_owner})
    turn_response = _call_tool("create_report", {"report": with_turn})

    assert owner_response["ok"] is False
    assert turn_response["ok"] is False
