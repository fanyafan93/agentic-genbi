from app.database.errors import SqlErrorCode, SqlToolError
from app.query import SqlExecutionResult, SqlResultColumn
from app.tools.execute_sql import execute_sql


class FakeExecutor:
    def __init__(self) -> None:
        self.sql: list[str] = []

    def execute(self, sql: str):
        self.sql.append(sql)
        from app.services.sql_executor import SqlToolResult

        return SqlToolResult(
            success=True,
            result=SqlExecutionResult(
                columns=[SqlResultColumn("channel", "varchar")],
                rows=[{"channel": "online"}],
                row_count=1,
                truncated=False,
                query_duration_ms=3,
            ),
        )


def test_execute_sql_returns_only_structured_query_data() -> None:
    executor = FakeExecutor()

    response = execute_sql("SELECT channel FROM sales_channel_monthly", executor)

    assert executor.sql == ["SELECT channel FROM sales_channel_monthly"]
    assert response == {
        "success": True,
        "result": {
            "columns": [{"name": "channel", "data_type": "varchar"}],
            "rows": [{"channel": "online"}],
            "row_count": 1,
            "truncated": False,
            "query_duration_ms": 3,
        },
        "error": None,
    }


def test_execute_sql_returns_sanitized_error_values() -> None:
    class FailingExecutor:
        def execute(self, sql: str):
            from app.services.sql_executor import SqlToolResult

            return SqlToolResult(
                success=False,
                error=SqlToolError(
                    SqlErrorCode.SQL_UNKNOWN_COLUMN,
                    "The query references an unknown column.",
                    True,
                ),
            )

    response = execute_sql("SELECT missing_metric FROM sales_channel_monthly", FailingExecutor())

    assert response == {
        "success": False,
        "result": None,
        "error": {
            "code": "SQL_UNKNOWN_COLUMN",
            "message": "The query references an unknown column.",
            "retryable": True,
        },
    }
