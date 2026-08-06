from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from backend.mcp_servers.genbi_report_build_tools import (
    export_columns_schema,
    invoke_report_build_tool,
    report_build_tool_schemas,
)
from backend.reports.build_service import REPORT_BUILD_TOOL_NAMES
from backend.reports.schema import (
    FILTER_TYPES,
    LAYOUT_BLOCK_TYPES,
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


def _handle(
    message: dict[str, Any],
    *,
    invoke: Callable[
        [str, dict[str, Any]],
        dict[str, Any],
    ]
    | None = None,
) -> dict[str, Any] | None:
    method = message.get("method")
    if method == "initialize":
        return _result(
            message,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "GenBI_report",
                    "version": "2.0.0",
                },
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(
            message,
            {"tools": report_build_tool_schemas()},
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
    if name in REPORT_BUILD_TOOL_NAMES:
        invoker = invoke or (
            lambda tool_name, tool_arguments:
                invoke_report_build_tool(
                    tool_name,
                    tool_arguments,
                )
        )
        return _tool_result(
            message,
            invoker(str(name), arguments),
        )
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
        report = _validated_report_argument(arguments)
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
        report = _validated_report_argument(arguments)
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


def _validated_report_argument(
    arguments: dict[str, Any],
) -> dict[str, Any]:
    has_report = "report" in arguments
    has_report_json = "report_json" in arguments
    if has_report == has_report_json:
        raise ReportValidationError(
            "report",
            "supply exactly one of report or report_json.",
        )
    if has_report:
        return _validated_report(arguments["report"])

    report_json = arguments["report_json"]
    if not isinstance(report_json, str) or not report_json.strip():
        raise ReportValidationError(
            "report_json",
            "report_json must be a non-empty JSON string.",
        )
    try:
        value = json.loads(report_json)
    except json.JSONDecodeError as exc:
        raise ReportValidationError(
            "report_json",
            f"report_json is not valid JSON: {exc.msg}.",
        ) from exc
    return _validated_report(value)


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
            "tables, and executable query configuration. Prefer "
            "report_json when deeply nested object arguments may be "
            "flattened; never flatten Report fields into tool arguments."
        ),
        "inputSchema": {
            "type": "object",
            "properties": _report_argument_schemas(),
            "oneOf": [
                {"required": ["report"]},
                {"required": ["report_json"]},
            ],
            "additionalProperties": False,
        },
    }


def _update_tool_schema() -> dict[str, Any]:
    return {
        "name": UPDATE_TOOL_NAME,
        "description": (
            "Replace an existing Report's complete configuration. Prefer "
            "report_json when deeply nested object arguments may be "
            "flattened."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_id": {"type": "string", "minLength": 1},
                **_report_argument_schemas(),
            },
            "required": ["report_id"],
            "oneOf": [
                {"required": ["report"]},
                {"required": ["report_json"]},
            ],
            "additionalProperties": False,
        },
    }


def _report_argument_schemas() -> dict[str, Any]:
    return {
        "report_json": {
            "type": "string",
            "minLength": 2,
            "description": (
                "Preferred transport: one complete JSON object serialized "
                "as a string. It must contain title, subtitle, layout, "
                "filters, charts, tables, and queries. Do not use Markdown "
                "fences and do not flatten its fields."
            ),
        },
        "report": _report_schema(),
    }


def _report_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "A complete, directly renderable Report configuration. "
            "Build every referenced query, filter, chart, table, and layout "
            "block before calling this tool; do not send placeholders or "
            "empty title/subtitle values."
        ),
        "properties": {
            "title": {
                "type": "string",
                "minLength": 1,
                "description": "Reader-facing Report title.",
            },
            "subtitle": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "Reader-facing scope, period, or analytical subtitle."
                ),
            },
            "layout": _layout_schema(),
            "filters": _filters_schema(),
            "charts": _charts_schema(),
            "tables": _tables_schema(),
            "queries": _queries_schema(),
        },
        "required": sorted(REPORT_FIELDS),
        "additionalProperties": False,
    }


