from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.reports.models import report_to_payload
from backend.reports.schema import ReportValidationError
from backend.reports.store import ReportStore


def report_config(title: str = "渠道销售") -> dict[str, Any]:
    return {
        "title": title,
        "subtitle": "2026-08",
        "layout": {
            "root": {"props": {}},
            "content": [
                {
                    "type": "FilterBlock",
                    "props": {"id": "filter-block", "filterIds": ["region"]},
                },
                {
                    "type": "ChartBlock",
                    "props": {"id": "chart-block", "chartId": "sales-chart"},
                },
                {
                    "type": "TableBlock",
                    "props": {"id": "table-block", "tableId": "sales-table"},
                },
            ],
            "zones": {},
        },
        "filters": {
            "region": {
                "type": "select",
                "label": "区域",
                "defaultValue": "华东",
                "options": [{"label": "华东", "value": "华东"}],
            }
        },
        "queries": {
            "sales-query": {
                "dataSource": "doris",
                "sql": (
                    "SELECT region, SUM(amount) AS amount "
                    "FROM sales WHERE region = :region GROUP BY region"
                ),
                "parameters": {
                    "region": {"filterId": "region", "type": "string"}
                },
                "pagination": False,
            }
        },
        "charts": {
            "sales-chart": {
                "queryId": "sales-query",
                "option": {"series": [{"type": "bar"}]},
            }
        },
        "tables": {
            "sales-table": {
                "queryId": "sales-query",
                "options": {
                    "columns": [{"field": "region", "title": "区域"}]
                },
            }
        },
    }


def test_create_and_full_update_keep_one_current_report(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports.json")

    created = store.create_report(
        report_config(),
        owner_id="user-1",
        turn_id="turn-1",
    )
    updated = store.update_report(
        created.id,
        report_config("渠道销售修订"),
        owner_id="user-1",
        turn_id="turn-2",
    )

    assert updated is not None
    assert updated.id == created.id
    assert updated.ownerId == created.ownerId
    assert updated.createdAt == created.createdAt
    assert updated.turnId == "turn-2"
    assert updated.title == "渠道销售修订"
    assert len(store.list_reports(owner_id="user-1")) == 1


def test_code_created_report_has_no_turn_or_legacy_artifact_fields(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")

    created = store.create_report(report_config(), owner_id="seed")
    payload = report_to_payload(created)

    assert payload["turnId"] is None
    assert "datasets" not in payload
    assert "artifactType" not in payload
    assert "renderer" not in payload
    assert "document" not in payload
    assert set(payload) >= {
        "id",
        "title",
        "subtitle",
        "ownerId",
        "turnId",
        "layout",
        "filters",
        "charts",
        "tables",
        "queries",
        "createdAt",
        "updatedAt",
    }


def test_non_agent_update_preserves_existing_turn(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports.json")
    created = store.create_report(
        report_config(),
        owner_id="user-1",
        turn_id="turn-1",
    )

    updated = store.update_report(
        created.id,
        report_config("用户编辑"),
        owner_id="user-1",
    )

    assert updated is not None
    assert updated.turnId == "turn-1"


def test_update_rejects_a_different_owner(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports.json")
    created = store.create_report(report_config(), owner_id="user-1")

    updated = store.update_report(
        created.id,
        report_config("越权覆盖"),
        owner_id="user-2",
    )

    assert updated is None
    assert store.get_report(created.id).title == "渠道销售"


def test_validation_rejects_missing_layout_reference(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports.json")
    invalid = report_config()
    invalid["layout"]["content"][1]["props"]["chartId"] = "missing-chart"

    with pytest.raises(ReportValidationError) as exc_info:
        store.create_report(invalid, owner_id="user-1")

    assert exc_info.value.path == "layout.content.1.props.chartId"


def test_validation_rejects_write_sql_and_unbound_placeholders(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    write_query = report_config()
    write_query["queries"]["sales-query"]["sql"] = (
        "UPDATE sales SET amount = 0"
    )
    missing_binding = report_config()
    missing_binding["queries"]["sales-query"]["sql"] += (
        " HAVING SUM(amount) > :minimum"
    )

    with pytest.raises(ReportValidationError) as write_error:
        store.create_report(write_query, owner_id="user-1")
    with pytest.raises(ReportValidationError) as binding_error:
        store.create_report(missing_binding, owner_id="user-1")

    assert write_error.value.path == "queries.sales-query.sql"
    assert (
        binding_error.value.path
        == "queries.sales-query.parameters"
    )


def test_sharing_keeps_one_record_and_supports_existing_permissions(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    created = store.create_report(report_config(), owner_id="user-1")

    first = store.share_report(
        created.id,
        owner_id="user-1",
        recipient_user_id="user-2",
        permission="view",
    )
    updated = store.share_report(
        created.id,
        owner_id="user-1",
        recipient_user_id="user-2",
        permission="view_and_reuse",
    )
    center = store.list_report_center(user_id="user-2")

    assert first is not None
    assert updated is not None
    assert len(center["sharedWithMe"]) == 1
    assert center["sharedWithMe"][0]["permission"] == "view_and_reuse"
