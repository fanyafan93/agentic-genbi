from app.config import Settings
from app.query import FIXED_SALES_SQL, SqlExecutionResult, SqlResultColumn
from tests.agents.fakes import FakeNarrativeRunner


def test_analysis_service_preserves_server_owned_query_fields(monkeypatch) -> None:
    from app.schemas.analysis import ReportNarrative
    from app.services.analysis_service import AnalysisService

    query_result = SqlExecutionResult(
        columns=[
            SqlResultColumn("month_start", "date"),
            SqlResultColumn("channel", "varchar"),
            SqlResultColumn("sales_amount", "decimal"),
        ],
        rows=[{"month_start": "2026-01-01", "channel": "online", "sales_amount": 120000.0}],
        row_count=1,
        truncated=False,
        query_duration_ms=7,
    )
    monkeypatch.setattr("app.services.analysis_service.execute_fixed_sales_query", lambda _: query_result)
    narrative_runner = FakeNarrativeRunner(
        ReportNarrative(
            title="Agent narrative",
            summary=["The trend is upward."],
            chart={
                "type": "line",
                "title": "Sales trend",
                "x_field": "month_start",
                "y_fields": ["sales_amount"],
                "series_field": "channel",
            },
            assumptions=[],
            warnings=[],
        )
    )
    settings = Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
    )

    report = AnalysisService(settings, narrative_runner).run("How did sales change?")

    assert report.title == "Agent narrative"
    assert report.sql == FIXED_SALES_SQL
    assert report.table.rows == query_result.rows
    assert report.query_duration_ms == 7
    assert report.sql_attempts == 1
