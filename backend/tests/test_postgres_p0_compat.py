"""Locks the P0 contract for the Postgres-backed session + turn stores.

The user spec demands:
* ``build_postgres_session_catalog()`` returns a usable
  ``SessionCatalog`` (no ``from_backend``).
* The Postgres-backed catalog / projection store use row-level
  CRUD methods instead of whole-table ``read_state`` /
  ``write_state`` snapshots.
* Old rows persisted under ``codex_thread_id`` /
  ``thread_id`` / ``genbi_thread_id`` survive the migration
  intact and the new read path returns the canonical
  ``session_id`` / ``codex_session_id`` values.

We use a fake ``psycopg`` connection to drive the full
ensure_schema + backfill + write/read sequence without
needing a live Postgres server; the integration is exercised
in CI by running the same SQL against the docker-compose
Postgres container separately.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.session_catalog import SessionCatalog
from backend.harness.codex_projection_store import CodexProjectionStore
from backend.persistence import postgres_stores
from backend.persistence.postgres_stores import (
    PostgresCodexProjectionBackend,
    PostgresSessionCatalogBackend,
    build_postgres_codex_projection_store,
    build_postgres_session_catalog,
    POSTGRES_TURN_TABLE,
    POSTGRES_CODEX_ITEM_PROJECTION_TABLE,
    POSTGRES_THREAD_TABLE,
)


class _Result:
    def __init__(self, rows: list[dict] | None = None, rowcount: int = 0) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> dict | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict]:
        return self._rows


class _Transaction:
    def __enter__(self) -> "_Transaction":
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeConnection:
    """Fake psycopg connection that pretends to be a PostgreSQL
    server. ``ensure_schema`` is a no-op for any statement we
    don't recognise; row-level SQL maps to a tiny in-memory store
    keyed by table name.

    The fake supports enough of the surface to:
    * Round-trip sessions and turns through the catalog /
      projection store.
    * Survive the backfill of legacy ``codex_thread_id`` /
      ``thread_id`` / ``genbi_thread_id`` columns.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, dict]] = {
            POSTGRES_THREAD_TABLE: {},
            POSTGRES_TURN_TABLE: {},
            POSTGRES_CODEX_ITEM_PROJECTION_TABLE: {},
        }
        # Mirror the legacy columns that the real DB has today;
        # we let ``ensure_schema`` ALTER/INSERT backfill them.
        self.legacy_thread_id: dict[str, str] = {}
        self.legacy_codex_thread_id: dict[str, str] = {}
        self.legacy_genbi_thread_id: dict[str, str] = {}
        self.sql_log: list[str] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction()

    def execute(self, sql: str, params: dict | None = None) -> _Result:
        params = self._unwrap(params)
        compact = " ".join(sql.split()).lower()
        self.sql_log.append(compact)
        if "from information_schema.columns" in compact:
            assert params is not None
            table = str(params["table_name"])
            column = str(params["column_name"])
            legacy_columns = {
                POSTGRES_THREAD_TABLE: {"codex_thread_id"},
                POSTGRES_TURN_TABLE: {"thread_id", "codex_thread_id"},
                POSTGRES_CODEX_ITEM_PROJECTION_TABLE: {"codex_thread_id", "genbi_thread_id"},
            }
            return _Result([{"exists": column in legacy_columns.get(table, set())}])
        if compact.startswith("create ") or compact.startswith("create index"):
            return _Result()
        if compact.startswith("alter table"):
            return _Result()
        if compact.startswith("update "):
            if compact.startswith("update analysis_threads") and params and "id" in params:
                row = self.rows[POSTGRES_THREAD_TABLE].get(str(params["id"]))
                if row is not None:
                    if "set status = 'archived'" in compact:
                        row["status"] = "archived"
                    if "updated_at" in params:
                        row["updated_at"] = params["updated_at"]
                return _Result(rowcount=1 if row is not None else 0)
            return _Result(rowcount=1)
        if "insert into analysis_threads" in compact:
            assert params is not None
            self.rows[POSTGRES_THREAD_TABLE][str(params["id"])] = dict(params)
            return _Result(rowcount=1)
        if "insert into analysis_turns" in compact:
            assert params is not None
            self.rows[POSTGRES_TURN_TABLE][str(params["id"])] = dict(params)
            return _Result(rowcount=1)
        if "insert into analysis_codex_item_projections" in compact:
            assert params is not None
            self.rows[POSTGRES_CODEX_ITEM_PROJECTION_TABLE][str(params["codex_item_id"])] = dict(params)
            return _Result(rowcount=1)
        if "select * from analysis_threads" in compact:
            if " where id =" in compact and params and "id" in params:
                row = self.rows[POSTGRES_THREAD_TABLE].get(str(params["id"]))
                return _Result([row] if row else [])
            return _Result(list(self.rows[POSTGRES_THREAD_TABLE].values()))
        if "select id from analysis_threads" in compact:
            assert params is not None
            raw_id = str(params["id"])
            direct = self.rows[POSTGRES_THREAD_TABLE].get(raw_id)
            if direct:
                return _Result([{"id": direct["id"]}])
            for row in self.rows[POSTGRES_THREAD_TABLE].values():
                if row.get("codex_session_id") == raw_id or row.get("codex_thread_id") == raw_id:
                    return _Result([{"id": row["id"]}])
            return _Result()
        if "select * from analysis_turns" in compact:
            if " where id =" in compact and params and "id" in params:
                row = self.rows[POSTGRES_TURN_TABLE].get(str(params["id"]))
                if "session_id" not in params:
                    return _Result([row] if row else [])
                if row and row.get("session_id") == params.get("session_id"):
                    return _Result([row])
                return _Result()
            if " where session_id =" in compact and params and "session_id" in params:
                rows = [
                    row for row in self.rows[POSTGRES_TURN_TABLE].values()
                    if row.get("session_id") == params["session_id"]
                ]
                return _Result(rows)
            return _Result(list(self.rows[POSTGRES_TURN_TABLE].values()))
        if "select * from analysis_codex_item_projections" in compact:
            if " where codex_item_id =" in compact and params and "codex_item_id" in params:
                row = self.rows[POSTGRES_CODEX_ITEM_PROJECTION_TABLE].get(str(params["codex_item_id"]))
                return _Result([row] if row else [])
            if " where genbi_session_id =" in compact and params and "session_id" in params:
                rows = [
                    row for row in self.rows[POSTGRES_CODEX_ITEM_PROJECTION_TABLE].values()
                    if row.get("genbi_session_id") == params["session_id"]
                    and ("turn_id" not in params or row.get("genbi_turn_id") == params["turn_id"])
                ]
                rows.sort(key=lambda row: (row.get("sequence", 0), row.get("created_at") or "", row.get("codex_item_id") or ""))
                return _Result(rows)
            return _Result(list(self.rows[POSTGRES_CODEX_ITEM_PROJECTION_TABLE].values()))
        return _Result()

    def _unwrap(self, params: dict | None) -> dict | None:
        if params is None:
            return None
        return {key: _unwrap_jsonb(value) for key, value in params.items()}


