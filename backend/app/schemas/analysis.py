from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4000)
    client_request_id: str | None = Field(default=None, max_length=128)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("question must not be blank")
        return normalized


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REQUIRES_INPUT = "requires_input"


class StepState(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentExecutionStep(StrictModel):
    step_id: str
    sequence: int = Field(ge=1)
    kind: Literal[
        "agent_started",
        "list_tables",
        "get_table_schema",
        "sql_validation",
        "execute_sql",
        "sql_repair",
        "report_generation",
    ]
    status: StepState
    title: str
    detail: str | None = None
    attempt: int | None = Field(default=None, ge=1, le=3)
    started_at: datetime
    finished_at: datetime | None = None


class ResultColumn(StrictModel):
    name: str
    data_type: str


class ReportTable(StrictModel):
    columns: list[ResultColumn]
    rows: list[dict[str, Any]]
    row_count: int = Field(ge=0)
    truncated: bool = False


class ChartSpec(StrictModel):
    type: Literal["line", "bar", "pie"]
    title: str
    x_field: str
    y_fields: list[str] = Field(min_length=1)
    series_field: str | None = None


class AnalysisReport(StrictModel):
    title: str
    summary: list[str] = Field(min_length=1, max_length=8)
    sql: str
    table: ReportTable
    chart: ChartSpec | None
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    warnings: list[str] = Field(default_factory=list, max_length=8)
    query_duration_ms: int = Field(ge=0)
    sql_attempts: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def chart_fields_must_exist_in_table(self) -> "AnalysisReport":
        if self.chart is None:
            return self
        column_names = {column.name for column in self.table.columns}
        chart_fields = [self.chart.x_field, *self.chart.y_fields]
        if self.chart.series_field is not None:
            chart_fields.append(self.chart.series_field)
        if not set(chart_fields).issubset(column_names):
            raise ValueError("chart fields must reference report table columns")
        return self


class ApiError(StrictModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None


class AnalysisTaskStatus(StrictModel):
    task_id: str
    status: TaskState
    steps: list[AgentExecutionStep] = Field(default_factory=list)
    report: AnalysisReport | None = None
    error: ApiError | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def enforce_terminal_field_invariants(self) -> "AnalysisTaskStatus":
        if self.status in {TaskState.QUEUED, TaskState.RUNNING}:
            if self.report is not None or self.error is not None or self.completed_at is not None:
                raise ValueError("non-terminal tasks cannot include terminal fields")
        elif self.status is TaskState.SUCCEEDED:
            if self.report is None or self.error is not None or self.completed_at is None:
                raise ValueError("succeeded tasks require report and completed_at only")
        elif self.report is not None or self.error is None or self.completed_at is None:
            raise ValueError("failed tasks require error and completed_at only")
        return self


class ApiErrorResponse(StrictModel):
    error: ApiError
