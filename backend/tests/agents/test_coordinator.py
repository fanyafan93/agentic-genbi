import time

import pytest

from app.agents.coordinator import AnalysisNeedsClarification, DynamicAnalysisCoordinator
from app.agents.runner import AgentProviderError, AgentRunError, InvalidAgentReport
from app.config import Settings
from app.database.errors import SqlErrorCode, SqlToolError
from app.query import SqlExecutionResult, SqlResultColumn
from app.schemas.analysis import (
    AgentExecutionStep,
    AnalysisReport,
    AnalysisRequest,
    ReportTable,
    ResultColumn,
    StepState,
    TaskState,
)
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


def test_coordinator_emits_ordered_safe_execution_steps() -> None:
    executor = SequencedExecutor()
    events = []

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
        list_tables_fn=lambda _: ListTablesResult(
            tables=[TableInfo(name="sales_channel_monthly", comment=None)]
        ),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=scripted_agent,
    )

    coordinator.run("Show channel sales", on_step=events.append)

    sequences_by_step_id: dict[str, int] = {}
    for event in events:
        assert sequences_by_step_id.setdefault(event.step_id, event.sequence) == event.sequence
    assert {event.kind for event in events} >= {
        "agent_started",
        "list_tables",
        "get_table_schema",
        "sql_validation",
        "execute_sql",
        "sql_repair",
        "report_generation",
    }
    assert all("SELECT" not in (event.detail or "") for event in events)
    assert any(
        event.kind == "execute_sql" and event.attempt == 1 and event.status is StepState.FAILED
        for event in events
    )
    assert any(
        event.kind == "execute_sql" and event.attempt == 2 and event.status is StepState.SUCCEEDED
        for event in events
    )


def test_coordinator_marks_report_generation_failed_for_non_json_output() -> None:
    class SuccessfulExecutor:
        def execute(self, _: str) -> SqlToolResult:
            return SqlToolResult(
                success=True,
                result=SqlExecutionResult(
                    columns=[SqlResultColumn("sales_amount", "decimal")],
                    rows=[{"sales_amount": 120000.0}],
                    row_count=1,
                    truncated=False,
                    query_duration_ms=4,
                ),
            )

    events = []

    def malformed_agent(_: str, tools) -> str:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        tools.execute_sql("SELECT sales_amount FROM sales_channel_monthly")
        return "I cannot produce a report right now."

    coordinator = DynamicAnalysisCoordinator(
        settings(),
        executor=SuccessfulExecutor(),
        list_tables_fn=lambda _: ListTablesResult(
            tables=[TableInfo(name="sales_channel_monthly", comment=None)]
        ),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=malformed_agent,
    )

    with pytest.raises(InvalidAgentReport) as error:
        coordinator.run("Show channel sales", on_step=events.append)

    assert error.value.code == "INVALID_REPORT"
    report_steps = [event for event in events if event.kind == "report_generation"]
    assert len(report_steps) == 2
    assert report_steps[-1].status is StepState.FAILED


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

    from app.agents.runner import AgentRunError

    def scripted_agent(_: str, tools) -> dict[str, object]:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        for _ in range(4):
            try:
                tools.execute_sql("SELECT missing_metric FROM sales_channel_monthly")
            except AgentRunError as error:
                return {"halt": True, "code": error.code, "title": "stops", "summary": ["stops"], "chart": None, "assumptions": [], "warnings": []}
        return {"title": "unused", "summary": ["unused"], "chart": None, "assumptions": [], "warnings": []}

    coordinator = DynamicAnalysisCoordinator(
        settings(),
        executor=executor,
        list_tables_fn=lambda _: ListTablesResult(),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=scripted_agent,
    )

    from app.agents.coordinator import DynamicAnalysisError

    with pytest.raises((DynamicAnalysisError, AgentRunError)) as error:
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

    from app.agents.runner import AgentRunError

    def scripted_agent(_: str, tools) -> dict[str, object]:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        try:
            tools.execute_sql("DELETE FROM sales_channel_monthly")
        except AgentRunError:
            return {"halt": True, "title": "unsafe", "summary": ["unsafe"], "chart": None, "assumptions": [], "warnings": []}
        return {"title": "unused", "summary": ["unused"], "chart": None, "assumptions": [], "warnings": []}

    coordinator = DynamicAnalysisCoordinator(
        settings(),
        executor=executor,
        list_tables_fn=lambda _: ListTablesResult(),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=scripted_agent,
    )

    from app.agents.coordinator import DynamicAnalysisError

    with pytest.raises((DynamicAnalysisError, AgentRunError)) as error:
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
    from app.agents.runner import AgentRunError

    executor = SequencedExecutor()
    tools = ApprovedAnalysisTools(
        settings(),
        executor=executor,
        list_tables_fn=lambda _: ListTablesResult(
            tables=[TableInfo(name="sales_channel_monthly", comment=None)]
        ),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
    )

    with pytest.raises(AgentRunError) as schema_before_list:
        tools.get_table_schema("sales_channel_monthly")
    assert schema_before_list.value.code == "METADATA_REQUIRED"

    with pytest.raises(AgentRunError) as sql_before_list:
        tools.execute_sql("SELECT channel FROM sales_channel_monthly")
    assert sql_before_list.value.code == "METADATA_REQUIRED"

    tools.list_tables()

    with pytest.raises(AgentRunError) as sql_after_list_only:
        tools.execute_sql("SELECT channel FROM sales_channel_monthly")
    assert sql_after_list_only.value.code == "METADATA_REQUIRED"

    tools.get_table_schema("sales_channel_monthly")
    result = tools.execute_sql("SELECT channel FROM sales_channel_monthly")
    assert result["success"] is False
    assert executor.sql == ["SELECT channel FROM sales_channel_monthly"]


