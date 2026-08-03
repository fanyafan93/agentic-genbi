from __future__ import annotations

import json
import sys
from typing import Any

from backend.analysis.report_compiler import compile_interactive_report


TOOL_NAME = "create_interactive_report"


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        response = _handle(json.loads(line))
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    if method == "initialize":
        return _result(message, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "GenBI_report", "version": "0.1.0"}})
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _result(message, {"tools": [_tool_schema()]})
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name != TOOL_NAME:
            return _error(message, -32602, f"Unknown tool: {name}")
        report = compile_interactive_report(
            arguments,
            thread_id=str(arguments.get("threadId") or arguments.get("thread_id") or "codex_thread_pending"),
            turn_id=str(arguments.get("turnId") or arguments.get("turn_id") or "codex_turn_pending"),
        )
        return _result(message, {"content": [{"type": "text", "text": json.dumps({"interactive_report": report}, ensure_ascii=False)}]})
    return _error(message, -32601, f"Method not found: {method}")


def _tool_schema() -> dict[str, Any]:
    return {
        "name": TOOL_NAME,
        "description": "Create a GenBI interactive_report artifact for the right-side Puck report panel from verified query results. Use this after data has been checked with business data tools; do not put the full report body in chat.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "subtitle": {"type": "string"},
                "summary": {"type": "string"},
                "sourceTable": {"type": "string", "description": "Optional source table or dataset name used as evidence. Not limited to any fixed table."},
                "sourceDescription": {"type": "string", "description": "Optional human-readable source or query scope when the evidence is not a single table."},
                "datasetId": {"type": "string", "default": "channel_sales"},
                "rows": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "threadId": {"type": "string"},
                "turnId": {"type": "string"},
            },
            "required": ["title", "summary", "rows"],
            "additionalProperties": True,
        },
    }


def _result(message: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}


def _error(message: dict[str, Any], code: int, message_text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": code, "message": message_text}}


if __name__ == "__main__":
    main()
