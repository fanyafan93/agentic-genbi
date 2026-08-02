from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_trace_store import RunCost, RunTrace, RunTraceStore, TokenUsage, build_run_trace
from backend.harness.thread_store import CodexItemProjectionRecord, ItemRecord, RunRecord, ThreadRecord, ThreadStore, TurnRecord
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
from backend.analysis.interactive_report_store import (
    InteractiveReportRecord,
    InteractiveReportVersionConflict,
    InteractiveReportVersionRecord,
)
from backend.resource_library.knowledge_store import KnowledgeRecord, KnowledgeStore


POSTGRES_TRACE_TABLE = "exploration_run_traces"
POSTGRES_EVENT_TABLE = "exploration_run_events"
POSTGRES_KNOWLEDGE_TABLE = "verified_knowledge"
POSTGRES_THREAD_TABLE = "analysis_threads"
POSTGRES_TURN_TABLE = "analysis_turns"
POSTGRES_RUN_TABLE = "analysis_runs"
POSTGRES_ITEM_TABLE = "analysis_items"
POSTGRES_CODEX_ITEM_PROJECTION_TABLE = "analysis_codex_item_projections"
POSTGRES_ANALYSIS_ASSET_TABLE = "analysis_assets"
POSTGRES_ARTIFACT_LINEAGE_TABLE = "analysis_artifact_lineage"
POSTGRES_INTERACTIVE_REPORT_TABLE = "analysis_reports"
POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE = "analysis_report_versions"
POSTGRES_REPORT_QUERY_AUDIT_TABLE = "analysis_report_query_audits"


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


def build_postgres_stores() -> tuple["PostgresRunTraceStore", "PostgresRunEventStore", "PostgresKnowledgeStore"]:
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres persistence.")
    return (
        PostgresRunTraceStore(database_url),
        PostgresRunEventStore(database_url),
        PostgresKnowledgeStore(database_url),
    )


def build_postgres_thread_store() -> "PostgresThreadStore":
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres ThreadStore persistence.")
    return PostgresThreadStore(database_url)


def build_postgres_interactive_report_store() -> "PostgresInteractiveReportStore":
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres interactive report persistence.")
    return PostgresInteractiveReportStore(database_url)


def build_postgres_analysis_asset_store() -> "PostgresAnalysisAssetStore":
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres analysis asset persistence.")
    return PostgresAnalysisAssetStore(database_url)


def build_postgres_report_query_audit_store() -> "PostgresReportQueryAuditStore":
    database_url = get_postgres_database_url()
    if not database_url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required for Postgres query auditing.")
    return PostgresReportQueryAuditStore(database_url)


class PostgresRunTraceStore(RunTraceStore):
    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_TRACE_TABLE} (
                    run_id TEXT PRIMARY KEY,
                    title TEXT,
                    status TEXT NOT NULL,
                    question TEXT NOT NULL,
                    conversation_id TEXT,
                    user_id TEXT,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    duration_ms INTEGER,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    tool_call_count INTEGER NOT NULL DEFAULT 0,
                    failed_tool_call_count INTEGER NOT NULL DEFAULT 0,
                    agent_message_count INTEGER NOT NULL DEFAULT 0,
                    token_usage JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    cost JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    error TEXT,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_TRACE_TABLE}_completed ON {POSTGRES_TRACE_TABLE} (completed_at DESC NULLS LAST)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_TRACE_TABLE}_user ON {POSTGRES_TRACE_TABLE} (user_id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_TRACE_TABLE}_conversation ON {POSTGRES_TRACE_TABLE} (conversation_id)")

    def save_trace(self, *, run_id: str, request: Any, events: list[Any], metadata: dict[str, Any] | None = None) -> RunTrace:
        trace = build_run_trace(run_id=run_id, request=request, events=events, metadata=metadata or {})
        self.upsert_trace(trace)
        return trace

    def upsert_trace(self, trace: RunTrace) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                INSERT INTO {POSTGRES_TRACE_TABLE} (
                    run_id, title, status, question, conversation_id, user_id, started_at, completed_at,
                    duration_ms, event_count, tool_call_count, failed_tool_call_count, agent_message_count,
                    token_usage, cost, error, metadata
                )
                VALUES (
                    %(run_id)s, %(title)s, %(status)s, %(question)s, %(conversation_id)s, %(user_id)s,
                    %(started_at)s, %(completed_at)s, %(duration_ms)s, %(event_count)s,
                    %(tool_call_count)s, %(failed_tool_call_count)s, %(agent_message_count)s,
                    %(token_usage)s, %(cost)s, %(error)s, %(metadata)s
                )
                ON CONFLICT (run_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    status = EXCLUDED.status,
                    question = EXCLUDED.question,
                    conversation_id = EXCLUDED.conversation_id,
                    user_id = EXCLUDED.user_id,
                    started_at = EXCLUDED.started_at,
                    completed_at = EXCLUDED.completed_at,
                    duration_ms = EXCLUDED.duration_ms,
                    event_count = EXCLUDED.event_count,
                    tool_call_count = EXCLUDED.tool_call_count,
                    failed_tool_call_count = EXCLUDED.failed_tool_call_count,
                    agent_message_count = EXCLUDED.agent_message_count,
                    token_usage = EXCLUDED.token_usage,
                    cost = EXCLUDED.cost,
                    error = EXCLUDED.error,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """,
                _trace_params(trace),
            )

    def list_traces(self, *, limit: int = 50) -> list[RunTrace]:
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM {POSTGRES_TRACE_TABLE}
                ORDER BY COALESCE(completed_at, started_at, created_at) DESC
                LIMIT %(limit)s
                """,
                {"limit": limit},
            ).fetchall()
        return [_trace_from_row(row) for row in rows]

    def get_trace(self, run_id: str) -> RunTrace | None:
        with _connect(self.database_url) as conn:
            row = conn.execute(f"SELECT * FROM {POSTGRES_TRACE_TABLE} WHERE run_id = %(run_id)s", {"run_id": run_id}).fetchone()
        return _trace_from_row(row) if row else None

    def list_conversation_run_ids(self, conversation_id: str, *, limit: int = 8) -> list[str]:
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"""
                SELECT run_id
                FROM (
                    SELECT run_id, COALESCE(started_at, completed_at, created_at) AS sort_at
                    FROM {POSTGRES_TRACE_TABLE}
                    WHERE run_id = %(conversation_id)s
                       OR conversation_id = %(conversation_id)s
                       OR metadata ->> 'continuation_of' = %(conversation_id)s
                    ORDER BY sort_at DESC
                    LIMIT %(limit)s
                ) recent_runs
                ORDER BY sort_at ASC
                """,
                {"conversation_id": conversation_id, "limit": limit},
            ).fetchall()
        run_ids = []
        seen = set()
        for row in rows:
            run_id = str(row["run_id"])
            if run_id in seen:
                continue
            seen.add(run_id)
            run_ids.append(run_id)
        return run_ids

    def delete_trace(self, run_id: str) -> int:
        with _connect(self.database_url) as conn:
            cursor = conn.execute(f"DELETE FROM {POSTGRES_TRACE_TABLE} WHERE run_id = %(run_id)s", {"run_id": run_id})
            return cursor.rowcount or 0

    def clear_traces(self) -> int:
        with _connect(self.database_url) as conn:
            cursor = conn.execute(f"DELETE FROM {POSTGRES_TRACE_TABLE}")
            return cursor.rowcount or 0


