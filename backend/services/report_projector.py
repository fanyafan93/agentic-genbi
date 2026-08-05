"""Project completed Codex Report tool calls into persisted Reports."""

from __future__ import annotations

import json
from typing import Any

from backend.harness.events import AgentEvent
from backend.reports.models import report_to_payload
from backend.reports.schema import ReportValidationError


def _report_tool_result(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            return _report_tool_result(json.loads(value))
        except json.JSONDecodeError:
            return None
    if isinstance(value, list):
        for item in value:
            candidate = _report_tool_result(item)
            if candidate:
                return candidate
        return None
    if not isinstance(value, dict):
        return None
    if value.get("type") == "text":
        return _report_tool_result(value.get("text"))
    if (
        value.get("ok") is True
        and value.get("action") in {"create", "update"}
        and isinstance(value.get("report"), dict)
    ):
        return value
    for key in ("content", "mcp_result", "mcp_output", "result", "output"):
        candidate = _report_tool_result(value.get(key))
        if candidate:
            return candidate
    return None


class ReportProjector:
    def __init__(self, report_store: Any | None = None) -> None:
        self._store = report_store

    @property
    def store(self) -> Any | None:
        return self._store

    def project_report(
        self,
        event: AgentEvent,
        *,
        session_id: str,
        turn_id: str,
        owner_id: str,
    ) -> AgentEvent | None:
        payload = dict(event.payload)
        if (
            event.type != "item/completed"
            or payload.get("codex_item_type") != "mcpToolCall"
            or payload.get("mcp_status")
            not in ("completed", "success", None)
        ):
            return None
        result = _report_tool_result(payload)
        if result is None:
            return None

        report_id = str(result.get("reportId") or "").strip()
        action = str(result.get("action") or "").strip()
        report = dict(result["report"])
        try:
            if self._store is None:
                return None
            if action == "create":
                saved = self._store.create_report(
                    report,
                    owner_id=owner_id,
                    turn_id=turn_id,
                    report_id=report_id,
                )
                event_type = "genbi/report/created"
            else:
                saved = self._store.update_report(
                    report_id,
                    report,
                    owner_id=owner_id,
                    turn_id=turn_id,
                )
                if saved is None:
                    raise ValueError("report_not_found")
                event_type = "genbi/report/updated"
        except (ReportValidationError, ValueError):
            return AgentEvent(
                type="genbi/report/failed",
                turn_id=turn_id,
                payload={
                    "eventSource": "genbi_projection",
                    "reportId": report_id,
                    "action": action,
                    "error": "report_save_failed",
                    "codex_item_id": payload.get("codex_item_id"),
                },
            )

        return AgentEvent(
            type=event_type,
            turn_id=turn_id,
            payload={
                **report_to_payload(saved),
                "eventSource": "genbi_projection",
                "codex_item_id": payload.get("codex_item_id"),
            },
        )
