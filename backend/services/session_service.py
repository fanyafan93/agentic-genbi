"""Business-facing Session lifecycle service.

This is the *only* place HTTP handlers go when they want to
create / read / list / archive a session or its turns. It wraps
the thin ``SessionCatalog`` (row storage) + ``CodexProjectionStore``
(turn + item projection storage) components and exposes a business
semantic API:

* ``get_session_detail`` / ``list_sessions`` — read-side views, with
  status filter so the default "sidebar" list is strictly ``active``.
* ``archive_session`` — soft delete (P2-3). The ``DELETE /sessions/{id}``
  HTTP handler calls this and never calls the catalog's
  ``delete_session`` row-level helper directly, which would leak
  orphan turns and projections.
* ``reactivate_session`` — recycle-bin UI.
* ``resolve_session_id`` — mirrors the catalog's canonical id lookup
  so the API layer never needs to know how legacy id aliases are
  resolved.

The API layer (``backend/api/analysis_api.py``) should only call this
service; it must not read or write session/turn rows directly. This
was the user's P2-3 complaint: "ThreadStore 确实删掉了，是对的。但现在
analysis_api.py 自己处理 Codex provisioned 事件 / Session 注册 /
Turn 预创建 / Projection 累积 / Turn 状态计算 / Artifact 投影 /
中断补偿 / 旧 ID 兼容 / Store 协调"。

This module handles the Session *lifecycle* slice of that list.
The turn execution slice lives in ``CodexTurnRunner``; the artifact
projection slice lives in ``ArtifactProjector``.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from backend.harness.codex_projection_store import (
    CodexItemProjectionRecord,
    CodexProjectionStore,
    TurnRecord,
)
from backend.harness.session_catalog import SessionCatalog, SessionRecord, SessionView


SessionStatus = Literal["active", "archived"]
VALID_SESSION_STATUSES: tuple[SessionStatus, ...] = ("active", "archived")
ANALYSIS_PRODUCT_KIND = "analysis_task"


class SessionNotFoundError(LookupError):
    """Raised when a session id does not resolve to a catalog row."""


class SessionArchivedError(RuntimeError):
    """Raised when a caller tries to start a new turn on an archived session."""


class SessionService:
    """Session lifecycle + read projections. Thread-safe iff the wrapped
    catalog/projection stores are."""

    def __init__(
        self,
        session_catalog: SessionCatalog,
        codex_projection_store: CodexProjectionStore,
    ) -> None:
        self._catalog = session_catalog
        self._projections = codex_projection_store
        # Wire up the catalog → latest-turn-status provider seam so
        # ``SessionView.latestTurnStatus`` works regardless of which
        # backend owns the turn rows. The catalog explicitly does NOT
        # read projections directly — it only owns the session row.
        self._catalog.bind_latest_turn_provider(self._projections)

    # -- id resolution + existence -------------------------------------

    def resolve_session_id(self, raw_id: str) -> str | None:
        """Map either a legacy alias or the canonical id to canonical id."""
        if not raw_id or not raw_id.strip():
            return None
        return self._catalog.resolve_session_id(raw_id)

    def require_active_view(self, raw_id: str) -> SessionView:
        """Return a session view if *and only if* it exists and is active.

        Raises ``SessionNotFoundError`` for missing ids and
        ``SessionArchivedError`` when the session has already been
        soft-deleted. The continuation endpoints (JSON + stream) are
        the primary callers so the API layer can return 404 / 409
        without ever touching the runtime.
        """
        canonical_id = self.resolve_session_id(raw_id)
        if canonical_id is None:
            raise SessionNotFoundError(raw_id)
        view = self._catalog.get_view(canonical_id)
        if view is None:
            raise SessionNotFoundError(raw_id)
        if view.session.status == "archived":
            raise SessionArchivedError(canonical_id)
        return view

    def require_view(self, raw_id: str) -> SessionView:
        """Return the view even for archived sessions (for GET detail)."""
        canonical_id = self.resolve_session_id(raw_id)
        if canonical_id is None:
            raise SessionNotFoundError(raw_id)
        view = self._catalog.get_view(canonical_id)
        if view is None:
            raise SessionNotFoundError(raw_id)
        return view

    # -- listings -------------------------------------------------------

    def list_sessions(
        self,
        *,
        limit: int = 50,
        status: SessionStatus | None = None,
        product_kind: str = ANALYSIS_PRODUCT_KIND,
    ) -> list[SessionView]:
        """Sidebar-facing list. Default is ``active`` sessions only.

        ``status=None`` is treated as ``active`` so the default
        sidebar never shows soft-deleted rows; explicit
        ``status="archived"`` enables a future recycle-bin UI.
        """
        effective_status: SessionStatus = status if status is not None else "active"
        if effective_status not in VALID_SESSION_STATUSES:
            raise ValueError(
                f"invalid status filter: {status!r}; expected one of {list(VALID_SESSION_STATUSES)}."
            )
        views = self._catalog.list_views(limit=limit, product_kind=product_kind)
        # ``draft_`` prefixed ids are transient preflight rows used in
        # legacy flows. Hide them from the visible list.
        views = [v for v in views if not str(v.session.id).startswith("draft_")]
        views = [v for v in views if v.session.status == effective_status]
        return views

    # -- session lifecycle ---------------------------------------------

    def get_session_detail(self, raw_id: str) -> dict[str, Any]:
        """Build the ``GET /sessions/{id}`` response envelope.

        Reads session metadata, turn rows, and the per-turn item
        projection timeline — exactly what the "open old analysis"
        page needs for historical replay.
        """
        view = self.require_view(raw_id)
        session = view.session
        turns = self._projections.list_turns(session_id=session.id)
        turn_dicts: list[dict[str, Any]] = []
        for turn in turns:
            events = self._projections.get_turn_events(session_id=session.id, turn_id=turn.id)
            turn_dict = asdict(turn)
            turn_dict["timeline"] = events
            turn_dicts.append(turn_dict)
        codex_items = self._projections.list_items(session_id=session.id)
        codex_item_projections = [asdict(item) for item in codex_items]
        return {
            "id": session.id,
            "title": session.title,
            "status": session.status,
            "createdAt": session.createdAt,
            "updatedAt": session.updatedAt,
            "productKind": session.productKind,
            "codexSessionId": session.codexSessionId,
            "metadata": dict(session.metadata or {}),
            "latestTurnId": view.latestTurnId,
            "latestTurnStatus": view.latestTurnStatus,
            "turns": turn_dicts,
            "codexItemProjections": codex_item_projections,
        }

    def archive_session(self, raw_id: str) -> SessionRecord:
        """Soft-delete a session.

        Physical deletion is intentionally deferred to an admin-level
        purge routine (see the ``docs/plans/current.md`` next steps):
        the JSONL backend has no transactional cascade and Postgres
        tables do not yet carry ``analysis_threads.id`` FKs +
        ``ON DELETE CASCADE``, so a row-level remove today would leak
        orphan ``turns`` / ``projections``. Archiving is strictly
        safer: the session disappears from the active sidebar, refuses
        new turns, but remains readable for historical replay.
        """
        canonical_id = self.resolve_session_id(raw_id)
        if canonical_id is None:
            raise SessionNotFoundError(raw_id)
        try:
            return self._catalog.archive_session(canonical_id)
        except ValueError as exc:
            if "session not found" in str(exc):
                raise SessionNotFoundError(raw_id) from exc
            raise

    def reactivate_session(self, raw_id: str) -> SessionRecord:
        """Restore a soft-deleted (archived) session back to active.

        Used by the future recycle-bin UI. ``POST /sessions/{id}/turns``
        refuses new turns while ``status=archived``, so callers must
        ``reactivate`` before adding work to a previously-deleted
        session.
        """
        canonical_id = self.resolve_session_id(raw_id)
        if canonical_id is None:
            raise SessionNotFoundError(raw_id)
        try:
            return self._catalog.reactivate_session(canonical_id)
        except ValueError as exc:
            if "session not found" in str(exc):
                raise SessionNotFoundError(raw_id) from exc
            raise

    def rename_session(self, raw_id: str, *, title: str) -> SessionRecord:
        canonical_id = self.resolve_session_id(raw_id)
        if canonical_id is None:
            raise SessionNotFoundError(raw_id)
        return self._catalog.rename_session(canonical_id, title=title)

    def update_status(self, raw_id: str, *, status: SessionStatus) -> SessionRecord:
        canonical_id = self.resolve_session_id(raw_id)
        if canonical_id is None:
            raise SessionNotFoundError(raw_id)
        if status == "archived":
            return self._catalog.archive_session(canonical_id)
        return self._catalog.reactivate_session(canonical_id)

    # -- turn read helpers (used by get_session_detail above) ----------

    def list_turns(self, session_id: str) -> list[TurnRecord]:
        return self._projections.list_turns(session_id=session_id)

    def list_items(self, *, session_id: str, turn_id: str | None = None) -> list[CodexItemProjectionRecord]:
        return self._projections.list_items(session_id=session_id, turn_id=turn_id)

    # -- raw seam for the turn runner ----------------------------------
    # The ``CodexTurnRunner`` needs direct access when it commits
    # turns and projections mid-flight. We deliberately expose these
    # as *explicitly named* raw accessors rather than leaking the
    # store objects themselves, so we can audit call sites.

    @property
    def raw_catalog(self) -> SessionCatalog:
        """Low-level catalog access. Prefer the service methods above."""
        return self._catalog

    @property
    def raw_projections(self) -> CodexProjectionStore:
        """Low-level projection access. Prefer the service methods above."""
        return self._projections
