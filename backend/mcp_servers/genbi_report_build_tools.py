from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.reports.build_service import REPORT_BUILD_TOOL_NAMES


def report_build_tool_schemas() -> list[dict[str, Any]]:
    schemas = {
        "start_report_build": _schema(
            "Start a persisted Report build with its reader-facing title.",
            {
                "title": _text(),
                "subtitle": _text(),
            },
            ["title", "subtitle"],
        ),
        "get_report_build": _build_id_schema(
            "Read the current persisted Report build."
        ),
        "set_report_filters": _schema(
            "Replace the build's complete filter definition map.",
            {
                "build_id": _text(),
                "filters": {
                    "type": "object",
                    "additionalProperties": {"type": "object"},
                },
            },
            ["build_id", "filters"],
        ),
        "upsert_report_query": _schema(
            "Add or replace one read-only query by stable query ID.",
            {
                "build_id": _text(),
                "query_id": _text(),
                "query": {
                    "type": "object",
                    "properties": {
                        "dataSource": {
                            "type": "string",
                            "enum": ["doris", "mysql"],
                            "description": (
                                "Database connection kind; use `doris` for "
                                "BI_doris tables, never a table name."
                            ),
                        },
                        "sql": _text(),
                        "parameters": query_parameters_schema(),
                        "pagination": {"type": "boolean"},
                        "controls": {"type": "object"},
                    },
                    "required": ["dataSource", "sql"],
                    "additionalProperties": True,
                },
            },
            ["build_id", "query_id", "query"],
        ),
        "upsert_report_chart": _schema(
            "Add or replace one ECharts definition by stable chart ID.",
            {
                "build_id": _text(),
                "chart_id": _text(),
                "chart": {
                    "type": "object",
                    "properties": {
                        "queryId": _text(),
                        "option": {
                            "type": "object",
                            "properties": {
                                "series": {
                                    "type": "array",
                                    "items": {"type": "object"},
                                }
                            },
                            "required": ["series"],
                            "additionalProperties": True,
                        },
                    },
                    "required": ["queryId", "option"],
                    "additionalProperties": True,
                },
            },
            ["build_id", "chart_id", "chart"],
        ),
        "upsert_report_table": _schema(
            "Add or replace one VTable definition by stable table ID.",
            {
                "build_id": _text(),
                "table_id": _text(),
                "table": {
                    "type": "object",
                    "properties": {
                        "queryId": _text(),
                        "type": {
                            "type": "string",
                            "enum": ["list", "pivot"],
                        },
                        "exportColumns": export_columns_schema(),
                        "options": {
                            "type": "object",
                            "properties": {
                                "columns": {
                                    "type": "array",
                                    "items": {"type": "object"},
                                }
                            },
                            "required": ["columns"],
                            "additionalProperties": True,
                        },
                    },
                    "required": ["queryId", "options"],
                    "additionalProperties": True,
                },
            },
            ["build_id", "table_id", "table"],
        ),
        "set_report_layout": _schema(
            "Set the Puck layout after its referenced components exist.",
            {
                "build_id": _text(),
                "layout": {
                    "type": "object",
                    "properties": {
                        "root": {"type": "object"},
                        "content": {
                            "type": "array",
                            "items": layout_block_schema(),
                        },
                        "zones": {"type": "object"},
                    },
                    "required": ["content"],
                    "additionalProperties": True,
                },
            },
            ["build_id", "layout"],
        ),
        "validate_report_build": _build_id_schema(
            "Validate the complete persisted Report build."
        ),
        "publish_report_build": _build_id_schema(
            "Atomically publish a valid build as one formal Report."
        ),
    }
    return [
        {
            "name": name,
            "description": schemas[name]["description"],
            "inputSchema": schemas[name]["inputSchema"],
        }
        for name in REPORT_BUILD_TOOL_NAMES
    ]


def layout_block_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            _layout_block(
                "FilterBlock",
                {
                    "filterIds": {
                        "type": "array",
                        "items": _text(),
                    },
                    "columnSpan": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 12,
                    },
                },
                ["filterIds"],
            ),
            _layout_block(
                "ChartBlock",
                {
                    "chartId": _text(),
                    "columnSpan": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 12,
                    },
                },
                ["chartId"],
            ),
            _layout_block(
                "TableBlock",
                {
                    "tableId": _text(),
                    "columnSpan": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 12,
                    },
                },
                ["tableId"],
            ),
            _layout_block(
                "SectionBlock",
                {"title": _text()},
                ["title"],
            ),
            _layout_block(
                "MarkdownBlock",
                {"content": _text()},
                ["content"],
            ),
        ]
    }


def export_columns_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "description": (
            "Optional Excel columns for a saved list table. Omit this "
            "property when the table must not offer Excel export."
        ),
        "minItems": 1,
        "items": {
            "type": "object",
            "properties": {
                "field": _text(),
                "title": _text(),
                "type": {
                    "type": "string",
                    "enum": [
                        "text",
                        "number",
                        "date",
                        "datetime",
                        "boolean",
                    ],
                },
            },
            "required": ["field", "title"],
            "additionalProperties": False,
        },
    }


def query_parameters_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "Bindings keyed by each SQL :name placeholder. Use an empty "
            "object when the SQL has no placeholders."
        ),
        "additionalProperties": {
            "type": "object",
            "properties": {
                "filterId": _text(),
                "type": {
                    "type": "string",
                    "enum": [
                        "string",
                        "string[]",
                        "date",
                        "number",
                        "boolean",
                    ],
                },
                "valueIndex": {
                    "type": "integer",
                    "minimum": 0,
                },
            },
            "required": ["filterId", "type"],
            "additionalProperties": False,
        },
    }


def _layout_block(
    block_type: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": [block_type],
            },
            "props": {
                "type": "object",
                "properties": {
                    "id": _text(),
                    **properties,
                },
                "required": ["id", *required],
                "additionalProperties": True,
            },
        },
        "required": ["type", "props"],
        "additionalProperties": False,
    }


def invoke_report_build_tool(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    endpoint: str | None = None,
    token: str | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    resolved_endpoint = str(
        endpoint
        or os.getenv("GENBI_REPORT_TOOL_ENDPOINT")
        or ""
    ).rstrip("/")
    resolved_token = str(
        token
        or os.getenv("GENBI_REPORT_TOOL_TOKEN")
        or ""
    ).strip()
    if not resolved_endpoint or not resolved_token:
        return _unavailable(
            "Report build execution context is unavailable."
        )
    if tool_name not in REPORT_BUILD_TOOL_NAMES:
        return _unavailable("Unknown Report build tool.")

    request = Request(
        f"{resolved_endpoint}/{tool_name}",
        data=json.dumps(
            arguments,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {resolved_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 422:
            return {
                "ok": False,
                "status": "validation_failed",
                "error": {
                    "code": "invalid_report_build_arguments",
                    "message": "Report build tool arguments are invalid.",
                },
            }
        return _unavailable("Report build service rejected the request.")
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return _unavailable("Report build service is unavailable.")
    if not isinstance(payload, dict):
        return _unavailable("Report build service returned an invalid result.")
    return payload


def _schema(
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def _build_id_schema(description: str) -> dict[str, Any]:
    return _schema(
        description,
        {"build_id": _text()},
        ["build_id"],
    )


def _text() -> dict[str, Any]:
    return {"type": "string", "minLength": 1}


def _unavailable(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "tool_unavailable",
        "error": {
            "code": "report_build_tool_unavailable",
            "message": message,
        },
    }
