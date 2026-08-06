from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from backend.harness.codex_projection_store import (
    CodexItemProjectionRecord,
    CodexProjectionStore,
    TurnRecord,
)
from backend.harness.session_catalog import SessionCatalog, SessionRecord, SessionView
from backend.analysis.asset_store import (
    AnalysisAssetRecord,
    AnalysisAssetReopenContext,
    AnalysisAssetStore,
    ArtifactLineageRecord,
    _codex_lineage,
    _optional_text,
    _require_text,
    _validate_reopen_context,
)
from backend.reports.models import (
    ReportRecord,
    ReportShareRecord,
    report_to_payload,
    share_to_payload,
)
from backend.reports.build_models import (
    ReportBuildRecord,
)
from backend.reports.schema import report_config_payload
from backend.business_semantics.knowledge_store import KnowledgeRecord, KnowledgeStore


POSTGRES_KNOWLEDGE_TABLE = "verified_knowledge"
POSTGRES_THREAD_TABLE = "analysis_threads"
POSTGRES_TURN_TABLE = "analysis_turns"
POSTGRES_CODEX_ITEM_PROJECTION_TABLE = "analysis_codex_item_projections"
POSTGRES_ANALYSIS_ASSET_TABLE = "analysis_assets"
POSTGRES_ARTIFACT_LINEAGE_TABLE = "analysis_artifact_lineage"
POSTGRES_REPORT_TABLE = "reports"
POSTGRES_REPORT_SHARE_TABLE = "report_shares"
POSTGRES_REPORT_BUILD_TABLE = "report_builds"


def postgres_persistence_enabled() -> bool:
    mode = os.getenv("GENBI_PERSISTENCE", "").strip().lower()
    if mode:
        return mode in {"postgres", "postgresql", "db", "database"}
    return bool(get_postgres_database_url())


def get_postgres_database_url() -> str | None:
    raw = os.getenv("GENBI_DATABASE_URL") or os.getenv("AUTH_DATABASE_URL")
    if not raw:
        return None
    return _normalize_postgres_url(raw.strip())


def build_postgres_stores() -> "PostgresKnowledgeStore":
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres persistence.")
    return PostgresKnowledgeStore(database_url)

def build_postgres_session_catalog() -> SessionCatalog:
    """Build the Postgres-backed :class:`SessionCatalog`.

    Returns an in-memory :class:`SessionCatalog` (the JSONL file
    implementation) wrapped with the same API. The store is the
    thin owner of ``analysis_threads``; it never sees Codex item
    payloads or turn execution.
    """
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres SessionCatalog persistence.")
    backend = PostgresSessionCatalogBackend(database_url)
    return SessionCatalog(backend=backend)


def build_postgres_codex_projection_store() -> CodexProjectionStore:
    """Build the Postgres-backed :class:`CodexProjectionStore`.

    Owns ``analysis_turns`` + ``analysis_codex_item_projections``
    and never sees session-level state.
    """
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres CodexProjectionStore persistence.")
    backend = PostgresCodexProjectionBackend(database_url)
    return CodexProjectionStore(backend=backend)


def build_postgres_report_store() -> "PostgresReportStore":
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres report persistence.")
    return PostgresReportStore(database_url)


def build_postgres_report_build_store() -> "PostgresReportBuildStore":
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError(
            "GENBI_DATABASE_URL or AUTH_DATABASE_URL is required "
            "for Postgres ReportBuild persistence."
        )
    return PostgresReportBuildStore(database_url)


def build_postgres_analysis_asset_store() -> "PostgresAnalysisAssetStore":
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres analysis asset persistence.")
    return PostgresAnalysisAssetStore(database_url)


