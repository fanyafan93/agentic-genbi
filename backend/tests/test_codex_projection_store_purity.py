"""Locks the user spec that the CodexProjectionStore is a thin owner of
the turn + Codex item rows.

The projection store MUST NOT know about:

* User permissions / sharing / bookmarking
* Artifact business rules
* Session-level "active" / "archived" state
"""

from __future__ import annotations

import importlib
import inspect
import tempfile
import unittest
from pathlib import Path

from backend.harness.codex_projection_store import (
    CodexProjectionStore,
    TurnRecord,
    TURN_STATES,
    TURN_TERMINAL_STATES,
)
from backend.harness.events import AgentEvent


class CodexProjectionStorePurityTest(unittest.TestCase):
    def test_projection_store_api_does_not_know_session_state(self) -> None:
        # The projection store never sees ``active`` / ``archived``
        # or any session-level state machine. Its mutations are
        # turn + projection writes only.
        public = {
            name
            for name, _ in inspect.getmembers(CodexProjectionStore, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        forbidden = {
            "archive_session",
            "reactivate_session",
            "register_session",
            "rename_session",
            "save_artifact",
            "share_artifact",
            "bookmark_artifact",
            "list_user_permissions",
        }
        leaked = public & forbidden
        self.assertEqual(
            leaked,
            set(),
            msg=f"CodexProjectionStore must not expose session/artifact APIs: {leaked}",
        )

    def test_projection_store_accepts_standardised_turn_fields_only(self) -> None:
        # ``save_turn`` accepts *pre-computed* status / timestamps;
        # it MUST NOT take an ``events`` list or any other AgentEvent
        # translation hint.
        signature = inspect.signature(CodexProjectionStore.save_turn)
        forbidden_params = {"events", "agent_events", "transient_state"}
        leaked = set(signature.parameters) & forbidden_params
        self.assertEqual(
            leaked,
            set(),
            msg=f"save_turn must not accept event translation: {leaked}",
        )

    def test_projection_store_turn_state_machine_is_terminal_only(self) -> None:
        # The projection store still owns the turn state machine,
        # but it must only know about TURN_TERMINAL_STATES for
        # complete_turn. ``active`` / ``archived`` is the catalog's
        # concern.
        signature = inspect.signature(CodexProjectionStore.complete_turn)
        status_param = signature.parameters["status"]
        # The status is required; no default. The Runtime must
        # always pass the canonical turn state explicitly.
        self.assertIs(status_param.default, inspect.Parameter.empty)

    def test_upsert_item_accepts_standardised_projection_fields(self) -> None:
        signature = inspect.signature(CodexProjectionStore.upsert_item)
        forbidden_params = {"events", "item_kind", "session_kind", "user_principal"}
        leaked = set(signature.parameters) & forbidden_params
        self.assertEqual(
            leaked,
            set(),
            msg=f"upsert_item must not accept event translation: {leaked}",
        )

    def test_save_turn_rejects_non_terminal_state_via_complete_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CodexProjectionStore(path=Path(temp_dir) / "p.jsonl")
            store.save_turn(
                session_id="s",
                turn_id="t",
                input_kind="start",
                input_text="q",
                status="running",
            )
            with self.assertRaises(ValueError):
                store.complete_turn(
                    session_id="s",
                    turn_id="t",
                    status="active",  # session-level state leaked into turn
                    completed_at="2026-08-05T00:00:00Z",
                )
            # The turn-state machine is the only allowed set.
            self.assertEqual(
                set(TURN_STATES),
                {"running", "completed", "failed", "cancelled", "needs_input"},
            )
            self.assertEqual(
                set(TURN_TERMINAL_STATES),
                {"completed", "failed", "cancelled"},
            )

    def test_upsert_item_requires_turn_to_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CodexProjectionStore(path=Path(temp_dir) / "p.jsonl")
            # Upserting a projection for a missing turn is rejected:
            # the store never auto-creates a turn row.
            with self.assertRaises(ValueError):
                store.upsert_item(
                    session_id="s",
                    turn_id="missing",
                    codex_item_id="it_1",
                    item_type="agentMessage",
                    status="streaming",
                    sequence=0,
                    payload={},
                    created_at="2026-08-05T00:00:00Z",
                )

    def test_upsert_item_rejects_turn_belonging_to_another_session(self) -> None:
        """Cross-session projection pollution MUST raise ValueError.

        The previous guard (``if turn_id not in state["turns"]``)
        allowed an attacker to append projections with
        ``genbiSessionId = B`` against a turn that really lives on
        session A, orphaning the lineage. The new guard checks
        ``turn.sessionId == session_id`` so mismatches are refused
        at write time.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CodexProjectionStore(path=Path(temp_dir) / "p.jsonl")
            # Turn ``t_a`` genuinely belongs to session A.
            store.save_turn(
                session_id="sess_a",
                turn_id="t_a",
                input_kind="start",
                input_text="a q",
                status="running",
                started_at="2026-08-05T00:00:00Z",
            )
            # The happy path: upsert on the *owning* session works.
            store.upsert_item(
                session_id="sess_a",
                turn_id="t_a",
                codex_item_id="it_ok",
                item_type="agentMessage",
                status="completed",
                sequence=0,
                payload={"text": "hi"},
                created_at="2026-08-05T00:00:01Z",
            )
            # The forbidden path: upserting with session_id = B on
            # the *same* turn_id must blow up, even though the turn
            # exists.
            with self.assertRaises(ValueError) as ctx:
                store.upsert_item(
                    session_id="sess_b",
                    turn_id="t_a",
                    codex_item_id="it_bad",
                    item_type="agentMessage",
                    status="streaming",
                    sequence=1,
                    payload={"text": "polluted"},
                    created_at="2026-08-05T00:00:02Z",
                )
            msg = str(ctx.exception)
            self.assertIn("t_a", msg)
            self.assertIn("sess_a", msg, "error must name the turn's real owning session")
            self.assertIn("sess_b", msg, "error must name the caller-supplied wrong session")
            # The projection store must never have written the bad
            # row: list_items on sess_b is empty and sess_b still
            # has no turns.
            self.assertEqual(store.list_items(session_id="sess_b"), [])
            self.assertEqual(store.list_turns(session_id="sess_b"), [])
            good_projections = store.list_items(session_id="sess_a", turn_id="t_a")
            self.assertEqual([p.codexItemId for p in good_projections], ["it_ok"])

    def test_save_turn_rejects_turn_id_owned_by_another_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CodexProjectionStore(path=Path(temp_dir) / "p.jsonl")
            store.save_turn(
                session_id="sess_a",
                turn_id="turn_shared",
                input_kind="start",
                input_text="a",
                status="running",
            )

            with self.assertRaises(ValueError) as ctx:
                store.save_turn(
                    session_id="sess_b",
                    turn_id="turn_shared",
                    input_kind="message",
                    input_text="b",
                    status="running",
                )

            msg = str(ctx.exception)
            self.assertIn("turn_shared", msg)
            self.assertIn("sess_a", msg)
            self.assertIn("sess_b", msg)
            self.assertEqual(store.get_turn("sess_a", "turn_shared").inputText, "a")
            self.assertIsNone(store.get_turn("sess_b", "turn_shared"))

    def test_upsert_item_rejects_item_id_owned_by_another_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CodexProjectionStore(path=Path(temp_dir) / "p.jsonl")
            store.save_turn(
                session_id="sess_a",
                turn_id="turn_a",
                input_kind="start",
                input_text="a",
                status="running",
            )
            store.save_turn(
                session_id="sess_b",
                turn_id="turn_b",
                input_kind="start",
                input_text="b",
                status="running",
            )
            store.upsert_item(
                session_id="sess_a",
                turn_id="turn_a",
                codex_item_id="item_shared",
                item_type="agentMessage",
                status="completed",
                sequence=0,
                payload={"text": "a"},
                created_at="2026-08-05T00:00:00Z",
            )

            with self.assertRaises(ValueError) as ctx:
                store.upsert_item(
                    session_id="sess_b",
                    turn_id="turn_b",
                    codex_item_id="item_shared",
                    item_type="agentMessage",
                    status="completed",
                    sequence=0,
                    payload={"text": "b"},
                    created_at="2026-08-05T00:00:01Z",
                )

            msg = str(ctx.exception)
            self.assertIn("item_shared", msg)
            self.assertIn("sess_a", msg)
            self.assertIn("turn_a", msg)
            self.assertIn("sess_b", msg)
            self.assertIn("turn_b", msg)
            self.assertEqual(store.list_items(session_id="sess_b", turn_id="turn_b"), [])
            self.assertEqual(
                store.list_items(session_id="sess_a", turn_id="turn_a")[0].payload,
                {"text": "a"},
            )

    def test_save_turn_rejects_moving_existing_turn_across_sessions(self) -> None:
        """``save_turn`` is an UPSERT — the existing guard must also
        refuse to re-parent a turn from session A onto session B.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CodexProjectionStore(path=Path(temp_dir) / "p.jsonl")
            store.save_turn(
                session_id="sess_a",
                turn_id="t_x",
                input_kind="message",
                input_text="q1",
                status="running",
                started_at="2026-08-05T00:00:00Z",
            )
            with self.assertRaises(ValueError) as ctx:
                store.save_turn(
                    session_id="sess_b",
                    turn_id="t_x",
                    input_kind="message",
                    input_text="q2",
                    status="completed",
                    started_at="2026-08-05T00:00:10Z",
                    completed_at="2026-08-05T00:00:20Z",
                )
            msg = str(ctx.exception)
            self.assertIn("t_x", msg)
            self.assertIn("sess_a", msg)
            self.assertIn("sess_b", msg)
            # The original turn row must still point at sess_a.
            turn = store.get_turn(session_id="sess_a", turn_id="t_x")
            self.assertIsNotNone(turn)
            self.assertEqual(turn.sessionId, "sess_a")
            self.assertIsNone(store.get_turn(session_id="sess_b", turn_id="t_x"))

    def test_projection_store_does_not_know_user_permissions(self) -> None:
        module = importlib.import_module("backend.harness.codex_projection_store")
        for forbidden in (
            "user_id",
            "tenant_id",
            "permission",
            "is_bookmarked",
            "is_shared",
            "share_token",
        ):
            self.assertFalse(
                hasattr(module, forbidden),
                msg=f"CodexProjectionStore must not depend on {forbidden}",
            )

    def test_projection_store_keeps_compact_public_api(self) -> None:
        # Lock the public surface. The store is intentionally small
        # so the Runtime is the only thing allowed to translate
        # events into projections.
        public = {
            name
            for name, _ in inspect.getmembers(CodexProjectionStore, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        expected = {
            "save_turn",
            "complete_turn",
            "upsert_item",
            "get_turn",
            "get_turn_by_id",
            "list_turns",
            "list_items",
            "get_turn_events",
            "latest_turn_status",
            "latest_turn_id",
            "bind_session_touch",
        }
        self.assertEqual(public, expected)


if __name__ == "__main__":
    unittest.main()
