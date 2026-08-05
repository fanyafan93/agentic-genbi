"""Codex projection store: the thin owner of the turn + Codex item rows.

The projection store knows about:

* ``analysis_turns`` (turn metadata: id, session_id, input_kind,
  input_text, status, started_at, completed_at, codex ids)
* ``analysis_codex_item_projections`` (the Codex item stream)

It MUST NOT know about:

* Session-level state (the catalog owns that)
* AgentEvent translation (the Codex Runtime owns that)
* ToolCall / Artifact / Share / Bookmark business rules
* The session-level "active" / "archived" state machine
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

TurnInputKind = Literal["start", "message", "reply"]

# Turn state machine (per the latest user spec).
TURN_STATES = ("running", "completed", "failed", "cancelled", "needs_input")
TURN_TERMINAL_STATES = ("completed", "failed", "cancelled")


@dataclass(frozen=True)
class TurnRecord:
    id: str
    sessionId: str
    inputKind: TurnInputKind
    # ``question`` is the historical column name; ``inputText`` is the
    # canonical name per the latest spec. The store keeps both in sync.
    question: str
    inputText: str
    status: str
    createdAt: str
    updatedAt: str
    startedAt: str | None
    completedAt: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    codexSessionId: str | None = None
    codexTurnId: str | None = None


@dataclass(frozen=True)
class CodexItemProjectionRecord:
    codexItemId: str
    codexSessionId: str | None
    codexTurnId: str | None
    itemType: str
    status: str
    sequence: int
    payload: dict[str, Any]
    createdAt: str
    completedAt: str | None = None
    genbiSessionId: str | None = None
    genbiTurnId: str | None = None


class SessionTouch(Protocol):
    """The projection store bumps ``updatedAt`` on the session after writes.

    Implemented by :class:`backend.harness.session_catalog.SessionCatalog`.
    The catalog owns the timestamp; the projection store just notifies.
    """

    def mark_updated(self, session_id: str, *, when: str | None = None) -> None: ...


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    payload.setdefault(
        "codexSessionId",
        _string_or_none(metadata.get("codex_session_id")) or payload.get("codexSessionId"),
    )
    payload.setdefault(
        "codexTurnId",
        _string_or_none(metadata.get("codex_turn_id") or metadata.get("codexTurnId"))
        or payload.get("codexTurnId"),
    )
    payload.setdefault("inputText", payload.get("question", ""))
    return payload


class CodexProjectionStore:
    """Owns ``analysis_turns`` + ``analysis_codex_item_projections``.

    Inputs are *already-decided* fields (status, timestamps,
    projection). The Runtime that calls this store is responsible
    for translating ``AgentEvent`` into the canonical state
    machine; this store never looks at events.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        session_touch: SessionTouch | None = None,
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
            self.path = Path(path or ".resource-index/codex-projection-store.jsonl")
        self._session_touch = session_touch

    # -- turn mutations --------------------------------------------------

    def save_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        input_kind: TurnInputKind,
        input_text: str,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        codex_session_id: str | None = None,
        codex_turn_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TurnRecord:
        """Persist a turn row using standardised fields.

        ``status`` is whatever the Runtime computed (``running`` /
        ``completed`` / ``failed`` / ``cancelled`` / ``needs_input``).
        ``started_at`` and ``completed_at`` are *pre-computed*; this
        store does not look at events.
        """
        if not session_id.strip():
            raise ValueError("session_id is required.")
        if not turn_id.strip():
            raise ValueError("turn_id is required.")
        if status not in TURN_STATES:
            raise ValueError(
                f"turn.status must be one of {TURN_STATES!r}; got {status!r}."
            )
        # New-session contract: ``analysis_turns.id == analysis_turns.codex_turn_id``.
        effective_codex_turn_id = _string_or_none(codex_turn_id) or turn_id
        if effective_codex_turn_id != turn_id:
            raise ValueError(
                "turn_id must equal codex_turn_id (new-session contract); "
                f"got turn_id={turn_id!r}, codex_turn_id={effective_codex_turn_id!r}."
            )
        if self._has_row_backend("get_turn_by_id", "upsert_turn"):
            existing = self.backend.get_turn_by_id(turn_id)
        elif self._has_row_backend("get_turn", "upsert_turn"):
            existing = self.backend.get_turn(session_id, turn_id)
        else:
            state = self._read_state()
            existing = state["turns"].get(turn_id)
        # The turn_id is globally unique in this store (it IS the
        # Codex-issued turn id per the new contract). If a row
        # already exists it must belong to the same session the
        # caller is updating; otherwise we would silently move a
        # turn from session A to B, which is exactly the cross-
        # session projection pollution we need to reject.
        if existing is not None and existing.sessionId != session_id:
            raise ValueError(
                f"turn {turn_id!r} belongs to session {existing.sessionId!r}; "
                f"cannot update it on session {session_id!r}."
            )
        now = _now()
        canonical_input = (input_text or "").strip() or (existing.inputText if existing else "")
        merged_metadata = {
            **(existing.metadata if existing else {}),
            **(metadata or {}),
        }
        if codex_session_id:
            merged_metadata["codex_session_id"] = codex_session_id
        if effective_codex_turn_id:
            merged_metadata["codex_turn_id"] = effective_codex_turn_id
        record = TurnRecord(
            id=turn_id,
            sessionId=session_id,
            inputKind=input_kind,
            question=canonical_input,
            inputText=canonical_input,
            status=status,
            createdAt=existing.createdAt if existing else (started_at or now),
            updatedAt=now,
            startedAt=started_at or (existing.startedAt if existing else None),
            completedAt=completed_at if status in TURN_TERMINAL_STATES else (existing.completedAt if existing else None),
            metadata=merged_metadata,
            codexSessionId=codex_session_id or (existing.codexSessionId if existing else None),
            codexTurnId=effective_codex_turn_id or (existing.codexTurnId if existing else None),
        )
        record_to_save = record
        # New title: only update if the Runtime provided one; the
        # catalog owns session titles, not us.
        if title is not None and title.strip():
            record_to_save = TurnRecord(
                **{**asdict(record), "metadata": {**record.metadata, "_title": title.strip()}}
            )
        if self._has_row_backend("upsert_turn"):
            self.backend.upsert_turn(record_to_save)
        else:
            state["turns"][turn_id] = record_to_save
            self._write_state(state)
        self._notify_session(session_id, now)
        return record_to_save

    def complete_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        status: str,
        completed_at: str,
    ) -> TurnRecord:
        """Mark a turn terminal.

        ``status`` must be a terminal state. The Runtime is the
        only thing allowed to decide when a turn is done; this
        method just persists that decision.
        """
        if status not in TURN_TERMINAL_STATES:
            raise ValueError(
                f"terminal status must be one of {TURN_TERMINAL_STATES!r}; got {status!r}."
            )
        if self._has_row_backend("get_turn", "upsert_turn"):
            existing = self.backend.get_turn(session_id, turn_id)
        else:
            state = self._read_state()
            existing = state["turns"].get(turn_id)
        if existing is None or existing.sessionId != session_id:
            raise ValueError(f"turn not found: {turn_id}")
        now = _now()
        record = TurnRecord(
            id=existing.id,
            sessionId=existing.sessionId,
            inputKind=existing.inputKind,
            question=existing.question,
            inputText=existing.inputText,
            status=status,
            createdAt=existing.createdAt,
            updatedAt=now,
            startedAt=existing.startedAt,
            completedAt=completed_at,
            metadata=dict(existing.metadata or {}),
            codexSessionId=existing.codexSessionId,
            codexTurnId=existing.codexTurnId,
        )
        if self._has_row_backend("upsert_turn"):
            self.backend.upsert_turn(record)
        else:
            state["turns"][turn_id] = record
            self._write_state(state)
        self._notify_session(session_id, now)
        return record

    # -- projection mutations -------------------------------------------

    def upsert_item(
        self,
        *,
        session_id: str,
        turn_id: str,
        codex_item_id: str,
        item_type: str,
        status: str,
        sequence: int,
        payload: dict[str, Any],
        created_at: str,
        completed_at: str | None = None,
        codex_session_id: str | None = None,
        codex_turn_id: str | None = None,
    ) -> CodexItemProjectionRecord:
        """Idempotently write a Codex item projection.

        The Runtime already decided ``status`` and ``sequence``;
        this store just persists. The session + turn must exist;
        we don't auto-create rows the catalog owns. The turn must
        also *belong* to the given session — otherwise we silently
        write cross-session projection pollution (a turn that lives
        on session A ends up with ``genbiSessionId = B``).
        """
        if not codex_item_id.strip():
            raise ValueError("codex_item_id is required.")
        if self._has_row_backend("get_turn", "upsert_item", "get_item"):
            turn = self.backend.get_turn(session_id, turn_id)
        else:
            state = self._read_state()
            turn = state["turns"].get(turn_id)
        if turn is None:
            raise ValueError(f"turn not found: {turn_id}")
        if turn.sessionId != session_id:
            raise ValueError(
                f"turn {turn_id!r} belongs to session {turn.sessionId!r}; "
                f"cannot upsert projection on session {session_id!r}."
            )
        existing = None
        if self._has_row_backend("get_item"):
            existing = self.backend.get_item(codex_item_id)
        else:
            for projection in state["projections"]:
                if projection.codexItemId == codex_item_id:
                    existing = projection
                    break
        if existing is not None and (
            existing.genbiSessionId != session_id
            or existing.genbiTurnId != turn_id
        ):
            raise ValueError(
                f"item {codex_item_id!r} belongs to session {existing.genbiSessionId!r} "
                f"turn {existing.genbiTurnId!r}; cannot update it on session {session_id!r} "
                f"turn {turn_id!r}."
            )
        # ``sequence`` is the dense ordering of the projection in
        # the turn's timeline. The Runtime assigns it; the store
        # just stores the value. The replay path reuses the same
        # dense index so live and historical projections agree.
        record = CodexItemProjectionRecord(
            codexItemId=codex_item_id,
            codexSessionId=codex_session_id or (existing.codexSessionId if existing else None),
            codexTurnId=codex_turn_id or (existing.codexTurnId if existing else None),
            itemType=item_type,
            status=status,
            sequence=sequence,
            payload=dict(payload or {}),
            createdAt=created_at,
            completedAt=completed_at if status in {"completed"} else None,
            genbiSessionId=session_id,
            genbiTurnId=turn_id,
        )
        if self._has_row_backend("upsert_item"):
            self.backend.upsert_item(record)
        elif existing is None:
            state["projections"].append(record)
            self._write_state(state)
        else:
            state["projections"] = [
                record if item.codexItemId == codex_item_id else item
                for item in state["projections"]
            ]
            self._write_state(state)
        return record

    # -- reads -----------------------------------------------------------

    def get_turn(self, session_id: str, turn_id: str) -> TurnRecord | None:
        if self._has_row_backend("get_turn"):
            return self.backend.get_turn(session_id, turn_id)
        state = self._read_state()
        record = state["turns"].get(turn_id)
        if record is None or record.sessionId != session_id:
            return None
        return record

    def list_turns(self, session_id: str) -> list[TurnRecord]:
        if self._has_row_backend("list_turns"):
            return self.backend.list_turns(session_id)
        state = self._read_state()
        records = [t for t in state["turns"].values() if t.sessionId == session_id]
        records.sort(key=lambda t: t.createdAt)
        return records

    def list_items(
        self,
        *,
        session_id: str,
        turn_id: str | None = None,
    ) -> list[CodexItemProjectionRecord]:
        if self._has_row_backend("list_items"):
            return self.backend.list_items(session_id, turn_id)
        state = self._read_state()
        rows = [p for p in state["projections"] if p.genbiSessionId == session_id]
        if turn_id is not None:
            rows = [p for p in rows if p.genbiTurnId == turn_id]
        rows.sort(key=lambda p: (p.createdAt, p.codexItemId))
        return rows

    def get_turn_events(self, session_id: str, turn_id: str) -> list[dict[str, Any]]:
        """Return the unified Codex projection timeline for a turn.

        Realtime stream + historical replay share this shape.
        """
        rows = self.list_items(session_id=session_id, turn_id=turn_id)
        return [_projection_to_event_dict(p) for p in rows]

    # -- sidebar signal --------------------------------------------------

    def latest_turn_status(self, session_id: str) -> str | None:
        if self._has_row_backend("latest_turn"):
            turn = self.backend.latest_turn(session_id)
            return turn.status if turn else None
        turns = self.list_turns(session_id)
        if not turns:
            return None
        turns.sort(key=lambda t: t.updatedAt)
        return turns[-1].status

    def latest_turn_id(self, session_id: str) -> str | None:
        if self._has_row_backend("latest_turn"):
            turn = self.backend.latest_turn(session_id)
            return turn.id if turn else None
        turns = self.list_turns(session_id)
        if not turns:
            return None
        turns.sort(key=lambda t: t.updatedAt)
        return turns[-1].id

    # -- seam ------------------------------------------------------------

    def bind_session_touch(self, session_touch: SessionTouch) -> None:
        self._session_touch = session_touch

    def _notify_session(self, session_id: str, when: str) -> None:
        if self._session_touch is None:
            return
        try:
            self._session_touch.mark_updated(session_id, when=when)
        except Exception:
            # The projection store must never raise because the
            # catalog failed to update its timestamp; the sidebar
            # ordering is non-critical.
            pass

    # -- persistence -----------------------------------------------------

    def _read_state(self) -> dict[str, Any]:
        if self.backend is not None:
            return self.backend.read_state()
        state: dict[str, Any] = {"turns": {}, "projections": []}
        if not self.path.exists():
            return state
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = dict(json.loads(line))
            record_type = payload.pop("record_type", "turn")
            if record_type == "projection":
                payload = _normalize_projection_payload(payload)
                record = CodexItemProjectionRecord(**payload)
                state["projections"].append(record)
            else:
                payload = _normalize_turn_payload(payload)
                record = TurnRecord(**payload)
                state["turns"][record.id] = record
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        if self.backend is not None:
            self.backend.write_state(state)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for record in sorted(state["turns"].values(), key=lambda value: value.createdAt):
                file.write(json.dumps({"record_type": "turn", **asdict(record)}, ensure_ascii=False, default=str))
                file.write("\n")
            for record in sorted(state["projections"], key=lambda value: value.createdAt):
                file.write(json.dumps({"record_type": "projection", **asdict(record)}, ensure_ascii=False, default=str))
                file.write("\n")

    def _has_row_backend(self, *method_names: str) -> bool:
        if self.backend is None:
            return False
        return all(callable(getattr(self.backend, name, None)) for name in method_names)


