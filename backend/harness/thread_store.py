from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from backend.harness.events import AgentEvent


DEFAULT_THREAD_STORE_PATH = Path(".resource-index/thread-store.jsonl")

ThreadProductKind = Literal["analysis_task", "asset_continuation"]
TurnInputKind = Literal["start", "message", "reply"]

# State machine (per user spec 2026-08-05):
# - Session (analysis_threads.status) is ONLY ``active`` or ``archived``.
#   We never copy a turn's state into the session; instead the API
#   surface (``list_threads``, ``get_thread``) returns the latest
#   turn's state as ``latestTurnStatus`` for sidebar display.
# - Turn (analysis_turns.status) is one of:
#   ``running`` / ``completed`` / ``failed`` / ``cancelled`` / ``needs_input``.
#   ``needs_input`` is the turn asking the user a clarifying question
#   (it is NOT a session-level state).

SESSION_STATES = ("active", "archived")
TURN_STATES = ("running", "completed", "failed", "cancelled", "needs_input")
TURN_TERMINAL_STATES = ("completed", "failed", "cancelled")


@dataclass(frozen=True)
class ThreadRecord:
    id: str
    productKind: ThreadProductKind
    title: str | None
    userId: str | None
    status: str
    createdAt: str
    updatedAt: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tenantId: str | None = None
    workspaceId: str | None = None
    codexThreadId: str | None = None


@dataclass(frozen=True)
class TurnRecord:
    id: str
    threadId: str
    inputKind: TurnInputKind
    # ``question`` is the historical field name for the user input;
    # ``inputText`` is the canonical field per the latest spec. We
    # keep both in sync so the canonical name always wins on read
    # while legacy rows still round-trip cleanly.
    question: str
    inputText: str
    status: str
    createdAt: str
    updatedAt: str
    startedAt: str | None
    completedAt: str | None
    metadata: dict[str, Any] = field(default_factory=dict)
    codexThreadId: str | None = None
    codexTurnId: str | None = None


@dataclass(frozen=True)
class CodexItemProjectionRecord:
    codexItemId: str
    codexThreadId: str | None
    codexTurnId: str | None
    itemType: str
    status: str
    # ``sequence`` is the dense ordering of the projection in the
    # turn's timeline. The realtime stream assigns it as the items
    # arrive; historical replay rebuilds it by sorting
    # ``createdAt`` and renumbering from zero.
    sequence: int
    payload: dict[str, Any]
    createdAt: str
    completedAt: str | None = None
    genbiThreadId: str | None = None
    genbiTurnId: str | None = None