def _unwrap_jsonb(value: Any) -> Any:
    return getattr(value, "obj", value)


class _FakeBuilder:
    """Wraps ``_FakeConnection`` so the same connection is
    handed back on every ``_connect`` call (the real code
    connects on each method)."""

    def __init__(self) -> None:
        self.conn = _FakeConnection()

    def __call__(self, _url: str) -> _FakeConnection:
        return self.conn


class PostgresSessionCatalogP0Test(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = _FakeBuilder()
        # The builders read ``GENBI_DATABASE_URL`` /
        # ``AUTH_DATABASE_URL``; provide a stub so they spin
        # up our fake backend without touching the env.
        self.env_patches = [
            patch.object(postgres_stores, "get_postgres_database_url", return_value="postgresql://stub"),
            patch.object(postgres_stores, "_connect", self.builder),
            patch.object(postgres_stores, "_jsonb", side_effect=lambda value: value),
        ]
        for ctx in self.env_patches:
            ctx.start()

    def tearDown(self) -> None:
        for ctx in self.env_patches:
            ctx.stop()

    def test_build_postgres_session_catalog_uses_public_constructor(self) -> None:
        # ``build_postgres_session_catalog`` previously called
        # ``SessionCatalog.from_backend(backend)`` which does not
        # exist. The fix routes through the real constructor.
        catalog = build_postgres_session_catalog()
        self.assertIsInstance(catalog, SessionCatalog)
        self.assertIsInstance(catalog.backend, PostgresSessionCatalogBackend)

    def test_catalog_uses_row_level_session_crud(self) -> None:
        # Postgres-backed catalogs must not fall back to whole-table
        # snapshot reads/writes. Session creation, lookup, alias
        # resolution, and touch are row-level operations.
        backend = PostgresSessionCatalogBackend("postgresql://unused")
        self.assertTrue(callable(getattr(backend, "get_session", None)))
        self.assertTrue(callable(getattr(backend, "insert_session", None)))
        self.assertTrue(callable(getattr(backend, "update_session", None)))
        self.assertTrue(callable(getattr(backend, "touch_session", None)))
        self.assertFalse(callable(getattr(backend, "read_state", None)))
        self.assertFalse(callable(getattr(backend, "write_state", None)))
        catalog = SessionCatalog(backend=backend)
        catalog.register_session(
            session_id="p0_session_1",
            product_kind="analysis_task",
            title="P0",
            user_id=None,
            status="active",
        )
        catalog.mark_updated("p0_session_1", when="2026-08-02T00:00:00+00:00")
        view = catalog.get_view("p0_session_1")
        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view.session.id, "p0_session_1")
        self.assertEqual(view.session.updatedAt, "2026-08-02T00:00:00+00:00")

    def test_legacy_codex_thread_id_is_backfilled_into_codex_session_id(self) -> None:
        # Old ``analysis_threads`` rows persisted under
        # ``codex_thread_id`` only; the migration must mirror
        # the value into ``codex_session_id`` so the new read
        # path (which selects ``codex_session_id`` first) keeps
        # working.
        backend = PostgresSessionCatalogBackend("postgresql://unused")
        # Inject a legacy row directly, mimicking what
        # ``ensure_schema`` would see on a real production DB
        # before the migration ran.
        conn = self.builder.conn
        conn.rows[POSTGRES_THREAD_TABLE]["legacy_session_1"] = {
            "id": "legacy_session_1",
            "product_kind": "analysis_task",
            "title": None,
            "tenant_id": None,
            "user_id": None,
            "workspace_id": None,
            "codex_session_id": None,
            "codex_thread_id": "codex_legacy_1",
            "status": "active",
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
            "metadata": {},
        }
        # The first call to ensure_schema backfills the row.
        backend.ensure_schema()  # type: ignore[no-untyped-call]
        # Row-level alias resolution should expose the canonical
        # session row without scanning every session.
        self.assertEqual(backend.resolve_session_id("codex_legacy_1"), "legacy_session_1")
        record = backend.get_session("legacy_session_1")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.codexSessionId, "codex_legacy_1")

    def test_touching_different_sessions_preserves_both_updated_at_values(self) -> None:
        catalog = SessionCatalog(backend=PostgresSessionCatalogBackend("postgresql://unused"))
        for session_id in ("session_a", "session_b"):
            catalog.register_session(
                session_id=session_id,
                product_kind="analysis_task",
                title=session_id,
                user_id=None,
                status="active",
            )
        catalog.mark_updated("session_a", when="2026-08-01T00:00:01+00:00")
        catalog.mark_updated("session_b", when="2026-08-01T00:00:02+00:00")
        session_a = catalog.get_session("session_a")
        session_b = catalog.get_session("session_b")
        self.assertIsNotNone(session_a)
        self.assertIsNotNone(session_b)
        assert session_a is not None and session_b is not None
        self.assertEqual(session_a.updatedAt, "2026-08-01T00:00:01+00:00")
        self.assertEqual(session_b.updatedAt, "2026-08-01T00:00:02+00:00")

    def test_legacy_thread_id_is_backfilled_into_session_id(self) -> None:
        # Old ``analysis_turns`` rows persisted under
        # ``thread_id`` (NOT NULL, FK to analysis_threads.id);
        # the migration must add ``session_id`` and mirror the
        # value so new INSERTs do not blow up on the missing
        # column or write nulls.
        backend = PostgresCodexProjectionBackend("postgresql://unused")
        conn = self.builder.conn
        conn.rows[POSTGRES_TURN_TABLE]["legacy_turn_1"] = {
            "id": "legacy_turn_1",
            "session_id": None,
            "thread_id": "genbi_legacy_1",
            "input_kind": "message",
            "question": "q",
            "input_text": "q",
            "status": "completed",
            "created_at": "2026-08-01T00:00:00+00:00",
            "updated_at": "2026-08-01T00:00:00+00:00",
            "started_at": None,
            "completed_at": "2026-08-01T00:00:00+00:00",
            "codex_session_id": None,
            "codex_thread_id": "codex_legacy_1",
            "codex_turn_id": "legacy_turn_1",
            "metadata": {},
        }
        backend.ensure_schema()  # type: ignore[no-untyped-call]
        # Now the new write path must work end-to-end: a fresh
        # turn row written by ``CodexProjectionStore.save_turn``
        # must land under the canonical column.
        store = CodexProjectionStore(backend=backend)
        store.save_turn(
            session_id="genbi_legacy_1",
            turn_id="new_turn_2",
            input_kind="message",
            input_text="q",
            status="running",
            codex_session_id="codex_legacy_1",
            codex_turn_id="new_turn_2",
        )
        turn = backend.get_turn("genbi_legacy_1", "new_turn_2")
        self.assertIsNotNone(turn)
        assert turn is not None
        self.assertEqual(turn.sessionId, "genbi_legacy_1")
        self.assertEqual(turn.codexSessionId, "codex_legacy_1")


