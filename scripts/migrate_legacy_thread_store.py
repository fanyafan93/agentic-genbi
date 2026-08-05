from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_projection_store import CodexItemProjectionRecord, CodexProjectionStore, TurnRecord
from backend.harness.session_catalog import SessionCatalog, SessionRecord
from backend.persistence.postgres_stores import (
    POSTGRES_CODEX_ITEM_PROJECTION_TABLE,
    POSTGRES_THREAD_TABLE,
    POSTGRES_TURN_TABLE,
    PostgresCodexProjectionBackend,
    PostgresSessionCatalogBackend,
    _connect,
    get_postgres_database_url,
)


@dataclass(frozen=True)
class LegacyMigrationStats:
    read_threads: int = 0
    read_turns: int = 0
    read_items: int = 0
    migrated_threads: int = 0
    migrated_turns: int = 0
    migrated_items: int = 0


def migrate_legacy_thread_store(
    legacy_path: Path,
    *,
    session_catalog: SessionCatalog,
    projection_store: CodexProjectionStore,
    dry_run: bool = True,
) -> LegacyMigrationStats:
    threads: list[SessionRecord] = []
    turns: list[TurnRecord] = []
    items: list[CodexItemProjectionRecord] = []

    for row in _read_legacy_rows(legacy_path):
        record_type = row.get("record_type")
        payload = dict(row.get("payload") or {})
        if record_type == "thread":
            threads.append(_session_from_legacy(payload))
        elif record_type == "turn":
            turns.append(_turn_from_legacy(payload))
        elif record_type == "codex_item_projection":
            items.append(_item_from_legacy(payload))

    read_thread_count = len(threads)
    read_turn_count = len(turns)
    read_item_count = len(items)

    threads = _backfill_session_titles_from_turns(threads, turns)
    items = _with_synthetic_user_items(turns, items)

    if dry_run:
        return LegacyMigrationStats(
            read_threads=len(threads),
            read_turns=len(turns),
            read_items=read_item_count,
        )

    for session in threads:
        if _has_methods(session_catalog.backend, "get_session", "insert_session", "update_session"):
            if session_catalog.backend.get_session(session.id) is None:
                session_catalog.backend.insert_session(session)
            else:
                session_catalog.backend.update_session(session)
            _force_session_timestamps(session_catalog.backend, session)
        else:
            session_catalog.register_session(
                session.id,
                product_kind=session.productKind,
                title=session.title,
                user_id=session.userId,
                status=session.status,
                metadata=session.metadata,
                codex_session_id=session.codexSessionId or session.id,
            )
    for turn in turns:
        if _has_methods(projection_store.backend, "upsert_turn"):
            projection_store.backend.upsert_turn(turn)
            _force_turn_timestamps(projection_store.backend, turn)
        else:
            projection_store.save_turn(
                session_id=turn.sessionId,
                turn_id=turn.id,
                input_kind=turn.inputKind,
                input_text=turn.inputText,
                status=turn.status,
                started_at=turn.startedAt,
                completed_at=turn.completedAt,
                metadata=turn.metadata,
                codex_session_id=turn.codexSessionId,
                codex_turn_id=turn.codexTurnId,
            )
    for item in items:
        projection_store.upsert_item(
            session_id=item.genbiSessionId or "",
            turn_id=item.genbiTurnId or "",
            codex_item_id=item.codexItemId,
            item_type=item.itemType,
            status=item.status,
            sequence=item.sequence,
            payload=item.payload,
            created_at=item.createdAt,
            completed_at=item.completedAt,
            codex_session_id=item.codexSessionId,
            codex_turn_id=item.codexTurnId,
        )
        if _has_methods(projection_store.backend, "upsert_item"):
            _force_item_timestamps(projection_store.backend, item)

    return LegacyMigrationStats(
        read_threads=read_thread_count,
        read_turns=read_turn_count,
        read_items=read_item_count,
        migrated_threads=len(threads),
        migrated_turns=len(turns),
        migrated_items=len(items),
    )


