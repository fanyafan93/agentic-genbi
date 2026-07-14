import pytest

from app.database.errors import SqlErrorCode, classify_database_error


@pytest.mark.parametrize(
    ("driver_message", "code", "retryable"),
    [
        ("(1054, Unknown column 'missing_metric' in 'field list')", SqlErrorCode.SQL_UNKNOWN_COLUMN, True),
        ("(1146, Table 'analytics.missing_table' doesn't exist)", SqlErrorCode.SQL_UNKNOWN_TABLE, True),
        ("(1064, You have an error in your SQL syntax)", SqlErrorCode.SQL_SYNTAX_ERROR, True),
        ("(1044, Access denied for user 'readonly_user')", SqlErrorCode.SQL_PERMISSION_DENIED, False),
        ("(3024, Query execution was interrupted, maximum statement execution time exceeded)", SqlErrorCode.SQL_TIMEOUT, False),
        ("(2003, Can't connect to MySQL server on 'internal-host')", SqlErrorCode.DATABASE_UNAVAILABLE, False),
        ("(1111, Invalid use of group function)", SqlErrorCode.SQL_EXECUTION_ERROR, False),
    ],
)
def test_database_errors_are_sanitized_and_classified(
    driver_message: str, code: SqlErrorCode, retryable: bool
) -> None:
    error = classify_database_error(RuntimeError(driver_message))

    assert error.code is code
    assert error.retryable is retryable
    assert "readonly_user" not in error.message
    assert "internal-host" not in error.message
    assert "missing_metric" not in error.message


def test_type_errors_are_repairable() -> None:
    error = classify_database_error(RuntimeError("Truncated incorrect DECIMAL value: 'not-a-number'"))

    assert error.code is SqlErrorCode.SQL_TYPE_ERROR
    assert error.retryable is True
