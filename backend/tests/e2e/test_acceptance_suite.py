import json
from pathlib import Path

import pytest

from app.agents.coordinator import DynamicAnalysisCoordinator
from app.config import Settings
from app.database.errors import SqlErrorCode, SqlToolError
from app.query import SqlExecutionResult, SqlResultColumn
from app.schemas.tools import ListTablesResult, TableColumn, TableInfo, TableSchema
from app.services.sql_executor import SqlToolResult


def _scenarios() -> list[dict[str, object]]:
    fixture_path = Path(__file__).parent / "fixtures" / "questions.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


class AcceptanceExecutor:
    def __init__(self, repair_once: bool) -> None:
        self.repair_once = repair_once
        self.sql: list[str] = []

    def execute(self, sql: str) -> SqlToolResult:
        self.sql.append(sql)
        if self.repair_once and len(self.sql) == 1:
            return SqlToolResult(
                success=False,
                error=SqlToolError(
                    SqlErrorCode.SQL_UNKNOWN_COLUMN,
                    "The query references an unknown column.",
                    True,
                ),
            )
        return SqlToolResult(
            success=True,
            result=SqlExecutionResult(
                columns=[
                    SqlResultColumn("channel", "varchar"),
                    SqlResultColumn("sales_amount", "decimal"),
                ],
                rows=[{"channel": "online", "sales_amount": 120000.0}],
                row_count=1,
                truncated=False,
                query_duration_ms=4,
            ),
        )


@pytest.mark.parametrize("scenario", _scenarios(), ids=lambda scenario: str(scenario["name"]))
def test_fixed_mvp_questions_complete_with_safe_steps(scenario: dict[str, object]) -> None:
    executor = AcceptanceExecutor(repair_once=scenario["name"] == "schema_repair")
    events = []
    settings = Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
        minimax_api_key="test-key",
        _env_file=None,
    )

    def scripted_agent(_: str, tools) -> dict[str, object]:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        if scenario["name"] == "schema_repair":
            tools.execute_sql("SELECT missing_metric FROM sales_channel_monthly")
            tools.get_table_schema("sales_channel_monthly")
        tools.execute_sql(str(scenario["sql"]))
        return {
            "title": str(scenario["name"]),
            "summary": ["The server query returned the report data."],
            "chart": None,
            "assumptions": [],
            "warnings": [],
        }

    coordinator = DynamicAnalysisCoordinator(
        settings,
        executor=executor,
        list_tables_fn=lambda _: ListTablesResult(
            tables=[TableInfo(name="sales_channel_monthly", comment=None)]
        ),
        get_schema_fn=lambda table_name, _: TableSchema(
            table_name=table_name,
            columns=[
                TableColumn(name="channel", data_type="varchar", nullable=False, comment=None),
                TableColumn(name="sales_amount", data_type="decimal", nullable=False, comment=None),
            ],
        ),
        agent_runner=scripted_agent,
    )

    report = coordinator.run(str(scenario["question"]), on_step=events.append)

    assert report.sql == scenario["sql"]
    assert report.sql_attempts == scenario["expected_attempts"]
    assert report.table.rows == [{"channel": "online", "sales_amount": 120000.0}]
    assert {event.kind for event in events} >= {
        "agent_started",
        "list_tables",
        "get_table_schema",
        "sql_validation",
        "execute_sql",
        "report_generation",
    }
    if scenario["name"] == "schema_repair":
        assert "sql_repair" in {event.kind for event in events}
    assert all("SELECT" not in (event.detail or "") for event in events)