class ThreadStore:
    def __init__(self, path: Path = DEFAULT_THREAD_STORE_PATH) -> None:
        self.path = path

    def create_thread(
        self,
        *,
        thread_id: str,
        product_kind: ThreadProductKind,
        title: str | None,
        user_id: str | None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
        codex_thread_id: str | None = None,
    ) -> dict[str, Any]:
        if not thread_id.strip():
            raise ValueError("thread_id is required.")
        # The session-level state machine is intentionally tiny: only
        # ``active`` or ``archived``. We reject legacy values
        # (``waiting_for_question``, ``running``, ``completed`` ...) that
        # used to mirror the latest turn.
        if status not in SESSION_STATES:
            raise ValueError(
                f"thread.status must be one of {SESSION_STATES!r}; got {status!r}."
            )
        # New-session contract: ``analysis_threads.id == analysis_threads.codex_thread_id``.
        # ``thread_id`` is the Codex-issued id; the legacy ``codex_thread_id`` column is
        # kept for compatibility and must mirror ``id`` exactly.
        effective_codex_thread_id = (codex_thread_id or thread_id or "").strip() or None
        if effective_codex_thread_id and effective_codex_thread_id != thread_id:
            raise ValueError(
                "thread_id must equal codex_thread_id (new-session contract); "
                f"got thread_id={thread_id!r}, codex_thread_id={effective_codex_thread_id!r}."
            )
        state = self._read_state()
        existing_thread = state["threads"].get(thread_id)
        now = _now()
        merged_metadata = {**(existing_thread.metadata if existing_thread else {}), **(metadata or {})}
        codex_thread_id = effective_codex_thread_id or _thread_codex_thread_id(merged_metadata, existing_thread=existing_thread)
        if codex_thread_id:
            merged_metadata["codex_thread_id"] = codex_thread_id
        # Existing rows may have been written under the legacy state
        # names; we keep the union for backwards compatibility but force
        # the public ``status`` to the small set the user spec allows.
        if existing_thread and existing_thread.status in SESSION_STATES:
            thread_status = existing_thread.status
        else:
            thread_status = status
        thread = ThreadRecord(
            id=thread_id,
            productKind=product_kind,
            title=str(title).strip() if title else (existing_thread.title if existing_thread else None),
            userId=user_id,
            status=thread_status,
            createdAt=existing_thread.createdAt if existing_thread else now,
            updatedAt=now,
            metadata=merged_metadata,
            tenantId=_thread_scope_value(merged_metadata, "tenant_id", "tenantId", existing_value=existing_thread.tenantId if existing_thread else None),
            workspaceId=_thread_scope_value(merged_metadata, "workspace_id", "workspaceId", existing_value=existing_thread.workspaceId if existing_thread else None),
            codexThreadId=codex_thread_id,
        )
        state["threads"][thread_id] = thread
        self._write_state(state)
        return {
            "thread": asdict(thread),
            "turns": [],
            "items": [],
            "codexItemProjections": [],
        }

    def archive_thread(self, thread_id: str) -> None:
        """Mark a session as ``archived``.

        Archiving is the only way to remove a session from the active
        list. The user explicitly asks: the session is otherwise always
        ``active`` regardless of what the most recent turn did.
        """
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if thread is None:
            raise ValueError(f"thread not found: {thread_id}")
        state["threads"][thread_id] = ThreadRecord(
            id=thread.id,
            productKind=thread.productKind,
            title=thread.title,
            userId=thread.userId,
            status="archived",
            createdAt=thread.createdAt,
            updatedAt=_now(),
            metadata=dict(thread.metadata or {}),
            tenantId=thread.tenantId,
            workspaceId=thread.workspaceId,
            codexThreadId=thread.codexThreadId,
        )
        self._write_state(state)

    def reactivate_thread(self, thread_id: str) -> None:
        """Restore an archived session back to ``active``."""
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if thread is None:
            raise ValueError(f"thread not found: {thread_id}")
        state["threads"][thread_id] = ThreadRecord(
            id=thread.id,
            productKind=thread.productKind,
            title=thread.title,
            userId=thread.userId,
            status="active",
            createdAt=thread.createdAt,
            updatedAt=_now(),
            metadata=dict(thread.metadata or {}),
            tenantId=thread.tenantId,
            workspaceId=thread.workspaceId,
            codexThreadId=thread.codexThreadId,
        )
        self._write_state(state)

    def create_turn_only(
        self,
        *,
        thread_id: str,
        turn_id: str,
        codex_turn_id: str | None = None,
    ) -> TurnRecord:
        """Persist a turn row using the Codex-issued ``turn_id``.

        Used by the analysis pipeline after it observes
        ``genbi/turn/provisioned``. Enforces the new-session contract:
        ``analysis_turns.id == analysis_turns.codex_turn_id``.
        """
        if not thread_id.strip():
            raise ValueError("thread_id is required.")
        if not turn_id.strip():
            raise ValueError("turn_id is required.")
        effective_codex_turn_id = (codex_turn_id or turn_id or "").strip() or None
        if effective_codex_turn_id and effective_codex_turn_id != turn_id:
            raise ValueError(
                "turn_id must equal codex_turn_id (new-session contract); "
                f"got turn_id={turn_id!r}, codex_turn_id={effective_codex_turn_id!r}."
            )
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if thread is None:
            raise ValueError(f"thread not found: {thread_id}")
        existing_turn = state["turns"].get(turn_id)
        now = _now()
        merged_metadata = {**(existing_turn.metadata if existing_turn else {}), "codex_turn_id": effective_codex_turn_id}
        if thread.codexThreadId:
            merged_metadata.setdefault("codex_thread_id", thread.codexThreadId)
        # A freshly provisioned turn is in flight — its state is
        # ``running`` until ``save_turn`` finalises it. We preserve any
        # existing turn status so we don't accidentally regress a
        # completed turn to ``running`` if the pipeline re-enters
        # ``create_turn_only``.
        if existing_turn and existing_turn.status in TURN_STATES:
            turn_status = existing_turn.status
        else:
            turn_status = "running"
        # ``create_turn_only`` runs as soon as Codex provisions the
        # turn; the user input has not been resolved yet. We still
        # keep the canonical ``inputText`` field but the real value
        # is set in ``save_turn``.
        placeholder_input = existing_turn.inputText if existing_turn and existing_turn.inputText else ""
        turn = TurnRecord(
            id=turn_id,
            threadId=thread_id,
            inputKind="start",
            question=placeholder_input,
            inputText=placeholder_input,
            status=turn_status,
            createdAt=existing_turn.createdAt if existing_turn else now,
            updatedAt=now,
            startedAt=existing_turn.startedAt if existing_turn else now,
            completedAt=existing_turn.completedAt if existing_turn else None,
            metadata=merged_metadata,
            codexThreadId=thread.codexThreadId,
            codexTurnId=effective_codex_turn_id,
        )
        state["turns"][turn_id] = turn
        # Re-write the thread with a refreshed updatedAt so list views see the new turn.
        state["threads"][thread_id] = ThreadRecord(
            id=thread.id,
            productKind=thread.productKind,
            title=thread.title,
            userId=thread.userId,
            status=thread.status,
            createdAt=thread.createdAt,
            updatedAt=now,
            metadata=dict(thread.metadata or {}),
            tenantId=thread.tenantId,
            workspaceId=thread.workspaceId,
            codexThreadId=thread.codexThreadId,
        )
        self._write_state(state)
        return turn

    def save_turn(
        self,
        *,
        thread_id: str,
        turn_id: str,
        question: str,
        input_kind: TurnInputKind,
        product_kind: ThreadProductKind,
        user_id: str | None,
        events: list["AgentEvent"],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not thread_id.strip():
            raise ValueError("thread_id is required.")
        if not turn_id.strip():
            raise ValueError("turn_id is required.")
        state = self._read_state()
        existing_thread = state["threads"].get(thread_id)
        existing_turn = state["turns"].get(turn_id)
        # Defensive contract guard: refuse to persist a turn whose ``id``
        # does not match the Codex-issued ``codex_turn_id``. New sessions
        # must satisfy ``analysis_turns.id == analysis_turns.codex_turn_id``.
        effective_codex_turn_id = _latest_payload_value(events, "codex_turn_id") or _string_or_none((metadata or {}).get("codex_turn_id"))
        if effective_codex_turn_id and effective_codex_turn_id != turn_id:
            raise ValueError(
                "turn_id must equal codex_turn_id (new-session contract); "
                f"got turn_id={turn_id!r}, codex_turn_id={effective_codex_turn_id!r}."
            )
        started_at = events[0].created_at if events else None
        completed_at = events[-1].created_at if events else started_at
        # The turn state is one of ``TURN_STATES``. It is NEVER copied
        # into the session row — a turn may fail, get cancelled, or
        # answer a clarifying question while the session itself stays
        # ``active``. The sidebar reads the latest turn's state via
        # ``latest_turn_status`` on the API surface.
        turn_status = _turn_status(events)
        merged_metadata = {**(existing_thread.metadata if existing_thread else {}), **(metadata or {})}
        codex_thread_id = _thread_codex_thread_id(
            merged_metadata,
            existing_thread=existing_thread,
        )
        codex_turn_id = _latest_payload_value(events, "codex_turn_id") or _string_or_none(merged_metadata.get("codex_turn_id"))
        if codex_thread_id:
            merged_metadata["codex_thread_id"] = codex_thread_id
        if codex_turn_id:
            merged_metadata["codex_turn_id"] = codex_turn_id
        # The user input lives on the turn row (``inputText``); we
        # never reconstruct a fake "GenBI User Item" from the
        # Codex events. The question parameter remains the
        # authoritative source for what the user actually asked.
        canonical_input = question.strip() or (existing_turn.inputText if existing_turn else "")
        codex_item_projections = _codex_item_projections_from_events(
            events,
            thread_id=thread_id,
            turn_id=turn_id,
            default_codex_thread_id=codex_thread_id,
        )
        title = (
            _first_payload_value(events, "turn/started", "title")
            or (existing_thread.title if existing_thread else None)
            or _title_from_question(question, input_kind=input_kind)
        )
        now = completed_at or started_at or ""

        # Preserve the existing session-level state. If there is no
        # existing row yet, fall back to ``active`` — the session is
        # always ``active`` unless the user explicitly archives it.
        session_status = existing_thread.status if existing_thread and existing_thread.status in SESSION_STATES else "active"
        thread = ThreadRecord(
            id=thread_id,
            productKind=product_kind,
            title=str(title) if title else None,
            userId=user_id,
            status=session_status,
            createdAt=existing_thread.createdAt if existing_thread else (started_at or now),
            updatedAt=now,
            metadata=merged_metadata,
            tenantId=_thread_scope_value(merged_metadata, "tenant_id", "tenantId", existing_value=existing_thread.tenantId if existing_thread else None),
            workspaceId=_thread_scope_value(merged_metadata, "workspace_id", "workspaceId", existing_value=existing_thread.workspaceId if existing_thread else None),
            codexThreadId=codex_thread_id,
        )
        turn = TurnRecord(
            id=turn_id,
            threadId=thread_id,
            inputKind=input_kind,
            question=canonical_input,
            # ``inputText`` is the canonical name per the latest
            # spec; keep ``question`` in sync so legacy readers
            # still see what the user asked.
            inputText=canonical_input,
            status=turn_status,
            createdAt=existing_turn.createdAt if existing_turn else (started_at or now),
            updatedAt=now,
            startedAt=started_at or (existing_turn.startedAt if existing_turn else None),
            completedAt=completed_at if turn_status in TURN_TERMINAL_STATES else (existing_turn.completedAt if existing_turn else None),
            metadata={**(existing_turn.metadata if existing_turn else {}), **merged_metadata},
            codexThreadId=codex_thread_id or (existing_turn.codexThreadId if existing_turn else None),
            codexTurnId=codex_turn_id or (existing_turn.codexTurnId if existing_turn else None),
        )
        state["threads"][thread_id] = thread
        state["turns"][turn_id] = turn
        state["codex_item_projections"] = [
            item for item in state["codex_item_projections"] if not (item.genbiThreadId == thread_id and item.genbiTurnId == turn_id)
        ]
        state["codex_item_projections"].extend(codex_item_projections)
        self._write_state(state)
        return {
            "thread": asdict(thread),
            "turn": asdict(turn),
            "codexItemProjections": [asdict(item) for item in codex_item_projections],
        }

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread:
            return None
        turns = [turn for turn in state["turns"].values() if turn.threadId == thread_id]
        turns.sort(key=lambda item: item.createdAt)
        codex_item_projections = [item for item in state["codex_item_projections"] if item.genbiThreadId == thread_id]
        codex_item_projections.sort(key=lambda item: item.createdAt)
        thread_row = asdict(thread)
        thread_row["latest_turn_status"] = self.latest_turn_status(thread_id, state=state)
        thread_row["latest_turn_id"] = self.latest_turn_id(thread_id, state=state)
        return {
            "thread": thread_row,
            "turns": [asdict(item) for item in turns],
            "codexItemProjections": [asdict(item) for item in codex_item_projections],
        }

    def get_turn(self, thread_id: str, turn_id: str) -> dict[str, Any] | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        turn = state["turns"].get(turn_id)
        if not thread or not turn or turn.threadId != thread_id:
            return None
        codex_item_projections = [
            item
            for item in state["codex_item_projections"]
            if item.genbiTurnId == turn_id and item.genbiThreadId == thread_id
        ]
        codex_item_projections.sort(key=lambda item: item.createdAt)
        return {
            "thread": asdict(thread),
            "turn": asdict(turn),
            "codexItemProjections": [asdict(item) for item in codex_item_projections],
        }

    def get_thread_metadata(self, thread_id: str) -> dict[str, Any]:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread:
            return {}
        metadata = dict(thread.metadata or {})
        if thread.codexThreadId:
            metadata.setdefault("codex_thread_id", thread.codexThreadId)
        if thread.tenantId:
            metadata.setdefault("tenant_id", thread.tenantId)
        if thread.workspaceId:
            metadata.setdefault("workspace_id", thread.workspaceId)
        return metadata

    def get_runtime_thread_id(self, thread_id: str, runtime: str) -> str | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if runtime == "openai-codex" and thread and thread.codexThreadId:
            return thread.codexThreadId
        metadata = self.get_thread_metadata(thread_id)
        if runtime == "openai-codex":
            return _string_or_none(metadata.get("codex_thread_id"))
        runtime_threads = metadata.get("runtime_threads")
        if isinstance(runtime_threads, dict):
            return _string_or_none(runtime_threads.get(runtime))
        return None

    def get_analysis_thread_mapping(self, thread_id: str) -> dict[str, Any] | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread:
            return None
        return {
            "id": thread.id,
            "tenantId": thread.tenantId,
            "userId": thread.userId,
            "workspaceId": thread.workspaceId,
            "codexThreadId": thread.codexThreadId,
            "title": thread.title,
            "status": thread.status,
            "latest_turn_status": self.latest_turn_status(thread_id, state=state),
            "latest_turn_id": self.latest_turn_id(thread_id, state=state),
            "createdAt": thread.createdAt,
            "updatedAt": thread.updatedAt,
        }

    def get_turn_events(self, turn_id: str) -> list[dict[str, Any]]:
        """Return the Codex projection timeline for a turn.

        The historical implementation surfaced the GenBI
        ``ItemRecord`` row; the new contract returns the same
        projection shape the live SSE stream produces. The realtime
        stream and historical replay therefore share one normalised
        ``CodexItemProjectionRecord`` shape.
        """
        state = self._read_state()
        projections = [
            item
            for item in state["codex_item_projections"]
            if item.genbiTurnId == turn_id
        ]
        projections.sort(key=lambda item: (item.createdAt, item.codexItemId))
        return [_projection_to_event_dict(item, index) for index, item in enumerate(projections)]

    def list_threads(self, *, limit: int = 50, product_kind: ThreadProductKind | None = None) -> list[dict[str, Any]]:
        """Return the most-recently-updated threads.

        The session-level ``status`` is always ``active`` or
        ``archived``; callers who need to know what the latest turn did
        should call :meth:`latest_turn_status` or rely on the API
        surface to attach ``latest_turn_status`` to each row.
        """
        state = self._read_state()
        threads = list(state["threads"].values())
        if product_kind:
            threads = [item for item in threads if item.productKind == product_kind]
        threads.sort(key=lambda item: item.updatedAt, reverse=True)
        rows: list[dict[str, Any]] = []
        for thread in threads[:limit]:
            row = asdict(thread)
            row["latest_turn_status"] = self.latest_turn_status(thread.id, state=state)
            row["latest_turn_id"] = self.latest_turn_id(thread.id, state=state)
            rows.append(row)
        return rows

    def latest_turn_status(self, thread_id: str, *, state: dict[str, Any] | None = None) -> str | None:
        state = state or self._read_state()
        thread_turns = [turn for turn in state["turns"].values() if turn.threadId == thread_id]
        if not thread_turns:
            return None
        # ``updatedAt`` advances on every ``save_turn``/``create_turn_only``
        # call, so the most recently touched turn is the latest.
        thread_turns.sort(key=lambda turn: turn.updatedAt)
        return thread_turns[-1].status

    def latest_turn_id(self, thread_id: str, *, state: dict[str, Any] | None = None) -> str | None:
        state = state or self._read_state()
        thread_turns = [turn for turn in state["turns"].values() if turn.threadId == thread_id]
        if not thread_turns:
            return None
        thread_turns.sort(key=lambda turn: turn.updatedAt)
        return thread_turns[-1].id

    def delete_thread(self, thread_id: str, *, product_kind: ThreadProductKind | None = None) -> bool:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread or (product_kind and thread.productKind != product_kind):
            return False
        state["threads"].pop(thread_id, None)
        state["turns"] = {key: turn for key, turn in state["turns"].items() if turn.threadId != thread_id}
        state["codex_item_projections"] = [
            item for item in state["codex_item_projections"] if item.genbiThreadId != thread_id
        ]
        self._write_state(state)
        return True

    def clear(self) -> int:
        count = len(self._read_raw())
        if self.path.exists():
            self.path.unlink()
        return count

    def _read_state(self) -> dict[str, Any]:
        # The legacy ``item`` record is no longer produced. The
        # ``codex_item_projection`` table is the single source of
        # truth for the turn's projection timeline.
        state = {"threads": {}, "turns": {}, "codex_item_projections": []}
        for record in self._read_raw():
            record_type = record.get("record_type")
            payload = dict(record.get("payload") or {})
            if record_type == "thread":
                payload = _normalize_thread_payload(payload)
                item = ThreadRecord(**payload)
                state["threads"][item.id] = item
            elif record_type == "turn":
                payload = _normalize_turn_payload(payload)
                item = TurnRecord(**payload)
                state["turns"][item.id] = item
            elif record_type == "codex_item_projection":
                state["codex_item_projections"].append(CodexItemProjectionRecord(**payload))
            # Legacy ``item`` records are intentionally ignored: we
            # never wrote them after the GenBI Item was removed and
            # we don't surface them through the API surface.
        return state

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def _write_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for item in sorted(state["threads"].values(), key=lambda value: value.updatedAt):
                _write_record(file, "thread", asdict(item))
            for item in sorted(state["turns"].values(), key=lambda value: value.createdAt):
                _write_record(file, "turn", asdict(item))
            for item in sorted(state["codex_item_projections"], key=lambda value: value.createdAt):
                _write_record(file, "codex_item_projection", asdict(item))


def _write_record(file: Any, record_type: str, payload: dict[str, Any]) -> None:
    file.write(json.dumps({"record_type": record_type, "payload": payload}, ensure_ascii=False, default=str))
    file.write("\n")


def _projection_to_event_dict(
    projection: CodexItemProjectionRecord,
    index: int,
) -> dict[str, Any]:
    """Serialise a projection row into the unified turn-event shape.

    The realtime SSE stream and the historical replay endpoint
    (``get_turn_events``) both surface the same shape so the
    frontend can replay a session with a single rendering path.
    The shape mirrors what the live stream emits (type, turn_id,
    payload, created_at) plus a stable ``sequence`` so the client
    can dedupe arrivals.
    """
    return {
        # ``codexItemProjections`` store an opaque ``itemType`` from
        # Codex; the historical stream surfaced an explicit ``type``
        # field per event, so we mirror the same key. The frontend
        # can branch on ``itemType`` inside the payload if it needs
        # the original Codex type.
        "type": f"codex/{projection.itemType}",
        "turn_id": projection.codexTurnId or projection.genbiTurnId,
        "codex_thread_id": projection.codexThreadId or projection.genbiThreadId,
        "codex_turn_id": projection.codexTurnId,
        "codex_item_id": projection.codexItemId,
        "item_type": projection.itemType,
        "status": projection.status,
        "sequence": projection.sequence,
        "payload": dict(projection.payload or {}),
        "created_at": projection.createdAt,
        "completed_at": projection.completedAt,
    }


def _codex_item_projections_from_events(
    events: list["AgentEvent"],
    *,
    thread_id: str,
    turn_id: str,
    default_codex_thread_id: str | None,
) -> list[CodexItemProjectionRecord]:
    projections: dict[str, CodexItemProjectionRecord] = {}
    for event in events:
        codex_item_id = _string_or_none(event.payload.get("codex_item_id"))
        if not codex_item_id:
            continue
        existing = projections.get(codex_item_id)
        payload = dict(event.payload)
        item_type = _string_or_none(payload.get("codex_item_type")) or (existing.itemType if existing else "unknown")
        codex_thread_id = _string_or_none(payload.get("codex_thread_id")) or (existing.codexThreadId if existing else default_codex_thread_id)
        codex_turn_id = _string_or_none(payload.get("codex_turn_id")) or (existing.codexTurnId if existing else None)
        completed = payload.get("codex_method") == "item/completed" or payload.get("phase") in {"item.completed", "agent_message.completed"}
        status = "completed" if completed else (existing.status if existing else "streaming")
        projections[codex_item_id] = CodexItemProjectionRecord(
            codexItemId=codex_item_id,
            codexThreadId=codex_thread_id,
            codexTurnId=codex_turn_id,
            itemType=item_type,
            status=status,
            sequence=existing.sequence if existing else 0,
            payload=payload,
            createdAt=existing.createdAt if existing else event.created_at,
            completedAt=event.created_at if completed else (existing.completedAt if existing else None),
            genbiThreadId=thread_id,
            genbiTurnId=turn_id,
        )
    # Renumber the projections in arrival order. The realtime
    # stream emits events in the order Codex produced them, so a
    # stable sort by ``createdAt`` is good enough to recover the
    # dense ``sequence`` value. ``codexItemId`` is the tie-breaker
    # so two projections that share a timestamp keep a stable order
    # between live and replay.
    ordered = sorted(
        projections.values(),
        key=lambda item: (item.createdAt, item.codexItemId),
    )
    return [
        CodexItemProjectionRecord(
            **{**asdict(item), "sequence": index},
        )
        for index, item in enumerate(ordered)
    ]


def _turn_status(events: list["AgentEvent"]) -> str:
    """Derive the canonical turn state from the event stream.

    The turn state machine is exactly:
        running | completed | failed | cancelled | needs_input
    We map the ``turn/completed`` payload ``status`` to one of
    ``completed`` / ``failed`` / ``cancelled``; the ``ask``/``user``
    question events raise ``needs_input`` while the turn is still
    running. Anything still in flight is ``running``.
    """
    if any(_is_agent_question_event(event) for event in events):
        # A clarifying question never stops the turn — the user can
        # answer it; the turn only finalises once Codex emits
        # ``turn/completed``. The ``needs_input`` state is therefore
        # already covered when the turn is in flight, but we still
        # surface it for turns that ended with an unresolved question.
        return "needs_input"
    completed = next((event for event in reversed(events) if event.type == "turn/completed"), None)
    if completed is not None:
        raw_status = str(completed.payload.get("status") or "complete").lower()
        if raw_status in {"failed", "cancelled", "completed", "complete", "succeeded", "success", "ok", "interrupted"}:
            if raw_status in {"complete", "succeeded", "success", "ok"}:
                return "completed"
            if raw_status == "interrupted":
                return "cancelled"
            return raw_status
        return "failed"
    interrupted = next((event for event in reversed(events) if event.type == "turn/interrupted"), None)
    if interrupted is not None:
        return "cancelled"
    return "running"


def _is_agent_question_event(event: "AgentEvent") -> bool:
    return event.type == "item/completed" and event.payload.get("codex_item_type") == "agentQuestion"


def _first_payload_value(events: list["AgentEvent"], event_type: str, key: str) -> Any:
    for event in events:
        if event.type == event_type and key in event.payload:
            return event.payload[key]
    return None


def _latest_payload_value(events: list["AgentEvent"], key: str) -> Any:
    for event in reversed(events):
        if key in event.payload:
            return event.payload[key]
    return None


def _normalize_thread_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    payload.setdefault("tenantId", _thread_scope_value(metadata, "tenant_id", "tenantId"))
    payload.setdefault("workspaceId", _thread_scope_value(metadata, "workspace_id", "workspaceId"))
    payload.setdefault("codexThreadId", _thread_codex_thread_id(metadata))
    return payload


def _normalize_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    payload.setdefault("codexThreadId", _thread_codex_thread_id(metadata))
    payload.setdefault("codexTurnId", _string_or_none(metadata.get("codex_turn_id") or metadata.get("codexTurnId")))
    return payload


def _thread_scope_value(
    metadata: dict[str, Any],
    snake_key: str,
    camel_key: str,
    *,
    existing_value: str | None = None,
) -> str | None:
    return _string_or_none(metadata.get(snake_key) or metadata.get(camel_key) or existing_value)


def _thread_codex_thread_id(
    metadata: dict[str, Any],
    *,
    existing_thread: ThreadRecord | None = None,
) -> str | None:
    explicit = _string_or_none(metadata.get("codex_thread_id") or metadata.get("codexThreadId"))
    if explicit:
        return explicit
    runtime_threads = metadata.get("runtime_threads") or metadata.get("runtimeThreads")
    if isinstance(runtime_threads, dict):
        resolved = _string_or_none(runtime_threads.get("openai-codex"))
        if resolved:
            return resolved
    if existing_thread:
        return existing_thread.codexThreadId
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _title_from_question(question: str, *, input_kind: TurnInputKind) -> str | None:
    if input_kind != "start":
        return None
    text = " ".join(str(question or "").split())
    if not text:
        return None
    return text[:32]
