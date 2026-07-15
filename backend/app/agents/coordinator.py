from collections.abc import Callable
from datetime import UTC, datetime
import json
import re
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
from app.schemas.analysis import (
    AgentExecutionStep,
    AnalysisReport,
    ReportNarrative,
    ReportTable,
    ResultColumn,
    StepState,
)
from app.schemas.tools import ListTablesResult, TableSchema
from app.services.retry_policy import RetryDecision, RetryPolicy
from app.services.sql_executor import SqlExecutor
from app.services.sql_policy import SqlPolicy
from app.tools.execute_sql import serialize_sql_tool_result
from app.tools.get_table_schema import get_table_schema
from app.tools.list_tables import list_tables


class DynamicAnalysisError(AgentRunError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class AnalysisNeedsClarification(AgentRunError):
    """The question lacks the business scope needed for a reliable query."""

    code = "ANALYSIS_NEEDS_CLARIFICATION"

    def __init__(self, message: str) -> None:
        super().__init__(message)


ListTablesFn = Callable[[Settings], ListTablesResult]
GetSchemaFn = Callable[[str, Settings], TableSchema]
AgentRunner = Callable[[str, "ApprovedAnalysisTools"], Any]
StepObserver = Callable[[AgentExecutionStep], None]


class ExecutionStepRecorder:
    """Emit product-safe lifecycle events without exposing SQL or model reasoning."""

    def __init__(self, observer: StepObserver | None = None) -> None:
        self._observer = observer
        self._next_sequence = 1
        self._open_steps: list[AgentExecutionStep] = []

    def start(
        self,
        kind: AgentExecutionStep.__annotations__["kind"],
        title: str,
        *,
        detail: str | None = None,
        attempt: int | None = None,
    ) -> AgentExecutionStep:
        step = AgentExecutionStep(
            step_id=f"step-{self._next_sequence}",
            sequence=self._next_sequence,
            kind=kind,
            status=StepState.STARTED,
            title=title,
            detail=detail,
            attempt=attempt,
            started_at=_utc_now(),
        )
        self._next_sequence += 1
        self._open_steps.append(step)
        self._emit(step)
        return step

    def finish(self, step: AgentExecutionStep, status: StepState) -> None:
        updated = step.model_copy(update={"status": status, "finished_at": _utc_now()})
        if step in self._open_steps:
            self._open_steps.remove(step)
        self._emit(updated)

    def finalize_open_steps(self, status: StepState = StepState.FAILED) -> None:
        """Close every still-open step so the task always carries finished_at."""

        for step in list(self._open_steps):
            self.finish(step, status)

    def _emit(self, step: AgentExecutionStep) -> None:
        if self._observer is not None:
            self._observer(step)


class ApprovedAnalysisTools:
    """Server-owned state and the only three tools available to the analysis Agent."""

    def __init__(
        self,
        settings: Settings,
        executor: SqlExecutor,
        list_tables_fn: ListTablesFn,
        get_schema_fn: GetSchemaFn,
        step_recorder: ExecutionStepRecorder | None = None,
    ) -> None:
        self._settings = settings
        self._executor = executor
        self._list_tables_fn = list_tables_fn
        self._get_schema_fn = get_schema_fn
        self._retry_policy = RetryPolicy(settings.max_sql_retries)
        self._metadata_policy = SqlPolicy(settings.allowed_tables, settings.max_query_rows)
        self._step_recorder = step_recorder or ExecutionStepRecorder()
        self._tool_calls = 0
        self._listed_tables = False
        self._inspected_tables: set[str] = set()
        self.sql_attempts = 0
        self.last_result: SqlExecutionResult | None = None
        self.last_sql: str | None = None
        self.terminal_error: SqlToolError | None = None

    def _fail_fast_if_terminal(self, step: AgentExecutionStep, kind: str) -> SqlToolError | None:
        """Refuse further tool calls once the coordinator is in a terminal state.

        Returning the stored SqlToolError keeps the agent loop honest: instead of
        silently feeding the same error to the LLM (which still likes to retry),
        the bound function raises and the SDK aborts the current turn.
        """

        if not self._claim_tool_call():
            self._step_recorder.finish(step, StepState.FAILED)
            error = SqlToolError(
                SqlErrorCode.TOOL_BUDGET_EXCEEDED,
                "The analysis tool-call budget has been reached.",
                False,
            )
            self.terminal_error = error
            raise AgentRunError.with_code(
                SqlErrorCode.SQL_EXECUTION_ERROR.value,
                "The analysis tool-call budget has been reached.",
            )
        if self.terminal_error is None:
            return None
        del kind  # retained for log forward-compatibility
        self._step_recorder.finish(step, StepState.FAILED)
        raise AgentRunError.with_code(
            self.terminal_error.code.value,
            self.terminal_error.message,
        )

    def list_tables(self) -> dict[str, object]:
        step = self._step_recorder.start("list_tables", "Reading approved tables")
        try:
            self._fail_fast_if_terminal(step, "list_tables")
            if not self._listed_tables:
                result = self._list_tables_fn(self._settings)
                self._listed_tables = True
                response = result.model_dump()
            else:
                response = self._error_response(
                    SqlToolError(
                        SqlErrorCode.METADATA_REQUIRED,
                        "list_tables can only be called once per task.",
                        False,
                    )
                )
        except Exception:
            self._step_recorder.finish(step, StepState.FAILED)
            raise
        self._step_recorder.finish(step, StepState.SUCCEEDED)
        return response

    def get_table_schema(self, table_name: str) -> dict[str, object]:
        step = self._step_recorder.start("get_table_schema", "Reading table structure")
        try:
            self._fail_fast_if_terminal(step, "get_table_schema")
            if not self._listed_tables:
                self._step_recorder.finish(step, StepState.FAILED)
                raise AgentRunError.with_code(
                    SqlErrorCode.METADATA_REQUIRED.value,
                    "Call list_tables before requesting a table schema.",
                )
            result = self._get_schema_fn(table_name, self._settings)
            self._inspected_tables.add(result.table_name)
            response = result.model_dump()
        except Exception:
            self._step_recorder.finish(step, StepState.FAILED)
            raise
        self._step_recorder.finish(step, StepState.SUCCEEDED)
        return response

    def execute_sql(self, sql: str) -> dict[str, object]:
        validation_step = self._step_recorder.start("sql_validation", "Validating query safety")
        try:
            self._fail_fast_if_terminal(validation_step, "execute_sql")
            metadata_error = self._metadata_error(sql)
            if metadata_error is not None:
                self._step_recorder.finish(validation_step, StepState.FAILED)
                raise AgentRunError.with_code(metadata_error.code.value, metadata_error.message)
            if self.sql_attempts >= self._settings.max_sql_retries + 1:
                self._step_recorder.finish(validation_step, StepState.FAILED)
                self.terminal_error = SqlToolError(
                    SqlErrorCode.SQL_RETRY_EXHAUSTED,
                    "The SQL repair limit has been reached.",
                    False,
                )
                raise AgentRunError.with_code(
                    SqlErrorCode.SQL_RETRY_EXHAUSTED.value,
                    "The SQL repair limit has been reached.",
                )

            if self.sql_attempts > 0:
                repair_step = self._step_recorder.start(
                    "sql_repair", "Preparing a corrected query", attempt=self.sql_attempts + 1
                )
                self._step_recorder.finish(repair_step, StepState.SUCCEEDED)
            self._step_recorder.finish(validation_step, StepState.SUCCEEDED)
            self.sql_attempts += 1
            execute_step = self._step_recorder.start(
                "execute_sql", "Executing read-only query", attempt=self.sql_attempts
            )
            tool_result = self._executor.execute(sql)
            response = serialize_sql_tool_result(tool_result)
            if response["success"]:
                assert tool_result.result is not None
                self.last_result = tool_result.result
                self.last_sql = sql
                self._step_recorder.finish(execute_step, StepState.SUCCEEDED)
                return response

            self._step_recorder.finish(execute_step, StepState.FAILED)

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
        except AgentRunError:
            self._step_recorder.finalize_open_steps(StepState.FAILED)
            raise
        except Exception:
            self._step_recorder.finish(validation_step, StepState.FAILED)
            self._step_recorder.finalize_open_steps(StepState.FAILED)
            raise

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

    def _metadata_error(self, sql: str) -> SqlToolError | None:
        if not self._listed_tables:
            return SqlToolError(
                SqlErrorCode.METADATA_REQUIRED,
                "Call list_tables before executing SQL.",
                True,
            )
        referenced_tables = self._metadata_policy.referenced_tables(sql)
        if not referenced_tables.issubset(self._inspected_tables):
            return SqlToolError(
                SqlErrorCode.METADATA_REQUIRED,
                "Call get_table_schema for every table referenced by the SQL.",
                True,
            )
        return None

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

    def run(self, question: str, on_step: StepObserver | None = None) -> AnalysisReport:
        if self._settings.minimax_api_key is None:
            raise AgentProviderNotConfigured
        step_recorder = ExecutionStepRecorder(on_step)
        agent_step = step_recorder.start("agent_started", "Starting analysis")
        tools = ApprovedAnalysisTools(
            self._settings,
            self._executor,
            self._list_tables_fn,
            self._get_schema_fn,
            step_recorder,
        )
        try:
            try:
                output = self._agent_runner(question, tools)
            except AgentRunError:
                step_recorder.finish(agent_step, StepState.FAILED)
                raise
            except Exception as error:
                step_recorder.finish(agent_step, StepState.FAILED)
                raise AgentProviderError from error
            step_recorder.finish(agent_step, StepState.SUCCEEDED)

            clarification_message = _clarification_message(output)
            if clarification_message is not None:
                raise AnalysisNeedsClarification(clarification_message)

            if tools.last_result is None or tools.last_sql is None:
                error = tools.terminal_error or SqlToolError(
                    SqlErrorCode.SQL_EXECUTION_ERROR,
                    "The Agent did not produce a successful query.",
                    False,
                )
                raise DynamicAnalysisError(error.code.value, error.message)

            report_step = step_recorder.start("report_generation", "Generating report")
            try:
                try:
                    narrative = validate_narrative_output(output)
                    report = _build_report(
                        narrative, tools.last_result, tools.last_sql, tools.sql_attempts
                    )
                except (ValidationError, json.JSONDecodeError, ValueError) as error:
                    head = str(error).splitlines()[0] if str(error).splitlines() else "<empty>"
                    raw = repr(output)[:200]
                    import logging
                    logging.getLogger("agentic_genbi").error(
                        "validate_narrative_output_failed: %s | raw=%s",
                        head,
                        raw,
                    )
                    raise InvalidAgentReport(f"{head} | raw={raw}") from error
            except Exception:
                step_recorder.finish(report_step, StepState.FAILED)
                raise
            step_recorder.finish(report_step, StepState.SUCCEEDED)
            return report
        except Exception:
            _finalize_open_steps(step_recorder)
            raise

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


def _clarification_message(output: Any) -> str | None:
    """Accept the explicit no-query response contract for ambiguous questions."""

    if isinstance(output, str):
        without_thinking = re.sub(r"<think>.*?</think>", "", output, flags=re.DOTALL).strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", without_thinking, flags=re.DOTALL)
        try:
            output = json.loads(fenced.group(1) if fenced else without_thinking)
        except json.JSONDecodeError:
            return None
    if not isinstance(output, dict) or output.get("requires_input") is not True:
        return None
    message = output.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return "Please provide the missing business scope before analysis can continue."


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _finalize_open_steps(recorder: ExecutionStepRecorder) -> None:
    """Mark any recorder-tracked steps that were started but never finished as failed."""

    recorder.finalize_open_steps(StepState.FAILED)
