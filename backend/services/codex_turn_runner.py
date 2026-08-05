"""Codex analysis turn execution + persistence runner.

P2-3 refactor: previously the streaming turn loop, projection fold,
turn precreation, session registration, terminal-event compensation,
and event enrichment all lived as module-level helpers inside
``backend/api/analysis_api.py``. That file was > 2000 LOC and the
HTTP layer owned orchestration logic it should not have cared about.

The new boundary is:

* ``analysis_api`` — Pydantic request models, route handlers, and
  HTTP/SSE formatting. It validates inputs and hands work off.
* ``SessionService`` — session create / read / list / archive /
  rename. Owns the session catalog + projection store read side.
* ``ArtifactProjector`` — turns an ``item/completed`` event with a
  create_interactive_report payload into an ``genbi/artifact/updated``
  event (and a saved report, when a store is configured).
* ``CodexTurnRunner`` — this module. It:
  - Starts or resumes a turn via ``CodexSdkAnalysisRuntime.async_stream``
  - Parses ``genbi/thread/provisioned`` + ``genbi/turn/provisioned``
  - Registers the session row the first time the Runtime issues an id
  - Precreates the turn row in ``running`` state
  - Folds each event into ``CodexProjectionStore`` on the fly
  - Enriches session/turn ids into event payloads (``_enrich_analysis_event``)
  - Asks ``ArtifactProjector`` to project artifact events
  - Compensates a missing ``turn/completed`` with a synthetic terminal event
  - On SSE cancelation, appends ``status=interrupted`` so the store is
    never stuck on ``running``.

The service is instantiated once per FastAPI app inside ``create_app``
and is wired through closure variables so routes can use it. Tests
continue to pass because the HTTP contract is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from backend.harness.codex_projection_store import CodexProjectionStore
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.analysis_runtime import InMemoryCodexAnalysisRuntime, turn_status_from_events
from backend.harness.events import AgentEvent
from backend.harness.session_catalog import SessionCatalog
from backend.services.artifact_projector import ArtifactProjector


LOGGER = logging.getLogger(__name__)
ANALYSIS_PRODUCT_KIND = "analysis_task"


@dataclass(frozen=True)
class AnalysisTurnRequest:
    question: str
    session_id: str | None = None
    user_id: str | None = None
    turn_kind: str = "start"
    metadata: dict[str, Any] = field(default_factory=dict)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _first_event_payload_value(events: list[Any], key: str) -> str | None:
    for event in events:
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict) and payload.get(key):
            return str(payload[key])
    return None


def _first_event_codex_thread_id(events: list[Any]) -> str:
    for event in events:
        if getattr(event, "type", None) != "genbi/thread/provisioned":
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue
        codex_thread_id = _string_or_none(payload.get("codex_thread_id")) or _string_or_none(payload.get("session_id"))
        if codex_thread_id:
            return codex_thread_id
    return ""


def _last_event_payload_value(events: list[AgentEvent], key: str) -> str | None:
    for event in reversed(events):
        value = event.payload.get(key)
        if value:
            return str(value)
    return None


def _has_terminal_turn_event(events: list[AgentEvent]) -> bool:
    return any(event.type == "turn/completed" for event in events)


def _missing_terminal_event(*, session_id: str, turn_id: str) -> AgentEvent:
    return AgentEvent(
        type="turn/completed",
        turn_id=turn_id,
        payload={
            "eventSource": "genbi",
            "session_id": session_id,
            "turn_id": turn_id,
            "status": "failed",
            "error": "codex_stream_ended_without_turn_completed",
            "detail": "Codex stream ended without a terminal turn/completed event.",
        },
    )


def _interrupted_terminal_event(*, session_id: str, turn_id: str) -> AgentEvent:
    return AgentEvent(
        type="turn/completed",
        turn_id=turn_id,
        payload={
            "eventSource": "genbi",
            "session_id": session_id,
            "turn_id": turn_id,
            "status": "interrupted",
            "error": "client_disconnected",
            "detail": "Analysis stream was interrupted before Codex returned a terminal event.",
        },
    )


def _enrich_analysis_event(
    event: AgentEvent, *, session_id: str, turn_id: str, question: str | None = None
) -> AgentEvent:
    payload = dict(event.payload)
    payload.setdefault("session_id", session_id)
    payload.setdefault("turn_id", turn_id)
    if event.type == "turn/started" and question:
        payload.setdefault("question", question)
    if payload.get("codex_item_type") == "userMessage" and question:
        payload.setdefault("content", question)
    return AgentEvent(type=event.type, turn_id=turn_id, payload=payload, created_at=event.created_at)


def _knowledge_metadata_from_body(body: Any, *, partial: bool = False) -> dict[str, Any]:
    metadata = dict(getattr(body, "metadata", {}) or {})
    field_names = [
        "type",
        "business_definition",
        "technical_definition",
        "formula",
        "excluded_scope",
        "owner",
        "visibility",
        "status",
        "approvals",
        "tags",
        "related_tables",
        "related_fields",
        "related_resources",
        "expires_at",
        "conflicts",
        "agent_visible",
        "version",
    ]
    for field_name in field_names:
        value = getattr(body, field_name, None)
        if value is None:
            continue
        if isinstance(value, list):
            if partial or value:
                metadata[field_name] = value
        elif partial or value != "":
            metadata[field_name] = value
    return metadata


def _analysis_request_from_body(body: Any, *, session_id: str) -> AnalysisTurnRequest:
    turn_kind = str(getattr(body, "turn_kind", "start") or "start").strip().lower()
    if turn_kind not in {"start", "message", "reply"}:
        turn_kind = "message"
    metadata = dict(getattr(body, "metadata", {}) or {})
    metadata.pop("data_egress_authorized", None)
    metadata.pop("semantic_context_egress_authorized", None)
    metadata.setdefault("domain", "analysis_task")
    metadata.setdefault("session_id", session_id)
    metadata.setdefault("codex_session_id", session_id)
    metadata.setdefault("thread_root", not bool(session_id))
    return AnalysisTurnRequest(
        question=getattr(body, "message", getattr(body, "question", "")) or "",
        session_id=session_id,
        user_id=getattr(body, "user_id", None),
        turn_kind=turn_kind,  # type: ignore[arg-type]
        metadata=metadata,
    )


async def _provision_codex_thread_id(
    *,
    analysis_runtime: CodexSdkAnalysisRuntime,
    body: Any,
    allow_client_preflight: bool = True,
) -> str:
    metadata = dict(getattr(body, "metadata", None) or {})
    preflight = ""
    if allow_client_preflight:
        preflight = (
            _string_or_none(metadata.get("codex_session_id"))
            or _string_or_none(metadata.get("codex_thread_id"))
            or _string_or_none(getattr(body, "session_id", None))
        )
    if preflight:
        return preflight
    if not getattr(analysis_runtime, "enabled", False):
        raise RuntimeError(
            "codex_runtime_not_configured: provide codex_thread_id in "
            "request metadata so the GenBI thread can be provisioned."
        )
    from backend.harness.codex_sdk_runner import CodexSdkRunnerContext  # noqa: WPS433

    context = CodexSdkRunnerContext(
        genbi_thread_id=None,
        genbi_turn_id=None,
        codex_thread_id=None,
        cwd=str(Path.cwd()),
    )
    async for event in analysis_runtime.async_stream(
        "",
        context={
            "genbi_thread_id": preflight,
            "genbi_turn_id": None,
            "codex_thread_id": preflight,
            "codex_session_id": preflight,
            "cwd": str(Path.cwd()),
        },
    ):
        if event.type == "genbi/thread/provisioned":
            codex_thread_id = _string_or_none(event.payload.get("codex_thread_id"))
            if codex_thread_id:
                return codex_thread_id
            break
    raise RuntimeError("codex_runtime_did_not_emit_thread_id")


class CodexTurnRunner:
    """Execute an analysis turn and persist every projection side-effect.

    Responsibilities (see module docstring for the boundary rationale):

    * ``run_turn_buffered`` — synchronous-style endpoint: runs the
      Codex runtime to completion, buffers events, then writes the
      turn in one go. Used by the JSON POST endpoints that predate
      the SSE streaming surface.
    * ``stream_first_turn`` — generator for the very first turn of a
      brand-new session (sessionless first-turn contract). Emits
      ``session/created`` the moment we know the Codex session id
      then streams every subsequent business event.
    * ``stream_continuation_turn`` — generator for every later turn
      of an existing session.
    * ``stream_runtime_events`` — the raw per-event folding primitive;
      the two stream wrappers above feed off it.
    * ``interrupt_turn`` — writes ``status=interrupted`` to the
      projection store row for the currently-running turn and asks
      the Codex runtime to actually interrupt.
    * ``save_turn`` — folds buffered events into a final persistent
      turn row.

    Thread safety: per-instance state is the four injected stores
    (shared, not mutated on the runner). Safe for concurrent use iff
    the stores themselves allow concurrent calls.
    """

    def __init__(
        self,
        analysis_runtime: CodexSdkAnalysisRuntime,
        session_catalog: SessionCatalog,
        codex_projection_store: CodexProjectionStore,
        artifact_projector: ArtifactProjector,
    ) -> None:
        self._runtime = analysis_runtime
        self._catalog = session_catalog
        self._projections = codex_projection_store
        self._artifacts = artifact_projector
        # Bind the session catalog → latest-turn-provider seam so its
        # views expose the latest-turn status without circular imports.
        self._catalog.bind_latest_turn_provider(self._projections)

    # -- store accessors (used from HTTP layer for turn listing) -------

    @property
    def catalog(self) -> SessionCatalog:
        return self._catalog

    @property
    def projections(self) -> CodexProjectionStore:
        return self._projections

    @property
    def runtime(self) -> CodexSdkAnalysisRuntime:
        return self._runtime

    @property
    def artifacts(self) -> ArtifactProjector:
        return self._artifacts

    # -- context + save primitives -------------------------------------

    def runtime_context(
        self,
        request: AnalysisTurnRequest,
        *,
        session_id: str,
        turn_id: str,
        codex_session_id: str | None = None,
    ) -> dict[str, Any]:
        if codex_session_id is None:
            session = self._catalog.get_session(session_id) if session_id else None
            codex_session_id = session.codexSessionId if session else None
        return {
            "genbi_thread_id": session_id,
            "genbi_turn_id": turn_id,
            "turn_id": turn_id,
            "codex_session_id": codex_session_id,
            "codex_thread_id": codex_session_id,
        }

    def save_turn(
        self, request: AnalysisTurnRequest, *, session_id: str, turn_id: str, events: list[AgentEvent]
    ) -> None:
        runtime = InMemoryCodexAnalysisRuntime(self._projections)
        stream = runtime.turn_stream(
            session_id=session_id,
            turn_id=turn_id,
            catalog=self._catalog,
            projection_store=self._projections,
            input_text=request.question.strip(),
            turn_kind=request.turn_kind,
            events=events,
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                stream._persist_projections()
                stream._persist_turn(turn_status_from_events(events))
                return
        except RuntimeError:
            pass
        stream._persist_projections()
        stream._persist_turn(turn_status_from_events(events))

    def _accumulate_projection(
        self,
        runtime: InMemoryCodexAnalysisRuntime,
        session_id: str,
        turn_id: str,
        request: AnalysisTurnRequest,
        event: AgentEvent,
    ) -> None:
        stream = runtime.turn_stream(
            session_id=session_id,
            turn_id=turn_id,
            catalog=runtime.projection_store,  # placeholder; unused
            projection_store=runtime.projection_store,
            input_text=request.question.strip(),
            turn_kind=request.turn_kind,
            events=[event],
        )
        stream._persist_projections()

    # -- raw event stream (per-event folding) --------------------------

    async def stream_runtime_events(
        self,
        request: AnalysisTurnRequest,
        *,
        session_id: str,
        turn_id: str,
        codex_session_id: str | None = None,
    ) -> AsyncIterator[tuple[AgentEvent, str, str]]:
        """Yield ``(event, effective_thread_id, resolved_turn_id)``.

        The thread/turn ids may change during the iteration: they
        start at the caller-supplied values and snap to the Runtime's
        ``genbi/thread/provisioned`` / ``genbi/turn/provisioned`` the
        moment those events appear. Callers read the second + third
        positions of the tuple so the post-stream save writes the
        correct rows.
        """
        saw_terminal_event = False
        effective_thread_id = session_id
        runtime_codex_session_id = codex_session_id
        resolved_turn_id = turn_id
        runtime = InMemoryCodexAnalysisRuntime(self._projections)
        async for event in self._runtime.async_stream(
            request.question.strip(),
            context=self.runtime_context(
                request, session_id=session_id, turn_id=turn_id, codex_session_id=codex_session_id
            ),
        ):
            if event.type == "genbi/thread/provisioned":
                runtime_thread_id = (
                    _string_or_none(event.payload.get("codex_thread_id"))
                    or _string_or_none(event.payload.get("codex_session_id"))
                    or _string_or_none(event.payload.get("session_id"))
                    or ""
                )
                if runtime_thread_id:
                    runtime_codex_session_id = runtime_thread_id
                if not session_id and runtime_thread_id and runtime_thread_id != effective_thread_id:
                    effective_thread_id = runtime_thread_id
            if event.type == "genbi/turn/provisioned":
                provisioned_turn_id = (
                    _string_or_none(event.payload.get("codex_turn_id"))
                    or _string_or_none(event.payload.get("turn_id"))
                    or ""
                )
                if provisioned_turn_id:
                    resolved_turn_id = provisioned_turn_id
            if (
                event.type == "genbi/thread/provisioned"
                and effective_thread_id
                and self._catalog.get_session(effective_thread_id) is None
            ):
                try:
                    self._catalog.register_session(
                        session_id=effective_thread_id,
                        product_kind="analysis_task",
                        title=None,
                        user_id=request.user_id,
                        status="active",
                        metadata=dict(request.metadata or {}),
                        codex_session_id=runtime_codex_session_id or effective_thread_id,
                    )
                except Exception:
                    LOGGER.warning("session_registration_failed", extra={"session_id": effective_thread_id})
            if (
                event.type == "genbi/turn/provisioned"
                and effective_thread_id
                and resolved_turn_id
                and self._projections.get_turn(effective_thread_id, resolved_turn_id) is None
            ):
                self._projections.save_turn(
                    session_id=effective_thread_id,
                    turn_id=resolved_turn_id,
                    input_kind="start" if request.turn_kind == "start" else "message",
                    input_text=request.question.strip(),
                    status="running",
                    started_at=event.created_at,
                    codex_session_id=runtime_codex_session_id or effective_thread_id,
                    codex_turn_id=resolved_turn_id,
                )
            if effective_thread_id and resolved_turn_id:
                self._accumulate_projection(runtime, effective_thread_id, resolved_turn_id, request, event)
            enriched = _enrich_analysis_event(
                event,
                session_id=effective_thread_id,
                turn_id=resolved_turn_id,
                question=request.question.strip(),
            )
            if enriched.type == "turn/completed":
                saw_terminal_event = True
            yield enriched, effective_thread_id, resolved_turn_id
            artifact_event = self._artifacts.project_interactive_report(
                enriched,
                session_id=effective_thread_id,
                turn_id=resolved_turn_id,
            )
            if artifact_event:
                yield artifact_event, effective_thread_id, resolved_turn_id
        if not saw_terminal_event:
            yield _missing_terminal_event(session_id=session_id, turn_id=resolved_turn_id), effective_thread_id, resolved_turn_id

    # -- buffered (non-streaming) entry point --------------------------

    async def run_turn_buffered(
        self,
        request: AnalysisTurnRequest,
        *,
        session_id: str,
        codex_session_id: str | None = None,
        emit_session_created: bool = False,
    ) -> dict[str, Any]:
        from dataclasses import asdict as _asdict

        resolved_request = (
            request
            if isinstance(request, AnalysisTurnRequest)
            else _analysis_request_from_body(request, session_id=session_id)
        )
        turn_id = ""
        events: list[AgentEvent] = []
        async for event, effective_thread_id, this_turn_id in self.stream_runtime_events(
            resolved_request,
            session_id=session_id or "",
            turn_id="",
            codex_session_id=codex_session_id,
        ):
            if not turn_id and event.type == "genbi/turn/provisioned":
                turn_id = (
                    _string_or_none(event.payload.get("codex_turn_id"))
                    or _string_or_none(event.payload.get("turn_id"))
                    or ""
                )
            events.append(event)
        if not turn_id:
            raise RuntimeError(
                "codex_runtime_did_not_emit_turn_id: cannot persist turn without Codex-issued turn id."
            )
        runtime_thread_id = _first_event_codex_thread_id(events)
        resolved_thread_id = session_id or runtime_thread_id
        self.save_turn(
            resolved_request,
            session_id=resolved_thread_id,
            turn_id=turn_id,
            events=events,
        )
        response_events: list[dict[str, Any]] = []
        if emit_session_created and resolved_thread_id:
            response_events.append(
                _asdict(
                    AgentEvent(
                        type="session/created",
                        turn_id=turn_id,
                        payload={
                            "eventSource": "genbi",
                            "runtime": "openai-codex",
                            "sessionId": resolved_thread_id,
                            "codexThreadId": runtime_thread_id or resolved_thread_id,
                            "codexTurnId": turn_id,
                            "threadId": resolved_thread_id,
                            "turnId": turn_id,
                        },
                    )
                )
            )
        if emit_session_created:
            for event in events:
                if event.type in {"genbi/thread/provisioned", "genbi/turn/provisioned"}:
                    continue
                response_events.append(_asdict(event))
        else:
            response_events.extend(_asdict(event) for event in events)
        return {
            "session_id": resolved_thread_id,
            "turn_id": turn_id,
            "events_url": f"/api/analysis/sessions/{resolved_thread_id or ''}/turns/{turn_id}",
            "events": response_events,
        }

    # -- streaming entry points ----------------------------------------

    def stream_first_turn(self, request: AnalysisTurnRequest) -> AsyncIterator[AgentEvent]:
        """Stream the very first turn of a brand-new session."""
        return _FirstTurnStream(self, request)

    def stream_continuation_turn(
        self,
        body: Any,
        *,
        session_id: str,
        codex_session_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Stream turn N+1 of an existing (already provisioned) session."""
        request = (
            body
            if isinstance(body, AnalysisTurnRequest)
            else _analysis_request_from_body(body, session_id=session_id)
        )
        return _ContinuationTurnStream(
            self,
            request,
            session_id=session_id,
            codex_session_id=codex_session_id,
        )

    # -- interrupt support ---------------------------------------------

    async def interrupt_turn(self, *, session_id: str, turn_id: str) -> tuple[bool, dict[str, Any]]:
        """Mark a turn ``interrupted`` in the store AND ask Codex to stop.

        Returns a ``(handled, updated_row)`` tuple: ``handled`` is
        ``True`` when the runner actually flipped the projection row
        to a terminal state, and ``updated_row`` carries the updated
        turn metadata the HTTP endpoint can echo back.
        """
        existing = self._projections.get_turn(session_id, turn_id)
        session = self._catalog.get_session(session_id)
        runtime_session_id = (
            _string_or_none(getattr(existing, "codexSessionId", None))
            or _string_or_none(getattr(session, "codexSessionId", None))
            or session_id
        )
        codex_runtime_interrupted = False
        if getattr(self._runtime, "enabled", False):
            try:
                result = self._runtime.interrupt_turn(thread_id=runtime_session_id, turn_id=turn_id)
                if asyncio.iscoroutine(result):
                    codex_runtime_interrupted = bool(await result)
                else:
                    codex_runtime_interrupted = bool(result)
            except Exception:
                LOGGER.warning("codex_interrupt_failed", extra={"session_id": session_id, "turn_id": turn_id})
        if existing is None:
            return False, {"codex_runtime_interrupted": codex_runtime_interrupted}
        existing_status = getattr(existing, "status", None) or ""
        if existing_status in {"completed", "failed", "cancelled"}:
            return False, {
                "turn": existing,
                "already_terminal": True,
                "codex_runtime_interrupted": codex_runtime_interrupted,
            }
        completed_at = _now_iso()
        updated = self._projections.save_turn(
            session_id=session_id,
            turn_id=turn_id,
            input_kind=getattr(existing, "inputKind", "message"),
            input_text=getattr(existing, "inputText", ""),
            status="cancelled",
            started_at=getattr(existing, "startedAt", None),
            completed_at=completed_at,
            codex_session_id=getattr(existing, "codexSessionId", None),
            codex_turn_id=getattr(existing, "codexTurnId", None),
            metadata={**(getattr(existing, "metadata", None) or {}), "interrupted_at": completed_at},
        )
        self._catalog.mark_updated(session_id)
        return True, {
            "turn": updated,
            "completed_at": completed_at,
            "codex_runtime_interrupted": codex_runtime_interrupted,
        }