def test_coordinator_always_closes_every_started_step_even_on_unexpected_error() -> None:
    class SuccessfulExecutor:
        def execute(self, _: str) -> SqlToolResult:
            return SqlToolResult(
                success=True,
                result=SqlExecutionResult(
                    columns=[SqlResultColumn("sales_amount", "decimal")],
                    rows=[{"sales_amount": 1.0}],
                    row_count=1,
                    truncated=False,
                    query_duration_ms=1,
                ),
            )

    events: list[AgentExecutionStep] = []

    def crashing_agent(_: str, tools) -> None:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        tools.execute_sql("SELECT sales_amount FROM sales_channel_monthly")
        raise RuntimeError("agent sdk transport blew up")

    coordinator = DynamicAnalysisCoordinator(
        settings(),
        executor=SuccessfulExecutor(),
        list_tables_fn=lambda _: ListTablesResult(
            tables=[TableInfo(name="sales_channel_monthly", comment=None)]
        ),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=crashing_agent,
    )

    with pytest.raises(AgentProviderError):
        coordinator.run("Show channel sales", on_step=events.append)

    latest_by_step_id: dict[str, AgentExecutionStep] = {}
    for event in events:
        latest = latest_by_step_id.get(event.step_id)
        if latest is None or event.sequence >= latest.sequence:
            latest_by_step_id[event.step_id] = event
    for step_id, event in latest_by_step_id.items():
        assert event.finished_at is not None, f"step {step_id} ({event.kind}) was never finished"


def test_coordinator_aborts_agent_loop_when_budget_is_exceeded() -> None:
    class AlwaysFailExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, _: str) -> SqlToolResult:
            self.calls += 1
            return SqlToolResult(
                success=False,
                error=SqlToolError(SqlErrorCode.SQL_UNKNOWN_COLUMN, "missing", True),
            )

    executor = AlwaysFailExecutor()

    def scripted_agent(_: str, tools) -> dict[str, object]:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        for _ in range(6):
            try:
                tools.execute_sql("SELECT sales_amount FROM sales_channel_monthly")
            except AgentRunError as error:
                return {"halt": True, "code": error.code}
        return {"unused": True}

    settings_with_tight_budget = Settings(
        app_env="test",
        database_url="mysql+pymysql://x:y@localhost:3306/db",
        minimax_api_key="k",
        max_tool_calls=4,
        max_sql_retries=2,
        _env_file=None,
    )
    coordinator = DynamicAnalysisCoordinator(
        settings_with_tight_budget,
        executor=executor,
        list_tables_fn=lambda _: ListTablesResult(tables=[TableInfo(name="sales_channel_monthly", comment=None)]),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=scripted_agent,
    )

    with pytest.raises((AgentRunError, Exception)) as exc:
        coordinator.run("query")

    assert executor.calls <= 3, f"Agent must not keep running after the budget is hit, got {executor.calls} calls"
    assert exc.value.code in {
        "SQL_RETRY_EXHAUSTED",
        "TOOL_BUDGET_EXCEEDED",
        "SQL_EXECUTION_ERROR",
    }


