from typing import Protocol

from app.services.sql_executor import SqlToolResult


class SqlExecutorProtocol(Protocol):
    def execute(self, sql: str) -> SqlToolResult: ...


def execute_sql(sql: str, executor: SqlExecutorProtocol) -> dict[str, object]:
    """Expose only sanitized, JSON-shaped SQL execution output to the Agent."""

    return serialize_sql_tool_result(executor.execute(sql))


def serialize_sql_tool_result(tool_result: SqlToolResult) -> dict[str, object]:
    """Serialize a result already produced by the server-owned executor."""

    if tool_result.success:
        assert tool_result.result is not None
        result = tool_result.result
        return {
            "success": True,
            "result": {
                "columns": [column.__dict__ for column in result.columns],
                "rows": result.rows,
                "row_count": result.row_count,
                "truncated": result.truncated,
                "query_duration_ms": result.query_duration_ms,
            },
            "error": None,
        }

    assert tool_result.error is not None
    return {
        "success": False,
        "result": None,
        "error": {
            "code": tool_result.error.code.value,
            "message": tool_result.error.message,
            "retryable": tool_result.error.retryable,
        },
    }
