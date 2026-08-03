from __future__ import annotations

import json
import sys
from typing import Any

from backend.analysis.report_artifact import issues_to_payload, normalize_report_artifact, validate_report_artifact
from backend.analysis.report_compiler import compile_interactive_report


CREATE_TOOL_NAME = "create_interactive_report"
VALIDATE_TOOL_NAME = "validate_interactive_report"


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
        return _result(message, {"tools": [_create_tool_schema(), _validate_tool_schema()]})
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if name == CREATE_TOOL_NAME:
            return _create_interactive_report(message, arguments)
        if name == VALIDATE_TOOL_NAME:
            return _validate_interactive_report(message, arguments)
        else:
            return _error(message, -32602, f"Unknown tool: {name}")
    return _error(message, -32601, f"Method not found: {method}")


def _create_interactive_report(message: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    report = _artifact_from_arguments(arguments, normalize=True)
    issues = validate_report_artifact(report)
    if issues:
        return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": False, "status": "validation_failed", "errors": issues_to_payload(issues)}, ensure_ascii=False)}]})
    return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": True, "status": "validated", "interactive_report": report}, ensure_ascii=False)}]})


def _validate_interactive_report(message: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    report = _artifact_from_arguments(arguments, normalize=False)
    issues = validate_report_artifact(report)
    return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": not issues, "status": "valid" if not issues else "validation_failed", "errors": issues_to_payload(issues), **({"interactive_report": report} if not issues else {})}, ensure_ascii=False)}]})


def _artifact_from_arguments(arguments: dict[str, Any], *, normalize: bool) -> dict[str, Any]:
    artifact = arguments.get("artifact")
    if isinstance(artifact, dict):
        source = dict(artifact.get("source") or {})
        source.setdefault("threadId", str(arguments.get("threadId") or arguments.get("thread_id") or source.get("threadId") or "codex_thread_pending"))
        source.setdefault("turnId", str(arguments.get("turnId") or arguments.get("turn_id") or source.get("turnId") or "codex_turn_pending"))
        next_artifact = {**artifact, "source": source}
        return normalize_report_artifact(next_artifact) if normalize else next_artifact
    return compile_interactive_report(
        arguments,
        thread_id=str(arguments.get("threadId") or arguments.get("thread_id") or "codex_thread_pending"),
        turn_id=str(arguments.get("turnId") or arguments.get("turn_id") or "codex_turn_pending"),
    )


def _create_tool_schema() -> dict[str, Any]:
    return {
        "name": CREATE_TOOL_NAME,
        "description": "Create a GenBI interactive_report artifact for the right-side Puck report panel. The tool validates ReportArtifact JSON before returning a savable artifact; invalid artifacts return structured errors and are not saved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact": {"type": "object", "description": "Preferred: complete ReportArtifact JSON with queries, datasets, components/specs, layout document, source, and ownerId."},
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


def _validate_tool_schema() -> dict[str, Any]:
    return {
        "name": VALIDATE_TOOL_NAME,
        "description": "Validate a GenBI ReportArtifact JSON without saving or emitting an artifact. Use this to inspect missing datasets, fields, chart specs, grid specs, query links, and layout contract issues before create/update.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact": {"type": "object", "description": "ReportArtifact JSON to validate."},
                "threadId": {"type": "string"},
                "turnId": {"type": "string"},
            },
            "required": ["artifact"],
            "additionalProperties": True,
        },
    }


def _result(message: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}


def _error(message: dict[str, Any], code: int, message_text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": code, "message": message_text}}


if __name__ == "__main__":
    main()