class PostgresSessionCatalogBackend:
    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_THREAD_TABLE} (
                    id TEXT PRIMARY KEY,
                    product_kind TEXT NOT NULL,
                    title TEXT,
                    tenant_id TEXT,
                    user_id TEXT,
                    workspace_id TEXT,
                    codex_session_id TEXT,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )
                """
            )
            conn.execute(f"ALTER TABLE {POSTGRES_THREAD_TABLE} ADD COLUMN IF NOT EXISTS tenant_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_THREAD_TABLE} ADD COLUMN IF NOT EXISTS workspace_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_THREAD_TABLE} ADD COLUMN IF NOT EXISTS codex_session_id TEXT")
            # Backfill the new canonical column from the legacy
            # ``codex_thread_id`` column. Idempotent: only fires
            # on rows where the new column is still null. The
            # ``id == codex_session_id`` invariant does not hold
            # for legacy rows (one row may carry a GenBI id AND
            # a Codex-issued id); the read path tolerates that.
            if _column_exists(conn, POSTGRES_THREAD_TABLE, "codex_thread_id"):
                conn.execute(
                    f"""
                    UPDATE {POSTGRES_THREAD_TABLE}
                    SET codex_session_id = codex_thread_id
                    WHERE codex_session_id IS NULL AND codex_thread_id IS NOT NULL
                    """
                )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_updated ON {POSTGRES_THREAD_TABLE} (updated_at DESC NULLS LAST)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_product ON {POSTGRES_THREAD_TABLE} (product_kind)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_codex ON {POSTGRES_THREAD_TABLE} (codex_session_id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_tenant_user ON {POSTGRES_THREAD_TABLE} (tenant_id, user_id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_tenant_user_updated ON {POSTGRES_THREAD_TABLE} (tenant_id, user_id, updated_at DESC)")

    def get_session(self, session_id: str) -> SessionRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"SELECT * FROM {POSTGRES_THREAD_TABLE} WHERE id = %(id)s",
                {"id": session_id},
            ).fetchone()
        return _session_record_from_row(row) if row else None

    def resolve_session_id(self, raw_id: str) -> str | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                SELECT id FROM {POSTGRES_THREAD_TABLE}
                WHERE id = %(id)s OR codex_session_id = %(id)s
                ORDER BY CASE WHEN id = %(id)s THEN 0 ELSE 1 END, updated_at DESC NULLS LAST
                LIMIT 1
                """,
                {"id": raw_id},
            ).fetchone()
        return str(row["id"]) if row else None

    def list_sessions(
        self,
        *,
        limit: int = 50,
        product_kind: str | None = None,
    ) -> list[SessionRecord]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if product_kind:
            clauses.append("product_kind = %(product_kind)s")
            params["product_kind"] = product_kind
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_THREAD_TABLE}
                {where}
                ORDER BY updated_at DESC NULLS LAST
                LIMIT %(limit)s
                """,
                params,
            ).fetchall()
        return [_session_record_from_row(row) for row in rows]

    def insert_session(self, record: SessionRecord) -> None:
        self._upsert_session(record)

    def update_session(self, record: SessionRecord) -> None:
        self._upsert_session(record)

    def archive_session(self, session_id: str, *, updated_at: str) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                UPDATE {POSTGRES_THREAD_TABLE}
                SET status = 'archived', updated_at = %(updated_at)s
                WHERE id = %(id)s
                """,
                {"id": session_id, "updated_at": updated_at},
            )

    def touch_session(self, session_id: str, updated_at: str) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"UPDATE {POSTGRES_THREAD_TABLE} SET updated_at = %(updated_at)s WHERE id = %(id)s",
                {"id": session_id, "updated_at": updated_at},
            )

    def delete_session(self, session_id: str) -> bool:
        with _connect(self.database_url) as conn:
            return bool(conn.execute(f"DELETE FROM {POSTGRES_THREAD_TABLE} WHERE id = %(id)s", {"id": session_id}).rowcount)

    def _upsert_session(self, record: SessionRecord) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                INSERT INTO {POSTGRES_THREAD_TABLE} (
                    id, product_kind, title, tenant_id, user_id, workspace_id, codex_session_id,
                    status, created_at, updated_at, metadata
                )
                VALUES (
                    %(id)s, %(product_kind)s, %(title)s, %(tenant_id)s, %(user_id)s, %(workspace_id)s,
                    %(codex_session_id)s, %(status)s, %(created_at)s, %(updated_at)s, %(metadata)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    product_kind = EXCLUDED.product_kind,
                    title = EXCLUDED.title,
                    tenant_id = EXCLUDED.tenant_id,
                    user_id = EXCLUDED.user_id,
                    workspace_id = EXCLUDED.workspace_id,
                    codex_session_id = EXCLUDED.codex_session_id,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
                """,
                _session_params(record),
            )

    def clear(self) -> int:
        with _connect(self.database_url) as conn:
            return conn.execute(f"DELETE FROM {POSTGRES_THREAD_TABLE}").rowcount or 0


class PostgresCodexProjectionBackend:
    """Postgres-backed implementation of the Codex projection store.

    Owns ``analysis_turns`` + ``analysis_codex_item_projections``.
    The catalog owns sessions; this backend never sees
    ``analysis_threads`` rows.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self._has_legacy_turn_thread_id = False
        self._has_legacy_turn_codex_thread_id = False
        self._has_legacy_item_codex_thread_id = False
        self._has_legacy_item_genbi_thread_id = False
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_TURN_TABLE} (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    input_kind TEXT NOT NULL,
                    question TEXT NOT NULL,
                    input_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    codex_session_id TEXT,
                    codex_turn_id TEXT,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )
                """
            )
            # Legacy schema: ``analysis_turns.thread_id`` (NOT NULL,
            # FK to ``analysis_threads.id``) and no ``session_id``
            # column at all. We add the canonical column and
            # backfill it from the legacy one so the new code
            # path (which writes ``session_id``) keeps working on
            # existing databases without losing data.
            conn.execute(f"ALTER TABLE {POSTGRES_TURN_TABLE} ADD COLUMN IF NOT EXISTS session_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_TURN_TABLE} ADD COLUMN IF NOT EXISTS codex_session_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_TURN_TABLE} ADD COLUMN IF NOT EXISTS codex_turn_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_TURN_TABLE} ADD COLUMN IF NOT EXISTS input_text TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_TURN_TABLE} ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ")
            conn.execute(f"ALTER TABLE {POSTGRES_TURN_TABLE} ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ")
            has_legacy_turn_thread_id = _column_exists(conn, POSTGRES_TURN_TABLE, "thread_id")
            has_legacy_turn_codex_thread_id = _column_exists(conn, POSTGRES_TURN_TABLE, "codex_thread_id")
            self._has_legacy_turn_thread_id = has_legacy_turn_thread_id
            self._has_legacy_turn_codex_thread_id = has_legacy_turn_codex_thread_id
            if has_legacy_turn_thread_id:
                conn.execute(
                    f"""
                    UPDATE {POSTGRES_TURN_TABLE}
                    SET session_id = thread_id
                    WHERE session_id IS NULL AND thread_id IS NOT NULL
                    """
                )
            if has_legacy_turn_codex_thread_id:
                conn.execute(
                    f"""
                    UPDATE {POSTGRES_TURN_TABLE}
                    SET codex_session_id = codex_thread_id
                    WHERE codex_session_id IS NULL AND codex_thread_id IS NOT NULL
                    """
                )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (
                    codex_item_id TEXT PRIMARY KEY,
                    codex_session_id TEXT,
                    codex_turn_id TEXT,
                    item_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sequence INTEGER NOT NULL DEFAULT 0,
                    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    genbi_session_id TEXT,
                    genbi_turn_id TEXT
                )
                """
            )
            conn.execute(f"ALTER TABLE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} ADD COLUMN IF NOT EXISTS codex_session_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} ADD COLUMN IF NOT EXISTS codex_turn_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} ADD COLUMN IF NOT EXISTS genbi_session_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} ADD COLUMN IF NOT EXISTS genbi_turn_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} ADD COLUMN IF NOT EXISTS sequence INTEGER NOT NULL DEFAULT 0")
            # Backfill canonical columns from the legacy aliases.
            # Idempotent.
            has_legacy_item_codex_thread_id = _column_exists(conn, POSTGRES_CODEX_ITEM_PROJECTION_TABLE, "codex_thread_id")
            self._has_legacy_item_codex_thread_id = has_legacy_item_codex_thread_id
            if has_legacy_item_codex_thread_id:
                conn.execute(
                    f"""
                    UPDATE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}
                    SET codex_session_id = codex_thread_id
                    WHERE codex_session_id IS NULL AND codex_thread_id IS NOT NULL
                    """
                )
            has_legacy_item_genbi_thread_id = _column_exists(conn, POSTGRES_CODEX_ITEM_PROJECTION_TABLE, "genbi_thread_id")
            self._has_legacy_item_genbi_thread_id = has_legacy_item_genbi_thread_id
            if has_legacy_item_genbi_thread_id:
                conn.execute(
                    f"""
                    UPDATE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}
                    SET genbi_session_id = genbi_thread_id
                    WHERE genbi_session_id IS NULL AND genbi_thread_id IS NOT NULL
                    """
                )
            conn.execute(
                f"""
                UPDATE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}
                SET genbi_turn_id = codex_turn_id
                WHERE genbi_turn_id IS NULL AND codex_turn_id IS NOT NULL
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_TURN_TABLE}_session ON {POSTGRES_TURN_TABLE} (session_id, created_at)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_TURN_TABLE}_session_updated ON {POSTGRES_TURN_TABLE} (session_id, updated_at DESC)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_TURN_TABLE}_codex ON {POSTGRES_TURN_TABLE} (codex_session_id, codex_turn_id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_CODEX_ITEM_PROJECTION_TABLE}_session ON {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (genbi_session_id, created_at)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_CODEX_ITEM_PROJECTION_TABLE}_session_turn_sequence ON {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (genbi_session_id, genbi_turn_id, sequence)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_CODEX_ITEM_PROJECTION_TABLE}_turn ON {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (codex_session_id, codex_turn_id)")

    def get_turn(self, session_id: str, turn_id: str) -> TurnRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_TURN_TABLE}
                WHERE id = %(id)s AND session_id = %(session_id)s
                """,
                {"id": turn_id, "session_id": session_id},
            ).fetchone()
        return _turn_record_from_row(row) if row else None

    def get_turn_by_id(self, turn_id: str) -> TurnRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"SELECT * FROM {POSTGRES_TURN_TABLE} WHERE id = %(id)s",
                {"id": turn_id},
            ).fetchone()
        return _turn_record_from_row(row) if row else None

    def list_turns(self, session_id: str) -> list[TurnRecord]:
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_TURN_TABLE}
                WHERE session_id = %(session_id)s
                ORDER BY created_at ASC NULLS LAST, id ASC
                """,
                {"session_id": session_id},
            ).fetchall()
        return [_turn_record_from_row(row) for row in rows]

    def latest_turn(self, session_id: str) -> TurnRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_TURN_TABLE}
                WHERE session_id = %(session_id)s
                ORDER BY updated_at DESC NULLS LAST, created_at DESC NULLS LAST, id DESC
                LIMIT 1
                """,
                {"session_id": session_id},
            ).fetchone()
        return _turn_record_from_row(row) if row else None

    def upsert_turn(self, record: TurnRecord) -> None:
        with _connect(self.database_url) as conn:
            self._upsert_turn(conn, record)

    def upsert_item(self, record: CodexItemProjectionRecord) -> None:
        with _connect(self.database_url) as conn:
            self._upsert_item(conn, record)

    def get_item(self, codex_item_id: str) -> CodexItemProjectionRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}
                WHERE codex_item_id = %(codex_item_id)s
                """,
                {"codex_item_id": codex_item_id},
            ).fetchone()
        return _codex_item_projection_from_row(row) if row else None

    def list_items(
        self,
        session_id: str,
        turn_id: str | None = None,
    ) -> list[CodexItemProjectionRecord]:
        clauses = ["genbi_session_id = %(session_id)s"]
        params: dict[str, Any] = {"session_id": session_id}
        if turn_id is not None:
            clauses.append("genbi_turn_id = %(turn_id)s")
            params["turn_id"] = turn_id
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}
                WHERE {' AND '.join(clauses)}
                ORDER BY sequence ASC, created_at ASC NULLS LAST, codex_item_id ASC
                """,
                params,
            ).fetchall()
        return [_codex_item_projection_from_row(row) for row in rows]

    def _upsert_turn(self, conn: Any, turn: TurnRecord) -> None:
        params = _turn_params(turn)
        legacy_columns: list[str] = []
        legacy_values: list[str] = []
        legacy_updates: list[str] = []
        if self._has_legacy_turn_thread_id:
            legacy_columns.append("thread_id")
            legacy_values.append("%(thread_id)s")
            legacy_updates.append("thread_id = EXCLUDED.thread_id")
            params["thread_id"] = params["session_id"]
        if self._has_legacy_turn_codex_thread_id:
            legacy_columns.append("codex_thread_id")
            legacy_values.append("%(codex_thread_id)s")
            legacy_updates.append("codex_thread_id = EXCLUDED.codex_thread_id")
            params["codex_thread_id"] = params["codex_session_id"]
        extra_columns = f", {', '.join(legacy_columns)}" if legacy_columns else ""
        extra_values = f", {', '.join(legacy_values)}" if legacy_values else ""
        extra_updates = (",\n                        " + ",\n                        ".join(legacy_updates)) if legacy_updates else ""
        conn.execute(
            f"""
            INSERT INTO {POSTGRES_TURN_TABLE} (
                id, session_id, input_kind, question, input_text, status,
                created_at, updated_at, started_at, completed_at,
                codex_session_id, codex_turn_id, metadata{extra_columns}
            )
            VALUES (
                %(id)s, %(session_id)s, %(input_kind)s, %(question)s, %(input_text)s, %(status)s,
                %(created_at)s, %(updated_at)s, %(started_at)s, %(completed_at)s,
                %(codex_session_id)s, %(codex_turn_id)s, %(metadata)s{extra_values}
            )
            ON CONFLICT (id) DO UPDATE SET
                input_kind = EXCLUDED.input_kind,
                question = EXCLUDED.question,
                input_text = EXCLUDED.input_text,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                codex_session_id = EXCLUDED.codex_session_id,
                codex_turn_id = EXCLUDED.codex_turn_id,
                metadata = EXCLUDED.metadata{extra_updates}
            WHERE {POSTGRES_TURN_TABLE}.session_id = EXCLUDED.session_id
            """,
            params,
        )

    def _upsert_item(self, conn: Any, item: CodexItemProjectionRecord) -> None:
        params = _codex_item_projection_params(item)
        legacy_columns: list[str] = []
        legacy_values: list[str] = []
        legacy_updates: list[str] = []
        if self._has_legacy_item_codex_thread_id:
            legacy_columns.append("codex_thread_id")
            legacy_values.append("%(codex_thread_id)s")
            legacy_updates.append("codex_thread_id = EXCLUDED.codex_thread_id")
            params["codex_thread_id"] = params["codex_session_id"]
        if self._has_legacy_item_genbi_thread_id:
            legacy_columns.append("genbi_thread_id")
            legacy_values.append("%(genbi_thread_id)s")
            legacy_updates.append("genbi_thread_id = EXCLUDED.genbi_thread_id")
            params["genbi_thread_id"] = params["genbi_session_id"]
        extra_columns = f", {', '.join(legacy_columns)}" if legacy_columns else ""
        extra_values = f", {', '.join(legacy_values)}" if legacy_values else ""
        extra_updates = (",\n                        " + ",\n                        ".join(legacy_updates)) if legacy_updates else ""
        conn.execute(
            f"""
            INSERT INTO {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (
                codex_item_id, codex_session_id, codex_turn_id, item_type, status, sequence, payload,
                created_at, completed_at, genbi_session_id, genbi_turn_id{extra_columns}
            )
            VALUES (
                %(codex_item_id)s, %(codex_session_id)s, %(codex_turn_id)s, %(item_type)s, %(status)s, %(sequence)s, %(payload)s,
                %(created_at)s, %(completed_at)s, %(genbi_session_id)s, %(genbi_turn_id)s{extra_values}
            )
            ON CONFLICT (codex_item_id) DO UPDATE SET
                codex_session_id = EXCLUDED.codex_session_id,
                codex_turn_id = EXCLUDED.codex_turn_id,
                item_type = EXCLUDED.item_type,
                status = EXCLUDED.status,
                sequence = EXCLUDED.sequence,
                payload = EXCLUDED.payload,
                completed_at = EXCLUDED.completed_at,
                genbi_session_id = EXCLUDED.genbi_session_id,
                genbi_turn_id = EXCLUDED.genbi_turn_id{extra_updates}
            WHERE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}.genbi_session_id = EXCLUDED.genbi_session_id
              AND {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}.genbi_turn_id = EXCLUDED.genbi_turn_id
            """,
            params,
        )

    def clear(self) -> int:
        with _connect(self.database_url) as conn:
            return conn.execute(f"DELETE FROM {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}").rowcount or 0


