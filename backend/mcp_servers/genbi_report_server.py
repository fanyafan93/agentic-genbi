from __future__ import annotations

import json
import sys
from typing import Any

from backend.analysis.report_artifact import issues_to_payload, validate_report_artifact


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
    # The tool is intentionally strict: ``artifact`` is the only
    # accepted input shape, and Thread/Turn IDs are NOT accepted from
    # the agent. The GenBI runtime injects source.threadId / turnId
    # at the projection layer; any incoming ``codex_*_pending`` or
    # client-supplied id was exactly the silent-fake-lineage behavior
    # the contract prohibits.
    artifact = arguments.get("artifact")
    if not isinstance(artifact, dict):
        return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": False, "status": "validation_failed", "errors": [{"path": "artifact", "code": "required", "message": "artifact is required and must be a complete ReportArtifact object."}], "fatal": True}, ensure_ascii=False)}]})
    # The agent must not supply lineage fields. GenBI Runtime
    # injects source.threadId / turnId / codex_* at projection time;
    # the agent fabricating them in the artifact creates fake
    # lineage, which is exactly the contract violation.
    forbidden_top_level = ("threadId", "turnId", "codex_thread_id", "codex_turn_id", "codex_item_id", "source")
    for forbidden in forbidden_top_level:
        if forbidden in artifact:
            return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": False, "status": "validation_failed", "errors": [{"path": f"artifact.{forbidden}", "code": "forbidden_field", "message": "Thread/Turn/Item IDs 与 source 由 GenBI Runtime 注入，agent 不应填写。"}], "fatal": True}, ensure_ascii=False)}]})
    issues = validate_report_artifact(artifact)
    if issues:
        return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": False, "status": "validation_failed", "errors": issues_to_payload(issues), "fatal": True}, ensure_ascii=False)}]})
    return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": True, "status": "validated", "interactive_report": artifact}, ensure_ascii=False)}]})


def _validate_interactive_report(message: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    artifact = arguments.get("artifact")
    if not isinstance(artifact, dict):
        return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": False, "status": "validation_failed", "errors": [{"path": "artifact", "code": "required", "message": "artifact is required."}], "fatal": True}, ensure_ascii=False)}]})
    issues = validate_report_artifact(artifact)
    if issues:
        return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": False, "status": "validation_failed", "errors": issues_to_payload(issues)}, ensure_ascii=False)}]})
    return _result(message, {"content": [{"type": "text", "text": json.dumps({"ok": True, "status": "valid", "interactive_report": artifact}, ensure_ascii=False)}]})


def _normalize_tool_arguments(value: Any) -> Any:
    """Drop empty values and unwrap single-key ``{item: ...}`` shells.

    PowerShell/MCP adapters sometimes serialize large arguments as
    ``{ "item": "..." }`` wrappers; we unwrap that shape to make
    ``artifact`` reachable. We do NOT perform any other rewriting
    (no field inference, no title/subtitle defaults, no row
    padding). Incomplete inputs are rejected, not coerced.
    """
    unwrapped = _unwrap_item_payload(value)
    return _drop_empty_values(unwrapped)


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
        # PowerShell object strings are not auto-coerced to dicts; the
        # call will surface a validation error rather than fabricate
        # a default report.
        return value
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


def _create_tool_schema() -> dict[str, Any]:
    return {
        "name": CREATE_TOOL_NAME,
        "description": "Submit a complete GenBI ReportArtifact for validation. The tool accepts only an ``artifact`` object; Thread/Turn/Item IDs are forbidden here (the GenBI Runtime injects them at projection time). Invalid artifacts return structured errors and are NOT saved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact": {
                    "type": "object",
                    "description": "Complete ReportArtifact JSON. Must satisfy validate_report_artifact. Thread/Turn/Item IDs and the source object are populated server-side; supplying them is an error.",
                },
            },
            "required": ["artifact"],
            "additionalProperties": False,
        },
    }


def _validate_tool_schema() -> dict[str, Any]:
    return {
        "name": VALIDATE_TOOL_NAME,
        "description": "Validate a GenBI ReportArtifact JSON without saving. Use this to inspect missing datasets, fields, chart specs, grid specs, query links, and layout contract issues before create.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact": {"type": "object", "description": "ReportArtifact JSON to validate."},
            },
            "required": ["artifact"],
            "additionalProperties": False,
        },
    }


def _result(message: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "result": result}


def _error(message: dict[str, Any], code: int, message_text: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": code, "message": message_text}}


if __name__ == "__main__":
    main()
