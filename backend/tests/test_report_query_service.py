from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.reports.query_service import (
    ReportFilterError,
    ReportQueryService,
    UnsafeReportQuery,
    bind_query_parameters,
    validate_readonly_sql,
)
from backend.reports.store import ReportStore
from backend.tests.test_report_store import report_config


class FakeQueryRunner:
    def __init__(self, *, count: int = 0) -> None:
        self.count = count
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def run(
        self,
        data_source: str,
        sql: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        self.calls.append((data_source, sql, params))
        if "genbi_count" in sql:
            return [{"total": self.count}]
        return [{"region": "华东", "amount": 1200.5}]


class BuildQuerySource:
    def __init__(self, queries: dict[str, Any]) -> None:
        self.queries = queries


def test_query_service_accepts_report_build_query_source() -> None:
    source = BuildQuerySource(
        {
            "q-sales": {
                "dataSource": "mysql",
                "sql": "SELECT region, amount FROM sales",
                "parameters": {},
                "pagination": False,
            }
        }
    )
    runner = FakeQueryRunner()

    result = ReportQueryService(runner, max_rows=50).execute(
        source,
        "q-sales",
        filters={},
    )

    assert result["rows"] == [{"region": "华东", "amount": 1200.5}]
    assert runner.calls[0][0] == "mysql"


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sales",
        "SELECT * FROM sales; DROP TABLE sales",
        (
            "WITH changed AS "
            "(UPDATE sales SET amount = 0 RETURNING *) "
            "SELECT * FROM changed"
        ),
        "SELECT * INTO OUTFILE '/tmp/sales.csv' FROM sales",
    ],
)
def test_readonly_validator_rejects_write_or_multiple_statements(
    sql: str,
) -> None:
    with pytest.raises(UnsafeReportQuery):
        validate_readonly_sql(sql)


def test_readonly_validator_accepts_select_and_cte() -> None:
    validate_readonly_sql(
        "WITH totals AS (SELECT region, SUM(amount) amount FROM sales "
        "GROUP BY region) SELECT * FROM totals"
    )


def test_parameter_binding_expands_multi_select_without_interpolation() -> None:
    query = {
        "sql": (
            "SELECT region FROM sales "
            "WHERE region IN (:regions) AND sale_date >= :startDate"
        ),
        "parameters": {
            "regions": {
                "filterId": "regions",
                "type": "string[]",
            },
            "startDate": {
                "filterId": "dateRange",
                "valueIndex": 0,
                "type": "date",
            },
        },
    }

    sql, params = bind_query_parameters(
        query,
        {
            "regions": ["华东", "华南"],
            "dateRange": ["2026-08-01", "2026-08-31"],
        },
    )

    assert "IN (%(regions_0)s, %(regions_1)s)" in sql
    assert "%(startDate)s" in sql
    assert "华东" not in sql
    assert params == {
        "regions_0": "华东",
        "regions_1": "华南",
        "startDate": "2026-08-01",
    }


def test_parameter_binding_rejects_missing_or_wrong_filter_values() -> None:
    query = {
        "sql": "SELECT * FROM sales WHERE sale_date >= :startDate",
        "parameters": {
            "startDate": {
                "filterId": "dateRange",
                "valueIndex": 0,
                "type": "date",
            }
        },
    }

    with pytest.raises(ReportFilterError):
        bind_query_parameters(query, {})
    with pytest.raises(ReportFilterError):
        bind_query_parameters(query, {"dateRange": "2026-08-01"})
    with pytest.raises(ReportFilterError):
        bind_query_parameters(
            query,
            {"dateRange": ["not-a-date", "2026-08-31"]},
        )


def test_paginated_query_returns_rows_columns_and_total(
    tmp_path: Path,
) -> None:
    config = report_config()
    config["queries"]["sales-query"]["pagination"] = True
    report = ReportStore(tmp_path / "reports.json").create_report(
        config,
        owner_id="user-1",
    )
    runner = FakeQueryRunner(count=12)

    result = ReportQueryService(runner, max_rows=1000).execute(
        report,
        "sales-query",
        filters={"region": "华东"},
        page=2,
        page_size=5,
    )

    assert result == {
        "columns": [
            {"field": "region", "label": "region", "type": "string"},
            {"field": "amount", "label": "amount", "type": "number"},
        ],
        "rows": [{"region": "华东", "amount": 1200.5}],
        "page": 2,
        "pageSize": 5,
        "total": 12,
    }
    assert len(runner.calls) == 2
    _, count_sql, count_params = runner.calls[0]
    _, page_sql, page_params = runner.calls[1]
    assert "genbi_count" in count_sql
    assert count_params == {"region": "华东"}
    assert "LIMIT %(genbi_limit)s OFFSET %(genbi_offset)s" in page_sql
    assert page_params["genbi_limit"] == 5
    assert page_params["genbi_offset"] == 5


