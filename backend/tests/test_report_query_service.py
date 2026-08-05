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

