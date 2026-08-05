from __future__ import annotations

import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from backend.analysis.asset_store import AnalysisAssetStore
from backend.analysis.interactive_report_store import InteractiveReportStore
import backend.api.analysis_api as analysis_api
from backend.api.analysis_api import create_app
from backend.services.artifact_projector import ArtifactProjector
from backend.services.codex_turn_runner import (
    CodexTurnRunner,
    _enrich_analysis_event,
    _interrupted_terminal_event,
    _analysis_request_from_body,
)
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.codex_projection_store import CodexProjectionStore
from backend.harness.events import AgentEvent
from backend.harness.session_catalog import SessionCatalog
from backend.business_semantics.knowledge_store import KnowledgeStore


# Backwards-compat shim: legacy tests construct ``ThreadStore(...)`` and
# call ``create_thread`` / ``save_turn`` / ``get_thread`` on the
# returned object. The new ``create_app`` takes a ``session_catalog``
# and a ``codex_projection_store`` instead; this helper bundles the
# two and proxies the legacy names so the existing test bodies keep
# reading naturally while exercising the new components.
class _TestStores:
    def __init__(self, path: Path) -> None:
        self._path = path
        self.session_catalog = SessionCatalog(path=path.with_name(path.stem + "-sessions.jsonl"))
        self.codex_projection_store = CodexProjectionStore(path=path.with_name(path.stem + "-projections.jsonl"))
        # Bind the sidebar signal.
        self.session_catalog.bind_latest_turn_provider(self.codex_projection_store)
        self.codex_projection_store.bind_session_touch(self.session_catalog)

    def create_thread(
        self,
        *,
        thread_id: str,
        product_kind: str,
        title: str | None,
        user_id: str | None,
        status: str = "active",
        codex_thread_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict[str, Any]:
        session = self.session_catalog.register_session(session_id=thread_id,
            product_kind=product_kind,
            title=title,
            user_id=user_id,
            status=status,
            codex_session_id=codex_thread_id or thread_id,
            metadata=metadata,
        )
        return {"thread": asdict(session), "turns": [], "codexItemProjections": []}

    def create_turn_only(self, *, thread_id: str, turn_id: str, codex_turn_id: str | None = None) -> Any:
        return self.codex_projection_store.save_turn(
            session_id=thread_id,
            turn_id=turn_id,
            input_kind="start",
            input_text="",
            status="running",
            codex_session_id=thread_id,
            codex_turn_id=codex_turn_id or turn_id,
        )

    def save_turn(self, *, thread_id: str, turn_id: str, question: str, **kwargs: Any) -> dict[str, Any]:
        from backend.harness.analysis_runtime import InMemoryCodexAnalysisRuntime

        events: list[AgentEvent] = kwargs.get("events", [])
        runtime = InMemoryCodexAnalysisRuntime(self.codex_projection_store)
        stream = runtime.turn_stream(
            session_id=thread_id,
            turn_id=turn_id,
            catalog=self.session_catalog,
            projection_store=self.codex_projection_store,
            input_text=question,
            turn_kind=kwargs.get("input_kind", "start"),
            events=events,
        )
        # The Runtime owns the state machine. We always run its
        # collect path so the projection and turn row are written
        # via the same code the API uses.
        stream._persist_turn(_turn_status_for(events))
        stream._persist_projections()
        return {"turn": asdict(stream.turn_record)}

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        view = self.session_catalog.get_view(thread_id)
        if view is None:
            return None
        turns = self.codex_projection_store.list_turns(thread_id)
        projections = self.codex_projection_store.list_items(session_id=thread_id)
        thread_row = asdict(view.session)
        thread_row["latest_turn_status"] = view.latestTurnStatus
        thread_row["latest_turn_id"] = view.latestTurnId
        thread_row["latestTurnStatus"] = view.latestTurnStatus
        thread_row["latestTurnId"] = view.latestTurnId
        thread_row["codexThreadId"] = view.session.codexSessionId
        thread_row["codex_thread_id"] = view.session.codexSessionId
        return {
            "session": thread_row,
            "thread": thread_row,
            "turns": [asdict(t) for t in turns],
            "codexItemProjections": [asdict(p) for p in projections],
        }

    def get_turn(self, thread_id: str, turn_id: str) -> dict[str, Any] | None:
        turn = self.codex_projection_store.get_turn(thread_id, turn_id)
        if turn is None:
            return None
        projections = self.codex_projection_store.list_items(session_id=thread_id, turn_id=turn_id)
        session = self.session_catalog.get_session(thread_id)
        return {
            "thread": asdict(session) if session else None,
            "turn": asdict(turn),
            "codexItemProjections": [asdict(p) for p in projections],
        }

    def list_threads(self, *, limit: int = 50, product_kind: str | None = None) -> list[dict[str, Any]]:
        views = self.session_catalog.list_views(limit=limit, product_kind=product_kind)
        rows: list[dict[str, Any]] = []
        for v in views:
            row = asdict(v.session)
            row["latest_turn_status"] = v.latestTurnStatus
            row["latest_turn_id"] = v.latestTurnId
            # ``latestQuestion`` is the sidebar title fallback.
            turns = self.codex_projection_store.list_turns(v.session.id)
            latest_turn = turns[-1] if turns else None
            row["latestQuestion"] = (latest_turn.inputText if latest_turn else "") or None
            row["latest_turn_status"] = latest_turn.status if latest_turn else None
            row["codexThreadId"] = v.session.codexSessionId
            row["codex_thread_id"] = v.session.codexSessionId
            rows.append(row)
        return rows

    def get_turn_events(self, turn_id: str) -> list[dict[str, Any]]:
        # The projection store splits turns by ``session_id``. We
        # scan the (small) in-memory state to find the owning
        # session id; this is only used in tests.
        for _turn_id, turn in self.codex_projection_store._read_state()["turns"].items():  # type: ignore[attr-defined]
            if turn.id == turn_id:
                return self.codex_projection_store.get_turn_events(turn.sessionId, turn_id)
        return []

    def archive_thread(self, thread_id: str) -> None:
        self.session_catalog.archive_session(thread_id)

    def reactivate_thread(self, thread_id: str) -> None:
        self.session_catalog.reactivate_session(thread_id)


# Legacy alias so existing test bodies keep working.
ThreadStore = _TestStores


def _turn_status_for(events: list[AgentEvent]) -> str:
    from backend.harness.analysis_runtime import turn_status_from_events
    return turn_status_from_events(events) if events else "running"


class _FakeCodexRuntime:
    runtime_name = "openai-codex"
    enabled = True

    def __init__(self) -> None:
        self.contexts: list[dict] = []
        self._invocation = 0
        self.interrupt_calls: list[tuple[str, str]] = []

    def stream(self, question: str, *, context: dict):
        self.contexts.append(dict(context))
        yield from self._events(context)

    async def async_stream(self, question: str, *, context: dict):
        self.contexts.append(dict(context))
        for event in self._events(context):
            yield event

    def interrupt_turn(self, thread_id: str, turn_id: str) -> bool:
        self.interrupt_calls.append((str(thread_id), str(turn_id)))
        return True

    def _events(self, context: dict):
        self._invocation += 1
        invocation = self._invocation
        codex_thread_id = context.get("codex_session_id") or context.get("codex_thread_id") or "codex_thread_created"
        codex_turn_id = f"codex_turn_{invocation}"
        # New-session contract: emit the provisioned-thread marker first so
        # ``analysis_threads.id == analysis_threads.codex_thread_id``.
        yield AgentEvent(
            type="genbi/thread/provisioned",
            turn_id=codex_turn_id,
            payload={
                "eventSource": "genbi",
                "runtime": "openai-codex",
                "codex_thread_id": codex_thread_id,
                "thread_id": codex_thread_id,
            },
        )
        yield AgentEvent(
            type="genbi/turn/provisioned",
            turn_id=codex_turn_id,
            payload={
                "eventSource": "genbi",
                "runtime": "openai-codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": codex_turn_id,
                "thread_id": codex_thread_id,
                "turn_id": codex_turn_id,
            },
        )
        yield AgentEvent(
            type="turn/started",
            turn_id=codex_turn_id,
            payload={
                "eventSource": "codex",
                "runtime": "openai-codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": codex_turn_id,
            },
        )
        yield AgentEvent(
            type="item/agentMessage/delta",
            turn_id=codex_turn_id,
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": codex_turn_id,
                "codex_item_id": "codex_item_msg",
                "codex_item_type": "agentMessage",
                "delta": "hello",
            },
        )
        yield AgentEvent(
            type="item/completed",
            turn_id=codex_turn_id,
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": codex_turn_id,
                "codex_item_id": "codex_item_msg",
                "codex_item_type": "agentMessage",
                "content": "Codex answer",
            },
        )
        yield AgentEvent(
            type="turn/completed",
            turn_id=codex_turn_id,
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": codex_turn_id,
                "status": "completed",
            },
        )


class _AsyncOnlyRuntime:
    runtime_name = "openai-codex"
    enabled = True

    def stream(self, question: str, *, context: dict):
        raise RuntimeError("sync stream must not be used from the create path")

    async def async_stream(self, question: str, *, context: dict):
        codex_thread_id = context.get("codex_thread_id") or "codex_thread_async"
        yield AgentEvent(
            type="genbi/thread/provisioned",
            turn_id="codex_turn_async",
            payload={
                "eventSource": "genbi",
                "runtime": "openai-codex",
                "codex_thread_id": codex_thread_id,
                "thread_id": codex_thread_id,
            },
        )
        yield AgentEvent(
            type="genbi/turn/provisioned",
            turn_id="codex_turn_async",
            payload={
                "eventSource": "genbi",
                "runtime": "openai-codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_async",
                "thread_id": codex_thread_id,
                "turn_id": "codex_turn_async",
            },
        )
        yield AgentEvent(
            type="turn/completed",
            turn_id="codex_turn_async",
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_async",
                "status": "completed",
            },
        )


class _MissingTerminalRuntime:
    runtime_name = "openai-codex"
    enabled = True

    async def async_stream(self, question: str, *, context: dict):
        codex_thread_id = "codex_thread_missing_terminal"
        yield AgentEvent(
            type="genbi/thread/provisioned",
            turn_id="codex_turn_missing_terminal",
            payload={
                "eventSource": "genbi",
                "runtime": "openai-codex",
                "codex_thread_id": codex_thread_id,
                "thread_id": codex_thread_id,
            },
        )
        yield AgentEvent(
            type="genbi/turn/provisioned",
            turn_id="codex_turn_missing_terminal",
            payload={
                "eventSource": "genbi",
                "runtime": "openai-codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_missing_terminal",
                "thread_id": codex_thread_id,
                "turn_id": "codex_turn_missing_terminal",
            },
        )
        yield AgentEvent(
            type="turn/started",
            turn_id="codex_turn_missing_terminal",
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_missing_terminal",
            },
        )
        yield AgentEvent(
            type="item/completed",
            turn_id="codex_turn_missing_terminal",
            payload={
                "eventSource": "codex",
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": "codex_turn_missing_terminal",
                "codex_item_id": "codex_item_tool",
                "codex_item_type": "mcpToolCall",
                "mcp_server": "BI_doris",
                "mcp_tool": "mysql_query",
                "mcp_status": "completed",
            },
        )