def _has_methods(target: Any, *names: str) -> bool:
    if target is None:
        return False
    return all(callable(getattr(target, name, None)) for name in names)


def _backfill_session_titles_from_turns(threads: list[SessionRecord], turns: list[TurnRecord]) -> list[SessionRecord]:
    first_questions_by_session: dict[str, str] = {}
    for turn in sorted(turns, key=lambda record: record.createdAt):
        question = _text(turn.inputText) or _text(turn.question)
        if question and turn.sessionId not in first_questions_by_session:
            first_questions_by_session[turn.sessionId] = question
    backfilled: list[SessionRecord] = []
    for session in threads:
        if session.title:
            backfilled.append(session)
            continue
        title = first_questions_by_session.get(session.id)
        if not title:
            backfilled.append(session)
            continue
        backfilled.append(
            SessionRecord(
                id=session.id,
                productKind=session.productKind,
                title=title,
                userId=session.userId,
                status=session.status,
                createdAt=session.createdAt,
                updatedAt=session.updatedAt,
                metadata={**session.metadata, "legacy_title_backfilled_from_turn": True},
                tenantId=session.tenantId,
                workspaceId=session.workspaceId,
                codexSessionId=session.codexSessionId,
            )
        )
    return backfilled


def _with_synthetic_user_items(
    turns: list[TurnRecord], items: list[CodexItemProjectionRecord]
) -> list[CodexItemProjectionRecord]:
    existing_user_item_turns = {
        (item.genbiSessionId, item.genbiTurnId)
        for item in items
        if item.itemType == "userMessage" and _text(item.payload.get("content"))
    }
    synthetic_items: list[CodexItemProjectionRecord] = []
    for turn in turns:
        if (turn.sessionId, turn.id) in existing_user_item_turns:
            continue
        content = _text(turn.inputText) or _text(turn.question)
        if not content:
            continue
        synthetic_items.append(
            CodexItemProjectionRecord(
                codexItemId=f"legacy_user_{turn.id}",
                codexSessionId=turn.codexSessionId,
                codexTurnId=turn.codexTurnId,
                itemType="userMessage",
                status="completed",
                sequence=-1,
                payload={
                    "content": content,
                    "codex_item_type": "userMessage",
                    "thread_id": turn.sessionId,
                    "conversation_id": turn.sessionId,
                    "turn_id": turn.id,
                    "legacy_thread_store_migration": True,
                    "synthetic_from_legacy_turn": True,
                },
                createdAt=turn.createdAt,
                completedAt=turn.startedAt or turn.createdAt,
                genbiSessionId=turn.sessionId,
                genbiTurnId=turn.id,
            )
        )
    return [*items, *synthetic_items]


def _force_session_timestamps(backend: Any, session: SessionRecord) -> None:
    database_url = getattr(backend, "database_url", None)
    if not database_url:
        return
    with _connect(database_url) as conn:
        conn.execute(
            f"""
            UPDATE {POSTGRES_THREAD_TABLE}
            SET created_at = %(created_at)s, updated_at = %(updated_at)s
            WHERE id = %(id)s
            """,
            {"id": session.id, "created_at": session.createdAt, "updated_at": session.updatedAt},
        )


def _force_turn_timestamps(backend: Any, turn: TurnRecord) -> None:
    database_url = getattr(backend, "database_url", None)
    if not database_url:
        return
    with _connect(database_url) as conn:
        conn.execute(
            f"""
            UPDATE {POSTGRES_TURN_TABLE}
            SET created_at = %(created_at)s, updated_at = %(updated_at)s
            WHERE id = %(id)s AND session_id = %(session_id)s
            """,
            {
                "id": turn.id,
                "session_id": turn.sessionId,
                "created_at": turn.createdAt,
                "updated_at": turn.updatedAt,
            },
        )


