from __future__ import annotations

from pathlib import Path
from runpy import run_path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.reports.query_service import bind_query_parameters
from backend.reports.schema import validate_report_config

examples = SimpleNamespace(
    **run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "seed_report_examples.py"
        )
    )
)
build_complex_report = examples.build_complex_report
build_simple_report = examples.build_simple_report


def test_simple_report_is_a_valid_single_chart_single_table_example() -> None:
    report = build_simple_report()

    validate_report_config(report)

    assert report["title"] == "抖音订单简版示例"
    assert len(report["charts"]) == 1
    assert len(report["tables"]) == 1
    assert set(report["queries"]) == {"daily_trend"}
    assert report["filters"]["date_range"]["defaultValue"] == [
        "2026-07-05",
        "2026-08-03",
    ]


def test_complex_report_is_a_valid_multi_chart_multi_table_example() -> None:
    report = build_complex_report()

    validate_report_config(report)

    assert report["title"] == "抖音订单经营分析（复杂示例）"
    assert len(report["charts"]) == 4
    assert len(report["tables"]) == 2
    assert len(report["queries"]) == 5
    assert (
        report["tables"]["product_ranking"]["options"]["widthMode"]
        == "standard"
    )
    assert {
        block["type"]
        for block in report["layout"]["content"]
    } >= {"FilterBlock", "ChartBlock", "TableBlock", "SectionBlock", "MarkdownBlock"}


def test_report_examples_query_real_order_data_with_bound_date_filters() -> None:
    reports = [build_simple_report(), build_complex_report()]

    for report in reports:
        for query in report["queries"].values():
            assert query["dataSource"] == "doris"
            assert "ods.ods_dy_order" in query["sql"]
            assert ":start_date" in query["sql"]
            assert ":end_date" in query["sql"]
            assert query["parameters"] == {
                "start_date": {
                    "filterId": "date_range",
                    "type": "date",
                    "valueIndex": 0,
                },
                "end_date": {
                    "filterId": "date_range",
                    "type": "date",
                    "valueIndex": 1,
                },
            }


def test_report_example_sql_can_be_formatted_by_pymysql() -> None:
    reports = [build_simple_report(), build_complex_report()]

    for report in reports:
        for query in report["queries"].values():
            sql, params = bind_query_parameters(
                query,
                {"date_range": ["2026-07-05", "2026-08-03"]},
            )
            escaped_params = {
                name: f"'{value}'"
                for name, value in params.items()
            }

            formatted_sql = sql % escaped_params

            assert "2026-07-05" in formatted_sql
            assert "2026-08-03" in formatted_sql


def test_additional_report_examples_cover_requested_layouts() -> None:
    complex_table = examples.build_complex_table_report()
    multi_column = examples.build_multi_column_report()
    independent = examples.build_independent_filters_report()

    for report in (complex_table, multi_column, independent):
        validate_report_config(report)
        assert report["filters"]
        assert report["queries"]

    assert len(complex_table["filters"]) >= 3
    detail_columns = complex_table["tables"]["order_detail"]["options"][
        "columns"
    ]
    assert sum(column["width"] for column in detail_columns) > 1000
    assert {
        column["field"]
        for column in detail_columns
        if column.get("sortable")
    } >= {"order_date", "pay_amount"}
    assert {
        column["field"]
        for column in detail_columns
        if column.get("filterOptions")
    } >= {"order_status", "traffic_source"}

    spans = {
        block["props"].get("columnSpan")
        for block in multi_column["layout"]["content"]
    }
    assert {4, 6, 12} <= spans


def test_independent_report_filters_bind_to_disjoint_queries() -> None:
    report = examples.build_independent_filters_report()
    left_filter_ids = {
        binding["filterId"]
        for query_id, query in report["queries"].items()
        if query_id.startswith("left_")
        for binding in query["parameters"].values()
    }
    right_filter_ids = {
        binding["filterId"]
        for query_id, query in report["queries"].items()
        if query_id.startswith("right_")
        for binding in query["parameters"].values()
    }

    assert left_filter_ids == {"left_date_range", "left_statuses"}
    assert right_filter_ids == {
        "right_date_range",
        "right_traffic_sources",
    }
    assert left_filter_ids.isdisjoint(right_filter_ids)