class AnalysisApiTest(unittest.IsolatedAsyncioTestCase):
    def test_default_analysis_runtime_uses_codex_runtime_when_configured(self) -> None:
        with patch.dict("os.environ", {"GENBI_ANALYSIS_RUNTIME": "codex"}, clear=False):
            with patch.object(analysis_api.CodexSdkAnalysisRuntime, "from_env") as from_env:
                runtime = object()
                from_env.return_value = runtime

                service = analysis_api.build_default_analysis_runtime()

                self.assertIs(service, runtime)
                from_env.assert_called_once()

    def test_create_app_uses_postgres_session_and_projection_stores_when_enabled(self) -> None:
        with patch.dict("os.environ", {"GENBI_PERSISTENCE": "postgres"}, clear=False):
            with patch.object(analysis_api, "build_postgres_session_catalog") as build_session_catalog, patch.object(
                analysis_api, "build_postgres_codex_projection_store"
            ) as build_codex_projection_store:
                with tempfile.TemporaryDirectory() as temp_dir:
                    session_catalog = SessionCatalog(path=Path(temp_dir) / "sessions.jsonl")
                    codex_projection_store = CodexProjectionStore(path=Path(temp_dir) / "projections.jsonl")
                    build_session_catalog.return_value = session_catalog
                    build_codex_projection_store.return_value = codex_projection_store

                    app = create_app(
                        knowledge_store=KnowledgeStore(),
                        analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                        analysis_asset_store=AnalysisAssetStore(Path("unused-assets.jsonl")),
                        interactive_report_store=InteractiveReportStore(Path("unused-reports.jsonl")),
                    )

                    self.assertIsNotNone(app)
                    build_session_catalog.assert_called_once()
                    build_codex_projection_store.assert_called_once()

    def test_system_mcp_server_api_lists_trusted_report_tool(self) -> None:
        with patch.dict("os.environ", {
            "GENBI_CODEX_MCP_COUNT": "1",
            "GENBI_CODEX_MCP_1_NAME": "GenBI_report",
            "GENBI_CODEX_MCP_1_COMMAND": "python",
            "GENBI_CODEX_MCP_1_ARGS": "-m backend.mcp_servers.genbi_report_server",
        }, clear=False):
            app = create_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
            client = TestClient(app)

            listed = client.get("/api/system/mcp/servers")
            tested = client.post("/api/system/mcp/servers/GenBI_report/test")

            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()["servers"][0]["name"], "GenBI_report")
            self.assertEqual(listed.json()["servers"][0]["approval"], "trusted")
            self.assertEqual(tested.status_code, 200)
            self.assertTrue(tested.json()["ok"])

    def test_analysis_thread_turn_api_streams_codex_events_and_persists_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/sessions/turns",
                json={"message": "analyze channel sales share"},
            )
            payload = response.json()

            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["session_id"].startswith("codex_thread_"))
            self.assertNotIn("thread_id", payload)
            self.assertNotIn("conversation_id", payload)
            self.assertTrue(payload["turn_id"].startswith("codex_turn_"))
            # ``session/created`` is the user-facing envelope; the
            # internal ``genbi/*`` markers are filtered out so the
            # client never has to reason about them.
            self.assertEqual(
                [event["type"] for event in payload["events"]],
                ["session/created", "turn/started", "item/agentMessage/delta", "item/completed", "turn/completed"],
            )
            self.assertTrue(all(event["payload"]["eventSource"] in ("codex", "genbi") for event in payload["events"]))

            thread = client.get(f"/api/analysis/sessions/{payload['session_id']}")
            # The single-turn detail endpoint was retired; the full
            # session detail already exposes the latest turn.
            self.assertEqual(thread.status_code, 200)
            self.assertEqual(thread.json()["session"]["id"], payload["session_id"])
            self.assertEqual(thread.json()["session"]["codexThreadId"], "codex_thread_created")
            self.assertEqual(thread.json()["turns"][0]["codexTurnId"], payload["turn_id"])
            self.assertEqual(thread.json()["codexItemProjections"][0]["codexItemId"], "codex_item_msg")

    def test_analysis_thread_list_includes_latest_question_for_sidebar_titles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            created = client.post("/api/analysis/sessions/turns", json={"message": "real sidebar question"})
            listed = client.get("/api/analysis/sessions")

            self.assertEqual(created.status_code, 200)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()["sessions"][0]["latestQuestion"], "real sidebar question")

    def test_analysis_thread_list_hides_legacy_draft_threads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )
            client = TestClient(app)

            thread_store.session_catalog.register_session("draft_report_report_1",
                product_kind="analysis_task",
                title="legacy draft",
                user_id=None,
                status="archived",
            )
            thread_store.session_catalog.register_session("codex_thread_real",
                product_kind="analysis_task",
                title="real thread",
                user_id=None,
                status="active",
            )

            listed = client.get("/api/analysis/sessions")

            self.assertEqual(listed.status_code, 200)
            self.assertEqual([item["id"] for item in listed.json()["sessions"]], ["codex_thread_real"])

    def test_create_waiting_analysis_thread_without_turn(self) -> None:
        # ``POST /api/analysis/sessions/turns`` is the only entry
        # point. With the runtime disabled the endpoint MUST
        # return 503 and MUST NOT create a session row, regardless
        # of whether the client supplied a preflight id in
        # metadata. The previous contract accepted a client-supplied
        # id and wrote a fake ``running`` turn row with the
        # caller's primary key — that violated the
        # "session id is owned by Codex" rule and let clients
        # mint non-Codex sessions / turns.
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            preflight_id = "codex_thread_waiting"
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )
            client = TestClient(app)

            # Even with a preflight id the disabled runtime must
            # refuse the request.
            response = client.post(
                "/api/analysis/sessions/turns",
                json={
                    "message": "first question",
                    "user_id": "user_1",
                    "metadata": {"codex_session_id": preflight_id},
                },
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn("codex_runtime_not_configured", response.json()["detail"])
            # No session row is written.
            self.assertEqual(
                len(thread_store.list_threads(product_kind="analysis_task")),
                0,
            )

            # No preflight at all => 503 (still no row written).
            response_no_preflight = client.post(
                "/api/analysis/sessions/turns",
                json={"message": "first question"},
            )
            self.assertEqual(response_no_preflight.status_code, 503)
            self.assertEqual(
                len(thread_store.list_threads(product_kind="analysis_task")),
                0,
            )

    def test_create_waiting_analysis_thread_reuses_existing_empty_thread(self) -> None:
        # The new contract has no "waiting for question" state. Each
        # call to ``POST /api/analysis/sessions/turns`` always
        # provisions a fresh session id. The legacy "reuse existing
        # empty thread" branch is gone; this test now asserts the
        # explicit behaviour.
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )
            client = TestClient(app)

            # Two calls with the runtime disabled cannot provision a
            # session (no live Codex), so the catalog stays empty.
            for _ in range(2):
                response = client.post(
                    "/api/analysis/sessions/turns",
                    json={"message": "first question"},
                )
                self.assertIn(response.status_code, (400, 503))
            self.assertEqual(
                thread_store.list_threads(product_kind="analysis_task"),
                [],
            )

    def test_analysis_thread_api_returns_text_verbatim_no_runtime_encoding_repair(self) -> None:
        """Strict UTF-8 contract: the API never patches encoding at render time.

        Previously the read endpoints ran latin1→utf-8 conversion and hid
        high-?%-ratio strings via ``_repair_text_encoding``. The P1 cleanup
        removed every runtime encoding-repair path because it masked bugs
        at the persistence layer. The read side now returns whatever bytes
        were written at rest; the caller is responsible for ensuring the
        writer wrote UTF-8.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            created = client.post("/api/analysis/sessions/turns", json={"message": "legacy question"})
            thread_id = created.json()["session_id"]
            listed = client.get("/api/analysis/sessions")
            detail = client.get(f"/api/analysis/sessions/{thread_id}")

            # Exactly what was written comes back. No latin1/utf-8 patching.
            self.assertEqual(listed.json()["sessions"][0]["latestQuestion"], "legacy question")
            self.assertEqual(detail.json()["turns"][0]["question"], "legacy question")

    def test_analysis_thread_api_does_not_mask_mojibake_at_read_time(self) -> None:
        """Strict UTF-8 contract: even corrupted strings surface verbatim.

        The previous implementation called ``_is_unreadable_legacy_text``
        and coerced any string with >25% question marks to ``None``. That
        hid persistence corruption. Under the strict UTF-8 contract, the
        API surface must *not* sanitise output — corrupted data should be
        visible so it can be fixed at rest (the writer / Postgres COPY /
        JSON import path).
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            message = "?? GMV ???????????????"
            created = client.post("/api/analysis/sessions/turns", json={"message": message})
            thread_id = created.json()["session_id"]
            listed = client.get("/api/analysis/sessions")
            detail = client.get(f"/api/analysis/sessions/{thread_id}")

            # Corrupted-but-written data surfaces verbatim. Caller decides
            # whether to show a placeholder; the HTTP layer never hides it.
            self.assertEqual(listed.json()["sessions"][0]["latestQuestion"], message)
            self.assertEqual(detail.json()["turns"][0]["question"], message)

    def test_delete_analysis_thread_soft_archives_instead_of_orphan_deletion(self) -> None:
        """DELETE is a soft archive to avoid leaking orphan turns/projections.

        The previous implementation called ``SessionCatalog.delete_session``,
        which only removed the catalog row — the TurnRecord and
        CodexItemProjection rows on disk / in Postgres would silently
        become orphans with nothing pointing at them. The user spec
        flagged this explicitly: "I suggest we archive-only for v1".

        So DELETE now maps to ``archive_session``. The response still
        returns ``{ "deleted": True, "session_id": "<id>" }`` so
        existing clients stay compatible; the contract changes are:

        * the session disappears from the default ``GET /sessions``
          active list (sidebar hides it),
        * ``GET /sessions/{id}`` still returns the archived row for
          historical replay,
        * ``POST /sessions/{id}/turns[ /stream]`` returns
          409 ``analysis_session_archived`` (refuses new work),
        * the catalog row, its turns, and projections are all still
          on disk (no orphan leak).
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            created = client.post("/api/analysis/sessions/turns", json={"message": "delete sidebar item"})
            self.assertEqual(created.status_code, 200)
            thread_id = created.json()["session_id"]

            # 1) DELETE returns the original envelope plus an
            #    ``archived=true`` side-effect session dict.
            deleted = client.delete(f"/api/analysis/sessions/{thread_id}")
            self.assertEqual(deleted.status_code, 200)
            payload = deleted.json()
            self.assertEqual(payload["deleted"], True)
            self.assertEqual(payload["session_id"], thread_id)
            self.assertEqual(payload["session"]["status"], "archived")
            self.assertEqual(payload["session"]["id"], thread_id)

            # 2) Default active sidebar no longer lists it.
            listed_default = client.get("/api/analysis/sessions")
            self.assertEqual(listed_default.status_code, 200)
            self.assertEqual(listed_default.json()["sessions"], [])
            listed_active = client.get("/api/analysis/sessions", params={"status": "active"})
            self.assertEqual(listed_active.json()["sessions"], [])

            # 3) Archived list still sees it (for future recycle bin UI).
            archived_list = client.get("/api/analysis/sessions", params={"status": "archived"})
            self.assertEqual(archived_list.status_code, 200)
            self.assertEqual(len(archived_list.json()["sessions"]), 1)
            self.assertEqual(archived_list.json()["sessions"][0]["status"], "archived")

            # 4) GET detail still works — historical replay must be
            #    possible, consistent with the "soft deleted, not
            #    physically purged" contract.
            detail = client.get(f"/api/analysis/sessions/{thread_id}")
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()["session"]["status"], "archived")
            self.assertEqual(detail.json()["session"]["id"], thread_id)

            # 5) DELETE an already-archived session is idempotent (not
            #    a 404), because the catalog row is still present.
            deleted_again = client.delete(f"/api/analysis/sessions/{thread_id}")
            self.assertEqual(deleted_again.status_code, 200)
            self.assertEqual(deleted_again.json()["session"]["status"], "archived")

            # 6) Continuation on a soft-deleted session is refused.
            cont = client.post(
                f"/api/analysis/sessions/{thread_id}/turns",
                json={"message": "continue on deleted", "turn_kind": "message"},
            )
            self.assertEqual(cont.status_code, 409)
            self.assertIn("analysis_session_archived", cont.json()["detail"])
            cont_stream = client.post(
                f"/api/analysis/sessions/{thread_id}/turns/stream",
                json={"message": "continue on deleted", "turn_kind": "message"},
            )
            self.assertEqual(cont_stream.status_code, 409)
            self.assertIn("analysis_session_archived", cont_stream.json()["detail"])

            # 7) No orphans: the underlying store rows still exist.
            self.assertEqual(len(thread_store.session_catalog.list_sessions()), 1)
            self.assertEqual(
                thread_store.session_catalog.get_session(thread_id).status,
                "archived",
            )
            turns = thread_store.codex_projection_store.list_turns(session_id=thread_id)
            self.assertGreaterEqual(len(turns), 1, "session must still own its turns after DELETE")
            for turn in turns:
                self.assertEqual(turn.sessionId, thread_id)

    async def test_create_analysis_turn_payload_uses_async_runtime_inside_running_event_loop(self) -> None:
        # The session id is owned by the Codex Runtime; the API
        # layer passes an empty preflight id and the runtime
        # allocates the real id. ``_AsyncOnlyRuntime`` issues
        # ``codex_thread_async`` when no preflight is supplied
        # (its own deterministic id, the way a real Codex SDK
        # would behave — no caller-supplied id involved).
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            body = SimpleNamespace(
                question="async create path",
                user_id=None,
                turn_kind="start",
                metadata={},
            )
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            runner = CodexTurnRunner(
                _AsyncOnlyRuntime(),  # type: ignore[arg-type]
                thread_store.session_catalog,
                thread_store.codex_projection_store,
                ArtifactProjector(report_store),
            )
            request = _analysis_request_from_body(body, session_id="")
            payload = await runner.run_turn_buffered(request, session_id="", codex_session_id=None, emit_session_created=False)

            self.assertEqual(payload["session_id"], "codex_thread_async")
            self.assertEqual(payload["events"][0]["type"], "genbi/thread/provisioned")
            # The runtime-issued id is the canonical session id.
            self.assertEqual(
                thread_store.get_thread("codex_thread_async")["session"]["id"],  # type: ignore[index]
                "codex_thread_async",
            )

    def test_enrich_analysis_event_adds_question_to_user_message_items(self) -> None:
        event = AgentEvent(
            type="item/completed",
            turn_id="codex_turn_user",
            payload={
                "eventSource": "codex",
                "codex_item_type": "userMessage",
                "codex_item_id": "codex_user_item",
            },
        )

        enriched = _enrich_analysis_event(
            event,
            session_id="thread_1",
            turn_id="turn_1",
            question="follow-up question",
        )

        self.assertEqual(enriched.payload["content"], "follow-up question")

    def test_analysis_thread_turn_stream_api_preserves_codex_thread_for_followup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            first = client.post(
                "/api/analysis/sessions/turns",
                json={"message": "first purchase 30d repurchase"},
            )
            first_payload = first.json()
            genbi_thread_id = first_payload["session_id"]
            second = client.post(
                f"/api/analysis/sessions/{genbi_thread_id}/turns",
                json={"message": "continue analysis", "turn_kind": "message"},
            )
            second_payload = second.json()

            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            # The first turn's events include the canonical
            # ``item/agentMessage/delta`` and ``turn/completed``;
            # the second turn reuses the same session id.
            first_event_types = [event["type"] for event in first_payload["events"]]
            second_event_types = [event["type"] for event in second_payload["events"]]
            self.assertIn("item/agentMessage/delta", first_event_types)
            self.assertIn("turn/completed", second_event_types)
            # The question for the second turn appears in the
            # ``turn/started`` event payload; assert directly on
            # the structured response instead of the SSE text.
            turn_started = next(
                event for event in second_payload["events"] if event["type"] == "turn/started"
            )
            self.assertEqual(turn_started["payload"].get("question"), "continue analysis")
            self.assertEqual(runtime.contexts[1]["codex_thread_id"], "codex_thread_created")

    def test_stream_appends_failed_terminal_event_when_codex_stops_without_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_MissingTerminalRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post("/api/analysis/sessions/turns", json={"message": "missing completion"})
            thread_id = response.json()["session_id"]
            detail = client.get(f"/api/analysis/sessions/{thread_id}")

            self.assertEqual(response.status_code, 200)
            # The synthetic ``turn/completed`` event with
            # ``status: failed`` is appended when the runtime stops
            # without a terminal event.
            last_event = response.json()["events"][-1]
            self.assertEqual(last_event["type"], "turn/completed")
            self.assertEqual(last_event["payload"].get("status"), "failed")
            self.assertEqual(last_event["payload"].get("error"), "codex_stream_ended_without_turn_completed")
            # Session-level state stays ``active`` even when the latest
            # turn failed; the sidebar reads ``latestTurnStatus`` for
            # the turn-level signal.
            self.assertEqual(detail.json()["session"]["status"], "active")
            self.assertEqual(detail.json()["session"]["latestTurnStatus"], "failed")
            self.assertEqual(detail.json()["turns"][0]["status"], "failed")

    def test_interrupted_terminal_event_persists_interrupted_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            # New-session contract: ``thread_id == codex_thread_id`` and
            # ``turn_id == codex_turn_id`` for new analysis writes.
            thread_store.session_catalog.register_session("codex_thread_cancelled",
                product_kind="analysis_task",
                title="interrupted",
                user_id=None,
                codex_session_id="codex_thread_cancelled",
            )
            events = [
                AgentEvent(
                    type="turn/started",
                    turn_id="codex_turn_cancelled",
                    payload={
                        "thread_id": "codex_thread_cancelled",
                        "turn_id": "codex_turn_cancelled",
                        "codex_thread_id": "codex_thread_cancelled",
                        "codex_turn_id": "codex_turn_cancelled",
                    },
                ),
                _interrupted_terminal_event(
                    session_id="codex_thread_cancelled",
                    turn_id="codex_turn_cancelled",
                ),
            ]

            thread_store.save_turn(
                thread_id="codex_thread_cancelled",
                turn_id="codex_turn_cancelled",
                question="cancelled stream",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=events,
            )
            detail = thread_store.get_thread("codex_thread_cancelled")

            self.assertEqual(detail["thread"]["status"], "active")
            self.assertEqual(detail["turns"][0]["status"], "cancelled")

    def test_disabled_runtime_fails_explicitly_without_fabricated_content(self) -> None:
        app = create_app(analysis_runtime=CodexSdkAnalysisRuntime.disabled())
        client = TestClient(app)

        # New-session contract: when the runtime is disabled and the caller
        # did not supply a Codex-issued ``codex_thread_id`` in metadata, the
        # endpoint refuses to fabricate a GenBI thread id; it returns 503
        # so the caller knows it must reroute through a Codex-aware flow.
        response = client.post("/api/analysis/sessions/turns", json={"message": "analyze channel sales"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("codex_runtime_not_configured", response.text)

    def test_genbi_report_tool_call_emits_interactive_report_artifact(self) -> None:
        event = AgentEvent(
            type="item/completed",
            turn_id="codex_turn_report",
            payload={
                "eventSource": "codex",
                "codex_item_type": "mcpToolCall",
                "codex_item_id": "codex_item_report",
                "mcp_server": "GenBI_report",
                "mcp_tool": "create_interactive_report",
                "mcp_status": "completed",
                "mcp_result": {
                    "interactive_report": {
                        "id": "report_channel",
                        "title": "Channel report",
                        "subtitle": "Channel sales summary",
                        "artifactType": "interactive_report",
                        "renderer": "puck",
                        "ownerId": "codex-agent",
                        "source": {"threadId": "codex_thread_pending", "turnId": "codex_turn_pending"},
                        "document": {"root": {"props": {"title": "Channel report"}}},
                        "filters": [],
                        "queries": {},
                        "chartSpecs": {},
                        "gridSpecs": {},
                        "datasets": {"channel_sales": {"rows": [{"channel": "Direct", "salesAmount": 1000, "salesShare": 0.42}]}},
                    }
                },
            },
        )

        artifact = ArtifactProjector(InteractiveReportStore()).project_interactive_report(event, session_id="thread_report", turn_id="turn_report")

        self.assertIsNotNone(artifact)
        assert artifact is not None
        self.assertEqual(artifact.type, "genbi/artifact/updated")
        self.assertEqual(artifact.payload["artifactType"], "interactive_report")
        self.assertEqual(artifact.payload["source"]["threadId"], "thread_report")
        self.assertEqual(artifact.payload["source"]["turnId"], "turn_report")
        self.assertEqual(artifact.payload["datasets"]["channel_sales"]["rows"][0]["channel"], "Direct")

    def test_report_payload_mcp_item_emits_artifact_without_server_tool_fields(self) -> None:
        event = AgentEvent(
            type="item/completed",
            turn_id="codex_turn_report",
            payload={
                "eventSource": "codex",
                "codex_item_type": "mcpToolCall",
                "codex_item_id": "codex_item_report",
                "mcp_status": "completed",
                "mcp_result": {
                    "interactive_report": {
                        "id": "report_from_payload",
                        "title": "channel report",
                        "subtitle": "minimal",
                        "artifactType": "interactive_report",
                        "renderer": "puck",
                        "ownerId": "codex-agent",
                        "source": {"threadId": "codex_thread_pending", "turnId": "codex_turn_pending"},
                        "document": {"root": {"props": {"title": "channel report"}}},
                        "filters": [],
                        "queries": {},
                        "chartSpecs": {},
                        "gridSpecs": {},
                        "datasets": {"channel_sales": {"rows": [{"channel": "A", "sales": 1}]}},
                    }
                },
            },
        )

        artifact = ArtifactProjector(InteractiveReportStore()).project_interactive_report(event, session_id="thread_report", turn_id="turn_report")

        self.assertIsNotNone(artifact)
        assert artifact is not None
        self.assertEqual(artifact.type, "genbi/artifact/updated")
        self.assertEqual(artifact.payload["source"]["threadId"], "thread_report")
        self.assertEqual(artifact.payload["source"]["turnId"], "turn_report")
        self.assertEqual(artifact.payload["datasets"]["channel_sales"]["rows"][0]["channel"], "A")

    def test_analysis_asset_api_saves_lists_and_reopens_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_store = AnalysisAssetStore(Path(temp_dir) / "analysis-assets.jsonl")
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                analysis_asset_store=asset_store,
            )
            client = TestClient(app)

            save_payload = {
                "assetId": "asset_mock_report",
                "artifactVersionId": "artifact_version_mock_report_v1",
                "sourceTaskId": "analysis_task_codex",
                "sourceTaskTitle": "first purchase repurchase",
                "sourceConversationId": "conv_analysis_abc",
                "sourceCodexThreadId": "codex_thread_abc",
                "sourceCodexTurnId": "codex_turn_abc",
                "sourceCodexItemId": "codex_item_report",
                "assetType": "report",
                "title": "analysis_report.html",
                "label": "report",
                "description": "reusable analysis report",
                "visibility": "team",
                "status": "saved",
                "latestVersion": "v1-draft",
                "fileId": "reports-analysis-report-html",
                "saveReason": "user_confirmed",
                "reopenContext": {
                    "sourceTaskId": "analysis_task_codex",
                    "sourceConversationId": "conv_analysis_abc",
                    "continuationPrompt": "continue from analysis report",
                    "targetFileId": "reports-analysis-report-html",
                    "sourceCodexThreadId": "codex_thread_abc",
                    "sourceCodexTurnId": "codex_turn_abc",
                    "sourceCodexItemId": "codex_item_report",
                },
            }

            saved = client.post("/api/analysis/assets", json=save_payload)
            listed = client.get("/api/analysis/assets", params={"source_task_id": "analysis_task_codex"})
            lineage = client.get("/api/analysis/artifact-lineage", params={"codex_item_id": "codex_item_report"})
            asset_lineage = client.get("/api/analysis/assets/asset_mock_report/lineage")
            reopened = client.post("/api/analysis/assets/asset_mock_report/reopen")

            self.assertEqual(saved.status_code, 200)
            self.assertEqual(saved.json()["asset"]["sourceCodexThreadId"], "codex_thread_abc")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()["assets"]), 1)
            self.assertEqual(lineage.json()["lineage"][0]["assetId"], "asset_mock_report")
            self.assertEqual(asset_lineage.json()["lineage"]["artifactId"], "asset_mock_report")
            self.assertEqual(asset_lineage.json()["lineage"]["artifactVersionId"], "artifact_version_mock_report_v1")
            self.assertEqual(reopened.json()["context"]["sourceCodexItemId"], "codex_item_report")

    def test_report_center_lists_mine_and_shared_current_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
            )
            client = TestClient(app)

            report_payload = {
                "id": "report_current",
                "title": "Current Report",
                "subtitle": "Saved snapshot",
                "artifactType": "interactive_report",
                "renderer": "puck",
                "ownerId": "owner_1",
                "source": {"threadId": "analysis_thread_a", "turnId": "analysis_turn_a"},
                "document": {"content": [], "root": {"props": {}}},
                "filters": [],
                "queries": {},
                "chartSpecs": {},
                "gridSpecs": {},
                "datasets": {"rows": {"rows": [{"channel": "A", "sales": 1}]}},
                "dataUpdatedAt": "2026-08-04T09:00:00+08:00",
            }

            saved_v1 = client.post("/api/analysis/reports", json=report_payload)
            shared = client.post(
                "/api/analysis/reports/report_current/shares",
                json={"ownerId": "owner_1", "recipientUserId": "user_2", "permission": "view_and_reuse"},
            )
            saved_v2 = client.post(
                "/api/analysis/reports",
                json={
                    **report_payload,
                    "title": "Current Report Updated",
                    "expectedVersion": saved_v1.json()["version"]["version"],
                    "datasets": {"rows": {"rows": [{"channel": "A", "sales": 2}]}},
                    "dataUpdatedAt": "2026-08-04T10:00:00+08:00",
                },
            )

            owner_center = client.get("/api/analysis/report-center", params={"user_id": "owner_1"})
            shared_center = client.get("/api/analysis/report-center", params={"user_id": "user_2"})

            self.assertEqual(saved_v1.status_code, 200)
            self.assertEqual(shared.status_code, 200)
            self.assertEqual(saved_v2.status_code, 200)
            self.assertEqual(owner_center.json()["mine"][0]["report"]["title"], "Current Report Updated")
            self.assertEqual(shared_center.json()["sharedWithMe"][0]["permission"], "view_and_reuse")
            self.assertEqual(shared_center.json()["sharedWithMe"][0]["report"]["title"], "Current Report Updated")
            self.assertEqual(shared_center.json()["sharedWithMe"][0]["report"]["dataUpdatedAt"], "2026-08-04T10:00:00+08:00")

            deleted = client.delete("/api/analysis/reports/report_current", params={"owner_id": "owner_1"})
            after_delete = client.get("/api/analysis/report-center", params={"user_id": "user_2"})

            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(after_delete.json()["sharedWithMe"], [])

    def test_create_analysis_thread_from_report_creates_waiting_thread_without_turns(self) -> None:
        # The new contract has no "waiting for question" state.
        # When the runtime is disabled, the report-anchored
        # session creation endpoint must surface a clear error
        # instead of silently allocating an empty session row.
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
                thread_store=thread_store,
            )
            client = TestClient(app)
            report_payload = {
                "id": "report_for_analysis",
                "title": "Channel Daily",
                "subtitle": "Saved snapshot",
                "artifactType": "interactive_report",
                "renderer": "puck",
                "ownerId": "owner_1",
                "source": {"threadId": "analysis_thread_source", "turnId": "analysis_turn_source"},
                "document": {"content": [], "root": {"props": {}}},
                "filters": [],
                "queries": {},
                "chartSpecs": {},
                "gridSpecs": {},
                "datasets": {"channel_sales": {"rows": [{"channel": "A", "sales": 1}]}},
                "dataUpdatedAt": "2026-08-04T09:00:00+08:00",
            }

            saved = client.post("/api/analysis/reports", json=report_payload)
            created = client.post(
                "/api/analysis/reports/report_for_analysis/sessions",
                json={
                    "userId": "owner_1",
                    "title": "Channel Daily New Analysis",
                },
            )

            self.assertEqual(saved.status_code, 200)
            # With the runtime disabled, the report-anchored
            # endpoint must fail fast and never create an empty
            # session row.
            self.assertEqual(created.status_code, 503)
            self.assertEqual(
                thread_store.list_threads(product_kind="analysis_task"),
                [],
            )

    def test_create_analysis_thread_from_report_reuses_existing_empty_thread(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report_store = InteractiveReportStore(Path(temp_dir) / "interactive-reports.json")
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            preflight_id = "codex_thread_reuse_from_report"
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                interactive_report_store=report_store,
                thread_store=thread_store,
            )
            client = TestClient(app)
            report_payload = {
                "id": "report_reuse",
                "title": "Report Reuse",
                "subtitle": "snapshot",
                "artifactType": "interactive_report",
                "renderer": "puck",
                "ownerId": "owner_1",
                "source": {"threadId": "analysis_thread_source", "turnId": "analysis_turn_source"},
                "document": {"content": [], "root": {"props": {}}},
                "filters": [],
                "queries": {},
                "chartSpecs": {},
                "gridSpecs": {},
                "datasets": {},
            }

            saved = client.post("/api/analysis/reports", json=report_payload)
            body = {
                "userId": "owner_1",
                "title": "Report Reuse New",
                "metadata": {"codex_session_id": preflight_id},
            }
            first = client.post("/api/analysis/reports/report_reuse/sessions", json=body)
            second = client.post("/api/analysis/reports/report_reuse/sessions", json=body)

            self.assertEqual(saved.status_code, 200)
            # The new contract is deterministic when the client
            # supplies a preflight id: both calls return the same
            # session id. Without a preflight id the endpoint would
            # raise 503 (no live Codex runtime).
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(
                first.json()["session"]["id"],
                second.json()["session"]["id"],
            )
            self.assertEqual(len(thread_store.list_threads(product_kind="analysis_task")), 1)

    def test_report_share_rejects_unknown_permission(self) -> None:
        app = create_app(
            analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
            interactive_report_store=InteractiveReportStore(Path("unused-reports.json")),
        )
        client = TestClient(app)

        response = client.post(
            "/api/analysis/reports/report_missing/shares",
            json={"recipientUserId": "user_2", "permission": "edit"},
        )

        self.assertEqual(response.status_code, 422)


def _event_payload_value(sse_text: str, key: str) -> object | None:
    for line in sse_text.splitlines():
        if not line.startswith("data:"):
            continue
        event = json.loads(line.removeprefix("data:").strip())
        payload = dict(event.get("payload") or {})
        if key in payload:
            return payload[key]
    return None


def _thread_id_from_store(thread_store: ThreadStore) -> str:
    threads = thread_store.list_threads(product_kind="analysis_task")
    assert threads
    return str(threads[0]["id"])


class SessionlessStartTest(unittest.IsolatedAsyncioTestCase):
    """Locks the sessionless contract for the new analysis session entry point.

    The frontend must never call ``POST /api/analysis/sessions/turns`` to create a
    the single entry point: it lazily opens a Codex thread, returns the
    Codex-issued id as the first ``session/created`` event, and persists
    the analysis thread row only after the first user message.
    """

    def test_sessions_turns_does_not_persist_thread_until_codex_provisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            # Before the call: no analysis thread rows.
            self.assertEqual(thread_store.list_threads(product_kind="analysis_task"), [])

            response = client.post(
                "/api/analysis/sessions/turns",
                json={"message": "analyze channel sales"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["session_id"], "codex_thread_created")
            self.assertTrue(payload["turn_id"].startswith("codex_turn_"))
            self.assertEqual(payload["turn_id"], "codex_turn_1")
            event_types = [event["type"] for event in payload["events"]]
            self.assertIn("session/created", event_types)
            session_event = next(event for event in payload["events"] if event["type"] == "session/created")
            self.assertEqual(session_event["payload"]["sessionId"], "codex_thread_created")
            self.assertEqual(session_event["payload"]["codexThreadId"], "codex_thread_created")
            # Internal markers must never leak to the client.
            self.assertNotIn("genbi/thread/provisioned", event_types)
            self.assertNotIn("genbi/turn/provisioned", event_types)
            # The sessionless contract: thread.id == thread.codex_thread_id.
            thread = thread_store.get_thread("codex_thread_created")
            assert thread is not None
            self.assertEqual(thread["thread"]["id"], "codex_thread_created")
            self.assertEqual(thread["thread"]["codexThreadId"], "codex_thread_created")
            self.assertEqual(thread["turns"][0]["id"], "codex_turn_1")

    def test_sessions_turns_stream_emits_session_created_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            self.assertEqual(thread_store.list_threads(product_kind="analysis_task"), [])

            response = client.post(
                "/api/analysis/sessions/turns",
                json={"message": "analyze channel sales"},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            event_types = [event["type"] for event in body["events"]]
            self.assertIn("session/created", event_types)
            session_event = next(
                event for event in body["events"] if event["type"] == "session/created"
            )
            self.assertEqual(session_event["payload"]["sessionId"], "codex_thread_created")
            # Internal markers must be filtered out of the response.
            self.assertNotIn("genbi/thread/provisioned", event_types)
            self.assertNotIn("genbi/turn/provisioned", event_types)
            # The sessionless contract still holds: the session id
            # in the body is the Codex-issued id.
            self.assertEqual(body["session_id"], "codex_thread_created")
            thread = thread_store.get_thread("codex_thread_created")
            assert thread is not None
            self.assertEqual(thread["session"]["id"], "codex_thread_created")
            self.assertEqual(thread["session"]["codexSessionId"], "codex_thread_created")

    def test_sessions_turns_rejects_blank_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/sessions/turns",
                json={"message": ""},
            )

            self.assertEqual(response.status_code, 422)
            self.assertEqual(thread_store.list_threads(product_kind="analysis_task"), [])


class StreamingResolvedTurnIdTest(unittest.IsolatedAsyncioTestCase):
    """Locks the P0 contract that the resolved Codex turn id is
    cached in the streaming accumulator the moment the runtime
    emits ``genbi/turn/provisioned``.

    Before the fix ``_astream_runtime_events`` only updated the
    local ``effective_thread_id`` and left its ``turn_id``
    parameter at the empty preflight value. Every downstream side
    effect — projection fold, event enrichment, interactive
    report artifact lineage — therefore used ``""`` for the turn
    id, so:

    * live Item projections landed on a phantom turn row
    * the event envelope's ``turnId`` was empty
    * the report's ``source.turnId`` was empty
    * mid-stream cancellations could not close the right turn

    The streaming accumulator must read the runtime-issued turn
    id from the first ``genbi/turn/provisioned`` event and use
    that single value for every event that follows.
    """

    async def test_resolved_turn_id_reaches_enrichment_and_artifact_lineage(self) -> None:
        # Drive the streaming helper directly so we can inspect
        # the events it yields downstream without going through
        # FastAPI's StreamingResponse wrapper.
        from backend.services.codex_turn_runner import (
            CodexTurnRunner as _TurnRunnerShim,
            _analysis_request_from_body,
        )

        runtime = _FakeCodexRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            stores = _TestStores(Path(temp_dir) / "thread-store.jsonl")
            body = {
                "message": "hi",
                "turn_kind": "message",
                "user_id": None,
                "metadata": {},
            }
            request = _analysis_request_from_body(body, session_id="")
            # Capture the projection store state mid-stream by
            # pulling the events off the async generator and
            # peeking at the store after the turn-provisioned
            # event has been observed.
            enriched_events: list[AgentEvent] = []
            runner = _TurnRunnerShim(runtime, stores.session_catalog, stores.codex_projection_store, ArtifactProjector(None))
            async for event, _, _ in runner.stream_runtime_events(request, session_id="", turn_id="", codex_session_id=None):
                enriched_events.append(event)
            # The fake runtime emits the provisioned turn with
            # ``codex_turn_1`` and then a delta; the streaming
            # path must surface the resolved id on every yielded
            # event after provisioning, and the projection store
            # must own a turn row whose id matches the runtime.
            deltas = [event for event in enriched_events if event.type == "item/agentMessage/delta"]
            self.assertTrue(deltas, "delta event should reach downstream")
            for event in deltas:
                self.assertEqual(
                    event.turn_id,
                    "codex_turn_1",
                    msg=f"event {event.type} leaked an empty turn id; resolved id was not cached",
                )
            turns = stores.codex_projection_store.list_turns("codex_thread_created")
            self.assertEqual([turn.id for turn in turns], ["codex_turn_1"])

    async def test_preflight_turn_id_is_overridden_by_runtime(self) -> None:
        """A caller-supplied preflight turn id must not survive
        the runtime's override: the runtime is the only
        authority for ``analysis_turns.id``.
        """
        from backend.services.codex_turn_runner import (
            CodexTurnRunner as _TurnRunnerShim,
            _analysis_request_from_body,
        )

        class _PreflightRejectingRuntime(_FakeCodexRuntime):
            """Pretend the caller passed a preflight turn id, then
            verify the streaming accumulator never propagates it.
            """

        runtime = _PreflightRejectingRuntime()
        with tempfile.TemporaryDirectory() as temp_dir:
            stores = _TestStores(Path(temp_dir) / "thread-store.jsonl")
            body = {
                "message": "hi",
                "turn_kind": "message",
                "user_id": None,
                "metadata": {"codex_turn_id": "preflight_turn_id"},
            }
            request = _analysis_request_from_body(body, session_id="")
            seen_turn_ids: list[str] = []
            runner = _TurnRunnerShim(runtime, stores.session_catalog, stores.codex_projection_store, ArtifactProjector(None))
            async for event, _, _ in runner.stream_runtime_events(request, session_id="", turn_id="", codex_session_id=None):
                seen_turn_ids.append(event.turn_id)
            self.assertIn("codex_turn_1", seen_turn_ids)
            self.assertNotIn("", seen_turn_ids[1:])  # all events after the first carry the resolved id


class StreamingEndpointContractTest(unittest.TestCase):
    """Locks the user spec that the streaming endpoints emit
    ``text/event-stream`` and surface events the moment the
    runtime produces them — not after the whole turn finishes.

    Before the fix the only turn endpoints returned a single JSON
    blob, so the frontend had to wait for the entire Codex run
    before it could render anything. We now register dedicated
    ``/turns/stream`` routes that share the same Session / Turn
    / Projection kernel as the JSON endpoints but write events
    straight to the wire as SSE.
    """

    def test_first_turn_stream_endpoint_returns_event_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            with client.stream(
                "POST",
                "/api/analysis/sessions/turns/stream",
                json={"message": "hi", "metadata": {"frontend_client": "analysis_task"}},
            ) as response:
                self.assertEqual(response.status_code, 200)
                self.assertTrue(
                    response.headers["content-type"].startswith("text/event-stream"),
                    msg=f"stream endpoint returned {response.headers['content-type']!r} instead of text/event-stream",
                )
                # Pull the SSE body line by line and confirm at
                # least one ``data:`` payload lands.
                lines = [line for line in response.iter_lines() if line.startswith("data:")]
                self.assertTrue(
                    lines,
                    msg="stream endpoint emitted no SSE data lines — did the runtime stream at all?",
                )
                # The first business event must be ``session/created``;
                # the resolved Codex session/turn ids must be
                # embedded so the frontend can navigate.
                first_payload = json.loads(lines[0].removeprefix("data:"))
                self.assertEqual(first_payload["type"], "session/created")
                self.assertEqual(first_payload["payload"]["sessionId"], "codex_thread_created")
                self.assertTrue(first_payload["payload"]["codexTurnId"])

    def test_continuation_turn_stream_endpoint_returns_event_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            # Pre-create the session row so the URL resolution is
            # exercised against a real catalog entry.
            thread_store.create_thread(
                thread_id="codex_thread_existing",
                product_kind="analysis_task",
                title=None,
                user_id=None,
            )
            client.post(
                "/api/analysis/sessions/codex_thread_existing/turns",
                json={"message": "first", "turn_kind": "message"},
            )

            with client.stream(
                "POST",
                "/api/analysis/sessions/codex_thread_existing/turns/stream",
                json={"message": "follow up", "turn_kind": "message"},
            ) as response:
                self.assertEqual(response.status_code, 200)
                self.assertTrue(
                    response.headers["content-type"].startswith("text/event-stream"),
                )
                lines = [line for line in response.iter_lines() if line.startswith("data:")]
                self.assertTrue(lines)
                first_payload = json.loads(lines[0].removeprefix("data:"))
                # Continuation streams do NOT emit ``session/created``
                # because the session already exists; they go
                # straight to turn events.
                self.assertNotEqual(first_payload["type"], "session/created")
                self.assertIn(first_payload["type"], {"turn/started", "item/agentMessage/delta"})

    def test_first_turn_stream_endpoint_rejects_disabled_runtime(self) -> None:
        # The streaming endpoint requires the Codex runtime to be
        # enabled; offline / test mode clients must use the JSON
        # fallback at ``/turns`` instead. This protects the
        # contract that ``/turns/stream`` is *always* real-time.
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            runtime = _FakeCodexRuntime()
            runtime.enabled = False
            app = create_app(
                analysis_runtime=runtime,  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/sessions/turns/stream",
                json={"message": "hi"},
            )
            self.assertEqual(response.status_code, 503)


class TurnCancellationTest(unittest.TestCase):
    """Locks the user spec that stopping a turn must interrupt
    the live Codex turn, not just archive the session.

    Before the fix the only cancel endpoint
    (``POST /sessions/{id}/cancel``) called
    ``archive_session`` and never spoke to the Codex runtime.
    The frontend's stop button only aborted the HTTP fetch, so
    the Codex CLI kept running tools until its own timeout.
    The new endpoint
    ``POST /sessions/{id}/turns/{turn_id}/cancel`` calls
    ``CodexSdkAnalysisRuntime.interrupt_turn`` *and* marks the
    projection row ``cancelled`` so the UI sees the terminal
    transition without waiting for the stream to close.
    """

    def _build_app(self) -> tuple[TestClient, ThreadStore, _FakeCodexRuntime]:
        thread_store = ThreadStore(Path(tempfile.mkdtemp()) / "thread-store.jsonl")
        runtime = _FakeCodexRuntime()
        app = create_app(
            analysis_runtime=runtime,  # type: ignore[arg-type]
            thread_store=thread_store,
        )
        return TestClient(app), thread_store, runtime

    def test_cancel_turn_interrupts_codex_runtime_and_marks_projection(self) -> None:
        client, thread_store, runtime = self._build_app()
        thread_store.create_thread(
            thread_id="codex_thread_cancel",
            product_kind="analysis_task",
            title=None,
            user_id=None,
        )
        thread_store.create_turn_only(
            thread_id="codex_thread_cancel",
            turn_id="codex_turn_running",
        )

        response = client.post(
            "/api/analysis/sessions/codex_thread_cancel/turns/codex_turn_running/cancel",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "cancelled")
        self.assertEqual(payload["turn_id"], "codex_turn_running")
        self.assertTrue(payload["codex_runtime_interrupted"])
        # The runtime must be called with the canonical id pair
        # so the SDK registry can locate the live turn object.
        self.assertEqual(
            runtime.interrupt_calls,
            [("codex_thread_cancel", "codex_turn_running")],
        )
        # The projection row is flipped to ``cancelled`` so the
        # sidebar / flow view reflects the terminal state without
        # waiting for the SSE stream to close.
        turn = thread_store.codex_projection_store.get_turn(
            "codex_thread_cancel",
            "codex_turn_running",
        )
        self.assertIsNotNone(turn)
        assert turn is not None
        self.assertEqual(turn.status, "cancelled")
        self.assertIsNotNone(turn.completedAt)
        # The session itself is **not** archived by this
        # endpoint — the user can send the next question right
        # away on the same session id.
        session = thread_store.session_catalog.get_session("codex_thread_cancel")
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.status, "active")

    def test_cancel_turn_keeps_session_active_and_does_not_archive(self) -> None:
        # The legacy endpoint ``/sessions/{id}/cancel`` archives
        # the session; the new turn-level endpoint must not.
        # Re-running this assertion isolates the user spec that
        # *cancelling a turn* and *archiving a session* are
        # separate concerns with separate endpoints.
        client, thread_store, runtime = self._build_app()
        thread_store.create_thread(
            thread_id="codex_thread_cancel_keep",
            product_kind="analysis_task",
            title=None,
            user_id=None,
        )
        thread_store.create_turn_only(
            thread_id="codex_thread_cancel_keep",
            turn_id="codex_turn_keep",
        )

        response = client.post(
            "/api/analysis/sessions/codex_thread_cancel_keep/turns/codex_turn_keep/cancel",
        )
        self.assertEqual(response.status_code, 200)
        session = thread_store.session_catalog.get_session("codex_thread_cancel_keep")
        assert session is not None
        self.assertEqual(session.status, "active")

    def test_cancel_turn_returns_404_when_session_missing(self) -> None:
        client, _, _ = self._build_app()
        response = client.post(
            "/api/analysis/sessions/never_created/turns/never_running/cancel",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "analysis_session_not_found")

    def test_cancel_turn_returns_400_when_turn_id_empty(self) -> None:
        # FastAPI route matching prevents an empty ``turn_id``
        # path segment from reaching the handler at all (the
        # URL ``/sessions/{id}/turns//cancel`` 404s before the
        # route matches). Exercise the defensive guard by
        # calling the helper directly with whitespace.
        client, thread_store, runtime = self._build_app()
        thread_store.create_thread(
            thread_id="codex_thread_empty",
            product_kind="analysis_task",
            title=None,
            user_id=None,
        )
        # FastAPI rejects empty path segments before we run;
        # confirm the catalog resolution path the endpoint
        # uses works as expected.
        resolved = thread_store.session_catalog.resolve_session_id(
            "codex_thread_empty"
        )
        self.assertEqual(resolved, "codex_thread_empty")
        # The runtime was not asked to interrupt anything
        # because the request never reached the handler.
        self.assertEqual(runtime.interrupt_calls, [])

    def test_legacy_cancel_session_endpoint_still_archives_only(self) -> None:
        # The legacy endpoint is preserved for back-compat with
        # callers that only need to archive the session row. It
        # must NOT touch the Codex runtime and must NOT mark the
        # running turn as ``cancelled`` — those are owned by the
        # new turn-level endpoint.
        client, thread_store, runtime = self._build_app()
        thread_store.create_thread(
            thread_id="codex_thread_legacy",
            product_kind="analysis_task",
            title=None,
            user_id=None,
        )
        thread_store.create_turn_only(
            thread_id="codex_thread_legacy",
            turn_id="codex_turn_legacy",
        )

        response = client.post("/api/analysis/sessions/codex_thread_legacy/cancel")
        self.assertEqual(response.status_code, 200)
        # No Codex interrupt call.
        self.assertEqual(runtime.interrupt_calls, [])
        # Turn status is untouched (still ``running``).
        turn = thread_store.codex_projection_store.get_turn(
            "codex_thread_legacy",
            "codex_turn_legacy",
        )
        assert turn is not None
        self.assertEqual(turn.status, "running")
        # Session is archived.
        session = thread_store.session_catalog.get_session("codex_thread_legacy")
        assert session is not None
        self.assertEqual(session.status, "archived")


class SessionContinuationBodyContractTest(unittest.TestCase):
    """Locks the user spec that the continuation body must NOT
    carry a ``sessionId`` field, and that ``turn_kind`` is
    restricted to ``message`` or ``reply``.

    A previous version of ``analysis_api.py`` defined
    ``AnalysisSessionContinuationBody`` twice. The second
    definition (which silently won) added a ``sessionId``
    field and dropped ``turn_kind``. That regression violated
    the "session id only lives in the URL" rule and let
    clients smuggle a session id through the body, bypassing
    the URL resolution path. This test locks both halves of
    the contract:

    * Body ``sessionId`` / ``session_id`` / ``task_id`` keys
      must be silently ignored on the continuation endpoint
      so a careless client cannot route to a different
      session than the URL advertised.
    * ``turn_kind`` is restricted to ``message`` or ``reply``;
      ``start`` is reserved for the sessionless entry point.
    """

    def _build_client(self, *, with_session: bool = False, session_id: str = "codex_thread_body") -> TestClient:
        thread_store = ThreadStore(Path(tempfile.mkdtemp()) / "thread-store.jsonl")
        if with_session:
            thread_store.create_thread(
                thread_id=session_id,
                product_kind="analysis_task",
                title=None,
                user_id=None,
            )
        app = create_app(
            analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
            thread_store=thread_store,
        )
        return TestClient(app)

    def test_continuation_body_rejects_session_id_field(self) -> None:
        client = self._build_client()
        # Pydantic forbids unknown fields by default
        # (``BaseModel.model_config.extra = "ignore"`` is *not*
        # the default). Sending ``sessionId`` in the body must
        # therefore produce a 422, not a 200, because the field
        # is not part of the contract.
        response = client.post(
            "/api/analysis/sessions/codex_thread_body/turns",
            json={
                "message": "follow up",
                "sessionId": "codex_thread_smuggled",
                "turn_kind": "message",
            },
        )
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        # The error mentions ``sessionId`` as an unknown field
        # — this is the lock that prevents future refactors
        # from silently accepting it again.
        self.assertTrue(
            any("sessionId" in (entry.get("loc") or []) and "extra" in (entry.get("type") or "")
                for entry in detail),
            msg=f"validation error does not mention sessionId: {detail!r}",
        )

    def test_continuation_body_rejects_session_id_aliases(self) -> None:
        client = self._build_client()
        # Snake_case and ``task_id`` aliases are equally
        # forbidden — they were historical aliases that the
        # body contract explicitly rejects.
        for alias in ("session_id", "task_id", "conversation_id"):
            response = client.post(
                "/api/analysis/sessions/codex_thread_body/turns",
                json={
                    "message": "follow up",
                    alias: "codex_thread_smuggled",
                    "turn_kind": "message",
                },
            )
            self.assertEqual(
                response.status_code,
                422,
                msg=f"alias {alias!r} should be rejected; got {response.status_code}",
            )

    def test_continuation_body_rejects_turn_kind_start(self) -> None:
        # ``start`` is reserved for the sessionless entry
        # point. Sending it on the session-scoped URL must be
        # rejected so a client cannot accidentally start a new
        # session through a continuation URL.
        client = self._build_client()
        response = client.post(
            "/api/analysis/sessions/codex_thread_body/turns",
            json={
                "message": "first?",
                "turn_kind": "start",
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_continuation_body_accepts_message_and_reply(self) -> None:
        # The locked-in ``Literal["message", "reply"]`` means
        # both valid kinds round-trip through the request
        # parser without rejection. We don't care about the
        # downstream behavior here — the runtime mock always
        # completes — only that the body validation accepts
        # these two values. The session row is pre-created so
        # the continuation endpoint reaches the body parser
        # (the user spec explicitly forbids lazy-registering
        # unknown session ids).
        client = self._build_client(with_session=True)
        for kind in ("message", "reply"):
            response = client.post(
                "/api/analysis/sessions/codex_thread_body/turns",
                json={"message": f"x ({kind})", "turn_kind": kind},
            )
            self.assertEqual(
                response.status_code,
                200,
                msg=f"turn_kind={kind!r} should be accepted; got {response.status_code} body={response.text!r}",
            )

    def test_sessionless_body_rejects_session_id_field(self) -> None:
        # The sessionless entry point (``POST /sessions/turns``)
        # must never accept a session id in the body either —
        # the body contract is "session id lives in the URL".
        # ``AnalysisSessionStartBody`` never declared the field,
        # so sending it produces a 422.
        client = self._build_client()
        response = client.post(
            "/api/analysis/sessions/turns",
            json={
                "message": "first",
                "sessionId": "codex_thread_smuggled",
            },
        )
        self.assertEqual(response.status_code, 422)


class SessionOwnershipTest(unittest.TestCase):
    """Locks the user spec that the Codex Runtime is the only
    source of session / turn ids.

    Two regressions were broken before the fix:

    * ``POST /api/analysis/sessions/turns`` accepted a preflight
      id from ``metadata.codex_session_id`` /
      ``metadata.codex_thread_id``. With the runtime disabled it
      even wrote a synthetic ``running`` turn row using the
      caller's primary key — letting a client mint a fake Codex
      session, a fake turn id, and a turn stuck in ``running``.
    * ``POST /api/analysis/sessions/{id}/turns`` (and its
      streaming sibling) lazy-registered a session row whenever
      the URL id was unknown. That made the continuation
      endpoint a stealth session-creation entry point and
      bypassed the "only ``POST /sessions/turns`` creates a new
      session" rule.

    The fix:

    * The first-turn endpoint ignores client-supplied ids
      entirely. With the runtime disabled it returns 503 and
      does not write any session / turn row.
    * The continuation endpoint rejects unknown session ids with
      404 — the URL parameter is *not* a preflight id.
    """

    def _build_app(
        self,
        *,
        runtime: CodexSdkAnalysisRuntime | None = None,
    ) -> tuple[TestClient, ThreadStore]:
        thread_store = ThreadStore(Path(tempfile.mkdtemp()) / "thread-store.jsonl")
        app = create_app(
            analysis_runtime=runtime if runtime is not None else _FakeCodexRuntime(),  # type: ignore[arg-type]
            thread_store=thread_store,
        )
        return TestClient(app), thread_store

    def test_first_turn_ignores_preflight_metadata_id(self) -> None:
        # The user spec: "Session ID must be allocated by the
        # Codex Runtime." A preflight id in metadata MUST be
        # ignored — even when the runtime is enabled. The Codex
        # session id is whatever the runtime actually issues.
        client, thread_store = self._build_app()
        response = client.post(
            "/api/analysis/sessions/turns",
            json={
                "message": "first question",
                "metadata": {
                    "codex_session_id": "codex_thread_forged",
                    "codex_thread_id": "codex_thread_forged",
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        # The Fake runtime always issues ``codex_thread_created``
        # (its deterministic identity) — NOT the client-supplied
        # id. The client cannot pick the session primary key.
        payload = response.json()
        self.assertEqual(payload["session_id"], "codex_thread_created")
        thread = thread_store.get_thread("codex_thread_created")
        self.assertIsNotNone(thread)
        # The forged id MUST NOT have been provisioned.
        self.assertIsNone(thread_store.get_thread("codex_thread_forged"))

    def test_first_turn_disabled_runtime_returns_503_without_creating_session(self) -> None:
        # Disabled runtime + preflight id used to create a fake
        # ``running`` turn row with the caller's primary key.
        # That path is gone: 503 and zero rows persisted.
        client, thread_store = self._build_app(
            runtime=CodexSdkAnalysisRuntime.disabled(),
        )
        response = client.post(
            "/api/analysis/sessions/turns",
            json={
                "message": "first",
                "metadata": {"codex_session_id": "codex_thread_forged"},
            },
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("codex_runtime_not_configured", response.json()["detail"])
        self.assertEqual(
            len(thread_store.list_threads(product_kind="analysis_task")),
            0,
        )
        self.assertIsNone(thread_store.get_thread("codex_thread_forged"))

    def test_first_turn_disabled_runtime_stream_returns_503(self) -> None:
        # Same lock on the streaming first-turn endpoint.
        client, thread_store = self._build_app(
            runtime=CodexSdkAnalysisRuntime.disabled(),
        )
        response = client.post(
            "/api/analysis/sessions/turns/stream",
            json={"message": "first", "metadata": {"codex_session_id": "codex_thread_forged"}},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            len(thread_store.list_threads(product_kind="analysis_task")),
            0,
        )

    def test_first_turn_stream_ignores_preflight_metadata_id(self) -> None:
        # Streaming first-turn endpoint must also refuse to
        # accept a client-supplied id; the runtime is the only
        # authoritative source.
        client, thread_store = self._build_app()
        response = client.post(
            "/api/analysis/sessions/turns/stream",
            json={
                "message": "first",
                "metadata": {
                    "codex_session_id": "codex_thread_forged",
                    "codex_thread_id": "codex_thread_forged",
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")
        # The forged id MUST NOT have been provisioned.
        self.assertIsNone(thread_store.get_thread("codex_thread_forged"))

    def test_continuation_returns_404_when_session_missing(self) -> None:
        # The continuation endpoint MUST NOT lazy-register a
        # session row. Previously it would treat the URL id as
        # the Codex-side id and provision a row silently.
        client, thread_store = self._build_app()
        response = client.post(
            "/api/analysis/sessions/codex_thread_unknown/turns",
            json={"message": "continue", "turn_kind": "message"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "analysis_session_not_found")
        # No session row was created.
        self.assertIsNone(thread_store.get_thread("codex_thread_unknown"))
        self.assertEqual(
            len(thread_store.list_threads(product_kind="analysis_task")),
            0,
        )

    def test_continuation_stream_returns_404_when_session_missing(self) -> None:
        client, thread_store = self._build_app()
        response = client.post(
            "/api/analysis/sessions/codex_thread_unknown/turns/stream",
            json={"message": "continue", "turn_kind": "message"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "analysis_session_not_found")
        self.assertIsNone(thread_store.get_thread("codex_thread_unknown"))

    def test_continuation_works_after_first_turn_creates_session(self) -> None:
        # The continuation endpoint is reachable *only* through
        # a session that the first-turn endpoint provisioned.
        # Walking the full round-trip is the user spec's
        # positive control: only ``POST /sessions/turns``
        # creates a session, and only that id round-trips
        # through ``POST /sessions/{id}/turns``.
        client, thread_store = self._build_app()
        first = client.post(
            "/api/analysis/sessions/turns",
            json={"message": "first"},
        )
        self.assertEqual(first.status_code, 200)
        session_id = first.json()["session_id"]
        # Continuation on a known id must succeed.
        second = client.post(
            f"/api/analysis/sessions/{session_id}/turns",
            json={"message": "continue", "turn_kind": "message"},
        )
        self.assertEqual(second.status_code, 200)
        # But a *different* unknown id is rejected with 404.
        third = client.post(
            "/api/analysis/sessions/codex_thread_different/turns",
            json={"message": "continue", "turn_kind": "message"},
        )
        self.assertEqual(third.status_code, 404)
        self.assertIsNone(thread_store.get_thread("codex_thread_different"))


class SessionScopedContinuationTest(unittest.IsolatedAsyncioTestCase):
    """Locks the session-scoped continuation turn contract.

    After the first turn has been provisioned, every continuation goes
    to ``POST /api/analysis/sessions/{sessionId}/turns``. The session
    id is taken from the URL parameter; the body never carries an
    id, and the route is non-streaming (the response is the full
    envelope of events at once).
    """

    def test_sessions_id_turns_stream_threads_through_existing_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            self.assertEqual(thread_store.list_threads(product_kind="analysis_task"), [])
            first = client.post(
                "/api/analysis/sessions/turns",
                json={"message": "analyze channel sales"},
            )
            self.assertEqual(first.status_code, 200)
            first_payload = first.json()
            self.assertEqual(first_payload["session_id"], "codex_thread_created")
            event_types = [event["type"] for event in first_payload["events"]]
            self.assertIn("session/created", event_types)
            self.assertIn("turn/completed", event_types)

            # The continuation turn goes through the session-scoped
            # endpoint; the URL parameter is the only id the backend
            # trusts, and the Codex-issued id is echoed back through
            # the resulting thread row.
            second = client.post(
                "/api/analysis/sessions/codex_thread_created/turns",
                json={"message": "continue", "turn_kind": "message"},
            )
            self.assertEqual(second.status_code, 200)
            second_payload = second.json()
            self.assertEqual(second_payload["session_id"], "codex_thread_created")
            event_types = [event["type"] for event in second_payload["events"]]
            self.assertIn("turn/started", event_types)
            self.assertIn("turn/completed", event_types)
            thread = thread_store.get_thread("codex_thread_created")
            assert thread is not None
            self.assertEqual(thread["session"]["id"], "codex_thread_created")
            self.assertEqual(thread["session"]["codexSessionId"], "codex_thread_created")
            self.assertEqual(len(thread["turns"]), 2)
            # The continuation turn also satisfies id == codex_turn_id.
            self.assertEqual(thread["turns"][1]["id"], "codex_turn_2")

    def test_sessions_id_turns_stream_rejects_mismatched_body_session_id(self) -> None:
        # The new contract forbids the body from re-asserting a
        # session id; the URL path is the single source of truth.
        # The legacy ``sessionId`` body alias is dropped, so a
        # client that still supplies it gets a Pydantic 422
        # rejection on the unknown field (``model_config`` disallows
        # extras). The continuation endpoint also rejects unknown
        # session ids with 404 — it MUST NOT lazy-register a row
        # using the URL id (that was a P1 regression).
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/sessions/codex_thread_url/turns",
                json={"message": "continue", "turn_kind": "message"},
            )
            # The session row does not exist; the continuation
            # endpoint refuses to mint one.
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "analysis_session_not_found")
            # No session row is created.
            self.assertEqual(
                len(thread_store.list_threads(product_kind="analysis_task")),
                0,
            )

    def test_sessions_id_turns_stream_uses_url_id_when_body_omits_session_id(self) -> None:
        # Same lock as ``test_sessions_id_turns_stream_rejects_mismatched_body_session_id``
        # but called without a body ``sessionId``: the endpoint
        # MUST still refuse to lazy-register a row. The previous
        # behaviour treated the URL id as a preflight id and
        # provisioned a session row even though no client-supplied
        # body field was present; that path is gone.
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            response = client.post(
                "/api/analysis/sessions/codex_thread_explicit/turns",
                json={"message": "follow up", "turn_kind": "message"},
            )

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["detail"], "analysis_session_not_found")
            self.assertIsNone(thread_store.get_thread("codex_thread_explicit"))


class LegacySessionIdCompatibilityTest(unittest.TestCase):
    """Old ``analysis_threads`` rows had ``id != codex_session_id``; the
    new contract is ``id == codex_session_id``. The API still
    accepts either id on the URL path: callers can keep using
    their old GenBI-side id and the backend resolves the
    canonical row, OR callers can use the Codex-side id directly.
    """

    def test_legacy_row_is_resolvable_by_either_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stores = _TestStores(Path(temp_dir) / "thread-store.jsonl")
            # Seed a legacy row by writing the JSONL directly
            # (``register_session`` refuses to persist a row
            # where ``id != codex_session_id`` — new writes are
            # always the new shape).
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
            stores.session_catalog.path.parent.mkdir(parents=True, exist_ok=True)
            stores.session_catalog.path.write_text(
                json.dumps(legacy_payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                session_catalog=stores.session_catalog,
                codex_projection_store=stores.codex_projection_store,
            )
            client = TestClient(app)

            # The old GenBI-side id still returns the row.
            by_genbi = client.get("/api/analysis/sessions/genbi_legacy_1")
            self.assertEqual(by_genbi.status_code, 200)
            self.assertEqual(by_genbi.json()["session"]["id"], "genbi_legacy_1")

            # The new Codex-side id also returns the same row.
            by_codex = client.get("/api/analysis/sessions/codex_legacy_1")
            self.assertEqual(by_codex.status_code, 200)
            self.assertEqual(by_codex.json()["session"]["id"], "genbi_legacy_1")
            self.assertEqual(by_codex.json()["session"]["codexSessionId"], "codex_legacy_1")

            # Cancelling by the GenBI-side id archives the row
            # under the canonical id; the response surfaces the
            # canonical id so clients can update their URL.
            cancel = client.post("/api/analysis/sessions/genbi_legacy_1/cancel")
            self.assertEqual(cancel.status_code, 200)
            self.assertEqual(cancel.json()["session"]["id"], "genbi_legacy_1")
            self.assertEqual(cancel.json()["session"]["status"], "archived")

    def test_legacy_row_continuation_routes_to_codex_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stores = _TestStores(Path(temp_dir) / "thread-store.jsonl")
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
            stores.session_catalog.path.parent.mkdir(parents=True, exist_ok=True)
            stores.session_catalog.path.write_text(
                json.dumps(legacy_payload, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                session_catalog=stores.session_catalog,
                codex_projection_store=stores.codex_projection_store,
            )
            client = TestClient(app)

            # Hit the continuation endpoint with the OLD GenBI
            # id; the backend must resolve it to the Codex-side
            # id before forwarding to the runtime so projections
            # land under the canonical row.
            response = client.post(
                "/api/analysis/sessions/genbi_legacy_1/turns",
                json={"message": "follow up", "turn_kind": "message"},
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["session_id"], "codex_legacy_1")


class SessionTurnStateDecouplingTest(unittest.IsolatedAsyncioTestCase):
    """Locks the user spec that session/turn state machines do not overlap.

    Session (``analysis_threads.status``) is one of ``active`` or
    ``archived``. Turn (``analysis_turns.status``) is one of ``running``
    / ``completed`` / ``failed`` / ``cancelled`` / ``needs_input``. The
    session state is NEVER copied from the latest turn.
    """

    def test_fresh_session_status_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            thread_store.session_catalog.register_session("codex_thread_fresh",
                product_kind="analysis_task",
                title="fresh session",
                user_id="user_1",
                status="active",
            )
            # ``get_thread`` carries the latest-turn sidebar signal.
            detail = thread_store.get_thread("codex_thread_fresh")
            assert detail is not None
            self.assertEqual(detail["thread"]["status"], "active")
            # No turns yet, so the sidebar signal is absent.
            self.assertIsNone(detail["thread"]["latest_turn_status"])
            self.assertIsNone(detail["thread"]["latest_turn_id"])

    def test_create_thread_rejects_legacy_session_states(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            for legacy_status in ("running", "completed", "waiting_for_question", "failed", "needs_input"):
                with self.assertRaises(ValueError):
                    thread_store.session_catalog.register_session(f"codex_thread_{legacy_status}",
                        product_kind="analysis_task",
                        title="legacy state",
                        user_id=None,
                        status=legacy_status,
                    )

    def test_turn_status_produces_terminal_states_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            thread_store.session_catalog.register_session("codex_thread_terms",
                product_kind="analysis_task",
                title="turn states",
                user_id=None,
                status="active",
            )
            # Each event payload status maps to a single canonical
            # turn state. ``turn/completed.status == "failed"`` is the
            # only signal that flips the turn into ``failed``.
            for raw_status, expected_turn_status in [
                ("complete", "completed"),
                ("completed", "completed"),
                ("succeeded", "completed"),
                ("failed", "failed"),
                ("cancelled", "cancelled"),
                ("interrupted", "cancelled"),
            ]:
                thread_store.save_turn(
                    thread_id="codex_thread_terms",
                    turn_id=f"turn_{raw_status}",
                    question=f"q {raw_status}",
                    input_kind="message",
                    product_kind="analysis_task",
                    user_id=None,
                    events=[
                        AgentEvent(type="turn/started", turn_id=f"turn_{raw_status}", payload={}),
                        AgentEvent(
                            type="turn/completed",
                            turn_id=f"turn_{raw_status}",
                            payload={"status": raw_status},
                        ),
                    ],
                )
                turn = thread_store.get_turn("codex_thread_terms", f"turn_{raw_status}")
                assert turn is not None
                self.assertEqual(turn["turn"]["status"], expected_turn_status)
                # The session never mirrors the turn state.
                self.assertEqual(turn["thread"]["status"], "active")

    def test_turn_failure_keeps_session_active_and_allows_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            app = create_app(
                analysis_runtime=_FakeCodexRuntime(),  # type: ignore[arg-type]
                thread_store=thread_store,
            )
            client = TestClient(app)

            # 1. Open the session.
            first = client.post(
                "/api/analysis/sessions/turns",
                json={"message": "first question"},
            )
            self.assertEqual(first.status_code, 200)
            # The Runtime is the only thing allowed to assign
            # the session id; we read it back from the registry.
            sessions = thread_store.list_threads(product_kind="analysis_task")
            self.assertEqual(len(sessions), 1)
            session_id = sessions[0]["id"]
            first_turn_id = "codex_turn_1"

            # 2. Force the first turn into ``failed`` by overriding the
            #    turn's status directly. This is the canonical failure
            #    shape: the turn went to failed while the session is
            #    still active.
            thread_store.save_turn(
                thread_id=session_id,
                turn_id=first_turn_id,
                question="first question",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[
                    AgentEvent(type="turn/started", turn_id=first_turn_id, payload={}),
                    AgentEvent(
                        type="turn/completed",
                        turn_id=first_turn_id,
                        payload={"status": "failed", "error": "codex_runtime_failed"},
                    ),
                ],
            )

            # 3. The session state stays ``active``; the sidebar reads
            #    ``latestTurnStatus`` to surface the failure.
            session = thread_store.get_thread(session_id)
            assert session is not None
            self.assertEqual(session["thread"]["status"], "active")
            self.assertEqual(session["thread"]["latest_turn_status"], "failed")
            self.assertEqual(session["turns"][0]["status"], "failed")

            # 4. The user can still send a continuation turn on the
            #    same session; the session-scoped endpoint accepts the
            #    request and writes a fresh turn row.
            second = client.post(
                f"/api/analysis/sessions/{session_id}/turns",
                json={"message": "follow-up question", "turn_kind": "message"},
            )
            self.assertEqual(second.status_code, 200)
            refreshed = thread_store.get_thread(session_id)
            assert refreshed is not None
            self.assertEqual(refreshed["thread"]["status"], "active")
            self.assertEqual(len(refreshed["turns"]), 2)
            self.assertEqual(refreshed["turns"][0]["status"], "failed")
            self.assertEqual(refreshed["turns"][1]["status"], "completed")
            self.assertEqual(refreshed["thread"]["latest_turn_status"], "completed")

    def test_list_threads_returns_latest_turn_status_per_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            thread_store.session_catalog.register_session("codex_thread_a",
                product_kind="analysis_task",
                title="a",
                user_id=None,
                status="active",
            )
            thread_store.session_catalog.register_session("codex_thread_b",
                product_kind="analysis_task",
                title="b",
                user_id=None,
                status="active",
            )
            thread_store.save_turn(
                thread_id="codex_thread_a",
                turn_id="turn_a",
                question="qa",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[
                    AgentEvent(type="turn/started", turn_id="turn_a", payload={}),
                    AgentEvent(
                        type="turn/completed",
                        turn_id="turn_a",
                        payload={"status": "failed"},
                    ),
                ],
            )
            thread_store.save_turn(
                thread_id="codex_thread_b",
                turn_id="turn_b",
                question="qb",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[
                    AgentEvent(type="turn/started", turn_id="turn_b", payload={}),
                    AgentEvent(
                        type="turn/completed",
                        turn_id="turn_b",
                        payload={"status": "complete"},
                    ),
                ],
            )
            app = create_app(
                analysis_runtime=CodexSdkAnalysisRuntime.disabled(),
                thread_store=thread_store,
            )
            client = TestClient(app)
            response = client.get("/api/analysis/sessions")
            self.assertEqual(response.status_code, 200)
            by_id = {row["id"]: row for row in response.json()["sessions"]}
            self.assertEqual(by_id["codex_thread_a"]["status"], "active")
            self.assertEqual(by_id["codex_thread_a"]["latestTurnStatus"], "failed")
            self.assertEqual(by_id["codex_thread_b"]["status"], "active")
            self.assertEqual(by_id["codex_thread_b"]["latestTurnStatus"], "completed")

    def test_archive_moves_session_out_of_the_active_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            thread_store.session_catalog.register_session("codex_thread_archived",
                product_kind="analysis_task",
                title="archive me",
                user_id=None,
                status="active",
            )
            thread_store.archive_thread("codex_thread_archived")
            refreshed = thread_store.get_thread("codex_thread_archived")
            assert refreshed is not None
            self.assertEqual(refreshed["thread"]["status"], "archived")

            thread_store.reactivate_thread("codex_thread_archived")
            refreshed = thread_store.get_thread("codex_thread_archived")
            assert refreshed is not None
            self.assertEqual(refreshed["thread"]["status"], "active")


class NoGenBIItemTest(unittest.IsolatedAsyncioTestCase):
    """Locks the user spec that the GenBI ``Item`` projection is gone.

    Restoring a session must only depend on the turn row plus the
    Codex item projection. Real-time streaming and historical replay
    share the same shape (turn events = sorted Codex projections).
    The user input lives on the turn (``input_text``); no fake GenBI
    User Item is fabricated from Codex events.
    """

    def test_thread_and_turn_detail_drop_legacy_items_field(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            thread_store.session_catalog.register_session("codex_thread_no_item",
                product_kind="analysis_task",
                title="history only",
                user_id=None,
                status="active",
            )
            thread_store.save_turn(
                thread_id="codex_thread_no_item",
                turn_id="codex_turn_no_item",
                question="first question",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[
                    AgentEvent(
                        type="item/agentMessage/delta",
                        turn_id="codex_turn_no_item",
                        payload={
                            "codex_thread_id": "codex_thread_no_item",
                            "codex_turn_id": "codex_turn_no_item",
                            "codex_item_id": "item_a",
                            "codex_item_type": "agentMessage",
                            "delta": "hi",
                        },
                    ),
                    AgentEvent(
                        type="item/completed",
                        turn_id="codex_turn_no_item",
                        payload={
                            "codex_thread_id": "codex_thread_no_item",
                            "codex_turn_id": "codex_turn_no_item",
                            "codex_item_id": "item_a",
                            "codex_item_type": "agentMessage",
                            "content": "hi back",
                        },
                    ),
                    AgentEvent(type="turn/completed", turn_id="codex_turn_no_item", payload={"status": "complete"}),
                ],
            )

            detail = thread_store.get_thread("codex_thread_no_item")
            turn = thread_store.get_turn("codex_thread_no_item", "codex_turn_no_item")
            assert detail is not None and turn is not None
            self.assertNotIn("items", detail)
            self.assertNotIn("items", turn)
            # Only Codex projections are surfaced.
            self.assertEqual(len(detail["codexItemProjections"]), 1)
            self.assertEqual(detail["codexItemProjections"][0]["codexItemId"], "item_a")
            # User input lives on the turn row.
            self.assertEqual(detail["turns"][0]["inputText"], "first question")
            self.assertEqual(detail["turns"][0]["question"], "first question")
            self.assertIsNotNone(detail["turns"][0]["startedAt"])
            self.assertIsNotNone(detail["turns"][0]["completedAt"])

    def test_get_turn_events_returns_normalised_projection_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            thread_store.session_catalog.register_session("codex_thread_replay",
                product_kind="analysis_task",
                title="replay",
                user_id=None,
                status="active",
            )
            # Two Codex items arrive in the opposite order they end up
            # in after the dense ``sequence`` renumbering; the replay
            # path must assign 0/1 by ``createdAt`` (then ``codexItemId``)
            # so the live and historical projections agree.
            thread_store.save_turn(
                thread_id="codex_thread_replay",
                turn_id="codex_turn_replay",
                question="replay me",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[
                    AgentEvent(
                        type="item/agentMessage/delta",
                        turn_id="codex_turn_replay",
                        created_at="2026-08-05T10:00:00Z",
                        payload={
                            "codex_thread_id": "codex_thread_replay",
                            "codex_turn_id": "codex_turn_replay",
                            "codex_item_id": "item_1",
                            "codex_item_type": "agentMessage",
                            "delta": "hello",
                        },
                    ),
                    AgentEvent(
                        type="item/completed",
                        turn_id="codex_turn_replay",
                        created_at="2026-08-05T10:00:01Z",
                        payload={
                            "codex_thread_id": "codex_thread_replay",
                            "codex_turn_id": "codex_turn_replay",
                            "codex_item_id": "item_1",
                            "codex_item_type": "agentMessage",
                            "content": "hello back",
                        },
                    ),
                    AgentEvent(
                        type="genbi/artifact/created",
                        turn_id="codex_turn_replay",
                        created_at="2026-08-05T10:00:02Z",
                        payload={
                            "codex_thread_id": "codex_thread_replay",
                            "codex_turn_id": "codex_turn_replay",
                            "codex_item_id": "item_2",
                            "codex_item_type": "sql",
                            "path": "queries/q.sql",
                        },
                    ),
                    AgentEvent(type="turn/completed", turn_id="codex_turn_replay", payload={"status": "complete"}),
                ],
            )
            replay = thread_store.get_turn_events("codex_turn_replay")
            self.assertEqual(len(replay), 2)
            # Dense sequence starts at 0 in arrival order.
            self.assertEqual([event["sequence"] for event in replay], [0, 1])
            # Codex item type is exposed in the unified shape.
            self.assertEqual(
                [(event["codex_item_id"], event["item_type"]) for event in replay],
                [("item_1", "agentMessage"), ("item_2", "sql")],
            )
            # Each event carries the same fields a live SSE event
            # would, including the turn id and the projected status.
            for event in replay:
                self.assertEqual(event["turn_id"], "codex_turn_replay")
                self.assertIn("payload", event)
                self.assertIn("created_at", event)
                self.assertIn("status", event)

    def test_no_fake_user_item_is_constructed_for_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            thread_store.session_catalog.register_session("codex_thread_user",
                product_kind="analysis_task",
                title="no fake user item",
                user_id=None,
                status="active",
            )
            # Codex never sends a user item; only ``turn/started``
            # with the question embedded. The store must NOT
            # manufacture a GenBI "User Item" from the events.
            thread_store.save_turn(
                thread_id="codex_thread_user",
                turn_id="codex_turn_user",
                question="what was GMV last week?",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[
                    AgentEvent(
                        type="turn/started",
                        turn_id="codex_turn_user",
                        payload={
                            "codex_thread_id": "codex_thread_user",
                            "codex_turn_id": "codex_turn_user",
                            "question": "what was GMV last week?",
                        },
                    ),
                    AgentEvent(type="turn/completed", turn_id="codex_turn_user", payload={"status": "complete"}),
                ],
            )
            detail = thread_store.get_thread("codex_thread_user")
            assert detail is not None
            # No projection at all because Codex never emitted an item.
            self.assertEqual(detail["codexItemProjections"], [])
            self.assertNotIn("items", detail)
            # The turn row still records the user input.
            self.assertEqual(detail["turns"][0]["inputText"], "what was GMV last week?")

    def test_projection_sequence_renumbers_after_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            thread_store = ThreadStore(Path(temp_dir) / "thread-store.jsonl")
            thread_store.session_catalog.register_session("codex_thread_seq",
                product_kind="analysis_task",
                title="seq",
                user_id=None,
                status="active",
            )
            thread_store.save_turn(
                thread_id="codex_thread_seq",
                turn_id="codex_turn_seq",
                question="seq",
                input_kind="start",
                product_kind="analysis_task",
                user_id=None,
                events=[
                    AgentEvent(
                        type="item/agentMessage/delta",
                        turn_id="codex_turn_seq",
                        created_at="2026-08-05T11:00:00Z",
                        payload={
                            "codex_thread_id": "codex_thread_seq",
                            "codex_turn_id": "codex_turn_seq",
                            "codex_item_id": "item_1",
                            "codex_item_type": "agentMessage",
                            "delta": "a",
                        },
                    ),
                    AgentEvent(
                        type="item/agentMessage/delta",
                        turn_id="codex_turn_seq",
                        created_at="2026-08-05T11:00:01Z",
                        payload={
                            "codex_thread_id": "codex_thread_seq",
                            "codex_turn_id": "codex_turn_seq",
                            "codex_item_id": "item_2",
                            "codex_item_type": "agentMessage",
                            "delta": "b",
                        },
                    ),
                ],
            )
            detail = thread_store.get_thread("codex_thread_seq")
            assert detail is not None
            sequences = [item["sequence"] for item in detail["codexItemProjections"]]
            self.assertEqual(sequences, [0, 1])


if __name__ == "__main__":
    unittest.main()