def _force_item_timestamps(backend: Any, item: CodexItemProjectionRecord) -> None:
    database_url = getattr(backend, "database_url", None)
    if not database_url:
        return
    with _connect(database_url) as conn:
        conn.execute(
            f"""
            UPDATE {POSTGRES_CODEX_ITEM_PROJECTION_TABLE}
            SET created_at = %(created_at)s, completed_at = %(completed_at)s
            WHERE codex_item_id = %(codex_item_id)s
            """,
            {
                "codex_item_id": item.codexItemId,
                "created_at": item.createdAt,
                "completed_at": item.completedAt,
            },
        )


def _read_legacy_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(dict(json.loads(line)))
    return rows


def _session_from_legacy(payload: dict[str, Any]) -> SessionRecord:
    metadata = dict(payload.get("metadata") or {})
    session_id = _text(payload.get("id")) or _text(metadata.get("thread_id"))
    if not session_id:
        raise ValueError(f"legacy thread missing id: {payload!r}")
    codex_session_id = (
        _text(payload.get("codexSessionId"))
        or _text(payload.get("codexThreadId"))
        or _text(metadata.get("codex_session_id"))
        or _text(metadata.get("codex_thread_id"))
    )
    if codex_session_id and codex_session_id != session_id:
        metadata["legacy_codex_session_id"] = codex_session_id
    codex_session_id = session_id
    tenant_id = _text(payload.get("tenantId")) or _text(metadata.get("tenant_id")) or _text(metadata.get("tenantId"))
    workspace_id = _text(payload.get("workspaceId")) or _text(metadata.get("workspace_id")) or _text(metadata.get("workspaceId"))
    if tenant_id:
        metadata["tenant_id"] = tenant_id
    if workspace_id:
        metadata["workspace_id"] = workspace_id
    status = _session_status(payload.get("status"))
    return SessionRecord(
        id=session_id,
        productKind=_product_kind(payload.get("productKind")),
        title=_text(payload.get("title")),
        userId=_text(payload.get("userId")),
        status=status,
        createdAt=_text(payload.get("createdAt")) or _text(payload.get("created_at")) or _now_fallback(),
        updatedAt=_text(payload.get("updatedAt")) or _text(payload.get("updated_at")) or _now_fallback(),
        metadata={**metadata, "legacy_thread_store_migration": True},
        tenantId=tenant_id,
        workspaceId=workspace_id,
        codexSessionId=codex_session_id,
    )


def _turn_from_legacy(payload: dict[str, Any]) -> TurnRecord:
    metadata = dict(payload.get("metadata") or {})
    turn_id = _text(payload.get("id")) or _text(metadata.get("turn_id"))
    session_id = (
        _text(payload.get("sessionId"))
        or _text(payload.get("threadId"))
        or _text(payload.get("conversationId"))
        or _text(metadata.get("session_id"))
        or _text(metadata.get("thread_id"))
    )
    if not turn_id or not session_id:
        raise ValueError(f"legacy turn missing id/session: {payload!r}")
    question = _text(payload.get("question")) or _text(payload.get("inputText")) or ""
    legacy_codex_turn_id = _text(payload.get("codexTurnId"))
    if legacy_codex_turn_id and legacy_codex_turn_id != turn_id:
        metadata["legacy_codex_turn_id"] = legacy_codex_turn_id
    legacy_codex_session_id = _text(payload.get("codexSessionId")) or _text(payload.get("codexThreadId"))
    if legacy_codex_session_id and legacy_codex_session_id != session_id:
        metadata["legacy_codex_session_id"] = legacy_codex_session_id
    return TurnRecord(
        id=turn_id,
        sessionId=session_id,
        inputKind=_input_kind(payload.get("inputKind")),
        question=question,
        inputText=_text(payload.get("inputText")) or question,
        status=_turn_status(payload.get("status")),
        createdAt=_text(payload.get("createdAt")) or _now_fallback(),
        updatedAt=_text(payload.get("updatedAt")) or _now_fallback(),
        startedAt=_text(payload.get("startedAt")) or _text(payload.get("createdAt")),
        completedAt=_text(payload.get("completedAt")),
        metadata={**metadata, "legacy_thread_store_migration": True},
        codexSessionId=session_id,
        codexTurnId=turn_id,
    )


