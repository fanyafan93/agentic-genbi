from app.database.errors import SqlErrorCode, SqlToolError
from app.services.retry_policy import RetryDecision, RetryPolicy


def error(code: SqlErrorCode, retryable: bool) -> SqlToolError:
    return SqlToolError(code=code, message="safe", retryable=retryable)


def test_retry_policy_allows_exactly_two_repairs_after_initial_execution() -> None:
    policy = RetryPolicy(max_retries=2)
    retryable_error = error(SqlErrorCode.SQL_UNKNOWN_COLUMN, True)

    assert policy.decide(attempt=1, sql_error=retryable_error) is RetryDecision.REPAIR
    assert policy.decide(attempt=2, sql_error=retryable_error) is RetryDecision.REPAIR
    assert policy.decide(attempt=3, sql_error=retryable_error) is RetryDecision.EXHAUSTED


def test_retry_policy_stops_non_repairable_errors_immediately() -> None:
    policy = RetryPolicy(max_retries=2)

    assert (
        policy.decide(
            attempt=1,
            sql_error=error(SqlErrorCode.SQL_SAFETY_VIOLATION, False),
        )
        is RetryDecision.STOP
    )
    assert (
        policy.decide(
            attempt=1,
            sql_error=error(SqlErrorCode.SQL_TIMEOUT, False),
        )
        is RetryDecision.STOP
    )
