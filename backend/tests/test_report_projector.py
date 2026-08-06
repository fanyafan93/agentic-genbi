from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.harness.events import AgentEvent
from backend.reports.store import ReportStore
from backend.services.report_projector import ReportProjector
from backend.tests.test_report_store import report_config


def _completed_event(action: str, report_id: str) -> AgentEvent:
    result = {
        "ok": True,
        "action": action,
        "reportId": report_id,
        "report": report_config(
            "已更新" if action == "update" else "新建报表"
        ),
    }
    return AgentEvent(
        type="item/completed",
        turn_id="turn-1",
        payload={
            "codex_item_type": "mcpToolCall",
            "mcp_status": "completed",
            "mcp_tool": f"{action}_report",
            "mcp_result": {
                "content": [
                    {"type": "text", "text": json.dumps(result)}
                ]
            },
            "codex_item_id": "item-1",
        },
    )


def _completed_build_event(
    *,
    action: str,
    build_id: str = "build-1",
    revision: int = 4,
    status: str = "building",
    changed_section: str = "charts",
    report: dict[str, object] | None = None,
) -> AgentEvent:
    result: dict[str, object] = {
        "ok": True,
        "action": action,
        "buildId": build_id,
        "revision": revision,
        "status": status,
        "changedSection": changed_section,
        "build": {
            "id": build_id,
            "content": {
                "queries": {
                    "secret-query": {
                        "sql": "SELECT secret FROM private_table"
                    }
                }
            },
        },
    }
    if report is not None:
        result["report"] = report
    return AgentEvent(
        type="item/completed",
        turn_id="turn-1",
        payload={
            "codex_item_type": "mcpToolCall",
            "mcp_status": "completed",
            "mcp_tool": "publish_report_build",
            "mcp_result": {
                "content": [
                    {"type": "text", "text": json.dumps(result)}
                ]
            },
            "codex_item_id": "item-1",
        },
    )


class _NoWriteReportStore:
    def __init__(self) -> None:
        self.create_calls = 0
        self.update_calls = 0

    def create_report(self, *args: object, **kwargs: object) -> None:
        self.create_calls += 1
        raise AssertionError("published reports are already persisted")

    def update_report(self, *args: object, **kwargs: object) -> None:
        self.update_calls += 1
        raise AssertionError("published reports are already persisted")


def test_projector_emits_metadata_only_build_revision_event() -> None:
    projected = ReportProjector(_NoWriteReportStore()).project_report(
        _completed_build_event(action="build_updated"),
        session_id="session-1",
        turn_id="turn-1",
        owner_id="user-1",
    )

    assert projected is not None
    assert projected.type == "genbi/report/build_updated"
    assert projected.payload == {
        "eventSource": "genbi_projection",
        "buildId": "build-1",
        "sessionId": "session-1",
        "turnId": "turn-1",
        "status": "building",
        "revision": 4,
        "changedSection": "charts",
        "codex_item_id": "item-1",
    }
    assert "content" not in projected.payload
    assert "sql" not in json.dumps(projected.payload)


def test_publish_projects_existing_report_without_second_save() -> None:
    store = _NoWriteReportStore()
    report = {
        "id": "report-1",
        "title": "渠道销售",
        "subtitle": "2026-08",
        "ownerId": "user-1",
        "turnId": "turn-1",
        "layout": {"content": [], "zones": {}},
        "filters": {},
        "queries": {},
        "charts": {},
        "tables": {},
        "createdAt": "2026-08-06T00:00:00+00:00",
        "updatedAt": "2026-08-06T00:00:00+00:00",
        "sourceSessionId": "session-1",
    }

    projected = ReportProjector(store).project_report(
        _completed_build_event(
            action="build_published",
            revision=5,
            status="published",
            changed_section="publication",
            report=report,
        ),
        session_id="session-1",
        turn_id="turn-1",
        owner_id="user-1",
    )

    assert projected is not None
    assert projected.type == "genbi/report/created"
    assert projected.payload["id"] == "report-1"
    assert projected.payload["sourceSessionId"] == "session-1"
    assert projected.payload["eventSource"] == "genbi_projection"
    assert store.create_calls == 0
    assert store.update_calls == 0


def test_projector_derives_owner_and_turn_and_emits_report_created(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")

    projected = ReportProjector(store).project_report(
        _completed_event("create", "report_created"),
        session_id="session-1",
        turn_id="turn-1",
        owner_id="user-1",
    )

    assert projected is not None
    assert projected.type == "genbi/report/created"
    assert projected.payload["id"] == "report_created"
    assert projected.payload["ownerId"] == "user-1"
    assert projected.payload["turnId"] == "turn-1"
    persisted = store.get_report("report_created")
    assert persisted is not None
    assert persisted.turnId == "turn-1"


def test_projector_full_update_emits_report_updated(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports.json")
    store.create_report(
        report_config(),
        owner_id="user-1",
        turn_id="turn-0",
        report_id="report_existing",
    )

    projected = ReportProjector(store).project_report(
        _completed_event("update", "report_existing"),
        session_id="session-1",
        turn_id="turn-2",
        owner_id="user-1",
    )

    assert projected is not None
    assert projected.type == "genbi/report/updated"
    assert projected.payload["title"] == "已更新"
    assert projected.payload["turnId"] == "turn-2"


def test_projector_emits_explicit_failure_when_update_target_missing(
    tmp_path: Path,
) -> None:
    projected = ReportProjector(
        ReportStore(tmp_path / "reports.json")
    ).project_report(
        _completed_event("update", "report_missing"),
        session_id="session-1",
        turn_id="turn-1",
        owner_id="user-1",
    )

    assert projected is not None
    assert projected.type == "genbi/report/failed"
    assert projected.payload["reportId"] == "report_missing"