class PostgresAnalysisAssetStore(AnalysisAssetStore):
    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_ANALYSIS_ASSET_TABLE} (
                    asset_id TEXT PRIMARY KEY,
                    artifact_version_id TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,
                    source_task_title TEXT NOT NULL,
                    source_conversation_id TEXT NOT NULL,
                    source_codex_thread_id TEXT,
                    source_codex_turn_id TEXT,
                    source_codex_item_id TEXT,
                    asset_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    label TEXT NOT NULL,
                    description TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latest_version TEXT NOT NULL,
                    file_id TEXT,
                    reopen_context JSONB NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_ARTIFACT_LINEAGE_TABLE} (
                    artifact_id TEXT PRIMARY KEY,
                    artifact_version_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL REFERENCES {POSTGRES_ANALYSIS_ASSET_TABLE}(asset_id) ON DELETE CASCADE,
                    asset_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_task_id TEXT NOT NULL,
                    source_conversation_id TEXT NOT NULL,
                    codex_thread_id TEXT,
                    codex_turn_id TEXT,
                    codex_item_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_ANALYSIS_ASSET_TABLE}_task_updated ON {POSTGRES_ANALYSIS_ASSET_TABLE} (source_task_id, updated_at DESC)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_ANALYSIS_ASSET_TABLE}_codex_item ON {POSTGRES_ANALYSIS_ASSET_TABLE} (source_codex_item_id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_ARTIFACT_LINEAGE_TABLE}_codex_item ON {POSTGRES_ARTIFACT_LINEAGE_TABLE} (codex_item_id, updated_at DESC)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_ARTIFACT_LINEAGE_TABLE}_codex_turn ON {POSTGRES_ARTIFACT_LINEAGE_TABLE} (codex_thread_id, codex_turn_id)")

    def save_asset(
        self,
        *,
        asset_id: str,
        artifact_version_id: str,
        source_task_id: str,
        source_task_title: str,
        source_conversation_id: str,
        source_codex_thread_id: str | None = None,
        source_codex_turn_id: str | None = None,
        source_codex_item_id: str | None = None,
        asset_type: str,
        title: str,
        label: str,
        description: str,
        visibility: str,
        status: str,
        latest_version: str,
        reopen_context: AnalysisAssetReopenContext,
        file_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AnalysisAssetRecord:
        for field_name, value in {
            "asset_id": asset_id,
            "artifact_version_id": artifact_version_id,
            "source_task_id": source_task_id,
            "source_task_title": source_task_title,
            "source_conversation_id": source_conversation_id,
            "asset_type": asset_type,
            "title": title,
            "label": label,
            "description": description,
            "visibility": visibility,
            "status": status,
            "latest_version": latest_version,
        }.items():
            _require_text(field_name, value)
        _validate_reopen_context(reopen_context)

        now = datetime.now(UTC).isoformat()
        existing = self.get_asset(asset_id)
        codex_lineage = _codex_lineage(source_codex_thread_id, source_codex_turn_id, source_codex_item_id)
        record_metadata = dict(metadata or {})
        if codex_lineage:
            record_metadata["codex_lineage"] = codex_lineage
        record = AnalysisAssetRecord(
            assetId=asset_id.strip(),
            artifactVersionId=artifact_version_id.strip(),
            sourceTaskId=source_task_id.strip(),
            sourceTaskTitle=source_task_title.strip(),
            sourceConversationId=source_conversation_id.strip(),
            sourceCodexThreadId=_optional_text(source_codex_thread_id),
            sourceCodexTurnId=_optional_text(source_codex_turn_id),
            sourceCodexItemId=_optional_text(source_codex_item_id),
            assetType=asset_type.strip(),
            title=title.strip(),
            label=label.strip(),
            description=description.strip(),
            visibility=visibility.strip(),
            status=status.strip(),
            latestVersion=latest_version.strip(),
            fileId=file_id.strip() if file_id else None,
            reopenContext=reopen_context,
            createdAt=existing.createdAt if existing else now,
            updatedAt=now,
            metadata=record_metadata,
        )
        with _connect(self.database_url) as conn:
            with conn.transaction():
                conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_ANALYSIS_ASSET_TABLE} (
                        asset_id, artifact_version_id, source_task_id, source_task_title, source_conversation_id,
                        source_codex_thread_id, source_codex_turn_id, source_codex_item_id,
                        asset_type, title, label, description, visibility, status, latest_version, file_id,
                        reopen_context, metadata, created_at, updated_at
                    )
                    VALUES (
                        %(asset_id)s, %(artifact_version_id)s, %(source_task_id)s, %(source_task_title)s, %(source_conversation_id)s,
                        %(source_codex_thread_id)s, %(source_codex_turn_id)s, %(source_codex_item_id)s,
                        %(asset_type)s, %(title)s, %(label)s, %(description)s, %(visibility)s, %(status)s, %(latest_version)s,
                        %(file_id)s, %(reopen_context)s, %(metadata)s, %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT (asset_id) DO UPDATE SET
                        artifact_version_id = EXCLUDED.artifact_version_id,
                        source_task_id = EXCLUDED.source_task_id,
                        source_task_title = EXCLUDED.source_task_title,
                        source_conversation_id = EXCLUDED.source_conversation_id,
                        source_codex_thread_id = EXCLUDED.source_codex_thread_id,
                        source_codex_turn_id = EXCLUDED.source_codex_turn_id,
                        source_codex_item_id = EXCLUDED.source_codex_item_id,
                        asset_type = EXCLUDED.asset_type,
                        title = EXCLUDED.title,
                        label = EXCLUDED.label,
                        description = EXCLUDED.description,
                        visibility = EXCLUDED.visibility,
                        status = EXCLUDED.status,
                        latest_version = EXCLUDED.latest_version,
                        file_id = EXCLUDED.file_id,
                        reopen_context = EXCLUDED.reopen_context,
                        metadata = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                    """,
                    _analysis_asset_params(record),
                )
                conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_ARTIFACT_LINEAGE_TABLE} (
                        artifact_id, artifact_version_id, asset_id, asset_type, title, source_task_id,
                        source_conversation_id, codex_thread_id, codex_turn_id, codex_item_id,
                        created_at, updated_at
                    )
                    VALUES (
                        %(artifact_id)s, %(artifact_version_id)s, %(asset_id)s, %(asset_type)s, %(title)s, %(source_task_id)s,
                        %(source_conversation_id)s, %(codex_thread_id)s, %(codex_turn_id)s,
                        %(codex_item_id)s, %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT (artifact_id) DO UPDATE SET
                        artifact_version_id = EXCLUDED.artifact_version_id,
                        asset_id = EXCLUDED.asset_id,
                        asset_type = EXCLUDED.asset_type,
                        title = EXCLUDED.title,
                        source_task_id = EXCLUDED.source_task_id,
                        source_conversation_id = EXCLUDED.source_conversation_id,
                        codex_thread_id = EXCLUDED.codex_thread_id,
                        codex_turn_id = EXCLUDED.codex_turn_id,
                        codex_item_id = EXCLUDED.codex_item_id,
                        updated_at = EXCLUDED.updated_at
                    """,
                    _artifact_lineage_params(_artifact_lineage_from_asset_record(record)),
                )
        return record

    def list_assets(self, *, limit: int = 50, source_task_id: str | None = None, q: str = "") -> list[AnalysisAssetRecord]:
        where = []
        params: dict[str, Any] = {"limit": limit}
        if source_task_id:
            where.append("source_task_id = %(source_task_id)s")
            params["source_task_id"] = source_task_id
        if q.strip():
            where.append("(asset_id ILIKE %(q)s OR source_task_title ILIKE %(q)s OR asset_type ILIKE %(q)s OR title ILIKE %(q)s OR label ILIKE %(q)s OR description ILIKE %(q)s OR metadata::text ILIKE %(q)s)")
            params["q"] = f"%{q.strip()}%"
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"SELECT * FROM {POSTGRES_ANALYSIS_ASSET_TABLE} {clause} ORDER BY updated_at DESC LIMIT %(limit)s",
                params,
            ).fetchall()
        return [_analysis_asset_from_row(row) for row in rows]

    def get_asset(self, asset_id: str) -> AnalysisAssetRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"SELECT * FROM {POSTGRES_ANALYSIS_ASSET_TABLE} WHERE asset_id = %(asset_id)s",
                {"asset_id": asset_id},
            ).fetchone()
        return _analysis_asset_from_row(row) if row else None

    def list_artifact_lineage(
        self,
        *,
        artifact_id: str | None = None,
        codex_thread_id: str | None = None,
        codex_turn_id: str | None = None,
        codex_item_id: str | None = None,
        limit: int = 50,
    ) -> list[ArtifactLineageRecord]:
        where = []
        params: dict[str, Any] = {"limit": limit}
        if artifact_id:
            where.append("artifact_id = %(artifact_id)s")
            params["artifact_id"] = artifact_id
        if codex_thread_id:
            where.append("codex_thread_id = %(codex_thread_id)s")
            params["codex_thread_id"] = codex_thread_id
        if codex_turn_id:
            where.append("codex_turn_id = %(codex_turn_id)s")
            params["codex_turn_id"] = codex_turn_id
        if codex_item_id:
            where.append("codex_item_id = %(codex_item_id)s")
            params["codex_item_id"] = codex_item_id
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"SELECT * FROM {POSTGRES_ARTIFACT_LINEAGE_TABLE} {clause} ORDER BY updated_at DESC LIMIT %(limit)s",
                params,
            ).fetchall()
        return [_artifact_lineage_from_row(row) for row in rows]

    def delete_asset(self, asset_id: str) -> bool:
        with _connect(self.database_url) as conn:
            cursor = conn.execute(
                f"DELETE FROM {POSTGRES_ANALYSIS_ASSET_TABLE} WHERE asset_id = %(asset_id)s",
                {"asset_id": asset_id},
            )
        return bool(cursor.rowcount)

    def clear_assets(self) -> int:
        with _connect(self.database_url) as conn:
            count = conn.execute(f"DELETE FROM {POSTGRES_ANALYSIS_ASSET_TABLE}").rowcount or 0
        return count

    def _read_all(self) -> list[AnalysisAssetRecord]:
        return self.list_assets(limit=10_000)

    def _write_all(self, records: list[AnalysisAssetRecord]) -> None:
        self.clear_assets()
        for record in records:
            self.save_asset(
                asset_id=record.assetId,
                artifact_version_id=record.artifactVersionId,
                source_task_id=record.sourceTaskId,
                source_task_title=record.sourceTaskTitle,
                source_conversation_id=record.sourceConversationId,
                source_codex_thread_id=record.sourceCodexThreadId,
                source_codex_turn_id=record.sourceCodexTurnId,
                source_codex_item_id=record.sourceCodexItemId,
                asset_type=record.assetType,
                title=record.title,
                label=record.label,
                description=record.description,
                visibility=record.visibility,
                status=record.status,
                latest_version=record.latestVersion,
                reopen_context=record.reopenContext,
                file_id=record.fileId,
                metadata=record.metadata,
            )


class PostgresReportBuildStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_REPORT_BUILD_TABLE} (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    session_id TEXT NOT NULL
                        REFERENCES {POSTGRES_THREAD_TABLE}(id)
                        ON DELETE CASCADE,
                    turn_id TEXT NOT NULL
                        REFERENCES {POSTGRES_TURN_TABLE}(id)
                        ON DELETE CASCADE,
                    target_report_id TEXT
                        REFERENCES {POSTGRES_REPORT_TABLE}(id)
                        ON DELETE SET NULL,
                    status TEXT NOT NULL,
                    content JSONB NOT NULL,
                    validation_errors JSONB NOT NULL
                        DEFAULT '[]'::jsonb,
                    revision BIGINT NOT NULL DEFAULT 0,
                    published_report_id TEXT
                        REFERENCES {POSTGRES_REPORT_TABLE}(id)
                        ON DELETE SET NULL,
                    last_successful_step TEXT,
                    step_attempts JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"{POSTGRES_REPORT_BUILD_TABLE}_session_id_updated_at_idx "
                f"ON {POSTGRES_REPORT_BUILD_TABLE} "
                "(session_id, updated_at DESC)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"{POSTGRES_REPORT_BUILD_TABLE}_turn_id_idx "
                f"ON {POSTGRES_REPORT_BUILD_TABLE} (turn_id)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"{POSTGRES_REPORT_BUILD_TABLE}_owner_id_status_updated_at_idx "
                f"ON {POSTGRES_REPORT_BUILD_TABLE} "
                "(owner_id, status, updated_at DESC)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS "
                f"{POSTGRES_REPORT_BUILD_TABLE}_expires_at_idx "
                f"ON {POSTGRES_REPORT_BUILD_TABLE} (expires_at)"
            )

    def create_build(
        self,
        record: ReportBuildRecord,
    ) -> ReportBuildRecord:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                INSERT INTO {POSTGRES_REPORT_BUILD_TABLE} (
                    id, owner_id, session_id, turn_id,
                    target_report_id, status, content,
                    validation_errors, revision,
                    published_report_id, last_successful_step,
                    step_attempts, created_at, updated_at, expires_at
                ) VALUES (
                    %(id)s, %(owner_id)s, %(session_id)s, %(turn_id)s,
                    %(target_report_id)s, %(status)s, %(content)s,
                    %(validation_errors)s, %(revision)s,
                    %(published_report_id)s, %(last_successful_step)s,
                    %(step_attempts)s, %(created_at)s, %(updated_at)s,
                    %(expires_at)s
                )
                RETURNING *
                """,
                _report_build_params(record),
            ).fetchone()
        if not row:
            raise RuntimeError("report_build_create_failed")
        return _report_build_from_row(row)

    def get_build(self, build_id: str) -> ReportBuildRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"SELECT * FROM {POSTGRES_REPORT_BUILD_TABLE} "
                "WHERE id = %(id)s",
                {"id": build_id},
            ).fetchone()
        return _report_build_from_row(row) if row else None

    def get_active_for_session(
        self,
        session_id: str,
        *,
        owner_id: str | None = None,
    ) -> ReportBuildRecord | None:
        clauses = [
            "session_id = %(session_id)s",
            "status IN ('building', 'validating', 'failed')",
            "expires_at > now()",
        ]
        params: dict[str, Any] = {"session_id": session_id}
        if owner_id:
            clauses.append("owner_id = %(owner_id)s")
            params["owner_id"] = owner_id
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_REPORT_BUILD_TABLE}
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, revision DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return _report_build_from_row(row) if row else None

    def mutate_build(
        self,
        build_id: str,
        *,
        owner_id: str,
        mutation: Callable[
            [ReportBuildRecord],
            ReportBuildRecord,
        ],
    ) -> ReportBuildRecord | None:
        with _connect(self.database_url) as conn:
            with conn.transaction():
                row = conn.execute(
                    f"""
                    SELECT * FROM {POSTGRES_REPORT_BUILD_TABLE}
                    WHERE id = %(id)s AND owner_id = %(owner_id)s
                    FOR UPDATE
                    """,
                    {"id": build_id, "owner_id": owner_id},
                ).fetchone()
                if not row:
                    return None
                current = _report_build_from_row(row)
                updated = mutation(current)
                if (
                    updated.id != current.id
                    or updated.ownerId != current.ownerId
                    or updated.sessionId != current.sessionId
                    or updated.turnId != current.turnId
                ):
                    raise ValueError("report_build_identity_changed")
                saved = conn.execute(
                    f"""
                    UPDATE {POSTGRES_REPORT_BUILD_TABLE}
                    SET status = %(status)s,
                        content = %(content)s,
                        validation_errors = %(validation_errors)s,
                        revision = %(revision)s,
                        published_report_id = %(published_report_id)s,
                        last_successful_step = %(last_successful_step)s,
                        step_attempts = %(step_attempts)s,
                        updated_at = %(updated_at)s,
                        expires_at = %(expires_at)s
                    WHERE id = %(id)s AND owner_id = %(owner_id)s
                    RETURNING *
                    """,
                    _report_build_params(updated),
                ).fetchone()
        return _report_build_from_row(saved) if saved else None

    def publish_build(
        self,
        build_id: str,
        *,
        owner_id: str,
        turn_id: str,
    ) -> tuple[ReportBuildRecord, ReportRecord] | None:
        with _connect(self.database_url) as conn:
            with conn.transaction():
                row = conn.execute(
                    f"""
                    SELECT * FROM {POSTGRES_REPORT_BUILD_TABLE}
                    WHERE id = %(id)s AND owner_id = %(owner_id)s
                    FOR UPDATE
                    """,
                    {"id": build_id, "owner_id": owner_id},
                ).fetchone()
                if not row:
                    return None
                current = _report_build_from_row(row)
                if current.publishedReportId:
                    report_row = conn.execute(
                        f"SELECT * FROM {POSTGRES_REPORT_TABLE} "
                        "WHERE id = %(id)s AND deleted_at IS NULL",
                        {"id": current.publishedReportId},
                    ).fetchone()
                    if not report_row:
                        raise ValueError("published_report_not_found")
                    return current, _report_from_row(report_row)

                normalized = report_config_payload(current.content)
                report_params = _report_params(
                    normalized,
                    report_id=f"report_{uuid4().hex}",
                    owner_id=owner_id,
                    turn_id=turn_id,
                )
                report_row = conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_REPORT_TABLE} (
                        id, title, subtitle, owner_id, turn_id,
                        layout, filters, charts, tables, queries
                    ) VALUES (
                        %(id)s, %(title)s, %(subtitle)s,
                        %(owner_id)s, %(turn_id)s,
                        %(layout)s, %(filters)s, %(charts)s,
                        %(tables)s, %(queries)s
                    )
                    RETURNING *
                    """,
                    report_params,
                ).fetchone()
                if not report_row:
                    raise RuntimeError("report_create_failed")
                now = datetime.now(UTC)
                published = replace(
                    current,
                    status="published",
                    content=normalized,
                    validationErrors=[],
                    revision=current.revision + 1,
                    publishedReportId=str(report_row["id"]),
                    lastSuccessfulStep="publish_report_build",
                    updatedAt=now.isoformat(),
                    expiresAt=(now + timedelta(hours=24)).isoformat(),
                )
                build_row = conn.execute(
                    f"""
                    UPDATE {POSTGRES_REPORT_BUILD_TABLE}
                    SET status = %(status)s,
                        content = %(content)s,
                        validation_errors = %(validation_errors)s,
                        revision = %(revision)s,
                        published_report_id = %(published_report_id)s,
                        last_successful_step = %(last_successful_step)s,
                        step_attempts = %(step_attempts)s,
                        updated_at = %(updated_at)s,
                        expires_at = %(expires_at)s
                    WHERE id = %(id)s AND owner_id = %(owner_id)s
                    RETURNING *
                    """,
                    _report_build_params(published),
                ).fetchone()
                if not build_row:
                    raise RuntimeError("report_build_publish_failed")
                return (
                    _report_build_from_row(build_row),
                    _report_from_row(report_row),
                )

    def cleanup_expired(
        self,
        *,
        now: datetime | None = None,
    ) -> int:
        with _connect(self.database_url) as conn:
            result = conn.execute(
                f"DELETE FROM {POSTGRES_REPORT_BUILD_TABLE} "
                "WHERE expires_at <= %(now)s",
                {"now": now or datetime.now(UTC)},
            )
        return result.rowcount or 0


class PostgresReportStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                DROP TABLE IF EXISTS analysis_report_shares;
                DROP TABLE IF EXISTS analysis_report_versions;
                DROP TABLE IF EXISTS analysis_reports;
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_REPORT_TABLE} (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    subtitle TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    turn_id TEXT REFERENCES {POSTGRES_TURN_TABLE}(id) ON DELETE SET NULL,
                    layout JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    filters JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    charts JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    tables JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    queries JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    deleted_at TIMESTAMPTZ,
                    is_example BOOLEAN NOT NULL DEFAULT false
                )
                """
            )
            conn.execute(
                f"ALTER TABLE {POSTGRES_REPORT_TABLE} "
                "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
            )
            conn.execute(
                f"ALTER TABLE {POSTGRES_REPORT_TABLE} "
                "ADD COLUMN IF NOT EXISTS is_example BOOLEAN "
                "NOT NULL DEFAULT false"
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_REPORT_SHARE_TABLE} (
                    report_id TEXT NOT NULL REFERENCES {POSTGRES_REPORT_TABLE}(id) ON DELETE CASCADE,
                    recipient_user_id TEXT NOT NULL,
                    permission TEXT NOT NULL CHECK (permission IN ('view', 'view_and_reuse')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (report_id, recipient_user_id)
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_REPORT_TABLE}_owner_updated "
                f"ON {POSTGRES_REPORT_TABLE} (owner_id, updated_at DESC)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_REPORT_TABLE}_turn "
                f"ON {POSTGRES_REPORT_TABLE} (turn_id, updated_at DESC)"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_REPORT_SHARE_TABLE}_recipient "
                f"ON {POSTGRES_REPORT_SHARE_TABLE} (recipient_user_id)"
            )

    def create_report(
        self,
        config: dict[str, Any],
        *,
        owner_id: str,
        turn_id: str | None = None,
        report_id: str | None = None,
    ) -> ReportRecord:
        normalized = report_config_payload(config)
        params = _report_params(
            normalized,
            report_id=report_id or f"report_{uuid4().hex}",
            owner_id=owner_id,
            turn_id=turn_id,
        )
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                INSERT INTO {POSTGRES_REPORT_TABLE} (
                    id, title, subtitle, owner_id, turn_id,
                    layout, filters, charts, tables, queries
                ) VALUES (
                    %(id)s, %(title)s, %(subtitle)s, %(owner_id)s, %(turn_id)s,
                    %(layout)s, %(filters)s, %(charts)s, %(tables)s, %(queries)s
                )
                RETURNING *
                """,
                params,
            ).fetchone()
        if not row:
            raise RuntimeError("report_create_failed")
        return _report_from_row(row)

    def update_report(
        self,
        report_id: str,
        config: dict[str, Any],
        *,
        owner_id: str,
        turn_id: str | None = None,
    ) -> ReportRecord | None:
        normalized = report_config_payload(config)
        params = _report_params(
            normalized,
            report_id=report_id,
            owner_id=owner_id,
            turn_id=turn_id,
        )
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                UPDATE {POSTGRES_REPORT_TABLE}
                SET title = %(title)s,
                    subtitle = %(subtitle)s,
                    turn_id = COALESCE(%(turn_id)s, turn_id),
                    layout = %(layout)s,
                    filters = %(filters)s,
                    charts = %(charts)s,
                    tables = %(tables)s,
                    queries = %(queries)s,
                    updated_at = now()
                WHERE id = %(id)s
                  AND owner_id = %(owner_id)s
                  AND deleted_at IS NULL
                RETURNING *
                """,
                params,
            ).fetchone()
        return _report_from_row(row) if row else None

    def list_reports(
        self,
        *,
        owner_id: str | None = None,
        turn_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[ReportRecord]:
        clauses: list[str] = ["deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": limit}
        if owner_id:
            clauses.append("owner_id = %(owner_id)s")
            params["owner_id"] = owner_id
        if turn_ids is not None:
            if not turn_ids:
                return []
            clauses.append("turn_id = ANY(%(turn_ids)s)")
            params["turn_ids"] = sorted(turn_ids)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"SELECT * FROM {POSTGRES_REPORT_TABLE} {where} "
                "ORDER BY updated_at DESC LIMIT %(limit)s",
                params,
            ).fetchall()
        return [_report_from_row(row) for row in rows]

    def get_report(self, report_id: str) -> ReportRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"SELECT * FROM {POSTGRES_REPORT_TABLE} "
                "WHERE id = %(id)s AND deleted_at IS NULL",
                {"id": report_id},
            ).fetchone()
        return _report_from_row(row) if row else None

    def delete_report(self, report_id: str, *, owner_id: str) -> bool:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                UPDATE {POSTGRES_REPORT_TABLE}
                SET deleted_at = COALESCE(deleted_at, now())
                WHERE id = %(id)s AND owner_id = %(owner_id)s
                RETURNING id
                """,
                {"id": report_id, "owner_id": owner_id},
            ).fetchone()
        return row is not None

    def set_report_example(
        self,
        report_id: str,
        *,
        owner_id: str,
        is_example: bool,
    ) -> ReportRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(
                f"""
                UPDATE {POSTGRES_REPORT_TABLE}
                SET is_example = %(is_example)s,
                    updated_at = now()
                WHERE id = %(id)s
                  AND owner_id = %(owner_id)s
                  AND deleted_at IS NULL
                RETURNING *
                """,
                {
                    "id": report_id,
                    "owner_id": owner_id,
                    "is_example": bool(is_example),
                },
            ).fetchone()
        return _report_from_row(row) if row else None

    def share_report(
        self,
        report_id: str,
        *,
        owner_id: str,
        recipient_user_id: str,
        permission: str,
    ) -> ReportShareRecord | None:
        if permission not in {"view", "view_and_reuse"}:
            raise ValueError("invalid_report_share_permission")
        with _connect(self.database_url) as conn:
            report = conn.execute(
                f"SELECT 1 FROM {POSTGRES_REPORT_TABLE} "
                "WHERE id = %(id)s AND owner_id = %(owner_id)s "
                "AND deleted_at IS NULL",
                {"id": report_id, "owner_id": owner_id},
            ).fetchone()
            if not report:
                return None
            row = conn.execute(
                f"""
                INSERT INTO {POSTGRES_REPORT_SHARE_TABLE} (report_id, recipient_user_id, permission)
                VALUES (%(report_id)s, %(recipient_user_id)s, %(permission)s)
                ON CONFLICT (report_id, recipient_user_id)
                DO UPDATE SET permission = EXCLUDED.permission, created_at = now()
                RETURNING *
                """,
                {"report_id": report_id, "recipient_user_id": recipient_user_id.strip(), "permission": permission},
            ).fetchone()
        return _report_share_from_row(row) if row else None

    def revoke_report_share(
        self,
        report_id: str,
        *,
        owner_id: str,
        recipient_user_id: str,
    ) -> bool:
        with _connect(self.database_url) as conn:
            report = conn.execute(
                f"SELECT 1 FROM {POSTGRES_REPORT_TABLE} "
                "WHERE id = %(id)s AND owner_id = %(owner_id)s "
                "AND deleted_at IS NULL",
                {"id": report_id, "owner_id": owner_id},
            ).fetchone()
            if not report:
                return False
            result = conn.execute(
                f"DELETE FROM {POSTGRES_REPORT_SHARE_TABLE} WHERE report_id = %(report_id)s AND recipient_user_id = %(recipient_user_id)s",
                {"report_id": report_id, "recipient_user_id": recipient_user_id},
            )
        return result.rowcount > 0

    def list_report_center(
        self,
        *,
        user_id: str,
        limit: int = 50,
    ) -> dict[str, list[dict[str, Any]]]:
        with _connect(self.database_url) as conn:
            mine_rows = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_REPORT_TABLE}
                WHERE owner_id = %(user_id)s
                  AND is_example = false
                  AND deleted_at IS NULL
                ORDER BY updated_at DESC
                LIMIT %(limit)s
                """,
                {"user_id": user_id, "limit": limit},
            ).fetchall()
            shared_rows = conn.execute(
                f"""
                SELECT share.report_id, share.recipient_user_id, share.permission, share.created_at,
                       report.*
                FROM {POSTGRES_REPORT_SHARE_TABLE} AS share
                JOIN {POSTGRES_REPORT_TABLE} AS report ON report.id = share.report_id
                WHERE share.recipient_user_id = %(user_id)s
                  AND report.is_example = false
                  AND report.deleted_at IS NULL
                ORDER BY report.updated_at DESC
                LIMIT %(limit)s
                """,
                {"user_id": user_id, "limit": limit},
            ).fetchall()
            example_rows = conn.execute(
                f"""
                SELECT * FROM (
                    SELECT DISTINCT ON (title) *
                    FROM {POSTGRES_REPORT_TABLE}
                    WHERE is_example = true
                      AND deleted_at IS NULL
                    ORDER BY title, updated_at DESC, id DESC
                ) AS latest_examples
                ORDER BY updated_at DESC
                LIMIT %(limit)s
                """,
                {"limit": limit},
            ).fetchall()
        mine = [_report_from_row(row) for row in mine_rows]
        examples = [
            _report_from_row(row)
            for row in example_rows
        ]
        shared = [
            {
                **share_to_payload(_report_share_from_row(row)),
                "report": report_to_payload(_report_from_row(row)),
            }
            for row in shared_rows
        ]
        return {
            "mine": [
                {"report": report_to_payload(report)}
                for report in mine
            ],
            "sharedWithMe": shared,
            "examples": [
                {"report": report_to_payload(report)}
                for report in examples
            ],
        }


class PostgresKnowledgeStore(KnowledgeStore):
    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_KNOWLEDGE_TABLE} (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    question TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    verification TEXT NOT NULL,
                    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
                    turn_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(f"ALTER TABLE {POSTGRES_KNOWLEDGE_TABLE} ADD COLUMN IF NOT EXISTS turn_id TEXT")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_KNOWLEDGE_TABLE}_created ON {POSTGRES_KNOWLEDGE_TABLE} (created_at DESC)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_KNOWLEDGE_TABLE}_turn ON {POSTGRES_KNOWLEDGE_TABLE} (turn_id)")

    def save_verified_knowledge(
        self,
        *,
        title: str,
        question: str,
        conclusion: str,
        scope: str,
        verification: str,
        evidence_refs: list[str],
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeRecord:
        _require_text("title", title)
        _require_text("question", question)
        _require_text("conclusion", conclusion)
        _require_text("scope", scope)
        _require_text("verification", verification)
        if not evidence_refs:
            raise ValueError("save_verified_knowledge requires at least one evidence reference.")
        record = KnowledgeRecord(
            id=f"kn_{uuid4().hex[:12]}",
            title=title.strip(),
            question=question.strip(),
            conclusion=conclusion.strip(),
            scope=scope.strip(),
            verification=verification.strip(),
            evidence_refs=[ref.strip() for ref in evidence_refs if ref.strip()],
            turn_id=turn_id.strip() if turn_id else None,
            created_at=datetime.now(UTC).isoformat(),
            metadata=metadata or {},
        )
        self.upsert_knowledge(record)
        return record

    def upsert_knowledge(self, record: KnowledgeRecord) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                INSERT INTO {POSTGRES_KNOWLEDGE_TABLE} (
                    id, title, question, conclusion, scope, verification, evidence_refs, turn_id, created_at, metadata
                )
                VALUES (
                    %(id)s, %(title)s, %(question)s, %(conclusion)s, %(scope)s, %(verification)s,
                    %(evidence_refs)s, %(turn_id)s, %(created_at)s, %(metadata)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    question = EXCLUDED.question,
                    conclusion = EXCLUDED.conclusion,
                    scope = EXCLUDED.scope,
                    verification = EXCLUDED.verification,
                    evidence_refs = EXCLUDED.evidence_refs,
                    turn_id = EXCLUDED.turn_id,
                    created_at = EXCLUDED.created_at,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """,
                _knowledge_params(record),
            )

    def list_knowledge(self, *, limit: int = 50) -> list[KnowledgeRecord]:
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"SELECT * FROM {POSTGRES_KNOWLEDGE_TABLE} ORDER BY created_at DESC LIMIT %(limit)s",
                {"limit": limit},
            ).fetchall()
        return [_knowledge_from_row(row) for row in rows]

    def search_knowledge(
        self,
        *,
        query: str = "",
        item_type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        owner: str | None = None,
        limit: int = 50,
    ) -> list[KnowledgeRecord]:
        clauses = []
        params: dict[str, Any] = {"limit": limit}
        if query.strip():
            params["query"] = f"%{query.strip()}%"
            clauses.append(
                "(title ILIKE %(query)s OR question ILIKE %(query)s OR conclusion ILIKE %(query)s OR scope ILIKE %(query)s OR verification ILIKE %(query)s OR metadata::text ILIKE %(query)s)"
            )
        if item_type:
            params["item_type"] = item_type
            clauses.append("metadata ->> 'type' = %(item_type)s")
        if status:
            params["status"] = status
            clauses.append("metadata ->> 'status' = %(status)s")
        if owner:
            params["owner"] = owner
            clauses.append("metadata ->> 'owner' = %(owner)s")
        if tag:
            params["tag"] = tag
            clauses.append("metadata -> 'tags' ? %(tag)s")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_KNOWLEDGE_TABLE}
                {where}
                ORDER BY created_at DESC
                LIMIT %(limit)s
                """,
                params,
            ).fetchall()
        return [_knowledge_from_row(row) for row in rows]

    def update_knowledge(
        self,
        record_id: str,
        *,
        title: str | None = None,
        question: str | None = None,
        conclusion: str | None = None,
        scope: str | None = None,
        verification: str | None = None,
        evidence_refs: list[str] | None = None,
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeRecord | None:
        current = self.get_knowledge(record_id)
        if not current:
            return None
        merged_metadata = dict(current.metadata or {})
        if metadata:
            merged_metadata.update(metadata)
        record = KnowledgeRecord(
            id=current.id,
            title=title.strip() if title is not None else current.title,
            question=question.strip() if question is not None else current.question,
            conclusion=conclusion.strip() if conclusion is not None else current.conclusion,
            scope=scope.strip() if scope is not None else current.scope,
            verification=verification.strip() if verification is not None else current.verification,
            evidence_refs=[ref.strip() for ref in evidence_refs if ref.strip()] if evidence_refs is not None else current.evidence_refs,
            turn_id=turn_id.strip() if turn_id else current.turn_id,
            created_at=current.created_at,
            metadata=merged_metadata,
        )
        self.upsert_knowledge(record)
        return record

    def get_knowledge(self, record_id: str) -> KnowledgeRecord | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(f"SELECT * FROM {POSTGRES_KNOWLEDGE_TABLE} WHERE id = %(id)s", {"id": record_id}).fetchone()
        return _knowledge_from_row(row) if row else None

    def list_tags(self) -> list[dict[str, Any]]:
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"""
                SELECT tag, COUNT(*) AS count
                FROM {POSTGRES_KNOWLEDGE_TABLE}, jsonb_array_elements_text(metadata -> 'tags') AS tag
                GROUP BY tag
                ORDER BY count DESC, tag ASC
                """
            ).fetchall()
        return [{"name": str(row["tag"]), "count": int(row["count"]), "group": "ungrouped"} for row in rows]

    def delete_knowledge(self, record_id: str) -> bool:
        with _connect(self.database_url) as conn:
            cursor = conn.execute(f"DELETE FROM {POSTGRES_KNOWLEDGE_TABLE} WHERE id = %(id)s", {"id": record_id})
            return bool(cursor.rowcount)

    def clear_knowledge(self) -> int:
        with _connect(self.database_url) as conn:
            cursor = conn.execute(f"DELETE FROM {POSTGRES_KNOWLEDGE_TABLE}")
            return cursor.rowcount or 0

    def _write_all(self, records: list[KnowledgeRecord]) -> None:
        self.clear_knowledge()
        for record in records:
            self.upsert_knowledge(record)


def _connect(database_url: str) -> Any:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - exercised only without optional dependency
        raise RuntimeError("Install psycopg from backend/requirements.txt to use Postgres persistence.") from exc
    return psycopg.connect(database_url, autocommit=True, row_factory=dict_row)


def _column_exists(conn: Any, table_name: str, column_name: str) -> bool:
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = %(table_name)s
              AND column_name = %(column_name)s
        ) AS exists
        """,
        {"table_name": table_name, "column_name": column_name},
    ).fetchone()
    if not row:
        return False
    return bool(row.get("exists"))


