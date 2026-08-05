from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.mcp_servers.genbi_report_server import _handle
from backend.tests.test_report_store import report_config


def _call_tool(name: str, arguments: dict) -> dict:
    response = _handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    assert response is not None
    return json.loads(response["result"]["content"][0]["text"])


def test_lists_only_create_and_update_report_tools() -> None:
    response = _handle(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    )
    assert response is not None

    assert [
        tool["name"] for tool in response["result"]["tools"]
    ] == ["create_report", "update_report"]
    create_schema = response["result"]["tools"][0]["inputSchema"]
    assert create_schema["required"] == ["report"]
    assert set(create_schema["properties"]) == {"report"}


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