def _layout_schema() -> dict[str, Any]:
    block = {
        "type": "object",
        "description": (
            "A render block. FilterBlock props use filterIds; ChartBlock "
            "props use chartId; TableBlock props use tableId. Referenced IDs "
            "must exist in the corresponding Report maps."
        ),
        "properties": {
            "type": {
                "type": "string",
                "enum": sorted(LAYOUT_BLOCK_TYPES),
            },
            "props": {
                "type": "object",
                "description": (
                    "Renderer props. Always include a stable id. FilterBlock "
                    "uses filterIds; ChartBlock uses chartId; TableBlock uses "
                    "tableId; SectionBlock uses title; MarkdownBlock uses "
                    "content. Use columnSpan, not colSpan."
                ),
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "filterIds": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                    },
                    "chartId": {"type": "string", "minLength": 1},
                    "tableId": {"type": "string", "minLength": 1},
                    "title": {"type": "string", "minLength": 1},
                    "content": {"type": "string", "minLength": 1},
                    "columnSpan": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 12,
                    },
                },
                "required": ["id"],
                "additionalProperties": True,
            },
        },
        "required": ["type", "props"],
        "additionalProperties": True,
    }
    return {
        "type": "object",
        "description": (
            "Puck-style Report layout. Put every visible block directly in "
            "content. Use exact PascalCase block types only; zones should "
            "normally be empty."
        ),
        "properties": {
            "root": {"type": "object", "additionalProperties": True},
            "content": {
                "type": "array",
                "items": block,
            },
            "zones": {
                "type": "object",
                "additionalProperties": {
                    "type": "array",
                    "items": block,
                },
            },
        },
        "required": ["content"],
        "additionalProperties": True,
    }


def _filters_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "Filter definitions keyed by stable filter ID. Use an empty "
            "object only when the Report genuinely has no filters."
        ),
        "additionalProperties": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": sorted(FILTER_TYPES),
                },
                "label": {"type": "string", "minLength": 1},
                "defaultValue": {},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "value": {},
                        },
                        "required": ["label", "value"],
                        "additionalProperties": True,
                    },
                },
            },
            "required": ["type", "label"],
            "additionalProperties": True,
        },
    }


def _queries_schema() -> dict[str, Any]:
    parameter_binding = {
        "type": "object",
        "description": (
            "Bind one named SQL placeholder to a Report filter. For a "
            "dateRange, use valueIndex 0 for the start and 1 for the end."
        ),
        "properties": {
            "filterId": {"type": "string", "minLength": 1},
            "type": {"type": "string", "minLength": 1},
            "valueIndex": {"type": "integer", "minimum": 0},
        },
        "required": ["filterId", "type"],
        "additionalProperties": True,
    }
    safe_fields = {
        "type": "array",
        "items": {
            "type": "string",
            "pattern": "^[A-Za-z_][A-Za-z0-9_]*$",
        },
    }
    return {
        "type": "object",
        "description": (
            "Executable read-only query definitions keyed by stable query "
            "ID. SQL rows are not embedded in the Report."
        ),
        "additionalProperties": {
            "type": "object",
            "properties": {
                "dataSource": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "Configured data source name, for example doris."
                    ),
                },
                "sql": {
                    "type": "string",
                    "minLength": 1,
                    "description": (
                        "One read-only SELECT or WITH query. Named "
                        "placeholders must use unquoted :parameter syntax "
                        "and exactly match parameters. ${parameter} template "
                        "syntax is unsupported."
                    ),
                },
                "parameters": {
                    "type": "object",
                    "additionalProperties": parameter_binding,
                },
                "pagination": {"type": "boolean"},
                "controls": {
                    "type": "object",
                    "properties": {
                        "sortableFields": safe_fields,
                        "filterableFields": safe_fields,
                    },
                    "additionalProperties": True,
                },
            },
            "required": ["dataSource", "sql"],
            "additionalProperties": True,
        },
    }


def _charts_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "ECharts definitions keyed by stable chart ID. Every queryId "
            "must reference an entry in queries."
        ),
        "additionalProperties": {
            "type": "object",
            "properties": {
                "queryId": {"type": "string", "minLength": 1},
                "option": {
                    "type": "object",
                    "description": (
                        "Native ECharts option using fields returned by the "
                        "referenced query. It must include a series array; "
                        "do not use xField, yField, angleField, colorField, "
                        "or type: metric pseudo-options."
                    ),
                    "properties": {
                        "series": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                    },
                    "required": ["series"],
                    "additionalProperties": True,
                },
            },
            "required": ["queryId", "option"],
            "additionalProperties": True,
        },
    }


def _tables_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "VTable definitions keyed by stable table ID. Every queryId "
            "must reference an entry in queries."
        ),
        "additionalProperties": {
            "type": "object",
            "properties": {
                "queryId": {"type": "string", "minLength": 1},
                "type": {
                    "type": "string",
                    "enum": ["list", "pivot"],
                },
                "exportColumns": export_columns_schema(),
                "options": {
                    "type": "object",
                    "description": (
                        "Complete VTable options, normally including columns "
                        "whose fields are returned by the query."
                    ),
                    "properties": {
                        "columns": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                    },
                    "required": ["columns"],
                    "additionalProperties": True,
                },
            },
            "required": ["queryId", "options"],
            "additionalProperties": True,
        },
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
