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
        arguments = _normalize_tool_arguments(params.get("arguments") if isinstance(params.get("arguments"), dict) else {})
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


def _normalize_tool_arguments(value: Any) -> Any:
    unwrapped = _unwrap_item_payload(value)
    return _normalize_report_shapes(_drop_empty_values(unwrapped))


def _unwrap_item_payload(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value.keys()) == {"item"}:
            return _unwrap_item_payload(value["item"])
        return {key: _unwrap_item_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unwrap_item_payload(item) for item in value]
    if isinstance(value, str):
        parsed_json = _parse_json_value(value)
        if parsed_json is not None:
            return _unwrap_item_payload(parsed_json)
        parsed = _parse_powershell_object(value)
        return parsed if parsed is not None else value
    return value


def _normalize_report_shapes(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        normalized = {item_key: _normalize_report_shapes(item_value, key=item_key) for item_key, item_value in value.items()}
        if key in {"rows", "series", "columns", "content", "filterBindings", "filters"}:
            return [normalized]
        return normalized
    if isinstance(value, list):
        items = [_normalize_report_shapes(item, key=key) for item in value]
        if key in {"rows", "series", "columns", "content", "filterBindings", "filters"}:
            flattened: list[Any] = []
            for item in items:
                if isinstance(item, list):
                    flattened.extend(item)
                else:
                    flattened.append(item)
            return flattened
        return items
    if value is None and key in {"queries", "datasets", "chartSpecs", "gridSpecs", "zones"}:
        return {}
    return value


def _drop_empty_values(value: Any) -> Any:
    if isinstance(value, list):
        return [item for item in (_drop_empty_values(item) for item in value) if item is not None]
    if isinstance(value, dict):
        return {key: item for key, item in ((key, _drop_empty_values(item)) for key, item in value.items()) if item is not None}
    if value == "":
        return None
    return value


def _parse_json_value(value: str) -> Any:
    text = value.strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_powershell_object(value: str) -> dict[str, Any] | None:
    text = value.strip()
    if not text.startswith("@{") or not text.endswith("}"):
        return None
    body = text[2:-1].strip()
    if not body or "System.Object[]" in body:
        return None
    parsed: dict[str, Any] = {}
    for part in body.split(";"):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            return None
        key, raw = item.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key or not raw or raw == "System.Object[]":
            continue
        parsed[key] = _coerce_scalar(raw)
    return parsed or None


def _coerce_scalar(value: str) -> Any:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if "." not in value and "e" not in value.lower():
            return int(value)
        return float(value)
    except ValueError:
        return value


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
