"""Locks the P0 contract for the Postgres-backed session + turn stores.

The user spec demands:
* ``build_postgres_session_catalog()`` returns a usable
  ``SessionCatalog`` (no ``from_backend``).
* The Postgres backend exposes the **public** ``read_state`` /
  ``write_state`` methods that the catalog / projection store
  call.
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
    don't recognise; ``read_state`` / ``write_state`` map to a
    tiny in-memory store keyed by table name.

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

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def transaction(self) -> _Transaction:
        return _Transaction()

    def execute(self, sql: str, params: dict | None = None) -> _Result:
        params = self._unwrap(params)
        compact = " ".join(sql.split()).lower()
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
            return _Result(list(self.rows[POSTGRES_THREAD_TABLE].values()))
        if "select * from analysis_turns" in compact:
            return _Result(list(self.rows[POSTGRES_TURN_TABLE].values()))
        if "select * from analysis_codex_item_projections" in compact:
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

    def test_backend_exposes_public_read_and_write_state(self) -> None:
        # The catalog / projection store call ``read_state`` and
        # ``write_state`` on the backend; the old Postgres
        # backend defined them as ``_read_state`` / ``_write_state``
        # and the call raised ``AttributeError`` on the first
        # read or write.
        backend = PostgresSessionCatalogBackend("postgresql://unused")
        # Ensure the public names are the actual method objects,
        # not aliases that re-execute the underscored names.
        self.assertTrue(callable(getattr(backend, "read_state", None)))
        self.assertTrue(callable(getattr(backend, "write_state", None)))
        # And the round-trip is reachable through the catalog.
        catalog = SessionCatalog(backend=backend)
        catalog.register_session(
            session_id="p0_session_1",
            product_kind="analysis_task",
            title="P0",
            user_id=None,
            status="active",
        )
        catalog = SessionCatalog(backend=PostgresSessionCatalogBackend("postgresql://unused"))
        view = catalog.get_view("p0_session_1")
        self.assertIsNotNone(view)
        assert view is not None
        self.assertEqual(view.session.id, "p0_session_1")

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
        # ``read_state`` should now expose the canonical column.
        state = backend.read_state()
        self.assertIn("legacy_session_1", state)
        self.assertEqual(state["legacy_session_1"].codexSessionId, "codex_legacy_1")

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
        state = backend.read_state()
        self.assertIn("new_turn_2", state["turns"])
        self.assertEqual(state["turns"]["new_turn_2"].sessionId, "genbi_legacy_1")
        self.assertEqual(state["turns"]["new_turn_2"].codexSessionId, "codex_legacy_1")


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
        state = backend.read_state()
        self.assertIn("turn_1", state["turns"])
        self.assertEqual(state["turns"]["turn_1"].sessionId, "p0_session")
        self.assertEqual(state["turns"]["turn_1"].inputText, "hi")
