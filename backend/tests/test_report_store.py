from __future__ import annotations

import json
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


def test_report_export_columns_require_safe_fields_and_supported_types(
    tmp_path: Path,
) -> None:
    valid = report_config()
    valid["tables"]["sales-table"]["type"] = "list"
    valid["tables"]["sales-table"]["exportColumns"] = [
        {"field": "region", "title": "区域", "type": "text"},
        {"field": "amount", "title": "销售额", "type": "number"},
    ]
    created = ReportStore(tmp_path / "valid.json").create_report(
        valid,
        owner_id="user-1",
    )

    assert created.tables["sales-table"]["exportColumns"][0]["field"] == "region"

    invalid = report_config()
    invalid["tables"]["sales-table"]["type"] = "list"
    invalid["tables"]["sales-table"]["exportColumns"] = [
        {"field": "region; DROP TABLE sales", "title": "区域", "type": "xml"}
    ]
    with pytest.raises(ReportValidationError, match="safe SQL identifier"):
        ReportStore(tmp_path / "invalid.json").create_report(
            invalid,
            owner_id="user-1",
        )


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


def test_validation_rejects_non_renderable_layout_block_type(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    invalid = report_config()
    invalid["layout"]["content"][1]["type"] = "chart"

    with pytest.raises(ReportValidationError) as exc_info:
        store.create_report(invalid, owner_id="user-1")

    assert exc_info.value.path == "layout.content.1.type"


def test_validation_rejects_non_echarts_chart_option(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    invalid = report_config()
    invalid["charts"]["sales-chart"]["option"] = {
        "type": "line",
        "xField": "region",
        "yField": "amount",
    }

    with pytest.raises(ReportValidationError) as exc_info:
        store.create_report(invalid, owner_id="user-1")

    assert exc_info.value.path == "charts.sales-chart.option.series"


def test_validation_rejects_unsupported_template_query_parameters(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    invalid = report_config()
    invalid["queries"]["sales-query"]["sql"] = (
        "SELECT region, SUM(amount) AS amount FROM sales "
        "WHERE region = '${region}' GROUP BY region"
    )
    invalid["queries"]["sales-query"]["parameters"] = {}

    with pytest.raises(ReportValidationError) as exc_info:
        store.create_report(invalid, owner_id="user-1")

    assert exc_info.value.path == "queries.sales-query.sql"


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


def test_validation_rejects_unsafe_query_control_fields(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    invalid = report_config()
    invalid["queries"]["sales-query"]["controls"] = {
        "sortableFields": ["amount DESC; DROP TABLE sales"],
        "filterableFields": ["region"],
    }

    with pytest.raises(ReportValidationError) as exc_info:
        store.create_report(invalid, owner_id="user-1")

    assert (
        exc_info.value.path
        == "queries.sales-query.controls.sortableFields.0"
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


def test_report_center_partitions_mine_shared_and_public_examples(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    mine = store.create_report(
        report_config("我的报表"),
        owner_id="user-1",
    )
    shared = store.create_report(
        report_config("分享报表"),
        owner_id="user-2",
    )
    example = store.create_report(
        report_config("公开示例"),
        owner_id="seed",
    )
    store.share_report(
        shared.id,
        owner_id="user-2",
        recipient_user_id="user-1",
        permission="view_and_reuse",
    )

    marked = store.set_report_example(
        example.id,
        owner_id="seed",
        is_example=True,
    )
    center = store.list_report_center(user_id="user-1")
    other_center = store.list_report_center(user_id="user-3")

    assert marked is not None and marked.isExample is True
    assert [item["report"]["id"] for item in center["mine"]] == [
        mine.id
    ]
    assert [
        item["report"]["id"] for item in center["sharedWithMe"]
    ] == [shared.id]
    assert [item["report"]["id"] for item in center["examples"]] == [
        example.id
    ]
    assert [
        item["report"]["id"] for item in other_center["examples"]
    ] == [example.id]


def test_example_marking_requires_owner_and_excludes_deleted_reports(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    report = store.create_report(
        report_config("公开示例"),
        owner_id="seed",
    )

    assert store.set_report_example(
        report.id,
        owner_id="other",
        is_example=True,
    ) is None
    assert store.set_report_example(
        report.id,
        owner_id="seed",
        is_example=True,
    ) is not None
    assert store.delete_report(report.id, owner_id="seed") is True
    assert store.list_report_center(user_id="user-1")["examples"] == []
    assert store.set_report_example(
        report.id,
        owner_id="seed",
        is_example=False,
    ) is None


def test_report_center_keeps_latest_example_for_duplicate_title(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    first = store.create_report(
        report_config("重复示例"),
        owner_id="seed-1",
    )
    second = store.create_report(
        report_config("重复示例"),
        owner_id="seed-2",
    )
    store.set_report_example(
        first.id,
        owner_id="seed-1",
        is_example=True,
    )
    store.set_report_example(
        second.id,
        owner_id="seed-2",
        is_example=True,
    )

    center = store.list_report_center(user_id="user-1")

    assert [item["report"]["id"] for item in center["examples"]] == [
        second.id
    ]


def test_delete_soft_deletes_report_without_removing_shares(
    tmp_path: Path,
) -> None:
    path = tmp_path / "reports.json"
    store = ReportStore(path)
    created = store.create_report(report_config(), owner_id="user-1")
    shared = store.share_report(
        created.id,
        owner_id="user-1",
        recipient_user_id="user-2",
        permission="view",
    )

    first_delete = store.delete_report(created.id, owner_id="user-1")
    repeated_delete = store.delete_report(created.id, owner_id="user-1")
    raw_state = json.loads(path.read_text(encoding="utf-8"))

    assert shared is not None
    assert first_delete is True
    assert repeated_delete is True
    assert store.get_report(created.id) is None
    assert store.list_reports(owner_id="user-1") == []
    assert store.list_report_center(user_id="user-2")["sharedWithMe"] == []
    assert raw_state["reports"][0]["deletedAt"] is not None
    assert len(raw_state["shares"]) == 1


def test_deleted_report_rejects_owner_mutations_and_other_owner_delete(
    tmp_path: Path,
) -> None:
    store = ReportStore(tmp_path / "reports.json")
    created = store.create_report(report_config(), owner_id="user-1")

    assert store.delete_report(created.id, owner_id="user-2") is False
    assert store.get_report(created.id) is not None
    assert store.delete_report(created.id, owner_id="user-1") is True
    assert store.update_report(
        created.id,
        report_config("删除后更新"),
        owner_id="user-1",
    ) is None
    assert store.share_report(
        created.id,
        owner_id="user-1",
        recipient_user_id="user-2",
        permission="view",
    ) is None