def _normalize_projection_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Backfill canonical fields from legacy column names.

    Older rows were persisted as ``codex_thread_id`` / ``genbi_thread_id``
    and ``codex_turn_id`` / ``genbi_turn_id``; new code reads
    ``codex_session_id`` / ``genbi_session_id`` etc.
    """
    payload.setdefault("codexSessionId", payload.get("codex_thread_id") or payload.get("codexThreadId"))
    payload.setdefault("codexTurnId", payload.get("codex_turn_id") or payload.get("codexTurnId"))
    payload.setdefault("genbiSessionId", payload.get("genbi_thread_id") or payload.get("genbiThreadId"))
    payload.setdefault("genbiTurnId", payload.get("genbi_turn_id") or payload.get("genbiTurnId"))
    payload.setdefault("sequence", payload.get("sequence", 0))
    return payload


def _projection_to_event_dict(projection: CodexItemProjectionRecord) -> dict[str, Any]:
    """Serialise a projection row into the unified turn-event shape.

    The realtime SSE stream and the historical replay endpoint
    both surface the same shape so the frontend can replay a
    session with a single rendering path.
    """
    return {
        "type": f"codex/{projection.itemType}",
        "turn_id": projection.codexTurnId or projection.genbiTurnId,
        "codex_session_id": projection.codexSessionId or projection.genbiSessionId,
        "codex_turn_id": projection.codexTurnId,
        "codex_item_id": projection.codexItemId,
        "item_type": projection.itemType,
        "status": projection.status,
        "sequence": projection.sequence,
        "payload": dict(projection.payload or {}),
        "created_at": projection.createdAt,
        "completed_at": projection.completedAt,
    }
