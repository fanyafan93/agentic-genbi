from __future__ import annotations

import json
import sys
from typing import Any
from uuid import uuid4

from backend.reports.schema import (
    ReportValidationError,
    report_config_payload,
)


CREATE_TOOL_NAME = "create_report"
UPDATE_TOOL_NAME = "update_report"
REPORT_FIELDS = {
    "title",
    "subtitle",
    "layout",
    "filters",
    "charts",
    "tables",
    "queries",
}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        response = _handle(json.loads(line))
        if response is not None:
            sys.stdout.write(
                json.dumps(
                    response,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            sys.stdout.flush()


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    if method == "initialize":
        return _result(
            message,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "GenBI_report",
                    "version": "1.0.0",
                },
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(
            message,
            {"tools": [_create_tool_schema(), _update_tool_schema()]},
        )
    if method != "tools/call":
        return _error(
            message,
            -32601,
            f"Method not found: {method}",
        )

    params = (
        message.get("params")
        if isinstance(message.get("params"), dict)
        else {}
    )
    arguments = (
        params.get("arguments")
        if isinstance(params.get("arguments"), dict)
        else {}
    )
    name = params.get("name")
    if name == CREATE_TOOL_NAME:
        return _create_report(message, arguments)
    if name == UPDATE_TOOL_NAME:
        return _update_report(message, arguments)
    return _error(message, -32602, f"Unknown tool: {name}")


def _create_report(
    message: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    try:
        report = _validated_report(arguments.get("report"))
    except ReportValidationError as exc:
        return _validation_failure(message, exc)
    return _tool_result(
        message,
        {
            "ok": True,
            "action": "create",
            "reportId": f"report_{uuid4().hex}",
            "report": report,
        },
    )


def _update_report(
    message: dict[str, Any],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    report_id = arguments.get("report_id")
    if not isinstance(report_id, str) or not report_id.strip():
        return _validation_failure(
            message,
            ReportValidationError(
                "report_id",
                "report_id must be a non-empty string.",
            ),
        )
    try:
        report = _validated_report(arguments.get("report"))
    except ReportValidationError as exc:
        return _validation_failure(message, exc)
    return _tool_result(
        message,
        {
            "ok": True,
            "action": "update",
            "reportId": report_id.strip(),
            "report": report,
        },
    )


def _validated_report(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportValidationError("report", "report must be an object.")
    extra = set(value) - REPORT_FIELDS
    if extra:
        key = sorted(extra)[0]
        raise ReportValidationError(
            key,
            f"{key} is not part of the Agent Report input.",
        )
    return report_config_payload(value)


def _validation_failure(
    message: dict[str, Any],
    error: ReportValidationError,
) -> dict[str, Any]:
    return _tool_result(
        message,
        {
            "ok": False,
            "status": "validation_failed",
            "error": {
                "path": error.path,
                "message": error.message,
            },
        },
    )


def _create_tool_schema() -> dict[str, Any]:
    return {
        "name": CREATE_TOOL_NAME,
        "description": (
            "Create a Report from complete layout, filters, charts, "
            "tables, and executable query configuration."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"report": _report_schema()},
            "required": ["report"],
            "additionalProperties": False,
        },
    }


def _update_tool_schema() -> dict[str, Any]:
    return {
        "name": UPDATE_TOOL_NAME,
        "description": (
            "Replace an existing Report's complete configuration."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_id": {"type": "string", "minLength": 1},
                "report": _report_schema(),
            },
            "required": ["report_id", "report"],
            "additionalProperties": False,
        },
    }


def _report_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "subtitle": {"type": "string", "minLength": 1},
            "layout": {"type": "object"},
            "filters": {"type": "object"},
            "charts": {"type": "object"},
            "tables": {"type": "object"},
            "queries": {"type": "object"},
        },
        "required": sorted(REPORT_FIELDS),
        "additionalProperties": False,
    }


def _tool_result(
    message: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _result(
        message,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False),
                }
            ]
        },
    )


def _result(
    message: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message.get("id"),
        "result": result,
    }


def _error(
    message: dict[str, Any],
    code: int,
    message_text: str,
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message.get("id"),
        "error": {"code": code, "message": message_text},
    }


if __name__ == "__main__":
    main()
