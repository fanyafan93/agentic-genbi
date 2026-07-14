import pytest

from app.config import Settings
from app.database.errors import SqlErrorCode
from app.services.sql_executor import SqlExecutor


@pytest.mark.integration
def test_dynamic_executor_reads_seeded_mysql_and_rejects_write_before_execution() -> None:
    settings = Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@127.0.0.1:3307/analytics",
        max_query_rows=10,
        _env_file=None,
    )
    executor = SqlExecutor(settings)

    select_result = executor.execute(
        "SELECT channel, sales_amount FROM sales_channel_monthly ORDER BY month_start"
    )
    write_result = executor.execute("INSERT INTO sales_channel_monthly (channel) VALUES ('blocked')")

    assert select_result.success is True
    assert select_result.result is not None
    assert select_result.result.row_count == 6
    assert write_result.success is False
    assert write_result.error is not None
    assert write_result.error.code is SqlErrorCode.SQL_SAFETY_VIOLATION
