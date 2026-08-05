"""Locks the user spec that the SessionCatalog is a thin owner of the
session row.

The catalog MUST NOT see:
* ``AgentEvent`` (Codex Runtime owns that translation)
* ``ToolCall`` (projection store owns the Codex item stream)
* Codex item payloads
* Any turn execution logic
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints

from backend.harness.session_catalog import (
    SessionCatalog,
    SessionRecord,
    SessionView,
)


class SessionCatalogPurityTest(unittest.TestCase):
    def test_session_catalog_api_does_not_accept_turn_events(self) -> None:
        # The catalog's public surface is bounded by the spec
        # (list / get / register / rename / archive). Anything
        # else is a leak.
        public_methods = {
            name
            for name, value in inspect.getmembers(SessionCatalog, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        forbidden = {
            "save_turn",
            "save_events",
            "create_turn",
            "create_turn_only",
            "upsert_item",
            "get_turn_events",
            "list_turns",
            "list_items",
        }
        leaked = public_methods & forbidden
        self.assertEqual(
            leaked,
            set(),
            msg=f"SessionCatalog must not expose turn-level APIs: {leaked}",
        )

    def test_session_catalog_does_not_import_agent_event_or_tool_call(self) -> None:
        # Lock the import surface: the catalog module must not bring
        # in AgentEvent / ToolCall / Codex item payload types.
        module = importlib_module("backend.harness.session_catalog")
        forbidden = {
            "AgentEvent",
            "ToolCall",
            "CodexItemProjection",
            "CodexItemProjectionRecord",
            "TurnRecord",
            "TURN_STATES",
        }
        leaked = {name for name in forbidden if hasattr(module, name)}
        self.assertEqual(
            leaked,
            set(),
            msg=f"SessionCatalog must not import runtime types: {leaked}",
        )

    def test_session_catalog_owns_only_active_and_archived(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = SessionCatalog(path=Path(temp_dir) / "sessions.jsonl")
            for session_id in ("s_active", "s_archived"):
                catalog.register_session(
                    session_id=session_id,
                    product_kind="analysis_task",
                    title=session_id,
                    user_id=None,
                    status="active" if session_id == "s_active" else "archived",
                )
            self.assertEqual(len(catalog.list_sessions()), 2)
            self.assertEqual(
                {s.status for s in catalog.list_sessions()},
                {"active", "archived"},
            )

    def test_session_catalog_rejects_legacy_session_states(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = SessionCatalog(path=Path(temp_dir) / "sessions.jsonl")
            for legacy in (
                "running",
                "completed",
                "failed",
                "waiting_for_question",
                "needs_input",
            ):
                with self.assertRaises(ValueError):
                    catalog.register_session(
                        session_id=f"s_{legacy}",
                        product_kind="analysis_task",
                        title=None,
                        user_id=None,
                        status=legacy,
                    )

    def test_session_catalog_latest_turn_signal_via_provider_seam(self) -> None:
        # The catalog asks the projection store for the latest turn
        # signal via the LatestTurnProvider seam. The catalog itself
        # never reads Codex item payloads.
        class _FakeProvider:
            def __init__(self, status: str, turn_id: str) -> None:
                self._status = status
                self._turn_id = turn_id

            def latest_turn_status(self, session_id: str) -> str | None:
                return self._status

            def latest_turn_id(self, session_id: str) -> str | None:
                return self._turn_id

        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = SessionCatalog(path=Path(temp_dir) / "sessions.jsonl")
            catalog.bind_latest_turn_provider(_FakeProvider("failed", "turn_42"))
            catalog.register_session(
                session_id="s_test",
                product_kind="analysis_task",
                title="t",
                user_id=None,
                status="active",
            )
            view = catalog.get_view("s_test")
            self.assertIsNotNone(view)
            assert view is not None
            self.assertEqual(view.latestTurnStatus, "failed")
            self.assertEqual(view.latestTurnId, "turn_42")

    def test_session_catalog_rename_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = SessionCatalog(path=Path(temp_dir) / "sessions.jsonl")
            catalog.register_session(
                session_id="s_rename",
                product_kind="analysis_task",
                title="old title",
                user_id=None,
                status="active",
            )
            catalog.rename_session("s_rename", "new title")
            refreshed = catalog.get_session("s_rename")
            assert refreshed is not None
            self.assertEqual(refreshed.title, "new title")

    def test_session_catalog_archive_reactivate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog = SessionCatalog(path=Path(temp_dir) / "sessions.jsonl")
            catalog.register_session(
                session_id="s_lifecycle",
                product_kind="analysis_task",
                title="t",
                user_id=None,
                status="active",
            )
            archived = catalog.archive_session("s_lifecycle")
            self.assertEqual(archived.status, "archived")
            self.assertEqual(catalog.get_session("s_lifecycle").status, "archived")
            reactivated = catalog.reactivate_session("s_lifecycle")
            self.assertEqual(reactivated.status, "active")

    def test_session_catalog_module_keeps_api_surface_compact(self) -> None:
        # The catalog API surface is exactly the spec; lock the
        # public method count so we don't accidentally grow it.
        public = {
            name
            for name, _ in inspect.getmembers(SessionCatalog, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        expected = {
            "get_session",
            "list_sessions",
            "get_view",
            "list_views",
            "resolve_session_id",
            "register_session",
            "rename_session",
            "archive_session",
            "reactivate_session",
            "delete_session",
            "mark_updated",
            "bind_latest_turn_provider",
        }
        self.assertEqual(public, expected)

    def test_resolve_session_id_accepts_legacy_codex_session_id_alias(self) -> None:
        # Old records were persisted with ``id != codex_session_id``
        # (the row carried a GenBI-assigned id AND a Codex-issued
        # id). The new contract is ``id == codex_session_id`` but
        # we still accept the Codex-issued id on the way in; the
        # resolver returns the canonical row id so the rest of
        # the stack only ever sees the row, never the alias.
        #
        # We can't go through ``register_session`` to write the
        # legacy shape: new registrations enforce ``id ==
        # codex_session_id``. The legacy row therefore has to be
        # seeded by writing the JSONL file directly, exactly as
        # the older code would have persisted it.
        with tempfile.TemporaryDirectory() as temp_dir:
            catalog_path = Path(temp_dir) / "legacy.jsonl"
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_payload = {
                "id": "genbi_legacy_1",
                "productKind": "analysis_task",
                "title": "legacy session",
                "userId": None,
                "status": "active",
                "createdAt": "2026-08-01T00:00:00.000000+00:00",
                "updatedAt": "2026-08-01T00:00:00.000000+00:00",
                "metadata": {"codex_session_id": "codex_legacy_1"},
                "tenantId": None,
                "workspaceId": None,
                "codexSessionId": "codex_legacy_1",
            }
            catalog_path.write_text(json.dumps(legacy_payload, ensure_ascii=False) + "\n", encoding="utf-8")
            catalog = SessionCatalog(catalog_path)

            # New record path: id == codexSessionId.
            catalog.register_session(
                session_id="new_session_2",
                product_kind="analysis_task",
                title="new session",
                user_id=None,
                status="active",
            )

            self.assertEqual(catalog.resolve_session_id("genbi_legacy_1"), "genbi_legacy_1")
            self.assertEqual(catalog.resolve_session_id("codex_legacy_1"), "genbi_legacy_1")
            self.assertEqual(catalog.resolve_session_id("new_session_2"), "new_session_2")
            self.assertEqual(catalog.resolve_session_id(""), None)
            self.assertEqual(catalog.resolve_session_id("missing"), None)

            view = catalog.get_view("codex_legacy_1")
            self.assertIsNotNone(view)
            assert view is not None
            self.assertEqual(view.session.id, "genbi_legacy_1")
            self.assertEqual(view.session.codexSessionId, "codex_legacy_1")


def importlib_module(name: str):
    import importlib

    return importlib.import_module(name)


if __name__ == "__main__":
    unittest.main()
