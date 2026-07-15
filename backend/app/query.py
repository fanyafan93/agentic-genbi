from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any

from sqlalchemy import text

from app.config import Settings
from app.database import connection_for_settings


FIXED_SALES_SQL = """SELECT month_start, channel, sales_amount
FROM sales_channel_monthly
ORDER BY month_start ASC, channel ASC"""


@dataclass(frozen=True)
class SqlResultColumn:
    name: str
    data_type: str


@dataclass(frozen=True)
class SqlExecutionResult:
    columns: list[SqlResultColumn]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    query_duration_ms: int


def normalize_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def execute_fixed_sales_query(settings: Settings) -> SqlExecutionResult:
    started_at = perf_counter()
    with connection_for_settings(settings) as connection:
        result = connection.execute(text(FIXED_SALES_SQL))
        raw_rows = [dict(row) for row in result.mappings()]

    rows = [{key: normalize_value(value) for key, value in row.items()} for row in raw_rows]
    columns = [
        SqlResultColumn("month_start", "date"),
        SqlResultColumn("channel", "varchar"),
        SqlResultColumn("sales_amount", "decimal"),
    ]
    return SqlExecutionResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=False,
        query_duration_ms=round((perf_counter() - started_at) * 1000),
    )