# ---------------------------------------------------------------------------
# Streaming helpers — implemented as classes with ``__aiter__`` so the
# streaming SSE route can return them directly, and ``finally`` blocks
# still run even if the server cancels the generator mid-flight.
# ---------------------------------------------------------------------------


class _FirstTurnStream:
    """Async-iterable wrapping the sessionless first-turn SSE contract."""

    def __init__(self, runner: CodexTurnRunner, request: AnalysisTurnRequest) -> None:
        self._runner = runner
        self._request = request
        self._events: list[AgentEvent] = []
        self._resolved_turn_id = ""
        self._resolved_thread_id = ""
        self._session_event_emitted = False

    def __aiter__(self):  # noqa: D105 — Magic method docstring is noise.
        return self._stream()

    async def _stream(self) -> AsyncIterator[AgentEvent]:
        try:
            async for event, effective_thread_id, turn_id in self._runner.stream_runtime_events(
                self._request, session_id="", turn_id=""
            ):
                if event.type == "genbi/thread/provisioned":
                    codex_thread_id = (
                        _string_or_none(event.payload.get("codex_thread_id"))
                        or _string_or_none(event.payload.get("session_id"))
                        or ""
                    )
                    if codex_thread_id:
                        self._resolved_thread_id = codex_thread_id
                if not self._resolved_turn_id and event.type == "genbi/turn/provisioned":
                    self._resolved_turn_id = (
                        _string_or_none(event.payload.get("codex_turn_id"))
                        or _string_or_none(event.payload.get("turn_id"))
                        or ""
                    )
                if event.type in {"genbi/thread/provisioned", "genbi/turn/provisioned"}:
                    continue
                if not self._session_event_emitted and self._resolved_thread_id and self._resolved_turn_id:
                    session_event = AgentEvent(
                        type="session/created",
                        turn_id=self._resolved_turn_id,
                        payload={
                            "eventSource": "genbi",
                            "runtime": "openai-codex",
                            "sessionId": self._resolved_thread_id,
                            "codexThreadId": self._resolved_thread_id,
                            "codexTurnId": self._resolved_turn_id,
                            "threadId": self._resolved_thread_id,
                            "turnId": self._resolved_turn_id,
                        },
                    )
                    self._events.append(session_event)
                    yield session_event
                    self._session_event_emitted = True
                self._events.append(event)
                yield event
        except asyncio.CancelledError:
            if not _has_terminal_turn_event(self._events):
                fallback_turn_id = self._resolved_turn_id or self._resolved_thread_id
                self._events.append(
                    _interrupted_terminal_event(
                        session_id=self._resolved_thread_id or "codex_session_pending",
                        turn_id=fallback_turn_id,
                    )
                )
            raise
        finally:
            if self._events and self._resolved_turn_id and self._resolved_thread_id:
                self._runner.save_turn(
                    self._request,
                    session_id=self._resolved_thread_id,
                    turn_id=self._resolved_turn_id,
                    events=self._events,
                )


