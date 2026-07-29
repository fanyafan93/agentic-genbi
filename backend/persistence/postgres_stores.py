from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_trace_store import RunCost, RunTrace, RunTraceStore, TokenUsage, build_run_trace
from backend.resource_library.knowledge_store import KnowledgeRecord, KnowledgeStore


POSTGRES_TRACE_TABLE = "exploration_run_traces"
POSTGRES_EVENT_TABLE = "exploration_run_events"
POSTGRES_KNOWLEDGE_TABLE = "verified_knowledge"


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