class PostgresRunEventStore(RunEventStore):
    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_EVENT_TABLE} (
                    id BIGSERIAL PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    event_index INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL,
                    event JSONB NOT NULL,
                    UNIQUE (run_id, event_index)
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_EVENT_TABLE}_run ON {POSTGRES_EVENT_TABLE} (run_id, event_index)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_EVENT_TABLE}_type ON {POSTGRES_EVENT_TABLE} (event_type)")

    def save_events(self, *, run_id: str, events: list[Any]) -> int:
        with _connect(self.database_url) as conn:
            conn.execute(f"DELETE FROM {POSTGRES_EVENT_TABLE} WHERE run_id = %(run_id)s", {"run_id": run_id})
            for index, event in enumerate(events):
                self._insert_event(conn, run_id=run_id, event_index=index, event=event)
        return len(events)

    def upsert_events(self, *, run_id: str, events: list[Any]) -> int:
        return self.save_events(run_id=run_id, events=events)

    def list_events(self, run_id: str) -> list[Any]:
        from backend.exploration.run_service import ExplorationRunEvent

        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"""
                SELECT event
                FROM {POSTGRES_EVENT_TABLE}
                WHERE run_id = %(run_id)s
                ORDER BY event_index ASC
                """,
                {"run_id": run_id},
            ).fetchall()
        return [
            ExplorationRunEvent(
                type=str(row["event"]["type"]),
                run_id=str(row["event"]["run_id"]),
                payload=dict(row["event"].get("payload") or {}),
                created_at=_iso(row["event"]["created_at"]),
            )
            for row in rows
        ]

    def delete_events(self, run_id: str) -> int:
        with _connect(self.database_url) as conn:
            cursor = conn.execute(f"DELETE FROM {POSTGRES_EVENT_TABLE} WHERE run_id = %(run_id)s", {"run_id": run_id})
            return cursor.rowcount or 0

    def clear_events(self) -> int:
        with _connect(self.database_url) as conn:
            cursor = conn.execute(f"DELETE FROM {POSTGRES_EVENT_TABLE}")
            return cursor.rowcount or 0

    def _insert_event(self, conn: Any, *, run_id: str, event_index: int, event: Any) -> None:
        payload = asdict(event) if hasattr(event, "__dataclass_fields__") else dict(event)
        conn.execute(
            f"""
            INSERT INTO {POSTGRES_EVENT_TABLE} (run_id, event_index, event_type, payload, created_at, event)
            VALUES (%(run_id)s, %(event_index)s, %(event_type)s, %(payload)s, %(created_at)s, %(event)s)
            ON CONFLICT (run_id, event_index) DO UPDATE SET
                event_type = EXCLUDED.event_type,
                payload = EXCLUDED.payload,
                created_at = EXCLUDED.created_at,
                event = EXCLUDED.event
            """,
            {
                "run_id": run_id,
                "event_index": event_index,
                "event_type": payload["type"],
                "payload": _jsonb(payload.get("payload") or {}),
                "created_at": payload["created_at"],
                "event": _jsonb(payload),
            },
        )