def _item_from_legacy(payload: dict[str, Any]) -> CodexItemProjectionRecord:
    item_id = _text(payload.get("codexItemId")) or _text(payload.get("codex_item_id"))
    if not item_id:
        raise ValueError(f"legacy codex item missing id: {payload!r}")
    item_payload = dict(payload.get("payload") or {})
    genbi_session_id = (
        _text(payload.get("genbiSessionId"))
        or _text(payload.get("genbiThreadId"))
        or _text(item_payload.get("session_id"))
        or _text(item_payload.get("thread_id"))
        or _text(item_payload.get("conversation_id"))
    )
    genbi_turn_id = (
        _text(payload.get("genbiTurnId"))
        or _text(item_payload.get("genbi_turn_id"))
        or _text(item_payload.get("turn_id"))
    )
    return CodexItemProjectionRecord(
        codexItemId=item_id,
        codexSessionId=_text(payload.get("codexSessionId")) or _text(payload.get("codexThreadId")),
        codexTurnId=_text(payload.get("codexTurnId")),
        itemType=_text(payload.get("itemType")) or "unknown",
        status=_item_status(payload.get("status")),
        sequence=int(payload.get("sequence") or 0),
        payload={**item_payload, "legacy_thread_store_migration": True},
        createdAt=_text(payload.get("createdAt")) or _now_fallback(),
        completedAt=_text(payload.get("completedAt")),
        genbiSessionId=genbi_session_id,
        genbiTurnId=genbi_turn_id,
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _session_status(value: Any) -> str:
    return "archived" if _text(value) == "archived" else "active"


def _turn_status(value: Any) -> str:
    raw = (_text(value) or "failed").lower()
    if raw in {"running", "completed", "failed", "cancelled", "needs_input"}:
        return raw
    if raw in {"interrupted", "canceled"}:
        return "cancelled"
    if raw in {"complete", "success", "succeeded", "ok"}:
        return "completed"
    return "failed"


def _item_status(value: Any) -> str:
    return _text(value) or "completed"


def _input_kind(value: Any) -> str:
    raw = (_text(value) or "start").lower()
    return raw if raw in {"start", "message", "reply"} else "message"


def _product_kind(value: Any) -> str:
    raw = _text(value) or "analysis_task"
    return raw if raw in {"analysis_task", "asset_continuation"} else "analysis_task"


def _now_fallback() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _build_postgres_stores(database_url: str | None) -> tuple[SessionCatalog, CodexProjectionStore]:
    url = database_url or get_postgres_database_url()
    if not url:
        raise RuntimeError("GENBI_DATABASE_URL or AUTH_DATABASE_URL is required.")
    catalog_backend = PostgresSessionCatalogBackend(url)
    projection_backend = PostgresCodexProjectionBackend(url)
    return SessionCatalog(backend=catalog_backend), CodexProjectionStore(backend=projection_backend)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy .resource-index/thread-store.jsonl into current stores.")
    parser.add_argument("legacy_path", nargs="?", default=".resource-index/thread-store.jsonl")
    parser.add_argument("--database-url", default=os.getenv("GENBI_DATABASE_URL") or os.getenv("AUTH_DATABASE_URL"))
    parser.add_argument("--apply", action="store_true", help="Write records. Omit for dry-run.")
    args = parser.parse_args()

    legacy_path = Path(args.legacy_path)
    if args.apply:
        catalog, projections = _build_postgres_stores(args.database_url)
    else:
        catalog = SessionCatalog(path=Path(os.devnull))
        projections = CodexProjectionStore(path=Path(os.devnull))
    stats = migrate_legacy_thread_store(
        legacy_path,
        session_catalog=catalog,
        projection_store=projections,
        dry_run=not args.apply,
    )
    print(json.dumps(stats.__dict__, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
