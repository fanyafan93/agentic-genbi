from __future__ import annotations

import json
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.harness.codex_projection_store import CodexProjectionStore
from backend.harness.events import AgentEvent
from backend.harness.session_catalog import SessionCatalog
from backend.reports.store import ReportStore
from backend.services.codex_turn_runner import (
    AnalysisTurnRequest,
    CodexTurnRunner,
)
from backend.services.report_projector import ReportProjector
from backend.tests.test_report_store import report_config


class FakeReportRuntime:
    enabled = True

    async def async_stream(self, _question: str, *, context: dict):
        result = {
            "ok": True,
            "action": "create",
            "reportId": "report_from_turn",
            "report": report_config(),
        }
        yield AgentEvent(
            type="item/completed",
            turn_id=str(context["turn_id"]),
            payload={
                "codex_item_type": "mcpToolCall",
                "mcp_status": "completed",
                "mcp_result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result),
                        }
                    ]
                },
            },
        )
        yield AgentEvent(
            type="turn/completed",
            turn_id=str(context["turn_id"]),
            payload={"status": "completed"},
        )


def test_turn_runner_projects_report_with_session_owner(
    tmp_path: Path,
) -> None:
    catalog = SessionCatalog(tmp_path / "sessions.jsonl")
    projections = CodexProjectionStore(tmp_path / "turns.jsonl")
    reports = ReportStore(tmp_path / "reports.json")
    catalog.register_session(
        session_id="session-1",
        product_kind="analysis_task",
        title="Report",
        user_id="session-owner",
        status="active",
        codex_session_id="session-1",
    )
    runner = CodexTurnRunner(
        analysis_runtime=FakeReportRuntime(),
        session_catalog=catalog,
        codex_projection_store=projections,
        report_projector=ReportProjector(reports),
    )

    async def collect() -> list[AgentEvent]:
        return [
            event
            async for event, _, _ in runner.stream_runtime_events(
                AnalysisTurnRequest(question="生成报表"),
                session_id="session-1",
                turn_id="turn-1",
            )
        ]

    events = asyncio.run(collect())

    saved = reports.get_report("report_from_turn")
    assert saved is not None
    assert saved.ownerId == "session-owner"
    assert saved.turnId == "turn-1"
    assert any(event.type == "genbi/report/created" for event in events)


def test_runtime_context_uses_initial_report_key(tmp_path: Path) -> None:
    runner = CodexTurnRunner(
        analysis_runtime=FakeReportRuntime(),
        session_catalog=SessionCatalog(tmp_path / "sessions.jsonl"),
        codex_projection_store=CodexProjectionStore(
            tmp_path / "turns.jsonl"
        ),
        report_projector=ReportProjector(
            ReportStore(tmp_path / "reports.json")
        ),
    )
    report = {"id": "report_context", **report_config()}

    context = runner.runtime_context(
        AnalysisTurnRequest(
            question="分析",
            metadata={"initial_report": report},
        ),
        session_id="session-1",
        turn_id="turn-1",
    )

    assert context["initial_report"] == report


def test_runtime_context_uses_server_session_principal_for_report_tools(
    tmp_path: Path,
) -> None:
    catalog = SessionCatalog(tmp_path / "sessions.jsonl")
    catalog.register_session(
        session_id="session-1",
        product_kind="analysis_task",
        title="Report",
        user_id="user-1",
        status="active",
        metadata={
            "tenant_id": "tenant-1",
            "workspace_id": "workspace-1",
        },
        codex_session_id="session-1",
    )
    runner = CodexTurnRunner(
        analysis_runtime=FakeReportRuntime(),
        session_catalog=catalog,
        codex_projection_store=CodexProjectionStore(
            tmp_path / "turns.jsonl"
        ),
        report_projector=ReportProjector(
            ReportStore(tmp_path / "reports.json")
        ),
    )

    context = runner.runtime_context(
        AnalysisTurnRequest(
            question="分析",
            user_id="user-1",
            metadata={"roles": ["analyst"]},
        ),
        session_id="session-1",
        turn_id="turn-1",
    )

    assert context["report_tool_owner_id"] == "user-1"
    assert context["report_tool_tenant_id"] == "tenant-1"
    assert context["report_tool_workspace_id"] == "workspace-1"
    assert context["report_tool_roles"] == ["analyst"]
