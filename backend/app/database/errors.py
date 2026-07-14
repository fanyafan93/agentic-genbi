from dataclasses import dataclass
from enum import StrEnum
import re


class SqlErrorCode(StrEnum):
    SQL_SAFETY_VIOLATION = "SQL_SAFETY_VIOLATION"
    SQL_SYNTAX_ERROR = "SQL_SYNTAX_ERROR"
    SQL_UNKNOWN_TABLE = "SQL_UNKNOWN_TABLE"
    SQL_UNKNOWN_COLUMN = "SQL_UNKNOWN_COLUMN"
    SQL_TYPE_ERROR = "SQL_TYPE_ERROR"
    SQL_PERMISSION_DENIED = "SQL_PERMISSION_DENIED"
    SQL_TIMEOUT = "SQL_TIMEOUT"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    SQL_EXECUTION_ERROR = "SQL_EXECUTION_ERROR"
    SQL_RETRY_EXHAUSTED = "SQL_RETRY_EXHAUSTED"
    TOOL_BUDGET_EXCEEDED = "TOOL_BUDGET_EXCEEDED"
    METADATA_REQUIRED = "METADATA_REQUIRED"


@dataclass(frozen=True)
class SqlToolError:
    code: SqlErrorCode
    message: str
    retryable: bool


def classify_database_error(error: Exception) -> SqlToolError:
    """Map expected database errors to stable public values without driver details."""

    message = str(error).lower()
    if "unknown column" in message:
        return SqlToolError(SqlErrorCode.SQL_UNKNOWN_COLUMN, "The query references an unknown column.", True)
    if "table" in message and ("doesn't exist" in message or "does not exist" in message):
        return SqlToolError(SqlErrorCode.SQL_UNKNOWN_TABLE, "The query references an unknown table.", True)
    if "syntax" in message:
        return SqlToolError(SqlErrorCode.SQL_SYNTAX_ERROR, "The query contains a SQL syntax error.", True)
    if re.search(r"(truncated incorrect|incorrect (?:date|decimal|integer|double)|invalid (?:date|decimal|integer))", message):
        return SqlToolError(SqlErrorCode.SQL_TYPE_ERROR, "The query contains an incompatible value or type.", True)
    if "access denied" in message or "permission" in message:
        return SqlToolError(SqlErrorCode.SQL_PERMISSION_DENIED, "The database denied this query.", False)
    if "maximum statement execution time" in message or "timeout" in message:
        return SqlToolError(SqlErrorCode.SQL_TIMEOUT, "The query exceeded the execution time limit.", False)
    if "can't connect" in message or "connection" in message:
        return SqlToolError(SqlErrorCode.DATABASE_UNAVAILABLE, "The database is unavailable.", False)
    return SqlToolError(SqlErrorCode.SQL_EXECUTION_ERROR, "The query could not be executed.", False)
