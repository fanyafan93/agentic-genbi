from datetime import date, datetime
from decimal import Decimal
from importlib import import_module


def test_query_result_normalizes_database_values_for_json() -> None:
    query = import_module("app.query")

    assert query.normalize_value(Decimal("12.50")) == 12.5
    assert query.normalize_value(date(2026, 1, 1)) == "2026-01-01"
    assert query.normalize_value(datetime(2026, 1, 1, 8, 30, 0)) == "2026-01-01T08:30:00"
    assert query.normalize_value(None) is None


def test_fixed_query_is_developer_owned_read_only_sql() -> None:
    query = import_module("app.query")

    assert query.FIXED_SALES_SQL.startswith("SELECT")
    assert "sales_channel_monthly" in query.FIXED_SALES_SQL
