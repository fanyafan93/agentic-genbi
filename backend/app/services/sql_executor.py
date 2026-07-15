from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.database import connection_for_settings
from app.database.errors import SqlErrorCode, SqlToolError, classify_database_error
from app.query import SqlExecutionResult, SqlResultColumn, normalize_value
from app.services.sql_policy import SqlPolicy, SqlPolicyViolation


@dataclass(frozen=True)
class SqlToolResult:
    success: bool
    result: SqlExecutionResult | None = None
    error: SqlToolError | None = None


ConnectionFactory = Callable[[Settings], AbstractContextManager[Any]]


class SqlExecutor:
    """Execute only SQL approved by the server-owned policy."""

    def __init__(
        self,
        settings: Settings,
        policy: SqlPolicy | None = None,
        connection_factory: ConnectionFactory = connection_for_settings,
    ) -> None:
        self._settings = settings
        self._policy = policy or SqlPolicy(settings.allowed_tables, settings.max_query_rows)
        self._connection_factory = connection_factory

    def execute(self, candidate_sql: str) -> SqlToolResult:
        try:
            normalized = self._policy.validate(candidate_sql)
        except SqlPolicyViolation:
            return SqlToolResult(
                success=False,
                error=SqlToolError(
                    SqlErrorCode.SQL_SAFETY_VIOLATION,
                    "The generated SQL did not pass the read-only safety policy.",
                    False,
                ),
            )

        started_at = perf_counter()
        try:
            with self._connection_factory(self._settings) as connection:
                connection.execute(
                    text("SET SESSION MAX_EXECUTION_TIME = :timeout"),
                    {"timeout": self._settings.query_timeout_ms},
                )
                query_result = connection.execute(text(normalized.sql))
                raw_rows = [dict(row) for row in query_result.mappings()]
        except SQLAlchemyError as error:
            return SqlToolResult(success=False, error=classify_database_error(error))

        truncated = len(raw_rows) > normalized.limit
        rows = [
            {key: normalize_value(value) for key, value in row.items()}
            for row in raw_rows[: normalized.limit]
        ]
        return SqlToolResult(
            success=True,
            result=SqlExecutionResult(
                columns=_result_columns(raw_rows),
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                query_duration_ms=round((perf_counter() - started_at) * 1000),
            ),
        )


def _result_columns(rows: list[dict[str, Any]]) -> list[SqlResultColumn]:
    if not rows:
        return []
    return [
        SqlResultColumn(name=name, data_type=_data_type(next((row[name] for row in rows if row[name] is not None), None)))
        for name in rows[0]
    ]


def _data_type(value: Any) -> str:
    if value is None:
        return "unknown"
    value_type = type(value).__name__.lower()
    return "decimal" if value_type == "decimal" else value_type