def test_task_service_watchdog_fails_task_when_runner_hangs(monkeypatch) -> None:
    from app.services.task_service import TaskService

    def hang_runner(_question, _observer):
        time.sleep(3)
        return None  # wake after watchdog already marked task failed; value must be ignored

    service = TaskService(
        step_aware_analysis_runner=hang_runner,
        max_seconds=1,
    )
    task_id = service.create_task(AnalysisRequest(question="hang forever")).task_id
    service.run_analysis(task_id, "hang forever")
    snapshot = service.get_task(task_id)
    assert snapshot.status is TaskState.FAILED
    assert snapshot.error is not None
    assert snapshot.error.code == "ANALYSIS_TIMEOUT"


def test_task_service_watchdog_noop_when_runner_finishes_quickly() -> None:
    from app.services.task_service import TaskService
    from app.services.task_service import _fixed_report

    service = TaskService(
        step_aware_analysis_runner=lambda _q, _on_step: _fixed_report(),
        max_seconds=1,
    )
    task_id = service.create_task(AnalysisRequest(question="q")).task_id
    service.run_analysis(task_id, "q")
    assert service.get_task(task_id).status is TaskState.SUCCEEDED


def test_coordinator_closes_report_step_when_build_report_raises(monkeypatch) -> None:
    class SuccessfulExecutor:
        def execute(self, _: str) -> SqlToolResult:
            return SqlToolResult(
                success=True,
                result=SqlExecutionResult(
                    columns=[SqlResultColumn("a", "int")],
                    rows=[{"a": 1}],
                    row_count=1,
                    truncated=False,
                    query_duration_ms=1,
                ),
            )

    from app.agents import coordinator as coordinator_module

    def build_report_bomb(_narrative, _result, _sql, _attempts):  # type: ignore[no-untyped-def]
        raise RuntimeError("post-processing crashed")

    monkeypatch.setattr(coordinator_module, "_build_report", build_report_bomb)

    events: list[AgentExecutionStep] = []

    def normal_agent(_: str, tools) -> dict[str, object]:
        tools.list_tables()
        tools.get_table_schema("sales_channel_monthly")
        tools.execute_sql("SELECT a FROM sales_channel_monthly")
        return {
            "title": "ok",
            "summary": ["ok"],
            "chart": None,
            "assumptions": [],
            "warnings": [],
        }

    coordinator = DynamicAnalysisCoordinator(
        settings(),
        executor=SuccessfulExecutor(),
        list_tables_fn=lambda _: ListTablesResult(
            tables=[TableInfo(name="sales_channel_monthly", comment=None)]
        ),
        get_schema_fn=lambda table_name, _: TableSchema(table_name=table_name, columns=[]),
        agent_runner=normal_agent,
    )

    with pytest.raises(RuntimeError):
        coordinator.run("q", on_step=events.append)

    report_steps = [event for event in events if event.kind == "report_generation"]
    assert report_steps, "report_generation step must have been emitted"
    assert report_steps[-1].finished_at is not None
    assert report_steps[-1].status is StepState.FAILED


def test_coordinator_requests_clarification_without_executing_sql() -> None:
    def ambiguous_agent(_: str, _tools) -> dict[str, object]:
        return {"requires_input": True, "message": "请说明要分析的销售指标和时间范围。"}

    coordinator = DynamicAnalysisCoordinator(settings(), agent_runner=ambiguous_agent)

    with pytest.raises(AnalysisNeedsClarification) as error:
        coordinator.run("销售情况")

    assert error.value.code == "ANALYSIS_NEEDS_CLARIFICATION"
    assert str(error.value) == "请说明要分析的销售指标和时间范围。"