class _ContinuationTurnStream:
    """Async-iterable wrapping the existing-session continuation contract."""

    def __init__(
        self,
        runner: CodexTurnRunner,
        request: AnalysisTurnRequest,
        *,
        session_id: str,
        codex_session_id: str | None,
    ) -> None:
        self._runner = runner
        self._request = request
        self._session_id = session_id
        self._codex_session_id = codex_session_id
        self._events: list[AgentEvent] = []
        self._resolved_turn_id = ""
        self._resolved_thread_id = ""

    def __aiter__(self):  # noqa: D105
        return self._stream()

    async def _stream(self) -> AsyncIterator[AgentEvent]:
        try:
            async for event, effective_thread_id, turn_id in self._runner.stream_runtime_events(
                self._request,
                session_id=self._session_id,
                turn_id="",
                codex_session_id=self._codex_session_id,
            ):
                if not self._resolved_thread_id and event.type == "genbi/thread/provisioned":
                    self._resolved_thread_id = (
                        _string_or_none(event.payload.get("codex_thread_id"))
                        or _string_or_none(event.payload.get("codex_session_id"))
                        or _string_or_none(event.payload.get("session_id"))
                        or ""
                    )
                if not self._resolved_turn_id and event.type == "genbi/turn/provisioned":
                    self._resolved_turn_id = (
                        _string_or_none(event.payload.get("codex_turn_id"))
                        or _string_or_none(event.payload.get("turn_id"))
                        or ""
                    )
                if event.type in {"genbi/thread/provisioned", "genbi/turn/provisioned"}:
                    continue
                self._events.append(event)
                yield event
        except asyncio.CancelledError:
            if not _has_terminal_turn_event(self._events):
                fallback_turn_id = self._resolved_turn_id or self._session_id
                self._events.append(
                    _interrupted_terminal_event(session_id=self._session_id, turn_id=fallback_turn_id)
                )
            raise
        finally:
            if self._events and self._resolved_turn_id and self._session_id:
                self._runner.save_turn(
                    self._request,
                    session_id=self._session_id,
                    turn_id=self._resolved_turn_id,
                    events=self._events,
                )
