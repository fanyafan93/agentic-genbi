from app.schemas.analysis import AnalysisReport, ReportTable, ResultColumn


def make_fixed_report() -> AnalysisReport:
    return AnalysisReport(
        title="固定销售概览",
        summary=["这是用于验证任务状态流转的确定性报告。"],
        sql="SELECT 'fixed' AS report_name",
        table=ReportTable(
            columns=[ResultColumn(name="report_name", data_type="varchar")],
            rows=[{"report_name": "fixed"}],
            row_count=1,
        ),
        chart=None,
        query_duration_ms=0,
        sql_attempts=1,
    )