class PostgresThreadStore(ThreadStore):
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
                    codex_thread_id TEXT,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )
                """
            )
            conn.execute(f"ALTER TABLE {POSTGRES_THREAD_TABLE} ADD COLUMN IF NOT EXISTS tenant_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_THREAD_TABLE} ADD COLUMN IF NOT EXISTS workspace_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_THREAD_TABLE} ADD COLUMN IF NOT EXISTS codex_thread_id TEXT")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_TURN_TABLE} (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES {POSTGRES_THREAD_TABLE}(id) ON DELETE CASCADE,
                    input_kind TEXT NOT NULL,
                    question TEXT NOT NULL,
                    status TEXT NOT NULL,
                    run_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                    created_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ,
                    codex_thread_id TEXT,
                    codex_turn_id TEXT,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )
                """
            )
            conn.execute(f"ALTER TABLE {POSTGRES_TURN_TABLE} ADD COLUMN IF NOT EXISTS codex_thread_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_TURN_TABLE} ADD COLUMN IF NOT EXISTS codex_turn_id TEXT")
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_RUN_TABLE} (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES {POSTGRES_THREAD_TABLE}(id) ON DELETE CASCADE,
                    turn_id TEXT NOT NULL REFERENCES {POSTGRES_TURN_TABLE}(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    item_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_ITEM_TABLE} (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES {POSTGRES_THREAD_TABLE}(id) ON DELETE CASCADE,
                    turn_id TEXT NOT NULL REFERENCES {POSTGRES_TURN_TABLE}(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES {POSTGRES_RUN_TABLE}(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (
                    codex_item_id TEXT PRIMARY KEY,
                    codex_thread_id TEXT,
                    codex_turn_id TEXT,
                    item_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    genbi_thread_id TEXT REFERENCES {POSTGRES_THREAD_TABLE}(id) ON DELETE CASCADE,
                    genbi_turn_id TEXT REFERENCES {POSTGRES_TURN_TABLE}(id) ON DELETE SET NULL,
                    genbi_run_id TEXT REFERENCES {POSTGRES_RUN_TABLE}(id) ON DELETE SET NULL
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_updated ON {POSTGRES_THREAD_TABLE} (updated_at DESC NULLS LAST)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_product ON {POSTGRES_THREAD_TABLE} (product_kind)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_codex ON {POSTGRES_THREAD_TABLE} (codex_thread_id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_THREAD_TABLE}_tenant_user ON {POSTGRES_THREAD_TABLE} (tenant_id, user_id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_TURN_TABLE}_thread ON {POSTGRES_TURN_TABLE} (thread_id, created_at)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_TURN_TABLE}_codex ON {POSTGRES_TURN_TABLE} (codex_thread_id, codex_turn_id)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_RUN_TABLE}_thread ON {POSTGRES_RUN_TABLE} (thread_id, started_at)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_ITEM_TABLE}_run ON {POSTGRES_ITEM_TABLE} (run_id, created_at)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_ITEM_TABLE}_thread ON {POSTGRES_ITEM_TABLE} (thread_id, created_at)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_CODEX_ITEM_PROJECTION_TABLE}_thread ON {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (genbi_thread_id, created_at)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_CODEX_ITEM_PROJECTION_TABLE}_turn ON {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (codex_thread_id, codex_turn_id)")

    def _write_state(self, state: dict[str, Any]) -> None:
        with _connect(self.database_url) as conn:
            for thread in state["threads"].values():
                conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_THREAD_TABLE} (
                        id, product_kind, title, tenant_id, user_id, workspace_id, codex_thread_id,
                        status, created_at, updated_at, metadata
                    )
                    VALUES (
                        %(id)s, %(product_kind)s, %(title)s, %(tenant_id)s, %(user_id)s, %(workspace_id)s,
                        %(codex_thread_id)s, %(status)s, %(created_at)s, %(updated_at)s, %(metadata)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        product_kind = EXCLUDED.product_kind,
                        title = EXCLUDED.title,
                        tenant_id = EXCLUDED.tenant_id,
                        user_id = EXCLUDED.user_id,
                        workspace_id = EXCLUDED.workspace_id,
                        codex_thread_id = EXCLUDED.codex_thread_id,
                        status = EXCLUDED.status,
                        updated_at = EXCLUDED.updated_at,
                        metadata = EXCLUDED.metadata
                    """,
                    _thread_params(thread),
                )
            for turn in state["turns"].values():
                conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_TURN_TABLE} (
                        id, thread_id, input_kind, question, status, run_ids, created_at, updated_at,
                        codex_thread_id, codex_turn_id, metadata
                    )
                    VALUES (
                        %(id)s, %(thread_id)s, %(input_kind)s, %(question)s, %(status)s, %(run_ids)s,
                        %(created_at)s, %(updated_at)s, %(codex_thread_id)s, %(codex_turn_id)s, %(metadata)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        input_kind = EXCLUDED.input_kind,
                        question = EXCLUDED.question,
                        status = EXCLUDED.status,
                        run_ids = EXCLUDED.run_ids,
                        updated_at = EXCLUDED.updated_at,
                        codex_thread_id = EXCLUDED.codex_thread_id,
                        codex_turn_id = EXCLUDED.codex_turn_id,
                        metadata = EXCLUDED.metadata
                    """,
                    _turn_params(turn),
                )
            for run in state["runs"].values():
                conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_RUN_TABLE} (
                        id, thread_id, turn_id, status, started_at, completed_at, event_count, item_count, error, metadata
                    )
                    VALUES (
                        %(id)s, %(thread_id)s, %(turn_id)s, %(status)s, %(started_at)s, %(completed_at)s,
                        %(event_count)s, %(item_count)s, %(error)s, %(metadata)s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        completed_at = EXCLUDED.completed_at,
                        event_count = EXCLUDED.event_count,
                        item_count = EXCLUDED.item_count,
                        error = EXCLUDED.error,
                        metadata = EXCLUDED.metadata
                    """,
                    _run_record_params(run),
                )
                conn.execute(f"DELETE FROM {POSTGRES_ITEM_TABLE} WHERE run_id = %(run_id)s", {"run_id": run.id})
                conn.execute(f"DELETE FROM {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} WHERE genbi_run_id = %(run_id)s", {"run_id": run.id})
            for item in state["items"]:
                conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_ITEM_TABLE} (id, thread_id, turn_id, run_id, kind, event_type, payload, created_at)
                    VALUES (%(id)s, %(thread_id)s, %(turn_id)s, %(run_id)s, %(kind)s, %(event_type)s, %(payload)s, %(created_at)s)
                    ON CONFLICT (id) DO UPDATE SET
                        kind = EXCLUDED.kind,
                        event_type = EXCLUDED.event_type,
                        payload = EXCLUDED.payload,
                        created_at = EXCLUDED.created_at
                    """,
                    _item_params(item),
                )
            for item in state["codex_item_projections"]:
                conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_CODEX_ITEM_PROJECTION_TABLE} (
                        codex_item_id, codex_thread_id, codex_turn_id, item_type, status, payload,
                        created_at, completed_at, genbi_thread_id, genbi_turn_id, genbi_run_id
                    )
                    VALUES (
                        %(codex_item_id)s, %(codex_thread_id)s, %(codex_turn_id)s, %(item_type)s, %(status)s, %(payload)s,
                        %(created_at)s, %(completed_at)s, %(genbi_thread_id)s, %(genbi_turn_id)s, %(genbi_run_id)s
                    )
                    ON CONFLICT (codex_item_id) DO UPDATE SET
                        codex_thread_id = EXCLUDED.codex_thread_id,
                        codex_turn_id = EXCLUDED.codex_turn_id,
                        item_type = EXCLUDED.item_type,
                        status = EXCLUDED.status,
                        payload = EXCLUDED.payload,
                        completed_at = EXCLUDED.completed_at,
                        genbi_thread_id = EXCLUDED.genbi_thread_id,
                        genbi_turn_id = EXCLUDED.genbi_turn_id,
                        genbi_run_id = EXCLUDED.genbi_run_id
                    """,
                    _codex_item_projection_params(item),
                )

    def _read_state(self) -> dict[str, Any]:
        with _connect(self.database_url) as conn:
            threads = {
                str(row["id"]): _thread_record_from_row(row)
                for row in conn.execute(f"SELECT * FROM {POSTGRES_THREAD_TABLE}").fetchall()
            }
            turns = {
                str(row["id"]): _turn_record_from_row(row)
                for row in conn.execute(f"SELECT * FROM {POSTGRES_TURN_TABLE}").fetchall()
            }
            runs = {
                str(row["id"]): _run_record_from_row(row)
                for row in conn.execute(f"SELECT * FROM {POSTGRES_RUN_TABLE}").fetchall()
            }
            items = [_item_record_from_row(row) for row in conn.execute(f"SELECT * FROM {POSTGRES_ITEM_TABLE}").fetchall()]
            codex_item_projections = [
                _codex_item_projection_from_row(row)
                for row in conn.execute(f"SELECT * FROM {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}").fetchall()
            ]
        return {"threads": threads, "turns": turns, "runs": runs, "items": items, "codex_item_projections": codex_item_projections}

    def clear(self) -> int:
        with _connect(self.database_url) as conn:
            item_count = conn.execute(f"DELETE FROM {POSTGRES_ITEM_TABLE}").rowcount or 0
            conn.execute(f"DELETE FROM {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}")
            conn.execute(f"DELETE FROM {POSTGRES_RUN_TABLE}")
            conn.execute(f"DELETE FROM {POSTGRES_TURN_TABLE}")
            conn.execute(f"DELETE FROM {POSTGRES_THREAD_TABLE}")
            return item_count


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
                    source_run_id TEXT NOT NULL,
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
                    source_run_id TEXT NOT NULL,
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
        source_run_id: str,
        source_execution_attempt_id: str | None = None,
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
        execution_attempt_id = (source_execution_attempt_id or source_run_id).strip()
        for field_name, value in {
            "asset_id": asset_id,
            "artifact_version_id": artifact_version_id,
            "source_task_id": source_task_id,
            "source_task_title": source_task_title,
            "source_conversation_id": source_conversation_id,
            "source_execution_attempt_id": execution_attempt_id,
            "source_run_id": source_run_id,
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
        record_metadata.setdefault("source_execution_attempt_id", execution_attempt_id)
        if codex_lineage:
            record_metadata["codex_lineage"] = codex_lineage
        record = AnalysisAssetRecord(
            assetId=asset_id.strip(),
            artifactVersionId=artifact_version_id.strip(),
            sourceTaskId=source_task_id.strip(),
            sourceTaskTitle=source_task_title.strip(),
            sourceConversationId=source_conversation_id.strip(),
            sourceExecutionAttemptId=execution_attempt_id,
            sourceRunId=source_run_id.strip(),
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
                        source_run_id, source_codex_thread_id, source_codex_turn_id, source_codex_item_id,
                        asset_type, title, label, description, visibility, status, latest_version, file_id,
                        reopen_context, metadata, created_at, updated_at
                    )
                    VALUES (
                        %(asset_id)s, %(artifact_version_id)s, %(source_task_id)s, %(source_task_title)s, %(source_conversation_id)s,
                        %(source_run_id)s, %(source_codex_thread_id)s, %(source_codex_turn_id)s, %(source_codex_item_id)s,
                        %(asset_type)s, %(title)s, %(label)s, %(description)s, %(visibility)s, %(status)s, %(latest_version)s,
                        %(file_id)s, %(reopen_context)s, %(metadata)s, %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT (asset_id) DO UPDATE SET
                        artifact_version_id = EXCLUDED.artifact_version_id,
                        source_task_id = EXCLUDED.source_task_id,
                        source_task_title = EXCLUDED.source_task_title,
                        source_conversation_id = EXCLUDED.source_conversation_id,
                        source_run_id = EXCLUDED.source_run_id,
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
                        source_conversation_id, source_run_id, codex_thread_id, codex_turn_id, codex_item_id,
                        created_at, updated_at
                    )
                    VALUES (
                        %(artifact_id)s, %(artifact_version_id)s, %(asset_id)s, %(asset_type)s, %(title)s, %(source_task_id)s,
                        %(source_conversation_id)s, %(source_run_id)s, %(codex_thread_id)s, %(codex_turn_id)s,
                        %(codex_item_id)s, %(created_at)s, %(updated_at)s
                    )
                    ON CONFLICT (artifact_id) DO UPDATE SET
                        artifact_version_id = EXCLUDED.artifact_version_id,
                        asset_id = EXCLUDED.asset_id,
                        asset_type = EXCLUDED.asset_type,
                        title = EXCLUDED.title,
                        source_task_id = EXCLUDED.source_task_id,
                        source_conversation_id = EXCLUDED.source_conversation_id,
                        source_run_id = EXCLUDED.source_run_id,
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
                source_execution_attempt_id=record.sourceExecutionAttemptId,
                source_run_id=record.sourceRunId,
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


class PostgresInteractiveReportStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_INTERACTIVE_REPORT_TABLE} (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    subtitle TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    renderer TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    source_thread_id TEXT NOT NULL,
                    source_turn_id TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    latest_version INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} (
                    report_id TEXT NOT NULL REFERENCES {POSTGRES_INTERACTIVE_REPORT_TABLE}(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    source_thread_id TEXT NOT NULL,
                    source_turn_id TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    document JSONB NOT NULL,
                    filters JSONB NOT NULL,
                    queries JSONB NOT NULL,
                    chart_specs JSONB NOT NULL,
                    grid_specs JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (report_id, version)
                )
                """
            )
            conn.execute(f"ALTER TABLE {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} ADD COLUMN IF NOT EXISTS source_thread_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} ADD COLUMN IF NOT EXISTS source_turn_id TEXT")
            conn.execute(f"ALTER TABLE {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} ADD COLUMN IF NOT EXISTS source_run_id TEXT")
            conn.execute(
                f"""
                UPDATE {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} AS version
                SET source_thread_id = report.source_thread_id,
                    source_turn_id = report.source_turn_id,
                    source_run_id = report.source_run_id
                FROM {POSTGRES_INTERACTIVE_REPORT_TABLE} AS report
                WHERE version.report_id = report.id
                  AND (version.source_thread_id IS NULL OR version.source_turn_id IS NULL OR version.source_run_id IS NULL)
                """
            )
            conn.execute(f"ALTER TABLE {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} ALTER COLUMN source_thread_id SET NOT NULL")
            conn.execute(f"ALTER TABLE {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} ALTER COLUMN source_turn_id SET NOT NULL")
            conn.execute(f"ALTER TABLE {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} ALTER COLUMN source_run_id SET NOT NULL")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_INTERACTIVE_REPORT_TABLE}_owner_updated ON {POSTGRES_INTERACTIVE_REPORT_TABLE} (owner_id, updated_at DESC)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_INTERACTIVE_REPORT_TABLE}_thread ON {POSTGRES_INTERACTIVE_REPORT_TABLE} (source_thread_id, updated_at DESC)")

    def save_report(self, payload: dict[str, Any]) -> tuple[InteractiveReportRecord, InteractiveReportVersionRecord]:
        from backend.analysis.interactive_report_store import _validate_payload

        _validate_payload(payload)
        report_id = str(payload["id"]).strip()
        expected_version = payload.get("expectedVersion")
        with _connect(self.database_url) as conn:
            with conn.transaction():
                existing = conn.execute(
                    f"SELECT * FROM {POSTGRES_INTERACTIVE_REPORT_TABLE} WHERE id = %(id)s FOR UPDATE",
                    {"id": report_id},
                ).fetchone()
                current_version = int(existing["latest_version"]) if existing else 0
                if (existing and expected_version != current_version) or (not existing and expected_version not in (None, 0)):
                    raise InteractiveReportVersionConflict("interactive_report_version_conflict")

                next_version = current_version + 1
                report_params = _interactive_report_params(payload, latest_version=next_version)
                if existing:
                    conn.execute(
                        f"""
                        UPDATE {POSTGRES_INTERACTIVE_REPORT_TABLE}
                        SET title = %(title)s, subtitle = %(subtitle)s, artifact_type = %(artifact_type)s,
                            renderer = %(renderer)s, owner_id = %(owner_id)s, source_thread_id = %(source_thread_id)s,
                            source_turn_id = %(source_turn_id)s, source_run_id = %(source_run_id)s,
                            latest_version = %(latest_version)s, updated_at = now()
                        WHERE id = %(id)s
                        """,
                        report_params,
                    )
                else:
                    conn.execute(
                        f"""
                        INSERT INTO {POSTGRES_INTERACTIVE_REPORT_TABLE} (
                            id, title, subtitle, artifact_type, renderer, owner_id, source_thread_id,
                            source_turn_id, source_run_id, latest_version
                        ) VALUES (
                            %(id)s, %(title)s, %(subtitle)s, %(artifact_type)s, %(renderer)s, %(owner_id)s,
                            %(source_thread_id)s, %(source_turn_id)s, %(source_run_id)s, %(latest_version)s
                        )
                        """,
                        report_params,
                    )
                conn.execute(
                    f"""
                    INSERT INTO {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} (
                        report_id, version, source_thread_id, source_turn_id, source_run_id,
                        document, filters, queries, chart_specs, grid_specs
                    ) VALUES (
                        %(report_id)s, %(version)s, %(source_thread_id)s, %(source_turn_id)s, %(source_run_id)s,
                        %(document)s, %(filters)s, %(queries)s, %(chart_specs)s, %(grid_specs)s
                    )
                    """,
                    _interactive_report_version_params(payload, version=next_version),
                )
                report_row = conn.execute(f"SELECT * FROM {POSTGRES_INTERACTIVE_REPORT_TABLE} WHERE id = %(id)s", {"id": report_id}).fetchone()
                version_row = conn.execute(
                    f"SELECT * FROM {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} WHERE report_id = %(report_id)s AND version = %(version)s",
                    {"report_id": report_id, "version": next_version},
                ).fetchone()
        return _interactive_report_from_row(report_row), _interactive_report_version_from_row(version_row)

    def list_reports(self, *, owner_id: str | None = None, limit: int = 50) -> list[InteractiveReportRecord]:
        where = "WHERE owner_id = %(owner_id)s" if owner_id else ""
        params: dict[str, Any] = {"limit": limit}
        if owner_id:
            params["owner_id"] = owner_id
        with _connect(self.database_url) as conn:
            rows = conn.execute(
                f"SELECT * FROM {POSTGRES_INTERACTIVE_REPORT_TABLE} {where} ORDER BY updated_at DESC LIMIT %(limit)s",
                params,
            ).fetchall()
        return [_interactive_report_from_row(row) for row in rows]

    def get_report(self, report_id: str, *, version: int | None = None) -> tuple[InteractiveReportRecord, InteractiveReportVersionRecord] | None:
        with _connect(self.database_url) as conn:
            report_row = conn.execute(f"SELECT * FROM {POSTGRES_INTERACTIVE_REPORT_TABLE} WHERE id = %(id)s", {"id": report_id}).fetchone()
            if not report_row:
                return None
            target_version = version if version is not None else int(report_row["latest_version"])
            version_row = conn.execute(
                f"SELECT * FROM {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} WHERE report_id = %(report_id)s AND version = %(version)s",
                {"report_id": report_id, "version": target_version},
            ).fetchone()
        return (_interactive_report_from_row(report_row), _interactive_report_version_from_row(version_row)) if version_row else None

    def list_versions(self, report_id: str) -> list[InteractiveReportVersionRecord] | None:
        with _connect(self.database_url) as conn:
            exists = conn.execute(f"SELECT 1 FROM {POSTGRES_INTERACTIVE_REPORT_TABLE} WHERE id = %(id)s", {"id": report_id}).fetchone()
            if not exists:
                return None
            rows = conn.execute(
                f"SELECT * FROM {POSTGRES_INTERACTIVE_REPORT_VERSION_TABLE} WHERE report_id = %(report_id)s ORDER BY version DESC",
                {"report_id": report_id},
            ).fetchall()
        return [_interactive_report_version_from_row(row) for row in rows]