def test_table_showcase_covers_grouped_pivot_and_all_field_tables() -> None:
    report = examples.build_table_showcase_report()

    validate_report_config(report)

    assert report["title"] == "抖音订单表格能力示例"
    assert set(report["tables"]) == {
        "traffic_shop_group",
        "status_traffic_pivot",
        "all_fields",
    }
    assert report["tables"]["traffic_shop_group"]["options"]["groupBy"] == [
        "traffic_source",
        "shop_name",
    ]
    assert report["tables"]["status_traffic_pivot"]["type"] == "pivot"
    pivot_options = report["tables"]["status_traffic_pivot"]["options"]
    assert pivot_options["rowHierarchyType"] == "tree"
    assert {
        indicator["indicatorKey"]
        for indicator in pivot_options["indicators"]
    } == {"order_count", "pay_amount"}

    wide_table = report["tables"]["all_fields"]
    assert len(wide_table["options"]["columns"]) == 53
    assert [
        column["field"]
        for column in wide_table["exportColumns"]
    ] == [
        "sub_trade_no",
        "trade_no",
        "order_time",
        "order_status",
        "product",
        "product_id",
        "product_cnt",
        "pay_amt",
        "traffic_source",
        "tlant_name",
    ]
    assert "exportColumns" not in report["tables"]["traffic_shop_group"]
    assert "exportColumns" not in report["tables"]["status_traffic_pivot"]
    assert sum(
        int(column["width"])
        for column in wide_table["options"]["columns"]
    ) > 7000
    assert report["queries"]["all_fields"]["pagination"] is True
    wide_sql = report["queries"]["all_fields"]["sql"]
    assert "consignee_tel" in wide_sql
    assert "****" in wide_sql
    assert "receiver_address" in wide_sql


def test_image_layout_report_uses_requested_multicolumn_template() -> None:
    report = examples.build_image_layout_report()

    validate_report_config(report)

    assert report["title"] == "抖音订单经营驾驶舱（图片布局模板）"
    assert len(report["charts"]) == 5
    assert len(report["tables"]) == 1
    visual_spans = [
        block["props"]["columnSpan"]
        for block in report["layout"]["content"]
        if block["type"] in {"ChartBlock", "TableBlock"}
    ]
    assert visual_spans == [4, 8, 4, 4, 4, 12]
    chart_types = {
        series["type"]
        for chart in report["charts"].values()
        for series in chart["option"]["series"]
    }
    assert {"radar", "bar", "line", "gauge", "funnel"} <= chart_types
    assert report["tables"]["department_summary"]["options"]["groupBy"] == [
        "traffic_source",
        "shop_name",
    ]

    for query in report["queries"].values():
        assert query["dataSource"] == "doris"
        assert "ods.ods_dy_order" in query["sql"]


def test_upsert_examples_marks_all_saved_reports_as_public_examples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    report_number = 0

    def fake_request_json(
        url: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        system_token: str | None = None,
    ) -> dict[str, Any]:
        nonlocal report_number
        calls.append(
            {
                "url": url,
                "method": method,
                "payload": payload,
                "system_token": system_token,
            }
        )
        if method == "GET":
            return {"reports": []}
        if "/api/internal/reports/" in url:
            return {"report": payload}
        report_number += 1
        return {
            "report": {
                "id": f"report-{report_number}",
                **(payload or {}),
                "isExample": False,
            }
        }

    monkeypatch.setitem(
        examples.upsert_examples.__globals__,
        "_request_json",
        fake_request_json,
    )

    saved = examples.upsert_examples(
        "http://example.test",
        "seed",
        "system-secret",
    )
    mark_calls = [
        call
        for call in calls
        if "/api/internal/reports/" in call["url"]
    ]

    assert len(saved) == 7
    assert all(report["isExample"] is True for report in saved)
    assert len(mark_calls) == 7
    assert all(call["method"] == "PUT" for call in mark_calls)
    assert all(
        call["payload"]["isExample"] is True
        for call in mark_calls
    )
    assert all(
        call["system_token"] == "system-secret"
        for call in mark_calls
    )
