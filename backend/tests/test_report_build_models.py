from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.reports.build_models import (
    ReportBuildRecord,
    renderable_report_from_build,
)
from backend.reports.schema import collect_report_validation_errors


def _valid_query() -> dict[str, Any]:
    return {
        "dataSource": "doris",
        "sql": (
            "SELECT region, SUM(amount) AS amount "
            "FROM sales WHERE region = :region GROUP BY region"
        ),
        "parameters": {
            "region": {"filterId": "region", "type": "string"},
        },
        "pagination": False,
    }


def _report_config() -> dict[str, Any]:
    return {
        "title": "渠道销售",
        "subtitle": "2026-08",
        "layout": {"root": {"props": {}}, "content": [], "zones": {}},
        "filters": {
            "region": {
                "type": "select",
                "label": "区域",
                "options": [{"label": "华东", "value": "华东"}],
            },
        },
        "queries": {"sales-query": _valid_query()},
        "charts": {
            "sales-chart": {
                "queryId": "sales-query",
                "option": {"series": [{"type": "bar"}]},
            },
        },
        "tables": {
            "sales-table": {
                "queryId": "sales-query",
                "options": {
                    "columns": [{"field": "region", "title": "区域"}],
                },
            },
        },
    }


def _build_record(content: dict[str, Any]) -> ReportBuildRecord:
    return ReportBuildRecord(
        id="build-1",
        ownerId="user-1",
        sessionId="session-1",
        turnId="turn-1",
        targetReportId=None,
        status="building",
        content=content,
        validationErrors=[],
        revision=3,
        publishedReportId=None,
        lastSuccessfulStep="upsert_report_table",
        stepAttempts={},
        createdAt="2026-08-06T10:00:00Z",
        updatedAt="2026-08-06T10:01:00Z",
        expiresAt="2026-08-13T10:00:00Z",
    )


def test_collect_report_validation_errors_keeps_independent_failures() -> None:
    invalid = _report_config()
    invalid["queries"]["sales-query"]["parameters"] = []
    invalid["charts"]["sales-chart"]["queryId"] = "missing-query"
    invalid["tables"]["sales-table"]["options"] = {}

    issues = collect_report_validation_errors(invalid)

    assert [issue.path for issue in issues] == [
        "queries.sales-query.parameters",
        "charts.sales-chart.queryId",
        "tables.sales-table.options.columns",
    ]


def test_renderable_build_derives_stable_layout_without_mutating_content() -> None:
    content = _report_config()
    content["layout"].pop("root")
    original = deepcopy(content)
    record = _build_record(content)

    rendered = renderable_report_from_build(record)

    assert record.content == original
    assert [block["type"] for block in rendered["layout"]["content"]] == [
        "FilterBlock",
        "ChartBlock",
        "TableBlock",
    ]
    assert rendered["layout"]["content"][0]["props"] == {
        "id": "build-1-filter-block",
        "filterIds": ["region"],
    }
    assert rendered["layout"]["content"][1]["props"]["chartId"] == "sales-chart"
    assert rendered["layout"]["content"][2]["props"]["tableId"] == "sales-table"
    assert rendered["buildId"] == "build-1"
    assert rendered["buildRevision"] == 3
    assert rendered["buildStatus"] == "building"
    assert rendered["sourceSessionId"] == "session-1"
    assert rendered["isExample"] is False
    assert rendered["layout"]["root"] == {"props": {}}


def test_renderable_build_preserves_explicit_layout() -> None:
    content = _report_config()
    content["layout"]["content"] = [
        {
            "type": "MarkdownBlock",
            "props": {"id": "note", "content": "结论"},
        },
    ]

    rendered = renderable_report_from_build(_build_record(content))

    assert rendered["layout"]["content"] == content["layout"]["content"]