def _normalize_postgres_url(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme in {"postgres", "postgresql"}:
        scheme = "postgresql"
    elif parts.scheme == "postgresql+psycopg":
        scheme = "postgresql"
    else:
        return raw
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != "schema"])
    return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))


def _knowledge_params(record: KnowledgeRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "title": record.title,
        "question": record.question,
        "conclusion": record.conclusion,
        "scope": record.scope,
        "verification": record.verification,
        "evidence_refs": _jsonb(record.evidence_refs),
        "turn_id": record.turn_id,
        "created_at": record.created_at,
        "metadata": _jsonb(record.metadata),
    }


def _session_params(record: SessionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "product_kind": record.productKind,
        "title": record.title,
        "tenant_id": record.tenantId,
        "user_id": record.userId,
        "workspace_id": record.workspaceId,
        "codex_session_id": record.codexSessionId,
        "status": record.status,
        "created_at": record.createdAt,
        "updated_at": record.updatedAt,
        "metadata": _jsonb(record.metadata),
    }


def _turn_params(record: TurnRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "session_id": record.sessionId,
        "input_kind": record.inputKind,
        # ``inputText`` is the canonical field per the latest spec;
        # we still write ``question`` for legacy backends that read
        # the historical column name.
        "question": record.question,
        "input_text": record.inputText,
        "status": record.status,
        "created_at": record.createdAt,
        "updated_at": record.updatedAt,
        "started_at": record.startedAt,
        "completed_at": record.completedAt,
        "codex_session_id": record.codexSessionId,
        "codex_turn_id": record.codexTurnId,
        "metadata": _jsonb(record.metadata),
    }