class PostgresReportQueryAuditStore:
    """Append-only audit metadata for server-owned report queries; result rows are never stored."""

    def __init__(self, database_url: str) -> None:
        self.database_url = _normalize_postgres_url(database_url)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {POSTGRES_REPORT_QUERY_AUDIT_TABLE} (
                    id TEXT PRIMARY KEY,
                    query_ref TEXT NOT NULL,
                    filters JSONB NOT NULL,
                    row_count INTEGER NOT NULL,
                    elapsed_ms INTEGER NOT NULL,
                    truncated BOOLEAN NOT NULL,
                    source TEXT NOT NULL,
                    thread_id TEXT,
                    run_id TEXT,
                    user_id TEXT,
                    data_egress_authorized BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_REPORT_QUERY_AUDIT_TABLE}_run "
                f"ON {POSTGRES_REPORT_QUERY_AUDIT_TABLE} (run_id, created_at DESC)"
            )

    def record_query(
        self,
        *,
        query_ref: str,
        filters: dict[str, str],
        response: Any,
        context: dict[str, Any],
    ) -> None:
        with _connect(self.database_url) as conn:
            conn.execute(
                f"""
                INSERT INTO {POSTGRES_REPORT_QUERY_AUDIT_TABLE} (
                    id, query_ref, filters, row_count, elapsed_ms, truncated, source,
                    thread_id, run_id, user_id, data_egress_authorized
                ) VALUES (
                    %(id)s, %(query_ref)s, %(filters)s, %(row_count)s, %(elapsed_ms)s, %(truncated)s, %(source)s,
                    %(thread_id)s, %(run_id)s, %(user_id)s, %(data_egress_authorized)s
                )
                """,
                {
                    "id": f"query_audit_{uuid4().hex}",
                    "query_ref": query_ref,
                    "filters": _jsonb(filters),
                    "row_count": response.rowCount,
                    "elapsed_ms": response.elapsedMs,
                    "truncated": response.truncated,
                    "source": str(context.get("source") or "unspecified"),
                    "thread_id": context.get("thread_id"),
                    "run_id": context.get("run_id"),
                    "user_id": context.get("user_id"),
                    "data_egress_authorized": context.get("data_egress_authorized") is True,
                },
            )


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
                    run_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_KNOWLEDGE_TABLE}_created ON {POSTGRES_KNOWLEDGE_TABLE} (created_at DESC)")
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{POSTGRES_KNOWLEDGE_TABLE}_run ON {POSTGRES_KNOWLEDGE_TABLE} (run_id)")

    def save_verified_knowledge(
        self,
        *,
        title: str,
        question: str,
        conclusion: str,
        scope: str,
        verification: str,
        evidence_refs: list[str],
        run_id: str | None = None,
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
            run_id=run_id.strip() if run_id else None,
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
                    id, title, question, conclusion, scope, verification, evidence_refs, run_id, created_at, metadata
                )
                VALUES (
                    %(id)s, %(title)s, %(question)s, %(conclusion)s, %(scope)s, %(verification)s,
                    %(evidence_refs)s, %(run_id)s, %(created_at)s, %(metadata)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    question = EXCLUDED.question,
                    conclusion = EXCLUDED.conclusion,
                    scope = EXCLUDED.scope,
                    verification = EXCLUDED.verification,
                    evidence_refs = EXCLUDED.evidence_refs,
                    run_id = EXCLUDED.run_id,
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
        run_id: str | None = None,
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
            run_id=run_id.strip() if run_id else current.run_id,
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
        return [{"name": str(row["tag"]), "count": int(row["count"]), "group": "未分组"} for row in rows]

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


def _trace_params(trace: RunTrace) -> dict[str, Any]:
    return {
        "run_id": trace.run_id,
        "title": trace.title,
        "status": trace.status,
        "question": trace.question,
        "conversation_id": trace.conversation_id,
        "user_id": trace.user_id,
        "started_at": trace.started_at,
        "completed_at": trace.completed_at,
        "duration_ms": trace.duration_ms,
        "event_count": trace.event_count,
        "tool_call_count": trace.tool_call_count,
        "failed_tool_call_count": trace.failed_tool_call_count,
        "agent_message_count": trace.agent_message_count,
        "token_usage": _jsonb(asdict(trace.token_usage)),
        "cost": _jsonb(asdict(trace.cost)),
        "error": trace.error,
        "metadata": _jsonb(trace.metadata),
    }


def _knowledge_params(record: KnowledgeRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "title": record.title,
        "question": record.question,
        "conclusion": record.conclusion,
        "scope": record.scope,
        "verification": record.verification,
        "evidence_refs": _jsonb(record.evidence_refs),
        "run_id": record.run_id,
        "created_at": record.created_at,
        "metadata": _jsonb(record.metadata),
    }


def _thread_params(record: ThreadRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "product_kind": record.productKind,
        "title": record.title,
        "tenant_id": record.tenantId,
        "user_id": record.userId,
        "workspace_id": record.workspaceId,
        "codex_thread_id": record.codexThreadId,
        "status": record.status,
        "created_at": record.createdAt,
        "updated_at": record.updatedAt,
        "metadata": _jsonb(record.metadata),
    }


def _turn_params(record: TurnRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "thread_id": record.threadId,
        "input_kind": record.inputKind,
        "question": record.question,
        "status": record.status,
        "run_ids": _jsonb(record.runIds),
        "created_at": record.createdAt,
        "updated_at": record.updatedAt,
        "codex_thread_id": record.codexThreadId,
        "codex_turn_id": record.codexTurnId,
        "metadata": _jsonb(record.metadata),
    }


def _run_record_params(record: RunRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "thread_id": record.threadId,
        "turn_id": record.turnId,
        "status": record.status,
        "started_at": record.startedAt,
        "completed_at": record.completedAt,
        "event_count": record.eventCount,
        "item_count": record.itemCount,
        "error": record.error,
        "metadata": _jsonb(record.metadata),
    }


def _item_params(record: ItemRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "thread_id": record.threadId,
        "turn_id": record.turnId,
        "run_id": record.runId,
        "kind": record.kind,
        "event_type": record.eventType,
        "payload": _jsonb(record.payload),
        "created_at": record.createdAt,
    }


def _codex_item_projection_params(record: CodexItemProjectionRecord) -> dict[str, Any]:
    return {
        "codex_item_id": record.codexItemId,
        "codex_thread_id": record.codexThreadId,
        "codex_turn_id": record.codexTurnId,
        "item_type": record.itemType,
        "status": record.status,
        "payload": _jsonb(record.payload),
        "created_at": record.createdAt,
        "completed_at": record.completedAt,
        "genbi_thread_id": record.genbiThreadId,
        "genbi_turn_id": record.genbiTurnId,
        "genbi_run_id": record.genbiRunId,
    }


def _analysis_asset_params(record: AnalysisAssetRecord) -> dict[str, Any]:
    return {
        "asset_id": record.assetId,
        "artifact_version_id": record.artifactVersionId,
        "source_task_id": record.sourceTaskId,
        "source_task_title": record.sourceTaskTitle,
        "source_conversation_id": record.sourceConversationId,
        "source_run_id": record.sourceRunId,
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
        "source_run_id": record.sourceRunId,
        "codex_thread_id": record.codexThreadId,
        "codex_turn_id": record.codexTurnId,
        "codex_item_id": record.codexItemId,
        "created_at": record.createdAt,
        "updated_at": record.updatedAt,
    }


def _interactive_report_params(payload: dict[str, Any], *, latest_version: int) -> dict[str, Any]:
    source = dict(payload["source"])
    execution_attempt_id = str(source.get("executionAttemptId") or source.get("runId")).strip()
    return {
        "id": str(payload["id"]).strip(),
        "title": str(payload["title"]).strip(),
        "subtitle": str(payload["subtitle"]).strip(),
        "artifact_type": str(payload["artifactType"]).strip(),
        "renderer": str(payload["renderer"]).strip(),
        "owner_id": str(payload["ownerId"]).strip(),
        "source_thread_id": str(source["threadId"]).strip(),
        "source_turn_id": str(source["turnId"]).strip(),
        "source_run_id": execution_attempt_id,
        "latest_version": latest_version,
    }


def _interactive_report_version_params(payload: dict[str, Any], *, version: int) -> dict[str, Any]:
    source = dict(payload["source"])
    execution_attempt_id = str(source.get("executionAttemptId") or source.get("runId")).strip()
    return {
        "report_id": str(payload["id"]).strip(),
        "version": version,
        "source_thread_id": str(source["threadId"]).strip(),
        "source_turn_id": str(source["turnId"]).strip(),
        "source_run_id": execution_attempt_id,
        "document": _jsonb(payload["document"]),
        "filters": _jsonb(payload["filters"]),
        "queries": _jsonb(payload["queries"]),
        "chart_specs": _jsonb(payload["chartSpecs"]),
        "grid_specs": _jsonb(payload["gridSpecs"]),
    }


def _trace_from_row(row: dict[str, Any]) -> RunTrace:
    return RunTrace(
        run_id=str(row["run_id"]),
        title=row.get("title"),
        status=str(row["status"]),
        question=str(row["question"]),
        conversation_id=row.get("conversation_id"),
        user_id=row.get("user_id"),
        started_at=_iso(row.get("started_at")),
        completed_at=_iso(row.get("completed_at")),
        duration_ms=row.get("duration_ms"),
        event_count=int(row.get("event_count") or 0),
        tool_call_count=int(row.get("tool_call_count") or 0),
        failed_tool_call_count=int(row.get("failed_tool_call_count") or 0),
        agent_message_count=int(row.get("agent_message_count") or 0),
        token_usage=TokenUsage(**dict(row.get("token_usage") or {})),
        cost=RunCost(**dict(row.get("cost") or {})),
        error=row.get("error"),
        metadata=dict(row.get("metadata") or {}),
    )


def _thread_record_from_row(row: dict[str, Any]) -> ThreadRecord:
    return ThreadRecord(
        id=str(row["id"]),
        productKind=str(row["product_kind"]),  # type: ignore[arg-type]
        title=row.get("title"),
        tenantId=row.get("tenant_id"),
        userId=row.get("user_id"),
        workspaceId=row.get("workspace_id"),
        codexThreadId=row.get("codex_thread_id"),
        status=str(row["status"]),
        createdAt=_iso(row.get("created_at")) or "",
        updatedAt=_iso(row.get("updated_at")) or "",
        metadata=dict(row.get("metadata") or {}),
    )


def _turn_record_from_row(row: dict[str, Any]) -> TurnRecord:
    return TurnRecord(
        id=str(row["id"]),
        threadId=str(row["thread_id"]),
        inputKind=str(row["input_kind"]),  # type: ignore[arg-type]
        question=str(row["question"]),
        status=str(row["status"]),
        runIds=[str(item) for item in row.get("run_ids") or []],
        createdAt=_iso(row.get("created_at")) or "",
        updatedAt=_iso(row.get("updated_at")) or "",
        codexThreadId=row.get("codex_thread_id"),
        codexTurnId=row.get("codex_turn_id"),
        metadata=dict(row.get("metadata") or {}),
    )


def _run_record_from_row(row: dict[str, Any]) -> RunRecord:
    return RunRecord(
        id=str(row["id"]),
        threadId=str(row["thread_id"]),
        turnId=str(row["turn_id"]),
        status=str(row["status"]),
        startedAt=_iso(row.get("started_at")),
        completedAt=_iso(row.get("completed_at")),
        eventCount=int(row.get("event_count") or 0),
        itemCount=int(row.get("item_count") or 0),
        error=row.get("error"),
        metadata=dict(row.get("metadata") or {}),
    )


def _item_record_from_row(row: dict[str, Any]) -> ItemRecord:
    return ItemRecord(
        id=str(row["id"]),
        threadId=str(row["thread_id"]),
        turnId=str(row["turn_id"]),
        runId=str(row["run_id"]),
        kind=str(row["kind"]),
        eventType=str(row["event_type"]),
        payload=dict(row.get("payload") or {}),
        createdAt=_iso(row.get("created_at")) or "",
    )


def _codex_item_projection_from_row(row: dict[str, Any]) -> CodexItemProjectionRecord:
    return CodexItemProjectionRecord(
        codexItemId=str(row["codex_item_id"]),
        codexThreadId=row.get("codex_thread_id"),
        codexTurnId=row.get("codex_turn_id"),
        itemType=str(row["item_type"]),
        status=str(row["status"]),
        payload=dict(row.get("payload") or {}),
        createdAt=_iso(row.get("created_at")) or "",
        completedAt=_iso(row.get("completed_at")),
        genbiThreadId=row.get("genbi_thread_id"),
        genbiTurnId=row.get("genbi_turn_id"),
        genbiRunId=row.get("genbi_run_id"),
    )


def _analysis_asset_from_row(row: dict[str, Any]) -> AnalysisAssetRecord:
    context_payload = dict(row.get("reopen_context") or {})
    metadata = dict(row.get("metadata") or {})
    source_run_id = str(row["source_run_id"])
    source_execution_attempt_id = str(metadata.get("source_execution_attempt_id") or source_run_id)
    context_payload.setdefault("sourceExecutionAttemptId", context_payload.get("sourceRunId") or source_execution_attempt_id)
    return AnalysisAssetRecord(
        assetId=str(row["asset_id"]),
        artifactVersionId=str(row["artifact_version_id"]),
        sourceTaskId=str(row["source_task_id"]),
        sourceTaskTitle=str(row["source_task_title"]),
        sourceConversationId=str(row["source_conversation_id"]),
        sourceExecutionAttemptId=source_execution_attempt_id,
        sourceRunId=source_run_id,
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
        artifactId=record.artifactVersionId,
        artifactVersionId=record.artifactVersionId,
        assetId=record.assetId,
        assetType=record.assetType,
        title=record.title,
        sourceTaskId=record.sourceTaskId,
        sourceConversationId=record.sourceConversationId,
        sourceExecutionAttemptId=record.sourceExecutionAttemptId,
        sourceRunId=record.sourceRunId,
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
        sourceExecutionAttemptId=str(row["source_run_id"]),
        sourceRunId=str(row["source_run_id"]),
        codexThreadId=row.get("codex_thread_id"),
        codexTurnId=row.get("codex_turn_id"),
        codexItemId=row.get("codex_item_id"),
        createdAt=_iso(row.get("created_at")) or "",
        updatedAt=_iso(row.get("updated_at")) or "",
    )


def _interactive_report_from_row(row: dict[str, Any]) -> InteractiveReportRecord:
    return InteractiveReportRecord(
        id=str(row["id"]),
        title=str(row["title"]),
        subtitle=str(row["subtitle"]),
        artifactType=str(row["artifact_type"]),
        renderer=str(row["renderer"]),
        ownerId=str(row["owner_id"]),
        sourceThreadId=str(row["source_thread_id"]),
        sourceTurnId=str(row["source_turn_id"]),
        sourceRunId=str(row["source_run_id"]),
        latestVersion=int(row["latest_version"]),
        createdAt=_iso(row["created_at"]) or "",
        updatedAt=_iso(row["updated_at"]) or "",
    )


def _interactive_report_version_from_row(row: dict[str, Any]) -> InteractiveReportVersionRecord:
    return InteractiveReportVersionRecord(
        reportId=str(row["report_id"]),
        version=int(row["version"]),
        sourceThreadId=str(row["source_thread_id"]),
        sourceTurnId=str(row["source_turn_id"]),
        sourceRunId=str(row["source_run_id"]),
        document=dict(row["document"] or {}),
        filters=list(row["filters"] or []),
        queries=dict(row["queries"] or {}),
        chartSpecs=dict(row["chart_specs"] or {}),
        gridSpecs=dict(row["grid_specs"] or {}),
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
        run_id=row.get("run_id"),
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
