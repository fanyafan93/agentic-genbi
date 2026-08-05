"""Artifact projection: translate Runtime ``item/completed`` events into
persisted analysis assets.

This is the *only* place a Codex MCP tool-call return value is materialised
into an interactive report (or any other projection asset). Previously the
same fold lived inline inside the streaming SSE loop in
``backend/api/analysis_api.py``; extracting it means the API layer no longer
knows how to validate or persist a report — it only wires events together.

The P2-3 architecture boundary:

* ``analysis_api`` — validates HTTP, calls services, returns HTTP/SSE.
* ``CodexTurnRunner`` — streams the Runtime, pre-creates turns, folds
  projections, enriches events, owns interrupt compensation.
* ``ArtifactProjector`` (this module) — handles the *artifact* side of
  the SSE loop: ``item/completed`` → save report → emit
  ``genbi/artifact/updated``. It never writes a turn row.
* ``SessionService`` — create / read / list / archive session rows
  plus their turn listings.
"""

from __future__ import annotations

import json
from typing import Any

from backend.analysis.report_artifact import normalize_report_artifact, validate_report_artifact
from backend.analysis.interactive_report_store import InteractiveReportStore
from backend.harness.events import AgentEvent


def _maybe_report_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        content_candidate = _maybe_report_payload(value.get("content"))
        if content_candidate:
            return content_candidate
        nested = value.get("interactive_report") or value.get("report") or value
        return dict(nested) if isinstance(nested, dict) and nested.get("artifactType") == "interactive_report" else None
    if isinstance(value, str):
        try:
            return _maybe_report_payload(json.loads(value))
        except json.JSONDecodeError:
            return None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                candidate = _maybe_report_payload(item.get("text"))
            else:
                candidate = _maybe_report_payload(item)
            if candidate:
                return candidate
    return None


def _extract_interactive_report(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("mcp_result", "mcp_output", "result", "output"):
        candidate = _maybe_report_payload(payload.get(key))
        if candidate:
            return candidate
    return None


def interactive_report_payload(report: Any) -> dict[str, Any]:
    payload = {
        "id": report.id,
        "title": report.title,
        "subtitle": report.subtitle,
        "artifactType": report.artifactType,
        "schemaVersion": "1.0",
        "renderer": report.renderer,
        "document": report.document,
        "filters": report.filters,
        "queries": report.queries,
        "chartSpecs": report.chartSpecs,
        "gridSpecs": report.gridSpecs,
        "datasets": report.datasets,
        "originType": report.originType,
    }
    if report.sourceThreadId and report.sourceTurnId:
        payload["source"] = {
            "threadId": report.sourceThreadId,
            "turnId": report.sourceTurnId,
        }
    return payload


class ArtifactProjector:
    """Owns the interactive-report save + artifact-updated event projection."""

    def __init__(self, interactive_report_store: InteractiveReportStore | None = None) -> None:
        self._store = interactive_report_store

    @property
    def store(self) -> InteractiveReportStore | None:
        return self._store

    def project_interactive_report(
        self,
        event: AgentEvent,
        *,
        session_id: str,
        turn_id: str,
        interactive_report_store: Any | None = None,
    ) -> AgentEvent | None:
        """Translate a ``item/completed`` (create_interactive_report) event.

        Strict contract (see P1 "Report Artifact validation must occur
        before normalization"):

        * Only an *already-serialized* report payload is accepted — we
          never call ``compile_interactive_report`` to "guess" one from
          raw MCP arguments. ``compile_interactive_report`` is reserved
          for test fixtures only.
        * If validation fails, we return ``None`` (no artifact event)
          and the Agent is expected to re-emit a corrected payload on
          the next turn.
        * ``normalize_report_artifact`` is a passthrough — no automatic
          field guessing or silent deletion of invalid fields.

        ``interactive_report_store`` is accepted per-call for backwards
        compatibility with call sites that still hold their own store
        handle (e.g. some integration tests). If omitted, the instance's
        constructor-provided store is used.
        """
        store = interactive_report_store if interactive_report_store is not None else self._store
        payload = dict(event.payload)
        if (
            event.type != "item/completed"
            or payload.get("codex_item_type") != "mcpToolCall"
            or payload.get("mcp_status") not in ("completed", "success", None)
        ):
            return None
        report = _extract_interactive_report(payload)
        if report is None:
            return None
        report = normalize_report_artifact(report)
        source = dict(report.get("source") or {})
        source["threadId"] = session_id
        source["turnId"] = turn_id
        report["source"] = source
        report = normalize_report_artifact(report)
        validation_errors = validate_report_artifact(report)
        if validation_errors:
            # Strict contract: do NOT patch, guess, or compile. The
            # Agent must correct the payload. Returning None means no
            # artifact event is emitted, so the UI shows "no artifact
            # yet" and the upstream stream keeps flowing.
            return None
        if store is not None:
            try:
                store.save_report(report)
            except ValueError:
                # Structural save failure must
                # be an explicit failure so the frontend shows an
                # error. Returning None here would mask a real save
                # bug — instead we emit genbi/artifact/failed via the
                # same event stream elsewhere (in CodexTurnRunner).
                return AgentEvent(
                    type="genbi/artifact/failed",
                    turn_id=turn_id,
                    payload={
                        "eventSource": "genbi_projection",
                        "error": "interactive_report_save_failed",
                        "artifactType": "interactive_report",
                        "title": report.get("title"),
                        "codex_thread_id": payload.get("codex_thread_id"),
                        "codex_turn_id": payload.get("codex_turn_id"),
                        "codex_item_id": payload.get("codex_item_id"),
                    },
                )
        return AgentEvent(
            type="genbi/artifact/updated",
            turn_id=turn_id,
            payload={
                **report,
                "eventSource": "genbi_projection",
                "codex_thread_id": payload.get("codex_thread_id"),
                "codex_turn_id": payload.get("codex_turn_id"),
                "codex_item_id": payload.get("codex_item_id"),
            },
        )
