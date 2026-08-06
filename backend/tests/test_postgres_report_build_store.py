from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.persistence.postgres_stores import PostgresReportBuildStore
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
    def __init__(self, build_row: dict[str, Any]) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.build_row = dict(build_row)
        self.report_row: dict[str, Any] | None = None

    def execute(
        self,
        sql: str,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        self.calls.append((sql, params))
        compact = " ".join(sql.split())
        if compact.startswith("SELECT * FROM report_builds"):
            if params and params.get("id") == self.build_row["id"]:
                return _Result(row=dict(self.build_row))
            return _Result()
        if compact.startswith("UPDATE report_builds") and "RETURNING *" in compact:
            assert params is not None
            self.build_row.update(
                {
                    "status": params["status"],
                    "content": params["content"],
                    "validation_errors": params["validation_errors"],
                    "revision": params["revision"],
                    "published_report_id": params["published_report_id"],
                    "last_successful_step": params["last_successful_step"],
                    "step_attempts": params["step_attempts"],
                    "updated_at": params["updated_at"],
                    "expires_at": params["expires_at"],
                }
            )
            return _Result(row=dict(self.build_row), rowcount=1)
        if compact.startswith("INSERT INTO reports"):
            assert params is not None
            self.report_row = {
                "id": params["id"],
                "title": params["title"],
                "subtitle": params["subtitle"],
                "owner_id": params["owner_id"],
                "turn_id": params["turn_id"],
                "layout": params["layout"],
                "filters": params["filters"],
                "charts": params["charts"],
                "tables": params["tables"],
                "queries": params["queries"],
                "created_at": "2026-08-06T10:02:00+00:00",
                "updated_at": "2026-08-06T10:02:00+00:00",
            }
            return _Result(row=dict(self.report_row), rowcount=1)
        if compact.startswith("SELECT * FROM reports"):
            return _Result(
                row=dict(self.report_row) if self.report_row else None
            )
        return _Result()

    def transaction(self) -> _Transaction:
        return _Transaction()


@contextmanager
def _connection_context(connection: _Connection):
    yield connection


def _build_row() -> dict[str, Any]:
    return {
        "id": "build-1",
        "owner_id": "user-1",
        "session_id": "session-1",
        "turn_id": "turn-1",
        "target_report_id": None,
        "status": "building",
        "content": {
            "title": "渠道销售",
            "subtitle": "2026-08",
            "layout": {"content": [], "zones": {}},
            "filters": {},
            "queries": {},
            "charts": {},
            "tables": {},
        },
        "validation_errors": [],
        "revision": 4,
        "published_report_id": None,
        "last_successful_step": "start_report_build",
        "step_attempts": {},
        "created_at": "2026-08-06T10:00:00+00:00",
        "updated_at": "2026-08-06T10:01:00+00:00",
        "expires_at": "2026-08-13T10:00:00+00:00",
    }


def test_postgres_schema_creates_report_build_table_and_required_indexes() -> None:
    connection = _Connection(_build_row())
    with patch(
        "backend.persistence.postgres_stores._connect",
        side_effect=lambda *_args: _connection_context(connection),
    ):
        PostgresReportBuildStore("postgresql://test")

    sql = " ".join(
        "\n".join(statement for statement, _ in connection.calls).split()
    )
    assert "CREATE TABLE IF NOT EXISTS report_builds" in sql
    assert "PRIMARY KEY" in sql
    assert "(session_id, updated_at DESC)" in sql
    assert "(turn_id)" in sql
    assert "(owner_id, status, updated_at DESC)" in sql
    assert "(expires_at)" in sql
    assert "idx_report_builds_" not in sql


def test_postgres_mutation_locks_and_updates_only_one_build() -> None:
    connection = _Connection(_build_row())
    with patch(
        "backend.persistence.postgres_stores._connect",
        side_effect=lambda *_args: _connection_context(connection),
    ), patch(
        "backend.persistence.postgres_stores._jsonb",
        side_effect=lambda value: value,
    ):
        store = PostgresReportBuildStore("postgresql://test")
        connection.calls.clear()
        updated = store.mutate_build(
            "build-1",
            owner_id="user-1",
            mutation=lambda current: replace(
                current,
                revision=current.revision + 1,
                content={
                    **current.content,
                    "charts": {"chart-1": {}},
                },
            ),
        )

    sql = " ".join(
        "\n".join(statement for statement, _ in connection.calls).split()
    )
    assert updated is not None
    assert updated.revision == 5
    assert "WHERE id = %(id)s AND owner_id = %(owner_id)s FOR UPDATE" in sql
    assert "UPDATE report_builds" in sql
    assert "WHERE id = %(id)s AND owner_id = %(owner_id)s" in sql
    assert "SELECT * FROM report_builds;" not in sql


def test_postgres_publish_is_atomic_and_idempotent() -> None:
    connection = _Connection(_build_row())
    with patch(
        "backend.persistence.postgres_stores._connect",
        side_effect=lambda *_args: _connection_context(connection),
    ), patch(
        "backend.persistence.postgres_stores._jsonb",
        side_effect=lambda value: value,
    ):
        store = PostgresReportBuildStore("postgresql://test")
        connection.calls.clear()
        first = store.publish_build(
            "build-1",
            owner_id="user-1",
            turn_id="turn-1",
        )
        second = store.publish_build(
            "build-1",
            owner_id="user-1",
            turn_id="turn-1",
        )

    assert first is not None and second is not None
    assert first[1].id == second[1].id
    inserts = [
        sql for sql, _ in connection.calls if "INSERT INTO reports" in sql
    ]
    assert len(inserts) == 1
    assert sum(
        1
        for sql, _ in connection.calls
        if "SELECT * FROM report_builds" in sql and "FOR UPDATE" in sql
    ) == 2
