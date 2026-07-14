import pytest

from app.agents.coordinator import AnalysisNeedsClarification, DynamicAnalysisCoordinator
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
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        for _ in range(4):
            tools.execute_sql("SELECT missing_metric FROM sales_channel_monthly")
        return {"title": "unused", "summary": ["unused"], "chart": None, "assumptions": [], "warnings": []}

    coordinator = DynamicAnalysisCoordinator(
        settings(),
        executor=executor,
        list_tables_fn=lambda _: ListTablesResult(),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=scripted_agent,
    )

    from app.agents.coordinator import DynamicAnalysisError
    import pytest

    with pytest.raises(DynamicAnalysisError) as error:
        coordinator.run("broken query")

    assert error.value.code == "SQL_RETRY_EXHAUSTED"
    assert executor.calls == 3


def test_coordinator_stops_a_non_repairable_error_without_another_sql_attempt() -> None:
    class UnsafeExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, _: str) -> SqlToolResult:
            self.calls += 1
            return SqlToolResult(
                success=False,
                error=SqlToolError(SqlErrorCode.SQL_SAFETY_VIOLATION, "safe", False),
            )

    executor = UnsafeExecutor()

    def scripted_agent(_: str, tools) -> dict[str, object]:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        tools.execute_sql("DELETE FROM sales_channel_monthly")
        tools.execute_sql("SELECT channel FROM sales_channel_monthly")
        return {"title": "unused", "summary": ["unused"], "chart": None, "assumptions": [], "warnings": []}

    coordinator = DynamicAnalysisCoordinator(
        settings(),
        executor=executor,
        list_tables_fn=lambda _: ListTablesResult(),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=scripted_agent,
    )

    from app.agents.coordinator import DynamicAnalysisError
    import pytest

    with pytest.raises(DynamicAnalysisError) as error:
        coordinator.run("unsafe query")

    assert error.value.code == "SQL_SAFETY_VIOLATION"
    assert executor.calls == 1


def test_approved_agent_tool_registry_contains_exactly_three_tools() -> None:
    from app.agents.coordinator import ApprovedAnalysisTools

    tools = ApprovedAnalysisTools(
        settings(),
        executor=SequencedExecutor(),
        list_tables_fn=lambda _: ListTablesResult(),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
    )

    assert [tool.name for tool in tools.as_agent_tools()] == [
        "list_tables",
        "get_table_schema",
        "execute_sql",
    ]


def test_sql_tool_requires_metadata_for_each_referenced_table() -> None:
    from app.agents.coordinator import ApprovedAnalysisTools

    executor = SequencedExecutor()
    tools = ApprovedAnalysisTools(
        settings(),
        executor=executor,
        list_tables_fn=lambda _: ListTablesResult(
            tables=[TableInfo(name="sales_channel_monthly", comment=None)]
        ),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
    )

    assert tools.get_table_schema("sales_channel_monthly")["error"]["code"] == "METADATA_REQUIRED"
    assert tools.execute_sql("SELECT channel FROM sales_channel_monthly")["error"]["code"] == "METADATA_REQUIRED"
    tools.list_tables()
    assert tools.execute_sql("SELECT channel FROM sales_channel_monthly")["error"]["code"] == "METADATA_REQUIRED"
    tools.get_table_schema("sales_channel_monthly")
    assert tools.execute_sql("SELECT channel FROM sales_channel_monthly")["success"] is False
    assert executor.sql == ["SELECT channel FROM sales_channel_monthly"]


def test_coordinator_requests_clarification_without_executing_sql() -> None:
    def ambiguous_agent(_: str, _tools) -> dict[str, object]:
        return {"requires_input": True, "message": "请说明要分析的销售指标和时间范围。"}

    coordinator = DynamicAnalysisCoordinator(settings(), agent_runner=ambiguous_agent)

    with pytest.raises(AnalysisNeedsClarification) as error:
        coordinator.run("销售情况")

    assert error.value.code == "ANALYSIS_NEEDS_CLARIFICATION"
    assert str(error.value) == "请说明要分析的销售指标和时间范围。"
