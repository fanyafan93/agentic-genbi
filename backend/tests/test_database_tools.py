from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resource_library.database_tools import DatabaseConfig, ReadonlyDatabaseTools, validate_readonly_sql


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.description = [(key,) for key in rows[0].keys()] if rows else []
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def close(self) -> None:
        pass


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.cursor_instance = FakeCursor(rows)

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        pass


class SequencedConnection:
    def __init__(self, row_sets: list[list[dict[str, Any]]]) -> None:
        self.row_sets = row_sets
        self.cursors: list[FakeCursor] = []

    def cursor(self) -> FakeCursor:
        cursor = FakeCursor(self.row_sets.pop(0))
        self.cursors.append(cursor)
        return cursor

    def close(self) -> None:
        pass


class DatabaseToolsTest(unittest.TestCase):
    def test_validate_adds_limit_to_select(self) -> None:
        result = validate_readonly_sql("select order_id from dm.sales", max_rows=100)

        self.assertTrue(result.ok)
        self.assertEqual(result.normalized_sql, "SELECT order_id FROM dm.sales LIMIT 100")

    def test_validate_rejects_writes_multi_statement_and_star(self) -> None:
        self.assertFalse(validate_readonly_sql("delete from dm.sales").ok)
        self.assertFalse(validate_readonly_sql("select id from a; select id from b").ok)
        self.assertFalse(validate_readonly_sql("select * from dm.sales").ok)

    def test_run_readonly_query_uses_validated_sql_and_reason(self) -> None:
        connection = FakeConnection([{"order_id": 1}])
        tools = ReadonlyDatabaseTools(
            DatabaseConfig(host="x", port=3306, user="u", password="p", enabled=True),
            connection=connection,
        )

        result = tools.run_readonly_query("select order_id from dm.sales", reason="validate sample")

        self.assertEqual(result.rows, [{"order_id": 1}])
        self.assertEqual(connection.cursor_instance.executed[0][0], "SELECT order_id FROM dm.sales LIMIT 1000")

    def test_run_readonly_template_binds_named_values_after_sql_validation(self) -> None:
        connection = FakeConnection([{"channel": "线上", "salesAmount": 100}])
        tools = ReadonlyDatabaseTools(
            DatabaseConfig(host="x", port=3306, user="u", password="p", enabled=True),
            connection=connection,
        )

        result = tools.run_readonly_template(
            "select vchannel_type as channel, sum(vvalues) as salesAmount from dm.sales where vmonth_code = :month group by vchannel_type",
            {"month": "2026-08"},
            reason="interactive report query",
        )

        self.assertEqual(result.rows, [{"channel": "线上", "salesAmount": 100}])
        sql, params = connection.cursor_instance.executed[0]
        self.assertIn("vmonth_code = %s", sql)
        self.assertEqual(params, ("2026-08",))

    def test_disabled_business_query_blocks_fetch(self) -> None:
        tools = ReadonlyDatabaseTools(
            DatabaseConfig(host="x", port=3306, user="u", password="p", enabled=False),
            connection=FakeConnection([]),
        )

        with self.assertRaises(RuntimeError):
            tools.search_db_tables("sales")

    def test_inspect_table_profile_reads_information_schema_metadata(self) -> None:
        connection = SequencedConnection(
            [
                [
                    {
                        "TABLE_SCHEMA": "dm",
                        "TABLE_NAME": "sales",
                        "TABLE_TYPE": "BASE TABLE",
                        "TABLE_COMMENT": "销售表",
                        "TABLE_ROWS": 123456,
                        "DATA_LENGTH": 2048,
                        "INDEX_LENGTH": 1024,
                        "CREATE_TIME": "2026-01-01 00:00:00",
                        "UPDATE_TIME": "2026-07-28 00:00:00",
                    }
                ],
                [{"partition_count": 12}],
                [
                    {"COLUMN_NAME": "order_id", "DATA_TYPE": "varchar", "COLUMN_COMMENT": "订单ID"},
                    {"COLUMN_NAME": "order_date", "DATA_TYPE": "date", "COLUMN_COMMENT": "订单日期"},
                ],
            ]
        )
        tools = ReadonlyDatabaseTools(
            DatabaseConfig(host="x", port=3306, user="u", password="p", enabled=True),
            connection=connection,
        )

        profile = tools.inspect_table_profile("dm", "sales")

        self.assertEqual(profile.approximate_rows, 123456)
        self.assertEqual(profile.total_length_bytes, 3072)
        self.assertEqual(profile.partition_count, 12)
        self.assertEqual(profile.time_column_candidates, ["order_date"])

    def test_database_config_reads_mysql_database_url(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GENBI_ENV_FILE": "missing-test.env",
                "DATABASE_URL": "mysql+pymysql://readonly_user:liran%402026@8.134.63.30:3307/dm",
            },
            clear=True,
        ):
            config = DatabaseConfig.from_env()

        self.assertEqual(config.host, "8.134.63.30")
        self.assertEqual(config.port, 3307)
        self.assertEqual(config.user, "readonly_user")
        self.assertEqual(config.password, "liran@2026")
        self.assertEqual(config.database, "dm")


if __name__ == "__main__":
    unittest.main()
