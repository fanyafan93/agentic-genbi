from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from app.config import Settings
from app.services.sql_executor import SqlExecutor, SqlToolResult
from app.services.sql_policy import SqlPolicy


class FakeResult:
    def mappings(self) -> "FakeResult":
        return self

    def __iter__(self):
        return iter(
            [
                {"month_start": date(2026, 1, 1), "sales_amount": Decimal("120.50")},
                {"month_start": date(2026, 2, 1), "sales_amount": Decimal("98.25")},
            ]
        )


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, int]]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if sql.startswith("SET SESSION"):
            return None
        return FakeResult()


def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
        max_query_rows=2,
        query_timeout_ms=1500,
        _env_file=None,
    )


def test_executor_applies_server_limits_and_normalizes_rows() -> None:
    connection = FakeConnection()

    @contextmanager
    def connection_factory(_: Settings):
        yield connection

    executor = SqlExecutor(
        settings(),
        policy=SqlPolicy(("sales_channel_monthly",), max_rows=2),
        connection_factory=connection_factory,
    )

    result = executor.execute("SELECT month_start, sales_amount FROM sales_channel_monthly")

    assert isinstance(result, SqlToolResult)
    assert result.success is True
    assert result.result is not None
    assert result.result.rows[0] == {"month_start": "2026-01-01", "sales_amount": 120.5}
    assert result.result.row_count == 2
    assert result.result.truncated is False
    assert connection.calls[0] == ("SET SESSION MAX_EXECUTION_TIME = :timeout", {"timeout": 1500})
    assert connection.calls[1][0].endswith("LIMIT 3")


def test_executor_uses_one_extra_row_only_to_detect_truncation() -> None:
    class ThreeRowResult(FakeResult):
        def __iter__(self):
            return iter([
                {"channel": "online"},
                {"channel": "retail"},
                {"channel": "distributor"},
            ])

    class ThreeRowConnection(FakeConnection):
        def execute(self, statement, params=None):
            result = super().execute(statement, params)
            return ThreeRowResult() if str(statement).startswith("SELECT") else result

    connection = ThreeRowConnection()

    @contextmanager
    def connection_factory(_: Settings):
        yield connection

    executor = SqlExecutor(settings(), connection_factory=connection_factory)
    result = executor.execute("SELECT channel FROM sales_channel_monthly")

    assert result.success is True
    assert result.result is not None
    assert result.result.rows == [{"channel": "online"}, {"channel": "retail"}]
    assert result.result.row_count == 2
    assert result.result.truncated is True


def test_executor_returns_sanitized_policy_failure_without_opening_a_connection() -> None:
    executor = SqlExecutor(settings(), policy=SqlPolicy(("sales_channel_monthly",), max_rows=2))

    result = executor.execute("DELETE FROM sales_channel_monthly")

    assert result.success is False
    assert result.error is not None
    assert result.error.code == "SQL_SAFETY_VIOLATION"
    assert result.error.retryable is False
