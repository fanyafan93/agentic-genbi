"""Codex analysis runtime.

The runtime owns everything between the Codex SDK and the two thin
stores (``SessionCatalog`` and ``CodexProjectionStore``):

* ``thread_start`` / ``thread_resume`` (Codex session id handshake)
* ``turn.stream`` (AgentEvent → projection writes)
* ``interrupt`` (terminal cancelled transition)
* The turn state machine (``running`` / ``completed`` / ``failed`` /
  ``cancelled`` / ``needs_input``)

It does **not** know about:

* Session-level "active" / "archived" state
* Bookmarking, sharing, or artifact business rules
* Persistence file paths (the stores own those)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol

from backend.harness.codex_projection_store import (
    CodexItemProjectionRecord,
    CodexProjectionStore,
    TurnRecord,
)
from backend.harness.events import AgentEvent
from backend.harness.session_catalog import SessionCatalog, SessionRecord

LOGGER = logging.getLogger(__name__)


# --- turn status derivation (the only place the state machine lives) ---

def turn_status_from_events(events: list[AgentEvent]) -> str:
    """Map the ``AgentEvent`` stream onto the canonical turn state machine.

    The state machine is exactly:
        running | completed | failed | cancelled | needs_input
    """
    if any(_is_agent_question_event(event) for event in events):
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


def _is_agent_question_event(event: AgentEvent) -> bool:
    return event.type == "item/completed" and event.payload.get("codex_item_type") == "agentQuestion"


# --- projection accumulator ---

@dataclass
class _ProjectionAccumulator:
    """Fold the AgentEvent stream into CodexItemProjectionRecord rows.

    The runtime keeps a single accumulator per turn. It tracks the
    dense ``sequence`` (in arrival order) so live and replay share
    the same shape.
    """

    session_id: str
    turn_id: str
    codex_session_id: str | None
    codex_turn_id: str | None
    default_codex_thread_id: str | None
    store: CodexProjectionStore
    rows: dict[str, CodexItemProjectionRecord]
    arrival_counter: int

    def __init__(
        self,
        *,
        session_id: str,
        turn_id: str,
        default_codex_thread_id: str | None,
        store: CodexProjectionStore,
    ) -> None:
        self.session_id = session_id
        self.turn_id = turn_id
        self.codex_session_id = None
        self.codex_turn_id = None
        self.default_codex_thread_id = default_codex_thread_id
        self.store = store
        self.rows = {}
        self.arrival_counter = 0

    def feed(self, event: AgentEvent) -> CodexItemProjectionRecord | None:
        codex_item_id = _string_or_none(event.payload.get("codex_item_id"))
        if not codex_item_id:
            return None
        existing = self.rows.get(codex_item_id)
        payload = dict(event.payload)
        item_type = (
            _string_or_none(payload.get("codex_item_type"))
            or (existing.itemType if existing else "unknown")
        )
        codex_session_id = (
            _string_or_none(payload.get("codex_session_id"))
            or (existing.codexSessionId if existing else self.codex_session_id)
            or self.default_codex_thread_id
        )
        codex_turn_id = (
            _string_or_none(payload.get("codex_turn_id"))
            or (existing.codexTurnId if existing else self.codex_turn_id)
        )
        if codex_session_id:
            self.codex_session_id = codex_session_id
        if codex_turn_id:
            self.codex_turn_id = codex_turn_id
        completed = (
            payload.get("codex_method") == "item/completed"
            or payload.get("phase") in {"item.completed", "agent_message.completed"}
        )
        status = "completed" if completed else (existing.status if existing else "streaming")
        if not completed and existing is None:
            # First sighting: assign a sequence.
            sequence = self.arrival_counter
            self.arrival_counter += 1
        else:
            sequence = existing.sequence if existing else 0
        record = CodexItemProjectionRecord(
            codexItemId=codex_item_id,
            codexSessionId=codex_session_id,
            codexTurnId=codex_turn_id,
            itemType=item_type,
            status=status,
            sequence=sequence,
            payload=payload,
            createdAt=existing.createdAt if existing else event.created_at,
            completedAt=event.created_at if completed else (existing.completedAt if existing else None),
            genbiSessionId=self.session_id,
            genbiTurnId=self.turn_id,
        )
        self.rows[codex_item_id] = record
        return record


# --- public runtime ---

class CodexAnalysisRuntime(Protocol):
    """Async interface the runtime exposes to the API layer.

    The runtime owns:
    * thread_start / thread_resume (id handshake)
    * turn.stream (projection writes)
    * interrupt (terminal cancelled transition)
    """

    runtime_name: str

    async def thread_start(
        self,
        *,
        session_id: str,
        catalog: SessionCatalog,
    ) -> SessionRecord: ...

    async def thread_resume(
        self,
        *,
        session_id: str,
        catalog: SessionCatalog,
    ) -> SessionRecord: ...

    def turn_stream(
        self,
        *,
        session_id: str,
        turn_id: str,
        catalog: SessionCatalog,
        projection_store: CodexProjectionStore,
        input_text: str,
        turn_kind: str,
    ) -> "TurnStream": ...


@dataclass
class TurnStream:
    """Async-iterable stream that yields events as they arrive.

    The runtime pushes events to the projection store as they
    arrive. The final ``status`` is computed by the runtime after
    the underlying Codex SDK signals ``turn/completed`` (or a
    ``turn/interrupted`` terminal). Consumers ``async for`` over
    the stream and persist nothing.
    """

    runtime: "InMemoryCodexAnalysisRuntime"
    session_id: str
    turn_id: str
    input_text: str
    turn_kind: str
    events: list[AgentEvent]
    accumulator: _ProjectionAccumulator
    turn_record: TurnRecord

    async def collect(self) -> TurnRecord:
        """Drive the runtime and persist the final turn status.

        This is the path the API takes for a one-shot turn. The
        runtime has already produced the events (from a fake or
        real Codex SDK); we fold them through the accumulator,
        write the final turn status, and return the persisted row.
        """
        status = turn_status_from_events(self.events)
        # Persist the turn row first so the projection upsert can
        # reference a known ``turn_id``. The Runtime never writes
        # projections before the turn row exists.
        self._persist_turn(status)
        self._persist_projections()
        return self.turn_record

    def _persist_projections(self) -> None:
        # Renumber in arrival order to honour the dense sequence
        # contract: live + replay both yield 0..N-1.
        ordered = sorted(self.accumulator.rows.values(), key=lambda p: (p.createdAt, p.codexItemId))
        for index, row in enumerate(ordered):
            self.runtime.projection_store.upsert_item(
                session_id=self.session_id,
                turn_id=self.turn_id,
                codex_item_id=row.codexItemId,
                item_type=row.itemType,
                status=row.status,
                sequence=index,
                payload=row.payload,
                created_at=row.createdAt,
                completed_at=row.completedAt,
                codex_session_id=row.codexSessionId,
                codex_turn_id=row.codexTurnId,
            )

    def _persist_turn(self, status: str) -> None:
        if not self.events:
            return
        started_at = self.events[0].created_at
        completed_at = self.events[-1].created_at
        terminal = status in {"completed", "failed", "cancelled"}
        self.turn_record = self.runtime.projection_store.save_turn(
            session_id=self.session_id,
            turn_id=self.turn_id,
            input_kind="start" if self.turn_kind == "start" else "message",
            input_text=self.input_text,
            status=status,
            started_at=started_at,
            completed_at=completed_at if terminal else None,
            codex_session_id=self.accumulator.codex_session_id,
            codex_turn_id=self.accumulator.codex_turn_id,
        )

    async def interrupt(self) -> TurnRecord:
        """Mark the in-flight turn as ``cancelled``.

        Used by the API layer when the client disconnects before
        Codex emits a terminal event.
        """
        from backend.harness.codex_projection_store import TURN_TERMINAL_STATES

        if self.turn_record.status in TURN_TERMINAL_STATES:
            return self.turn_record
        completed_at = self.events[-1].created_at if self.events else None
        return self.runtime.projection_store.complete_turn(
            session_id=self.session_id,
            turn_id=self.turn_id,
            status="cancelled",
            completed_at=completed_at or "",
        )


class InMemoryCodexAnalysisRuntime:
    """A pure-CPU implementation of :class:`CodexAnalysisRuntime`.

    Tests use this to drive a turn end-to-end without the real
    Codex SDK. The API layer also uses it when the runtime is
    disabled (``CodexSdkAnalysisRuntime.disabled()``).
    """

    runtime_name = "in-memory"

    def __init__(self, projection_store: CodexProjectionStore) -> None:
        self.projection_store = projection_store

    async def thread_start(
        self,
        *,
        session_id: str,
        catalog: SessionCatalog,
    ) -> SessionRecord:
        # In the real SDK this issues ``thread.start``; for the
        # in-memory runtime we just register the session with the
        # catalog using the canonical ``active`` state. The new-
        # session contract (``session_id == codex_session_id``)
        # is enforced inside :meth:`SessionCatalog.register_session`.
        return catalog.register_session(
            session_id=session_id,
            product_kind="analysis_task",
            title=None,
            user_id=None,
            status="active",
            codex_session_id=session_id,
        )

    async def thread_resume(
        self,
        *,
        session_id: str,
        catalog: SessionCatalog,
    ) -> SessionRecord:
        existing = catalog.get_session(session_id)
        if existing is None:
            return catalog.register_session(
                session_id=session_id,
                product_kind="analysis_task",
                title=None,
                user_id=None,
                status="active",
                codex_session_id=session_id,
            )
        # Reactivating ensures the session is ``active`` again.
        if existing.status != "active":
            catalog.reactivate_session(session_id)
        return existing

    def turn_stream(
        self,
        *,
        session_id: str,
        turn_id: str,
        catalog: SessionCatalog,
        projection_store: CodexProjectionStore,
        input_text: str,
        turn_kind: str,
        events: list[AgentEvent] | None = None,
    ) -> TurnStream:
        accumulator = _ProjectionAccumulator(
            session_id=session_id,
            turn_id=turn_id,
            default_codex_thread_id=session_id,
            store=projection_store,
        )
        for event in events or []:
            accumulator.feed(event)
        return TurnStream(
            runtime=self,
            session_id=session_id,
            turn_id=turn_id,
            input_text=input_text,
            turn_kind=turn_kind,
            events=list(events or []),
            accumulator=accumulator,
            turn_record=_empty_turn(turn_id=turn_id, session_id=session_id, input_text=input_text),
        )


def _empty_turn(*, turn_id: str, session_id: str, input_text: str) -> TurnRecord:
    """Placeholder record used while the runtime accumulates events."""
    return TurnRecord(
        id=turn_id,
        sessionId=session_id,
        inputKind="start",
        question=input_text,
        inputText=input_text,
        status="running",
        createdAt="",
        updatedAt="",
        startedAt=None,
        completedAt=None,
        metadata={},
        codexSessionId=None,
        codexTurnId=turn_id,
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
