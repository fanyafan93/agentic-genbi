from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class ReportValidationIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class ReportBuildRecord:
    id: str
    ownerId: str
    sessionId: str
    turnId: str
    targetReportId: str | None
    status: str
    content: dict[str, Any]
    validationErrors: list[dict[str, str]]
    revision: int
    publishedReportId: str | None
    lastSuccessfulStep: str | None
    stepAttempts: dict[str, int]
    createdAt: str
    updatedAt: str
    expiresAt: str


def report_build_to_payload(
    record: ReportBuildRecord,
    *,
    renderable: bool = False,
) -> dict[str, Any]:
    if renderable:
        return renderable_report_from_build(record)
    return {
        field.name: deepcopy(getattr(record, field.name))
        for field in fields(record)
    }


def report_build_from_payload(
    payload: dict[str, Any],
) -> ReportBuildRecord:
    allowed = {field.name for field in fields(ReportBuildRecord)}
    return ReportBuildRecord(
        **{
            key: deepcopy(value)
            for key, value in payload.items()
            if key in allowed
        }
    )


def renderable_report_from_build(
    record: ReportBuildRecord,
) -> dict[str, Any]:
    content = deepcopy(record.content)
    layout = content.setdefault(
        "layout",
        {"content": [], "zones": {}},
    )
    layout.setdefault("root", {"props": {}})
    explicit_content = layout.get("content")
    if isinstance(explicit_content, list) and not explicit_content:
        layout["content"] = _derived_layout_content(record, content)

    return {
        "id": record.id,
        "title": str(content.get("title", "")),
        "subtitle": str(content.get("subtitle", "")),
        "ownerId": record.ownerId,
        "turnId": record.turnId,
        "sourceSessionId": record.sessionId,
        "isExample": False,
        "layout": layout,
        "filters": deepcopy(content.get("filters", {})),
        "charts": deepcopy(content.get("charts", {})),
        "tables": deepcopy(content.get("tables", {})),
        "queries": deepcopy(content.get("queries", {})),
        "createdAt": record.createdAt,
        "updatedAt": record.updatedAt,
        "buildId": record.id,
        "buildRevision": record.revision,
        "buildStatus": record.status,
        "buildValidationErrors": deepcopy(record.validationErrors),
    }


def _derived_layout_content(
    record: ReportBuildRecord,
    content: dict[str, Any],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    filters = content.get("filters")
    if isinstance(filters, dict) and filters:
        blocks.append(
            {
                "type": "FilterBlock",
                "props": {
                    "id": f"{record.id}-filter-block",
                    "filterIds": sorted(str(filter_id) for filter_id in filters),
                },
            }
        )

    charts = content.get("charts")
    if isinstance(charts, dict):
        for chart_id in sorted(str(key) for key in charts):
            blocks.append(
                {
                    "type": "ChartBlock",
                    "props": {
                        "id": f"{record.id}-chart-{chart_id}",
                        "chartId": chart_id,
                    },
                }
            )

    tables = content.get("tables")
    if isinstance(tables, dict):
        for table_id in sorted(str(key) for key in tables):
            blocks.append(
                {
                    "type": "TableBlock",
                    "props": {
                        "id": f"{record.id}-table-{table_id}",
                        "tableId": table_id,
                    },
                }
            )
    return blocks
