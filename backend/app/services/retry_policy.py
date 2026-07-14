from enum import StrEnum

from app.database.errors import SqlToolError


class RetryDecision(StrEnum):
    REPAIR = "repair"
    EXHAUSTED = "exhausted"
    STOP = "stop"


class RetryPolicy:
    """Allow at most the configured number of repairs after the initial SQL attempt."""

    def __init__(self, max_retries: int) -> None:
        self._max_retries = max_retries

    def decide(self, attempt: int, sql_error: SqlToolError) -> RetryDecision:
        if not sql_error.retryable:
            return RetryDecision.STOP
        return RetryDecision.REPAIR if attempt <= self._max_retries else RetryDecision.EXHAUSTED
