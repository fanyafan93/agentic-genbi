from datetime import UTC, datetime
from uuid import uuid4

from app.schemas.analysis import (
    AnalysisReport,
    AnalysisRequest,
    AnalysisTaskStatus,
    ReportTable,
    ResultColumn,
    TaskState,
)


class TaskNotFound(Exception):
    """Raised when the in-process registry does not contain a task."""


class TaskCapacityExceeded(Exception):
    """Raised when the MVP's one worker slot is occupied."""


class TaskService:
    """In-memory task registry for exactly one FastAPI process and worker slot.

    The registry intentionally has no persistence: a process restart discards every
    task, and callers must receive TASK_NOT_FOUND afterwards. This keeps the MVP
    boundary explicit until durable queueing is justified.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, AnalysisTaskStatus] = {}

    def create_task(self, request: AnalysisRequest) -> AnalysisTaskStatus:
        if any(task.status in {TaskState.QUEUED, TaskState.RUNNING} for task in self._tasks.values()):
            raise TaskCapacityExceeded

        now = _utc_now()
        task = AnalysisTaskStatus(
            task_id=str(uuid4()),
            status=TaskState.QUEUED,
            created_at=now,
            updated_at=now,
        )
        self._tasks[task.task_id] = task
        return _snapshot(task)

    def get_task(self, task_id: str) -> AnalysisTaskStatus:
        try:
            return _snapshot(self._tasks[task_id])
        except KeyError as error:
            raise TaskNotFound from error

    def start_task(self, task_id: str) -> AnalysisTaskStatus:
        task = self._get_mutable_task(task_id)
        if task.status is not TaskState.QUEUED:
            raise ValueError("only queued tasks may start")
        self._tasks[task_id] = task.model_copy(update={"status": TaskState.RUNNING, "updated_at": _utc_now()})
        return self.get_task(task_id)

    def succeed_task(self, task_id: str, report: AnalysisReport) -> AnalysisTaskStatus:
        task = self._get_mutable_task(task_id)
        if task.status is not TaskState.RUNNING:
            raise ValueError("only running tasks may succeed")
        completed_at = _utc_now()
        self._tasks[task_id] = task.model_copy(
            update={
                "status": TaskState.SUCCEEDED,
                "report": report,
                "updated_at": completed_at,
                "completed_at": completed_at,
            }
        )
        return self.get_task(task_id)

    def run_fixed_analysis(self, task_id: str) -> None:
        """Complete the temporary deterministic analysis used before Agent/DB work."""

        self.start_task(task_id)
        self.succeed_task(task_id, _fixed_report())

    def _get_mutable_task(self, task_id: str) -> AnalysisTaskStatus:
        try:
            return self._tasks[task_id]
        except KeyError as error:
            raise TaskNotFound from error


def _fixed_report() -> AnalysisReport:
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


def _snapshot(task: AnalysisTaskStatus) -> AnalysisTaskStatus:
    return task.model_copy(deep=True)


def _utc_now() -> datetime:
    return datetime.now(UTC)
