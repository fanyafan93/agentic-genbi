from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.reports.build_service import (
    ReportBuildContext,
    ReportBuildService,
)
from backend.reports.build_store import ReportBuildStore
from backend.reports.store import ReportStore


def _service(tmp_path: Path) -> tuple[ReportBuildService, ReportStore]:
    report_store = ReportStore(tmp_path / "reports.json")
    build_store = ReportBuildStore(
        tmp_path / "report-builds.json",
        report_store=report_store,
    )
    return ReportBuildService(build_store), report_store


def _context(
    *,
    owner_id: str = "user-1",
    session_id: str = "session-1",
    turn_id: str = "turn-1",
) -> ReportBuildContext:
    return ReportBuildContext(
        owner_id=owner_id,
        session_id=session_id,
        turn_id=turn_id,
    )


def _start(
    service: ReportBuildService,
    context: ReportBuildContext,
) -> dict[str, Any]:
    return service.invoke(
        "start_report_build",
        {"title": "渠道销售", "subtitle": "2026-08"},
        context,
    )


def _valid_query() -> dict[str, Any]:
    return {
        "dataSource": "doris",
        "sql": "SELECT channel, SUM(amount) AS amount FROM sales GROUP BY channel",
        "parameters": {},
        "pagination": False,
    }


def _complete_build(
    service: ReportBuildService,
    context: ReportBuildContext,
) -> str:
    started = _start(service, context)
    build_id = started["buildId"]
    service.invoke(
        "upsert_report_query",
        {
            "build_id": build_id,
            "query_id": "sales-query",
            "query": _valid_query(),
        },
        context,
    )
    service.invoke(
        "upsert_report_chart",
        {
            "build_id": build_id,
            "chart_id": "sales-chart",
            "chart": {
                "queryId": "sales-query",
                "option": {"series": [{"type": "bar"}]},
            },
        },
        context,
    )
    service.invoke(
        "set_report_layout",
        {
            "build_id": build_id,
            "layout": {
                "content": [
                    {
                        "type": "ChartBlock",
                        "props": {
                            "id": "sales-chart-block",
                            "chartId": "sales-chart",
                        },
                    },
                ],
                "zones": {},
            },
        },
        context,
    )
    return build_id


def test_service_persists_incremental_revisions_for_small_upserts(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    context = _context()

    started = _start(service, context)
    query = service.invoke(
        "upsert_report_query",
        {
            "build_id": started["buildId"],
            "query_id": "sales-query",
            "query": _valid_query(),
        },
        context,
    )
    chart = service.invoke(
        "upsert_report_chart",
        {
            "build_id": started["buildId"],
            "chart_id": "sales-chart",
            "chart": {
                "queryId": "sales-query",
                "option": {"series": [{"type": "bar"}]},
            },
        },
        context,
    )
    restored = service.invoke(
        "get_report_build",
        {"build_id": started["buildId"]},
        context,
    )

    assert [started["revision"], query["revision"], chart["revision"]] == [
        0,
        1,
        2,
    ]
    assert restored["build"]["content"]["charts"]["sales-chart"][
        "queryId"
    ] == "sales-query"


def test_failed_step_keeps_content_and_stops_after_two_corrections(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    context = _context()
    build_id = _start(service, context)["buildId"]
    arguments = {
        "build_id": build_id,
        "chart_id": "bad",
        "chart": {
            "queryId": "missing",
            "option": {"series": [{"type": "bar"}]},
        },
    }

    first = service.invoke("upsert_report_chart", arguments, context)
    second = service.invoke("upsert_report_chart", arguments, context)
    third = service.invoke("upsert_report_chart", arguments, context)

    assert first["ok"] is False
    assert first["retryable"] is True
    assert first["build"]["content"]["charts"] == {}
    assert first["errors"][0]["path"] == "charts.bad.queryId"
    assert [first["revision"], second["revision"], third["revision"]] == [
        1,
        2,
        3,
    ]
    assert third["retryable"] is False
    assert third["error"]["code"] == "report_build_retry_exhausted"


def test_query_step_rejects_unsupported_data_source_before_render(
    tmp_path: Path,
) -> None:
    service, _ = _service(tmp_path)
    context = _context()
    build_id = _start(service, context)["buildId"]

    result = service.invoke(
        "upsert_report_query",
        {
            "build_id": build_id,
            "query_id": "sales-query",
            "query": {
                **_valid_query(),
                "dataSource": "dm.dm_channel_mtsg_sale_total",
            },
        },
        context,
    )

    assert result["ok"] is False
    assert result["errors"][0]["path"] == (
        "queries.sales-query.dataSource"
    )
    assert "doris" in result["errors"][0]["message"]
    assert result["build"]["content"]["queries"] == {}


def test_service_rejects_cross_session_build_access(tmp_path: Path) -> None:
    service, _ = _service(tmp_path)
    build_id = _start(service, _context())["buildId"]

    denied = service.invoke(
        "get_report_build",
        {"build_id": build_id},
        _context(session_id="session-2"),
    )

    assert denied["ok"] is False
    assert denied["error"]["code"] == "report_build_access_denied"


def test_publish_is_idempotent_and_creates_one_formal_report(
    tmp_path: Path,
) -> None:
    service, report_store = _service(tmp_path)
    context = _context()
    build_id = _complete_build(service, context)

    first = service.invoke(
        "publish_report_build",
        {"build_id": build_id},
        context,
    )
    second = service.invoke(
        "publish_report_build",
        {"build_id": build_id},
        context,
    )

    assert first["ok"] is True
    assert first["report"]["id"] == second["report"]["id"]
    assert first["buildId"] == build_id
    assert len(report_store.list_reports(owner_id="user-1")) == 1
