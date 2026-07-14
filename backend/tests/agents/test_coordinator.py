from app.agents.coordinator import DynamicAnalysisCoordinator
from app.config import Settings
from app.database.errors import SqlErrorCode, SqlToolError
from app.query import SqlExecutionResult, SqlResultColumn
from app.schemas.tools import ListTablesResult, TableColumn, TableInfo, TableSchema
from app.services.sql_executor import SqlToolResult


def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
        minimax_api_key="test-key",
        _env_file=None,
    )


class SequencedExecutor:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, sql: str) -> SqlToolResult:
        self.sql.append(sql)
        if len(self.sql) == 1:
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


def test_coordinator_repairs_a_retryable_query_and_uses_last_server_result() -> None:
    executor = SequencedExecutor()
    calls: list[str] = []

    def list_tables(_: Settings) -> ListTablesResult:
        calls.append("list_tables")
        return ListTablesResult(tables=[TableInfo(name="sales_channel_monthly", comment=None)])

    def get_schema(table_name: str, _: Settings) -> TableSchema:
        calls.append(f"schema:{table_name}")
        return TableSchema(
            table_name=table_name,
            columns=[TableColumn(name="channel", data_type="varchar", nullable=False, comment=None)],
        )

    def scripted_agent(_: str, tools) -> dict[str, object]:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        tools.execute_sql("SELECT missing_metric FROM sales_channel_monthly")
        tools.get_table_schema("sales_channel_monthly")
        tools.execute_sql("SELECT channel, sales_amount FROM sales_channel_monthly")
        return {
            "title": "Channel sales",
            "summary": ["Online sales are available."],
            "chart": None,
            "assumptions": [],
            "warnings": [],
        }

    coordinator = DynamicAnalysisCoordinator(
        settings(),
        executor=executor,
        list_tables_fn=list_tables,
        get_schema_fn=get_schema,
        agent_runner=scripted_agent,
    )

    report = coordinator.run("Show channel sales")

    assert calls == ["list_tables", "schema:sales_channel_monthly", "schema:sales_channel_monthly"]
    assert executor.sql == [
        "SELECT missing_metric FROM sales_channel_monthly",
        "SELECT channel, sales_amount FROM sales_channel_monthly",
    ]
    assert report.sql == "SELECT channel, sales_amount FROM sales_channel_monthly"
    assert report.table.rows == [{"channel": "online", "sales_amount": 120000.0}]
    assert report.sql_attempts == 2


def test_coordinator_stops_after_the_third_failed_query() -> None:
    class AlwaysFailExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, _: str) -> SqlToolResult:
            self.calls += 1
            return SqlToolResult(
                success=False,
                error=SqlToolError(SqlErrorCode.SQL_UNKNOWN_COLUMN, "safe", True),
            )

    executor = AlwaysFailExecutor()

    def scripted_agent(_: str, tools) -> dict[str, object]:
        for _ in range(4):
            tools.execute_sql("SELECT missing_metric FROM sales_channel_monthly")
        return {"title": "unused", "summary": ["unused"], "chart": None, "assumptions": [], "warnings": []}

    coordinator = DynamicAnalysisCoordinator(settings(), executor=executor, agent_runner=scripted_agent)

    from app.agents.coordinator import DynamicAnalysisError
    import pytest

    with pytest.raises(DynamicAnalysisError) as error:
        coordinator.run("broken query")

    assert error.value.code == "SQL_RETRY_EXHAUSTED"
    assert executor.calls == 3