class PostgresCodexProjectionP0Test(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = _FakeBuilder()
        self.env_patches = [
            patch.object(postgres_stores, "get_postgres_database_url", return_value="postgresql://stub"),
            patch.object(postgres_stores, "_connect", self.builder),
            patch.object(postgres_stores, "_jsonb", side_effect=lambda value: value),
        ]
        for ctx in self.env_patches:
            ctx.start()

    def tearDown(self) -> None:
        for ctx in self.env_patches:
            ctx.stop()

    def test_build_postgres_codex_projection_store_uses_public_constructor(self) -> None:
        store = build_postgres_codex_projection_store()
        self.assertIsInstance(store, CodexProjectionStore)
        self.assertIsInstance(store.backend, PostgresCodexProjectionBackend)
        self.assertFalse(callable(getattr(store.backend, "read_state", None)))
        self.assertFalse(callable(getattr(store.backend, "write_state", None)))

    def test_round_trip_turns_and_projections(self) -> None:
        backend = PostgresCodexProjectionBackend("postgresql://unused")
        store = CodexProjectionStore(backend=backend)
        store.save_turn(
            session_id="p0_session",
            turn_id="turn_1",
            input_kind="message",
            input_text="hi",
            status="running",
            codex_session_id="p0_session",
            codex_turn_id="turn_1",
        )
        turn = backend.get_turn("p0_session", "turn_1")
        self.assertIsNotNone(turn)
        assert turn is not None
        self.assertEqual(turn.sessionId, "p0_session")
        self.assertEqual(turn.inputText, "hi")

    def test_projection_store_uses_row_level_turn_and_item_writes(self) -> None:
        backend = PostgresCodexProjectionBackend("postgresql://unused")
        store = CodexProjectionStore(backend=backend)
        store.save_turn(
            session_id="session_a",
            turn_id="turn_a",
            input_kind="message",
            input_text="a",
            status="running",
            codex_session_id="session_a",
            codex_turn_id="turn_a",
        )
        self.builder.conn.sql_log.clear()
        store.upsert_item(
            session_id="session_a",
            turn_id="turn_a",
            codex_item_id="item_a",
            item_type="message",
            status="completed",
            sequence=7,
            payload={"text": "a"},
            created_at="2026-08-01T00:00:00+00:00",
            completed_at="2026-08-01T00:00:01+00:00",
            codex_session_id="session_a",
            codex_turn_id="turn_a",
        )
        full_scans = [
            sql for sql in self.builder.conn.sql_log
            if sql == "select * from analysis_turns"
            or sql == "select * from analysis_codex_item_projections"
        ]
        item_upserts = [
            sql for sql in self.builder.conn.sql_log
            if "insert into analysis_codex_item_projections" in sql
        ]
        self.assertEqual(full_scans, [])
        self.assertEqual(len(item_upserts), 1)
        self.assertFalse(any("where genbi_session_id =" in sql for sql in self.builder.conn.sql_log))

    def test_turn_id_collision_cannot_update_another_session_turn(self) -> None:
        backend = PostgresCodexProjectionBackend("postgresql://unused")
        store = CodexProjectionStore(backend=backend)
        store.save_turn(
            session_id="session_a",
            turn_id="turn_shared",
            input_kind="message",
            input_text="a",
            status="running",
            codex_session_id="session_a",
            codex_turn_id="turn_shared",
        )

        with self.assertRaises(ValueError):
            store.save_turn(
                session_id="session_b",
                turn_id="turn_shared",
                input_kind="message",
                input_text="b",
                status="failed",
                codex_session_id="session_b",
                codex_turn_id="turn_shared",
            )

        self.assertEqual(store.get_turn("session_a", "turn_shared").inputText, "a")
        self.assertIsNone(store.get_turn("session_b", "turn_shared"))

    def test_item_id_collision_cannot_move_item_to_another_session(self) -> None:
        backend = PostgresCodexProjectionBackend("postgresql://unused")
        store = CodexProjectionStore(backend=backend)
        for session_id, turn_id in (("session_a", "turn_a"), ("session_b", "turn_b")):
            store.save_turn(
                session_id=session_id,
                turn_id=turn_id,
                input_kind="message",
                input_text=session_id,
                status="running",
                codex_session_id=session_id,
                codex_turn_id=turn_id,
            )
        store.upsert_item(
            session_id="session_a",
            turn_id="turn_a",
            codex_item_id="item_shared",
            item_type="message",
            status="completed",
            sequence=1,
            payload={"text": "a"},
            created_at="2026-08-01T00:00:00+00:00",
            completed_at="2026-08-01T00:00:01+00:00",
            codex_session_id="session_a",
            codex_turn_id="turn_a",
        )

        with self.assertRaises(ValueError):
            store.upsert_item(
                session_id="session_b",
                turn_id="turn_b",
                codex_item_id="item_shared",
                item_type="message",
                status="completed",
                sequence=2,
                payload={"text": "b"},
                created_at="2026-08-01T00:00:02+00:00",
                completed_at="2026-08-01T00:00:03+00:00",
                codex_session_id="session_b",
                codex_turn_id="turn_b",
            )

        self.assertEqual(store.list_items(session_id="session_b", turn_id="turn_b"), [])
        self.assertEqual(
            store.list_items(session_id="session_a", turn_id="turn_a")[0].payload,
            {"text": "a"},
        )

    def test_cross_session_row_writes_do_not_overwrite_each_other(self) -> None:
        backend = PostgresCodexProjectionBackend("postgresql://unused")
        store = CodexProjectionStore(backend=backend)
        for session_id, turn_id in (("session_a", "turn_a"), ("session_b", "turn_b")):
            store.save_turn(
                session_id=session_id,
                turn_id=turn_id,
                input_kind="message",
                input_text=session_id,
                status="running",
                codex_session_id=session_id,
                codex_turn_id=turn_id,
            )
        store.complete_turn(
            session_id="session_a",
            turn_id="turn_a",
            status="completed",
            completed_at="2026-08-01T00:01:00+00:00",
        )
        store.save_turn(
            session_id="session_b",
            turn_id="turn_b2",
            input_kind="message",
            input_text="b2",
            status="running",
            codex_session_id="session_b",
            codex_turn_id="turn_b2",
        )
        self.assertEqual(store.get_turn("session_a", "turn_a").status, "completed")
        self.assertEqual(store.get_turn("session_b", "turn_b").status, "running")
        self.assertEqual(store.get_turn("session_b", "turn_b2").status, "running")