def test_paginated_query_applies_declared_column_filters_and_sort(
    tmp_path: Path,
) -> None:
    config = report_config()
    query = config["queries"]["sales-query"]
    query["pagination"] = True
    query["controls"] = {
        "sortableFields": ["amount"],
        "filterableFields": ["region"],
    }
    report = ReportStore(tmp_path / "reports.json").create_report(
        config,
        owner_id="user-1",
    )
    runner = FakeQueryRunner(count=7)

    ReportQueryService(runner, max_rows=1000).execute(
        report,
        "sales-query",
        filters={"region": "华东"},
        page=1,
        page_size=20,
        sort={"field": "amount", "direction": "desc"},
        column_filters={"region": ["华东", "华南"]},
    )

    _, count_sql, count_params = runner.calls[0]
    _, page_sql, page_params = runner.calls[1]
    assert (
        "WHERE `region` IN "
        "(%(genbi_column_region_0)s, %(genbi_column_region_1)s)"
        in count_sql
    )
    assert "ORDER BY `amount` DESC" not in count_sql
    assert "ORDER BY `amount` DESC" in page_sql
    assert (
        page_sql.index("AS genbi_page")
        < page_sql.rindex("ORDER BY `amount` DESC")
        < page_sql.index("LIMIT %(genbi_limit)s")
    )
    assert count_params == {
        "region": "华东",
        "genbi_column_region_0": "华东",
        "genbi_column_region_1": "华南",
    }
    assert page_params["genbi_limit"] == 20


def test_query_controls_reject_undeclared_fields(tmp_path: Path) -> None:
    config = report_config()
    query = config["queries"]["sales-query"]
    query["pagination"] = True
    query["controls"] = {
        "sortableFields": ["amount"],
        "filterableFields": ["region"],
    }
    report = ReportStore(tmp_path / "reports.json").create_report(
        config,
        owner_id="user-1",
    )

    with pytest.raises(ReportFilterError, match="not sortable"):
        ReportQueryService(FakeQueryRunner()).execute(
            report,
            "sales-query",
            filters={"region": "华东"},
            sort={"field": "region", "direction": "asc"},
        )
    with pytest.raises(ReportFilterError, match="not filterable"):
        ReportQueryService(FakeQueryRunner()).execute(
            report,
            "sales-query",
            filters={"region": "华东"},
            column_filters={"amount": ["1200.5"]},
        )


def test_non_paginated_query_is_capped_without_changing_saved_sql(
    tmp_path: Path,
) -> None:
    report = ReportStore(tmp_path / "reports.json").create_report(
        report_config(),
        owner_id="user-1",
    )
    runner = FakeQueryRunner()

    result = ReportQueryService(runner, max_rows=100).execute(
        report,
        "sales-query",
        filters={"region": "华东"},
        page=9,
        page_size=5,
    )

    assert result["page"] == 1
    assert result["pageSize"] == 100
    assert result["total"] == 1
    assert (
        report.queries["sales-query"]["sql"]
        == report_config()["queries"]["sales-query"]["sql"]
    )
    _, sql, params = runner.calls[0]
    assert "LIMIT %(genbi_limit)s" in sql
    assert params["genbi_limit"] == 100


def test_export_query_selects_declared_columns_and_applies_controls(
    tmp_path: Path,
) -> None:
    config = report_config()
    query = config["queries"]["sales-query"]
    query["controls"] = {
        "sortableFields": ["amount"],
        "filterableFields": ["region"],
    }
    report = ReportStore(tmp_path / "reports.json").create_report(
        config,
        owner_id="user-1",
    )
    runner = FakeQueryRunner()

    rows = ReportQueryService(runner, max_rows=1000).execute_export(
        report,
        "sales-query",
        filters={"region": "华东"},
        fields=["region", "amount"],
        max_rows=100_000,
        sort={"field": "amount", "direction": "desc"},
        column_filters={"region": ["华东"]},
    )

    assert rows == [{"region": "华东", "amount": 1200.5}]
    _, sql, params = runner.calls[0]
    assert "SELECT `region`, `amount`" in sql
    assert "ORDER BY `amount` DESC" in sql
    assert params["genbi_limit"] == 100_001
    assert params["genbi_column_region_0"] == "华东"


def test_export_query_rejects_results_above_limit() -> None:
    class OversizedRunner(FakeQueryRunner):
        def run(
            self,
            data_source: str,
            sql: str,
            params: dict[str, Any],
        ) -> list[dict[str, Any]]:
            self.calls.append((data_source, sql, params))
            return [
                {"region": f"区域-{index}"}
                for index in range(4)
            ]

    source = BuildQuerySource(
        {
            "q-sales": {
                "dataSource": "mysql",
                "sql": "SELECT region FROM sales",
                "parameters": {},
                "pagination": True,
            }
        }
    )

    with pytest.raises(RuntimeError, match="3"):
        ReportQueryService(OversizedRunner()).execute_export(
            source,
            "q-sales",
            filters={},
            fields=["region"],
            max_rows=3,
        )
