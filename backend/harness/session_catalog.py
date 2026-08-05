"""Session catalog: the thin owner of the analysis session rows.

The session catalog only knows about the session-level state
machine (``active`` / ``archived``) and the row's identity, title,
owner, and metadata. It MUST NOT see:

* ``AgentEvent`` (the Codex Runtime owns that translation)
* ``ToolCall`` (the projection store owns the Codex item stream)
* Codex item payloads
* Any turn execution logic

``latest_turn_status`` is a *derived view* the catalog exposes by
asking the projection store for the most recent turn. The catalog
itself never copies turn state into the session row; it just hands
the caller the live signal so a turn failure does not flip the
session to ``completed``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

SessionProductKind = Literal["analysis_task", "asset_continuation"]

# Session state machine — tiny on purpose.
SESSION_STATES = ("active", "archived")


@dataclass(frozen=True)
class SessionRecord:
    id: str
    productKind: SessionProductKind
    title: str | None
    userId: str | None
    status: str
    createdAt: str
    updatedAt: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tenantId: str | None = None
    workspaceId: str | None = None
    codexSessionId: str | None = None


@dataclass(frozen=True)
class SessionView:
    """Session row plus the *derived* turn signal for the sidebar.

    The catalog computes ``latest_turn_status`` / ``latest_turn_id``
    from the projection store on read; the value is never persisted
    on the session row. This is the only place the catalog is
    allowed to look at turn state.
    """

    session: SessionRecord
    latestTurnStatus: str | None
    latestTurnId: str | None

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self.session)
        row["latest_turn_status"] = self.latestTurnStatus
        row["latest_turn_id"] = self.latestTurnId
        row["latestTurnStatus"] = self.latestTurnStatus
        row["latestTurnId"] = self.latestTurnId
        return row


class LatestTurnProvider(Protocol):
    """Tiny seam the catalog uses to look up the latest turn signal.

    Implemented by :class:`backend.harness.codex_projection_store.CodexProjectionStore`
    so the catalog never reaches into the projection store itself;
    that dependency is owned by the application composition root.
    """

    def latest_turn_status(self, session_id: str) -> str | None: ...
    def latest_turn_id(self, session_id: str) -> str | None: ...


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return dict(metadata or {})


class SessionCatalog:
    """Owns the ``analysis_threads`` row.

    The catalog is intentionally thin: it never observes Codex item
    payloads, agent events, or turn execution. The only side effect
    it knows about is the ``active`` / ``archived`` flip and the
    ``updatedAt`` timestamp that the projection store bumps each
    time a turn finalises.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        latest_turn_provider: LatestTurnProvider | None = None,
        backend: Any | None = None,
    ) -> None:
        # Two implementations: file-backed (default) or a Postgres
        # backend that overrides the read/write state hooks. The
        # backend is the only thing allowed to talk to SQL.
        if backend is not None:
            self.backend = backend
            self.path = Path(str(backend))
        else:
            self.backend = None
            self.path = Path(path or ".resource-index/session-catalog.jsonl")
        self._latest_turn_provider = latest_turn_provider

    # -- lookups ---------------------------------------------------------

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self._read_state().get(session_id)

    def list_sessions(
        self,
        *,
        limit: int = 50,
        product_kind: SessionProductKind | None = None,
    ) -> list[SessionRecord]:
        state = self._read_state()
        sessions = list(state.values())
        if product_kind:
            sessions = [s for s in sessions if s.productKind == product_kind]
        sessions.sort(key=lambda s: s.updatedAt, reverse=True)
        return sessions[:limit]

    def get_view(self, session_id: str) -> SessionView | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        return SessionView(
            session=session,
            latestTurnStatus=self._latest_turn_status(session_id),
            latestTurnId=self._latest_turn_id(session_id),
        )

    def list_views(
        self,
        *,
        limit: int = 50,
        product_kind: SessionProductKind | None = None,
    ) -> list[SessionView]:
        return [
            SessionView(
                session=session,
                latestTurnStatus=self._latest_turn_status(session.id),
                latestTurnId=self._latest_turn_id(session.id),
            )
            for session in self.list_sessions(limit=limit, product_kind=product_kind)
        ]

    # -- mutations -------------------------------------------------------

    def register_session(
        self,
        session_id: str,
        *,
        product_kind: SessionProductKind,
        title: str | None,
        user_id: str | None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
        codex_session_id: str | None = None,
    ) -> SessionRecord:
        """Register a new analysis session.

        ``session_id`` and ``codex_session_id`` must agree (new-session
        contract: ``analysis_threads.id == analysis_threads.codex_session_id``).
        """
        if not session_id.strip():
            raise ValueError("session_id is required.")
        if status not in SESSION_STATES:
            raise ValueError(
                f"session.status must be one of {SESSION_STATES!r}; got {status!r}."
            )
        effective_codex_id = (codex_session_id or session_id or "").strip() or None
        if effective_codex_id and effective_codex_id != session_id:
            raise ValueError(
                "session_id must equal codex_session_id (new-session contract); "
                f"got session_id={session_id!r}, codex_session_id={effective_codex_id!r}."
            )
        state = self._read_state()
        existing = state.get(session_id)
        now = _now()
        merged_metadata = {
            **(existing.metadata if existing else {}),
            **_normalize_metadata(metadata),
        }
        if effective_codex_id:
            merged_metadata["codex_session_id"] = effective_codex_id
        # Preserve the existing session-level state when re-registering
        # a row; otherwise default to the requested state.
        next_status = (
            existing.status if existing and existing.status in SESSION_STATES else status
        )
        record = SessionRecord(
            id=session_id,
            productKind=product_kind,
            title=str(title).strip() if title else (existing.title if existing else None),
            userId=user_id,
            status=next_status,
            createdAt=existing.createdAt if existing else now,
            updatedAt=now,
            metadata=merged_metadata,
            tenantId=_string_or_none(merged_metadata.get("tenant_id") or merged_metadata.get("tenantId"))
            or (existing.tenantId if existing else None),
            workspaceId=_string_or_none(merged_metadata.get("workspace_id") or merged_metadata.get("workspaceId"))
            or (existing.workspaceId if existing else None),
            codexSessionId=effective_codex_id or (existing.codexSessionId if existing else None),
        )
        state[session_id] = record
        self._write_state(state)
        return record

    def rename_session(self, session_id: str, title: str) -> SessionRecord:
        state = self._read_state()
        existing = state.get(session_id)
        if existing is None:
            raise ValueError(f"session not found: {session_id}")
        updated = SessionRecord(
            id=existing.id,
            productKind=existing.productKind,
            title=str(title).strip() or None,
            userId=existing.userId,
            status=existing.status,
            createdAt=existing.createdAt,
            updatedAt=_now(),
            metadata=dict(existing.metadata or {}),
            tenantId=existing.tenantId,
            workspaceId=existing.workspaceId,
            codexSessionId=existing.codexSessionId,
        )
        state[session_id] = updated
        self._write_state(state)
        return updated

    def archive_session(self, session_id: str) -> SessionRecord:
        """Move a session into the ``archived`` bucket.

        Archiving is the only way to remove a session from the
        active list. The user explicitly asks: the session is
        otherwise always ``active`` regardless of what the most
        recent turn did.
        """
        state = self._read_state()
        existing = state.get(session_id)
        if existing is None:
            raise ValueError(f"session not found: {session_id}")
        archived = SessionRecord(
            id=existing.id,
            productKind=existing.productKind,
            title=existing.title,
            userId=existing.userId,
            status="archived",
            createdAt=existing.createdAt,
            updatedAt=_now(),
            metadata=dict(existing.metadata or {}),
            tenantId=existing.tenantId,
            workspaceId=existing.workspaceId,
            codexSessionId=existing.codexSessionId,
        )
        state[session_id] = archived
        self._write_state(state)
        return archived

    def reactivate_session(self, session_id: str) -> SessionRecord:
        state = self._read_state()
        existing = state.get(session_id)
        if existing is None:
            raise ValueError(f"session not found: {session_id}")
        active = SessionRecord(
            id=existing.id,
            productKind=existing.productKind,
            title=existing.title,
            userId=existing.userId,
            status="active",
            createdAt=existing.createdAt,
            updatedAt=_now(),
            metadata=dict(existing.metadata or {}),
            tenantId=existing.tenantId,
            workspaceId=existing.workspaceId,
            codexSessionId=existing.codexSessionId,
        )
        state[session_id] = active
        self._write_state(state)
        return active

    def delete_session(self, session_id: str) -> bool:
        state = self._read_state()
        if session_id not in state:
            return False
        state.pop(session_id, None)
        self._write_state(state)
        return True

    def mark_updated(self, session_id: str, *, when: str | None = None) -> None:
        """Refresh ``updatedAt`` after the projection store finalised a turn.

        The catalog owns only the timestamp; the projection store
        owns the row contents. This is the only cross-store call
        allowed.
        """
        state = self._read_state()
        existing = state.get(session_id)
        if existing is None:
            return
        state[session_id] = SessionRecord(
            id=existing.id,
            productKind=existing.productKind,
            title=existing.title,
            userId=existing.userId,
            status=existing.status,
            createdAt=existing.createdAt,
            updatedAt=when or _now(),
            metadata=dict(existing.metadata or {}),
            tenantId=existing.tenantId,
            workspaceId=existing.workspaceId,
            codexSessionId=existing.codexSessionId,
        )
        self._write_state(state)

    # -- seam ------------------------------------------------------------

    def bind_latest_turn_provider(self, provider: LatestTurnProvider) -> None:
        self._latest_turn_provider = provider

    def _latest_turn_status(self, session_id: str) -> str | None:
        if self._latest_turn_provider is None:
            return None
        return self._latest_turn_provider.latest_turn_status(session_id)

    def _latest_turn_id(self, session_id: str) -> str | None:
        if self._latest_turn_provider is None:
            return None
        return self._latest_turn_provider.latest_turn_id(session_id)

    # -- persistence -----------------------------------------------------

    def _read_state(self) -> dict[str, SessionRecord]:
        if self.backend is not None:
            return self.backend.read_state()
        if not self.path.exists():
            return {}
        records: dict[str, SessionRecord] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = dict(json.loads(line))
            payload.setdefault(
                "codexSessionId",
                _string_or_none((payload.get("metadata") or {}).get("codex_session_id"))
                or _string_or_none(payload.get("codexThreadId")),
            )
            payload.setdefault(
                "tenantId",
                _string_or_none((payload.get("metadata") or {}).get("tenant_id"))
                or _string_or_none(payload.get("tenantId")),
            )
            payload.setdefault(
                "workspaceId",
                _string_or_none((payload.get("metadata") or {}).get("workspace_id"))
                or _string_or_none(payload.get("workspaceId")),
            )
            record = SessionRecord(**payload)
            records[record.id] = record
        return records

    def _write_state(self, state: dict[str, SessionRecord]) -> None:
        if self.backend is not None:
            self.backend.write_state(state)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for record in sorted(state.values(), key=lambda value: value.updatedAt):
                file.write(json.dumps(asdict(record), ensure_ascii=False, default=str))
                file.write("\n")