def _codex_item_projection_params(record: CodexItemProjectionRecord) -> dict[str, Any]:
    return {
        "codex_item_id": record.codexItemId,
        "codex_session_id": record.codexSessionId,
        "codex_turn_id": record.codexTurnId,
        "item_type": record.itemType,
        "status": record.status,
        "sequence": record.sequence,
        "payload": _jsonb(record.payload),
        "created_at": record.createdAt,
        "completed_at": record.completedAt,
        "genbi_session_id": record.genbiSessionId,
        "genbi_turn_id": record.genbiTurnId,
    }


def _analysis_asset_params(record: AnalysisAssetRecord) -> dict[str, Any]:
    return {
        "asset_id": record.assetId,
        "artifact_version_id": record.artifactVersionId,
        "source_task_id": record.sourceTaskId,
        "source_task_title": record.sourceTaskTitle,
        "source_conversation_id": record.sourceConversationId,
        "source_codex_thread_id": record.sourceCodexThreadId,
        "source_codex_turn_id": record.sourceCodexTurnId,
        "source_codex_item_id": record.sourceCodexItemId,
        "asset_type": record.assetType,
        "title": record.title,
        "label": record.label,
        "description": record.description,
        "visibility": record.visibility,
        "status": record.status,
        "latest_version": record.latestVersion,
        "file_id": record.fileId,
        "reopen_context": _jsonb(asdict(record.reopenContext)),
        "metadata": _jsonb(record.metadata),
        "created_at": record.createdAt,
        "updated_at": record.updatedAt,
    }


def _artifact_lineage_params(record: ArtifactLineageRecord) -> dict[str, Any]:
    return {
        "artifact_id": record.artifactId,
        "artifact_version_id": record.artifactVersionId,
        "asset_id": record.assetId,
        "asset_type": record.assetType,
        "title": record.title,
        "source_task_id": record.sourceTaskId,
        "source_conversation_id": record.sourceConversationId,
        "codex_thread_id": record.codexThreadId,
        "codex_turn_id": record.codexTurnId,
        "codex_item_id": record.codexItemId,
        "created_at": record.createdAt,
        "updated_at": record.updatedAt,
    }


def _report_params(
    config: dict[str, Any],
    *,
    report_id: str,
    owner_id: str,
    turn_id: str | None,
) -> dict[str, Any]:
    return {
        "id": str(report_id).strip(),
        "title": str(config["title"]).strip(),
        "subtitle": str(config["subtitle"]).strip(),
        "owner_id": str(owner_id).strip(),
        "turn_id": str(turn_id).strip() if turn_id else None,
        "layout": _jsonb(config["layout"]),
        "filters": _jsonb(config["filters"]),
        "charts": _jsonb(config["charts"]),
        "tables": _jsonb(config["tables"]),
        "queries": _jsonb(config["queries"]),
    }


