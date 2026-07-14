from collections.abc import Callable
from typing import Any

from agents import Runner, RunConfig, function_tool
from pydantic import ValidationError

from app.agents.analysis_agent import build_minimax_analysis_agent
from app.agents.prompts import build_dynamic_analysis_prompt
from app.agents.runner import (
    AgentProviderError,
    AgentProviderNotConfigured,
    AgentRunError,
    InvalidAgentReport,
    validate_narrative_output,
)
from app.config import Settings
from app.database.errors import SqlErrorCode, SqlToolError
from app.query import SqlExecutionResult
from app.schemas.analysis import AnalysisReport, ReportNarrative, ReportTable, ResultColumn
from app.schemas.tools import ListTablesResult, TableSchema
from app.services.retry_policy import RetryDecision, RetryPolicy
from app.services.sql_executor import SqlExecutor
from app.tools.execute_sql import serialize_sql_tool_result
from app.tools.get_table_schema import get_table_schema
from app.tools.list_tables import list_tables


class DynamicAnalysisError(AgentRunError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


ListTablesFn = Callable[[Settings], ListTablesResult]
GetSchemaFn = Callable[[str, Settings], TableSchema]
AgentRunner = Callable[[str, "ApprovedAnalysisTools"], Any]


class ApprovedAnalysisTools:
    """Server-owned state and the only three tools available to the analysis Agent."""

    def __init__(
        self,
        settings: Settings,
        executor: SqlExecutor,
        list_tables_fn: ListTablesFn,
        get_schema_fn: GetSchemaFn,
    ) -> None:
        self._settings = settings
        self._executor = executor
        self._list_tables_fn = list_tables_fn
        self._get_schema_fn = get_schema_fn
        self._retry_policy = RetryPolicy(settings.max_sql_retries)
        self._tool_calls = 0
        self.sql_attempts = 0
        self.last_result: SqlExecutionResult | None = None
        self.last_sql: str | None = None
        self.terminal_error: SqlToolError | None = None

    def list_tables(self) -> dict[str, object]:
        if not self._claim_tool_call():
            return self._budget_error()
        return self._list_tables_fn(self._settings).model_dump()

    def get_table_schema(self, table_name: str) -> dict[str, object]:
        if not self._claim_tool_call():
            return self._budget_error()
        return self._get_schema_fn(table_name, self._settings).model_dump()

    def execute_sql(self, sql: str) -> dict[str, object]:
        if not self._claim_tool_call():
            return self._budget_error()
        if self.terminal_error is not None:
            return self._error_response(self.terminal_error)
        if self.sql_attempts >= self._settings.max_sql_retries + 1:
            self.terminal_error = SqlToolError(
                SqlErrorCode.SQL_RETRY_EXHAUSTED,
                "The SQL repair limit has been reached.",
                False,
            )
            return self._error_response(self.terminal_error)

        self.sql_attempts += 1
        tool_result = self._executor.execute(sql)
        response = serialize_sql_tool_result(tool_result)
        if response["success"]:
            assert tool_result.result is not None
            self.last_result = tool_result.result
            self.last_sql = sql
            return response

        error_data = response["error"]
        assert isinstance(error_data, dict)
        error = SqlToolError(
            SqlErrorCode(error_data["code"]),
            str(error_data["message"]),
            bool(error_data["retryable"]),
        )
        decision = self._retry_policy.decide(self.sql_attempts, error)
        if decision is RetryDecision.STOP:
            self.terminal_error = error
        elif decision is RetryDecision.EXHAUSTED:
            self.terminal_error = SqlToolError(
                SqlErrorCode.SQL_RETRY_EXHAUSTED,
                "The SQL repair limit has been reached.",
                False,
            )
        return response

    def as_agent_tools(self) -> list[Any]:
        @function_tool(name_override="list_tables")
        def list_tables_tool() -> dict[str, object]:
            """List the database tables approved for analysis."""

            return self.list_tables()

        @function_tool(name_override="get_table_schema")
        def get_table_schema_tool(table_name: str) -> dict[str, object]:
            """Get columns for one approved database table."""

            return self.get_table_schema(table_name)

        @function_tool(name_override="execute_sql")
        def execute_sql_tool(sql: str) -> dict[str, object]:
            """Safely execute one read-only MySQL SELECT query."""

            return self.execute_sql(sql)

        return [list_tables_tool, get_table_schema_tool, execute_sql_tool]

    def _claim_tool_call(self) -> bool:
        self._tool_calls += 1
        return self._tool_calls <= self._settings.max_tool_calls

    def _budget_error(self) -> dict[str, object]:
        self.terminal_error = SqlToolError(
            SqlErrorCode.TOOL_BUDGET_EXCEEDED,
            "The analysis tool-call budget has been reached.",
            False,
        )
        return self._error_response(self.terminal_error)

    @staticmethod
    def _error_response(error: SqlToolError) -> dict[str, object]:
        return {
            "success": False,
            "result": None,
            "error": {"code": error.code.value, "message": error.message, "retryable": error.retryable},
        }


class DynamicAnalysisCoordinator:
    """Coordinate metadata discovery, constrained SQL, repair, and final narrative output."""

    def __init__(
        self,
        settings: Settings,
        executor: SqlExecutor | None = None,
        list_tables_fn: ListTablesFn = list_tables,
        get_schema_fn: GetSchemaFn = get_table_schema,
        agent_runner: AgentRunner | None = None,
    ) -> None:
        self._settings = settings
        self._executor = executor or SqlExecutor(settings)
        self._list_tables_fn = list_tables_fn
        self._get_schema_fn = get_schema_fn
        self._agent_runner = agent_runner or self._run_with_sdk

    def run(self, question: str) -> AnalysisReport:
        if self._settings.minimax_api_key is None:
            raise AgentProviderNotConfigured
        tools = ApprovedAnalysisTools(
            self._settings, self._executor, self._list_tables_fn, self._get_schema_fn
        )
        try:
            output = self._agent_runner(question, tools)
        except AgentRunError:
            raise
        except Exception as error:
            raise AgentProviderError from error

        if tools.last_result is None or tools.last_sql is None:
            error = tools.terminal_error or SqlToolError(
                SqlErrorCode.SQL_EXECUTION_ERROR,
                "The Agent did not produce a successful query.",
                False,
            )
            raise DynamicAnalysisError(error.code.value, error.message)

        try:
            narrative = validate_narrative_output(output)
            return _build_report(narrative, tools.last_result, tools.last_sql, tools.sql_attempts)
        except ValidationError as error:
            raise InvalidAgentReport from error

    def _run_with_sdk(self, question: str, tools: ApprovedAnalysisTools) -> Any:
        agent = build_minimax_analysis_agent(self._settings, tools=tools.as_agent_tools())
        result = Runner.run_sync(
            agent,
            build_dynamic_analysis_prompt(question),
            run_config=RunConfig(tracing_disabled=True),
            max_turns=self._settings.max_tool_calls + 1,
        )
        return result.final_output


def _build_report(
    narrative: ReportNarrative, result: SqlExecutionResult, sql: str, sql_attempts: int
) -> AnalysisReport:
    return AnalysisReport(
        title=narrative.title,
        summary=narrative.summary,
        sql=sql,
        table=ReportTable(
            columns=[ResultColumn(name=column.name, data_type=column.data_type) for column in result.columns],
            rows=result.rows,
            row_count=result.row_count,
            truncated=result.truncated,
        ),
        chart=narrative.chart,
        assumptions=narrative.assumptions,
        warnings=narrative.warnings,
        query_duration_ms=result.query_duration_ms,
        sql_attempts=sql_attempts,
    )
