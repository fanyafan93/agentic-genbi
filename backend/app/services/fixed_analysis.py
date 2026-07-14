from app.query import FIXED_SALES_SQL, SqlExecutionResult, execute_fixed_sales_query
from app.schemas.analysis import AnalysisReport, ChartSpec, ReportTable, ResultColumn


def report_from_result(result: SqlExecutionResult) -> AnalysisReport:
    return AnalysisReport(
        title="月度渠道销售额",
        summary=["展示测试库中 2026 年第一季度各渠道的月度销售额。"],
        sql=FIXED_SALES_SQL,
        table=ReportTable(
            columns=[ResultColumn(name=column.name, data_type=column.data_type) for column in result.columns],
            rows=result.rows,
            row_count=result.row_count,
            truncated=result.truncated,
        ),
        chart=ChartSpec(
            type="line",
            title="月度渠道销售额",
            x_field="month_start",
            y_fields=["sales_amount"],
            series_field="channel",
        ),
        assumptions=["数据来自本地确定性 MySQL 测试库。"],
        query_duration_ms=result.query_duration_ms,
        sql_attempts=1,
    )


def run_fixed_analysis(settings):
    return report_from_result(execute_fixed_sales_query(settings))
