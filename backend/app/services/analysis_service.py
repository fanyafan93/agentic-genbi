from typing import Protocol

from pydantic import ValidationError

from app.agents.runner import InvalidAgentReport
from app.config import Settings
from app.query import FIXED_SALES_SQL, SqlExecutionResult, execute_fixed_sales_query
from app.schemas.analysis import AnalysisReport, ReportNarrative, ReportTable, ResultColumn


class NarrativeRunner(Protocol):
    def run(self, question: str, trusted_context: str) -> ReportNarrative: ...


class AnalysisService:
    """Combine a deterministic query result with an Agent-authored narrative."""

    def __init__(self, settings: Settings, narrative_runner: NarrativeRunner) -> None:
        self._settings = settings
        self._narrative_runner = narrative_runner

    def run(self, question: str) -> AnalysisReport:
        result = execute_fixed_sales_query(self._settings)
        trusted_context = _trusted_context(result)
        narrative = self._narrative_runner.run(question, trusted_context)
        return _report_from_narrative(narrative, result)


def _trusted_context(result: SqlExecutionResult) -> str:
    table = ReportTable(
        columns=[ResultColumn(name=column.name, data_type=column.data_type) for column in result.columns],
        rows=result.rows,
        row_count=result.row_count,
        truncated=result.truncated,
    )
    return table.model_dump_json()


def _report_from_narrative(
    narrative: ReportNarrative, result: SqlExecutionResult
) -> AnalysisReport:
    try:
        return AnalysisReport(
            title=narrative.title,
            summary=narrative.summary,
            sql=FIXED_SALES_SQL,
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
            sql_attempts=1,
        )
    except ValidationError as error:
        raise InvalidAgentReport from error