def _report_build_params(
    record: ReportBuildRecord,
) -> dict[str, Any]:
    return {
        "id": record.id,
        "owner_id": record.ownerId,
        "session_id": record.sessionId,
        "turn_id": record.turnId,
        "target_report_id": record.targetReportId,
        "status": record.status,
        "content": _jsonb(record.content),
        "validation_errors": _jsonb(record.validationErrors),
        "revision": record.revision,
        "published_report_id": record.publishedReportId,
        "last_successful_step": record.lastSuccessfulStep,
        "step_attempts": _jsonb(record.stepAttempts),
        "created_at": record.createdAt,
        "updated_at": record.updatedAt,
        "expires_at": record.expiresAt,
    }


def _session_record_from_row(row: dict[str, Any]) -> SessionRecord:
    codex_session_id = row.get("codex_session_id") or row.get("codex_thread_id")
    return SessionRecord(
        id=str(row["id"]),
        productKind=str(row["product_kind"]),  # type: ignore[arg-type]
        title=row.get("title"),
        tenantId=row.get("tenant_id"),
        userId=row.get("user_id"),
        workspaceId=row.get("workspace_id"),
        codexSessionId=codex_session_id,
        status=str(row["status"]),
        createdAt=_iso(row.get("created_at")) or "",
        updatedAt=_iso(row.get("updated_at")) or "",
        metadata=dict(row.get("metadata") or {}),
    )


def _turn_record_from_row(row: dict[str, Any]) -> TurnRecord:
    raw_question = str(row.get("question") or "")
    # Prefer the canonical ``input_text`` column; fall back to
    # ``question`` for legacy rows that pre-date the spec change.
    input_text = row.get("input_text")
    if input_text in (None, ""):
        input_text = raw_question
    return TurnRecord(
        id=str(row["id"]),
        sessionId=str(row.get("session_id") or row.get("thread_id")),
        inputKind=str(row["input_kind"]),  # type: ignore[arg-type]
        question=raw_question,
        inputText=str(input_text),
        status=str(row["status"]),
        createdAt=_iso(row.get("created_at")) or "",
        updatedAt=_iso(row.get("updated_at")) or "",
        startedAt=_iso(row.get("started_at")),
        completedAt=_iso(row.get("completed_at")),
        codexSessionId=row.get("codex_session_id") or row.get("codex_thread_id"),
        codexTurnId=row.get("codex_turn_id"),
        metadata=dict(row.get("metadata") or {}),
    )


def _codex_item_projection_from_row(row: dict[str, Any]) -> CodexItemProjectionRecord:
    raw_sequence = row.get("sequence")
    sequence = int(raw_sequence) if raw_sequence is not None else 0
    return CodexItemProjectionRecord(
        codexItemId=str(row["codex_item_id"]),
        codexSessionId=row.get("codex_session_id") or row.get("codex_thread_id"),
        codexTurnId=row.get("codex_turn_id"),
        itemType=str(row["item_type"]),
        status=str(row["status"]),
        sequence=sequence,
        payload=dict(row.get("payload") or {}),
        createdAt=_iso(row.get("created_at")) or "",
        completedAt=_iso(row.get("completed_at")),
        genbiSessionId=row.get("genbi_session_id") or row.get("genbi_thread_id"),
        genbiTurnId=row.get("genbi_turn_id"),
    )


def _analysis_asset_from_row(row: dict[str, Any]) -> AnalysisAssetRecord:
    context_payload = dict(row.get("reopen_context") or {})
    metadata = dict(row.get("metadata") or {})
    return AnalysisAssetRecord(
        assetId=str(row["asset_id"]),
        artifactVersionId=str(row["artifact_version_id"]),
        sourceTaskId=str(row["source_task_id"]),
        sourceTaskTitle=str(row["source_task_title"]),
        sourceConversationId=str(row["source_conversation_id"]),
        sourceCodexThreadId=row.get("source_codex_thread_id"),
        sourceCodexTurnId=row.get("source_codex_turn_id"),
        sourceCodexItemId=row.get("source_codex_item_id"),
        assetType=str(row["asset_type"]),
        title=str(row["title"]),
        label=str(row["label"]),
        description=str(row["description"]),
        visibility=str(row["visibility"]),
        status=str(row["status"]),
        latestVersion=str(row["latest_version"]),
        fileId=row.get("file_id"),
        reopenContext=AnalysisAssetReopenContext(**context_payload),
        createdAt=_iso(row.get("created_at")) or "",
        updatedAt=_iso(row.get("updated_at")) or "",
        metadata=metadata,
    )


def _artifact_lineage_from_asset_record(record: AnalysisAssetRecord) -> ArtifactLineageRecord:
    return ArtifactLineageRecord(
        artifactId=record.assetId,
        artifactVersionId=record.artifactVersionId,
        assetId=record.assetId,
        assetType=record.assetType,
        title=record.title,
        sourceTaskId=record.sourceTaskId,
        sourceConversationId=record.sourceConversationId,
        codexThreadId=record.sourceCodexThreadId,
        codexTurnId=record.sourceCodexTurnId,
        codexItemId=record.sourceCodexItemId,
        createdAt=record.createdAt,
        updatedAt=record.updatedAt,
    )


def _artifact_lineage_from_row(row: dict[str, Any]) -> ArtifactLineageRecord:
    return ArtifactLineageRecord(
        artifactId=str(row["artifact_id"]),
        artifactVersionId=str(row["artifact_version_id"]),
        assetId=str(row["asset_id"]),
        assetType=str(row["asset_type"]),
        title=str(row["title"]),
        sourceTaskId=str(row["source_task_id"]),
        sourceConversationId=str(row["source_conversation_id"]),
        codexThreadId=row.get("codex_thread_id"),
        codexTurnId=row.get("codex_turn_id"),
        codexItemId=row.get("codex_item_id"),
        createdAt=_iso(row.get("created_at")) or "",
        updatedAt=_iso(row.get("updated_at")) or "",
    )


def _report_from_row(row: dict[str, Any]) -> ReportRecord:
    return ReportRecord(
        id=str(row["id"]),
        title=str(row["title"]),
        subtitle=str(row["subtitle"]),
        ownerId=str(row["owner_id"]),
        turnId=str(row["turn_id"]) if row.get("turn_id") else None,
        layout=dict(row["layout"] or {}),
        filters=dict(row["filters"] or {}),
        charts=dict(row["charts"] or {}),
        tables=dict(row["tables"] or {}),
        queries=dict(row["queries"] or {}),
        createdAt=_iso(row["created_at"]) or "",
        updatedAt=_iso(row["updated_at"]) or "",
        isExample=bool(row.get("is_example", False)),
    )


def _report_build_from_row(
    row: dict[str, Any],
) -> ReportBuildRecord:
    return ReportBuildRecord(
        id=str(row["id"]),
        ownerId=str(row["owner_id"]),
        sessionId=str(row["session_id"]),
        turnId=str(row["turn_id"]),
        targetReportId=(
            str(row["target_report_id"])
            if row.get("target_report_id")
            else None
        ),
        status=str(row["status"]),
        content=dict(row.get("content") or {}),
        validationErrors=[
            dict(item)
            for item in row.get("validation_errors") or []
            if isinstance(item, dict)
        ],
        revision=int(row.get("revision") or 0),
        publishedReportId=(
            str(row["published_report_id"])
            if row.get("published_report_id")
            else None
        ),
        lastSuccessfulStep=(
            str(row["last_successful_step"])
            if row.get("last_successful_step")
            else None
        ),
        stepAttempts={
            str(key): int(value)
            for key, value in dict(
                row.get("step_attempts") or {}
            ).items()
        },
        createdAt=_iso(row.get("created_at")) or "",
        updatedAt=_iso(row.get("updated_at")) or "",
        expiresAt=_iso(row.get("expires_at")) or "",
    )


def _report_share_from_row(row: dict[str, Any]) -> ReportShareRecord:
    return ReportShareRecord(
        reportId=str(row["report_id"]),
        recipientUserId=str(row["recipient_user_id"]),
        permission=str(row["permission"]),
        createdAt=_iso(row["created_at"]) or "",
    )


def _knowledge_from_row(row: dict[str, Any]) -> KnowledgeRecord:
    return KnowledgeRecord(
        id=str(row["id"]),
        title=str(row["title"]),
        question=str(row["question"]),
        conclusion=str(row["conclusion"]),
        scope=str(row["scope"]),
        verification=str(row["verification"]),
        evidence_refs=[str(item) for item in row.get("evidence_refs") or []],
        turn_id=row.get("turn_id"),
        created_at=_iso(row["created_at"]) or "",
        metadata=dict(row.get("metadata") or {}),
    )


def _jsonb(value: Any) -> Any:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install psycopg from backend/requirements.txt to use Postgres persistence.") from exc
    return Jsonb(value)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _require_text(field: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} is required.")


