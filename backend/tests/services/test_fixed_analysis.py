from importlib import import_module


def test_fixed_analysis_builds_chart_report_from_query_result() -> None:
    fixed_analysis = import_module("app.services.fixed_analysis")
    query = import_module("app.query")
    result = query.SqlExecutionResult(
        columns=[
            query.SqlResultColumn("month_start", "date"),
            query.SqlResultColumn("channel", "varchar"),
            query.SqlResultColumn("sales_amount", "decimal"),
        ],
        rows=[{"month_start": "2026-01-01", "channel": "online", "sales_amount": 120000.0}],
        row_count=1,
        truncated=False,
        query_duration_ms=3,
    )

    report = fixed_analysis.report_from_result(result)

    assert report.sql == query.FIXED_SALES_SQL
    assert report.table.rows == result.rows
    assert report.chart is not None
    assert report.chart.type == "line"
    assert report.chart.x_field == "month_start"
    assert report.chart.series_field == "channel"
    assert report.query_duration_ms == 3
