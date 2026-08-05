from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.persistence.postgres_stores import PostgresReportStore
from backend.tests.test_report_store import report_config


class _Result:
    def __init__(
        self,
        *,
        row: dict[str, Any] | None = None,
        rows: list[dict[str, Any]] | None = None,
        rowcount: int = 0,
    ) -> None:
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> dict[str, Any] | None:
        return self._row

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _Transaction:
    def __enter__(self) -> "_Transaction":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


class _Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.next_row: dict[str, Any] | None = None
        self.next_rows: list[dict[str, Any]] = []

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        self.calls.append((sql, params))
        row = self.next_row if "RETURNING" in sql else None
        rows = self.next_rows if sql.lstrip().startswith("SELECT") else []
        return _Result(row=row, rows=rows, rowcount=1 if row else 0)

    def transaction(self) -> _Transaction:
        return _Transaction()


@contextmanager
def _connection_context(connection: _Connection):
    yield connection


def _report_row(
    *,
    title: str = "渠道销售",
    turn_id: str | None = "turn-1",
) -> dict[str, Any]:
    config = report_config(title)
    return {
        "id": "report-1",
        "title": config["title"],
        "subtitle": config["subtitle"],
        "owner_id": "owner-1",
        "turn_id": turn_id,
        "layout": config["layout"],
        "filters": config["filters"],
        "charts": config["charts"],
        "tables": config["tables"],
        "queries": config["queries"],
        "created_at": "2026-08-05T00:00:00+00:00",
        "updated_at": "2026-08-05T00:00:00+00:00",
    }


def test_report_schema_drops_legacy_tables_and_creates_direct_tables() -> None:
    connection = _Connection()

    with patch(
        "backend.persistence.postgres_stores._connect",
        side_effect=lambda *_args: _connection_context(connection),
    ):
        PostgresReportStore("postgresql://test")

    sql = "\n".join(statement for statement, _ in connection.calls)
    direct_create = sql.split(
        "CREATE TABLE IF NOT EXISTS reports",
        maxsplit=1,
    )[1].split(
        "CREATE TABLE IF NOT EXISTS report_shares",
        maxsplit=1,
    )[0]
    assert "DROP TABLE IF EXISTS analysis_report_shares" in sql
    assert "DROP TABLE IF EXISTS analysis_report_versions" in sql
    assert "DROP TABLE IF EXISTS analysis_reports" in sql
    assert "turn_id TEXT REFERENCES analysis_turns(id) ON DELETE SET NULL" in sql
    assert "artifact_type" not in direct_create
    assert "datasets" not in direct_create
    assert "source_thread_id" not in direct_create


def test_postgres_create_persists_only_direct_report_columns() -> None:
    connection = _Connection()
    connection.next_row = _report_row(turn_id=None)

    with patch(
        "backend.persistence.postgres_stores._connect",
        side_effect=lambda *_args: _connection_context(connection),
    ), patch(
        "backend.persistence.postgres_stores._jsonb",
        side_effect=lambda value: value,
    ):
        store = PostgresReportStore("postgresql://test")
        created = store.create_report(
            report_config(),
            owner_id="owner-1",
            report_id="report-1",
        )

    insert_sql, params = next(
        (sql, params)
        for sql, params in connection.calls
        if "INSERT INTO reports" in sql
    )
    assert created.turnId is None
    assert params is not None
    assert set(params) == {
        "id",
        "title",
        "subtitle",
        "owner_id",
        "turn_id",
        "layout",
        "filters",
        "charts",
        "tables",
        "queries",
    }
    assert "datasets" not in insert_sql
    assert "artifact_type" not in insert_sql


def test_postgres_update_replaces_config_without_changing_owner() -> None:
    connection = _Connection()
    connection.next_row = _report_row(
        title="渠道销售修订",
        turn_id="turn-2",
    )

    with patch(
        "backend.persistence.postgres_stores._connect",
        side_effect=lambda *_args: _connection_context(connection),
    ), patch(
        "backend.persistence.postgres_stores._jsonb",
        side_effect=lambda value: value,
    ):
        store = PostgresReportStore("postgresql://test")
        updated = store.update_report(
            "report-1",
            report_config("渠道销售修订"),
            owner_id="owner-1",
            turn_id="turn-2",
        )

    update_sql, params = next(
        (sql, params)
        for sql, params in connection.calls
        if "UPDATE reports" in sql
    )
    set_clause = update_sql.partition("SET")[2].partition("WHERE")[0]
    assert updated is not None
    assert updated.title == "渠道销售修订"
    assert "owner_id =" not in set_clause
    assert "created_at =" not in set_clause
    assert params is not None
    assert params["turn_id"] == "turn-2"
    assert set(params) >= {
        "layout",
        "filters",
        "charts",
        "tables",
        "queries",
    }


def test_postgres_delete_physically_removes_report_and_cascades_shares() -> None:
    connection = _Connection()
    connection.next_row = {"id": "report-1"}

    with patch(
        "backend.persistence.postgres_stores._connect",
        side_effect=lambda *_args: _connection_context(connection),
    ):
        store = PostgresReportStore("postgresql://test")
        deleted = store.delete_report("report-1", owner_id="owner-1")

    delete_sql = next(
        sql
        for sql, _ in connection.calls
        if "DELETE FROM reports" in sql
    )
    assert deleted is True
    assert "owner_id = %(owner_id)s" in delete_sql
    assert not any(
        "DELETE FROM report_shares" in sql for sql, _ in connection.calls
    )
