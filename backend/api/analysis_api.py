import json
import asyncio
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

LOGGER = logging.getLogger(__name__)

from backend.config import check_runtime_env, load_project_env
from backend.analysis.report_artifact import normalize_report_artifact, validate_report_artifact
from backend.analysis.report_compiler import compile_interactive_report
from backend.analysis.asset_store import AnalysisAssetReopenContext, AnalysisAssetStore
from backend.analysis.interactive_report_store import InteractiveReportStore, InteractiveReportVersionConflict, asdict_report
from backend.business_semantics.finereport_reports import FineReportReportRepository
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.codex_mcp_config import codex_mcp_server_status_payload, test_codex_mcp_server
from backend.harness.events import AgentEvent
from backend.harness.minimax_codex_adapter import proxy_minimax_response
from backend.harness.session_catalog import SessionCatalog, SessionRecord, SessionView
from backend.harness.codex_projection_store import (
    CodexItemProjectionRecord,
    CodexProjectionStore,
    TurnRecord,
)
from backend.harness.analysis_runtime import InMemoryCodexAnalysisRuntime, TurnStream, turn_status_from_events
from backend.persistence.postgres_stores import (
    build_postgres_analysis_asset_store,
    build_postgres_stores,
    build_postgres_session_catalog,
    build_postgres_codex_projection_store,
    postgres_persistence_enabled,
)
from backend.business_semantics.knowledge_store import KnowledgeStore


@dataclass(frozen=True)
class AnalysisTurnRequest:
    question: str
    thread_id: str | None = None
    user_id: str | None = None
    turn_kind: str = "start"
    metadata: dict[str, Any] = field(default_factory=dict)


def create_app(
    knowledge_store: KnowledgeStore | None = None,
    analysis_runtime: CodexSdkAnalysisRuntime | None = None,
    analysis_asset_store: AnalysisAssetStore | None = None,
    interactive_report_store: Any | None = None,
    session_catalog: SessionCatalog | None = None,
    codex_projection_store: CodexProjectionStore | None = None,
    # Legacy shim: older tests (and external callers) still pass a
    # single ``thread_store`` keyword. If we see one, we split it
    # into the new pair; this is the only place the legacy alias
    # is recognised.
    thread_store: Any | None = None,
    finereport_repository: FineReportReportRepository | None = None,
) -> Any:
    if thread_store is not None and (session_catalog is None or codex_projection_store is None):
        session_catalog = session_catalog or getattr(thread_store, "session_catalog", None)
        codex_projection_store = codex_projection_store or getattr(thread_store, "codex_projection_store", None)
    load_project_env()
    try:
        from fastapi import Body, FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import Response, StreamingResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Install FastAPI dependencies from backend/requirements.txt to start the API.") from exc

    class AnalysisTurnBody(BaseModel):
        question: str = Field(min_length=1)
        thread_id: str | None = None
        conversation_id: str | None = None
        user_id: str | None = None
        turn_kind: str = "start"
        metadata: dict[str, Any] = Field(default_factory=dict)

    class AnalysisThreadBody(BaseModel):
        title: str | None = None
        user_id: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)

    class AnalysisAssetReopenContextBody(BaseModel):
        sourceTaskId: str = Field(min_length=1)
        sourceConversationId: str = Field(min_length=1)
        continuationPrompt: str = Field(min_length=1)
        targetFileId: str | None = None
        sourceCodexThreadId: str | None = None
        sourceCodexTurnId: str | None = None
        sourceCodexItemId: str | None = None

    class AnalysisAssetBody(BaseModel):
        assetId: str = Field(min_length=1)
        artifactVersionId: str = Field(min_length=1)
        sourceTaskId: str = Field(min_length=1)
        sourceTaskTitle: str = Field(min_length=1)
        sourceConversationId: str = Field(min_length=1)
        sourceCodexThreadId: str | None = None
        sourceCodexTurnId: str | None = None
        sourceCodexItemId: str | None = None
        assetType: str = Field(min_length=1)
        title: str = Field(min_length=1)
        label: str | None = None
        description: str | None = None
        visibility: str = "team"
        status: str = "saved"
        latestVersion: str = "v1-draft"
        fileId: str | None = None
        saveReason: str | None = None
        reopenContext: AnalysisAssetReopenContextBody
        metadata: dict[str, Any] = Field(default_factory=dict)

    class InteractiveReportSourceBody(BaseModel):
        threadId: str = Field(min_length=1)
        turnId: str = Field(min_length=1)

    class InteractiveReportBody(BaseModel):
        id: str = Field(min_length=1)
        title: str = Field(min_length=1)
        subtitle: str = Field(min_length=1)
        artifactType: str = "interactive_report"
        renderer: str = "puck"
        document: dict[str, Any]
        filters: list[dict[str, Any]] = Field(default_factory=list)
        queries: dict[str, Any] = Field(default_factory=dict)
        chartSpecs: dict[str, Any] = Field(default_factory=dict)
        gridSpecs: dict[str, Any] = Field(default_factory=dict)
        datasets: dict[str, Any] = Field(default_factory=dict)
        source: InteractiveReportSourceBody
        ownerId: str = Field(min_length=1)
        expectedVersion: int | None = Field(default=None, ge=0)
        dataUpdatedAt: str | None = None
        derivedFromReportId: str | None = None

    class InteractiveReportRenameBody(BaseModel):
        ownerId: str = Field(min_length=1)
        title: str = Field(min_length=1)

    class ReportShareBody(BaseModel):
        ownerId: str = Field(default="local-user", min_length=1)
        recipientUserId: str = Field(min_length=1)
        permission: Literal["view", "view_and_reuse"]

    class ReportAnalysisThreadBody(BaseModel):
        userId: str | None = None
        title: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)

    class AnalysisSessionStartBody(BaseModel):
        """Request body for ``POST /api/analysis/sessions/turns``.

        The frontend must POST exactly this shape (instead of calling
        ``POST /api/analysis/threads`` first). The endpoint lazily opens
        a Codex thread and returns the Codex-issued id as part of the
        first ``session/created`` event.
        """
        message: str = Field(min_length=1)
        user_id: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)

    class AnalysisSessionContinuationBody(BaseModel):
        """Request body for ``POST /api/analysis/sessions/{sessionId}/turns/stream``.

        The ``sessionId`` is normally taken from the URL path, but the
        body is allowed to carry it for clients that prefer a single
        source of truth. If the body field disagrees with the URL the
        endpoint returns ``400 session_id_mismatch``.
        """
        message: str = Field(min_length=1)
        sessionId: str | None = None
        turn_kind: str = "message"
        user_id: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)

    class KnowledgeBody(BaseModel):
        title: str = Field(min_length=1)
        question: str = Field(min_length=1)
        conclusion: str = Field(min_length=1)
        scope: str = Field(min_length=1)
        verification: str = Field(min_length=1)
        evidence_refs: list[str] = Field(min_length=1)
        turn_id: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)
        type: str | None = None
        business_definition: str | None = None
        technical_definition: str | None = None
        formula: str | None = None
        excluded_scope: str | None = None
        owner: str | None = None
        visibility: str | None = None
        status: str | None = None
        approvals: list[dict[str, Any]] = Field(default_factory=list)
        tags: list[str] = Field(default_factory=list)
        related_tables: list[str] = Field(default_factory=list)
        related_fields: list[str] = Field(default_factory=list)
        related_resources: list[str] = Field(default_factory=list)
        expires_at: str | None = None
        conflicts: list[str] = Field(default_factory=list)
        agent_visible: bool | None = None
        version: str | None = None

    class KnowledgeUpdateBody(BaseModel):
        title: str | None = None
        question: str | None = None
        conclusion: str | None = None
        scope: str | None = None
        verification: str | None = None
        evidence_refs: list[str] | None = None
        turn_id: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)
        type: str | None = None
        business_definition: str | None = None
        technical_definition: str | None = None
        formula: str | None = None
        excluded_scope: str | None = None
        owner: str | None = None
        visibility: str | None = None
        status: str | None = None
        approvals: list[dict[str, Any]] | None = None
        tags: list[str] | None = None
        related_tables: list[str] | None = None
        related_fields: list[str] | None = None
        related_resources: list[str] | None = None
        expires_at: str | None = None
        conflicts: list[str] | None = None
        agent_visible: bool | None = None
        version: str | None = None

    cors_origins = [
        origin.strip()
        for origin in os.getenv(
            "GENBI_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3010,http://127.0.0.1:3010",
        ).split(",")
        if origin.strip()
    ]
    for env_name in ("FRONTEND_BASE_URL", "NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_GENBI_API_BASE_URL"):
        origin = os.getenv(env_name, "").strip()
        if origin and origin not in cors_origins:
            cors_origins.append(origin)

    app = FastAPI(title="Agentic GenBI Backend")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    configured_knowledge_store = knowledge_store or _build_default_knowledge_store()
    configured_analysis_runtime = analysis_runtime or build_default_analysis_runtime()
    configured_analysis_asset_store = analysis_asset_store or _build_default_analysis_asset_store()
    configured_interactive_report_store = interactive_report_store or _build_default_interactive_report_store()
    configured_session_catalog = session_catalog or _build_default_session_catalog()
    configured_codex_projection_store = codex_projection_store or _build_default_codex_projection_store()
    # The catalog asks the projection store for the latest turn
    # signal so the sidebar reads ``latest_turn_status`` without
    # the session row having to mirror a turn's state.
    configured_session_catalog.bind_latest_turn_provider(configured_codex_projection_store)
    configured_codex_projection_store.bind_session_touch(configured_session_catalog)
    configured_finereport_repository = finereport_repository or FineReportReportRepository()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/runtime/status")
    def runtime_status() -> dict[str, Any]:
        return check_runtime_env()

    @app.get("/api/system/mcp/servers")
    def list_mcp_servers() -> dict[str, Any]:
        return codex_mcp_server_status_payload()

    @app.post("/api/system/mcp/servers/{server_name}/test")
    def test_mcp_server(server_name: str) -> dict[str, Any]:
        return test_codex_mcp_server(server_name)

    @app.post("/api/codex-minimax/v1/responses")
    async def codex_minimax_responses(body: dict[str, Any] = Body(...)) -> Any:
        raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        status, headers, payload = proxy_minimax_response(
            raw_body,
            stream=bool(body.get("stream")),
        )
        media_type = headers.get("content-type", "application/json")
        if bool(body.get("stream")) and not isinstance(payload, bytes):
            return StreamingResponse(payload, status_code=status, media_type=media_type)
        return Response(
            content=payload if isinstance(payload, bytes) else b"".join(payload),
            status_code=status,
            media_type=media_type,
        )

    @app.get("/api/business-semantics/finereport/reports")
    def list_finereport_reports() -> dict[str, Any]:
        return {"reports": configured_finereport_repository.list_reports()}

    @app.get("/api/business-semantics/finereport/reports/{report_id}")
    def get_finereport_report(report_id: str) -> dict[str, Any]:
        report = configured_finereport_repository.get_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="finereport_report_not_found")
        return report

    @app.get("/api/analysis/threads")
    def list_analysis_threads(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        sessions = configured_session_catalog.list_sessions(limit=limit, product_kind="analysis_task")
        sessions = [s for s in sessions if not str(s.id).startswith("draft_")]
        return {"threads": [_session_view_to_thread_dict(s, configured_codex_projection_store) for s in sessions]}

    @app.post("/api/analysis/threads")
    async def create_waiting_analysis_thread(body: AnalysisThreadBody = Body(...)) -> dict[str, Any]:
        title = str(body.title or "新分析").strip() or "新分析"
        existing = _find_waiting_analysis_session(
            configured_session_catalog,
            configured_codex_projection_store,
            title=title,
            user_id=body.user_id,
            metadata_match={"source_report_id": None},
        )
        if existing:
            return {"thread": _session_view_to_thread_dict(existing, configured_codex_projection_store)}
        thread_id = await _provision_codex_thread_id(
            analysis_runtime=configured_analysis_runtime,
            body=body,
        )
        session = configured_session_catalog.register_session(
            session_id=thread_id,
            product_kind="analysis_task",
            title=title,
            user_id=body.user_id,
            status="active",
            codex_session_id=thread_id,
            metadata={**body.metadata, "domain": "analysis_task", "thread_id": thread_id, "codex_session_id": thread_id},
        )
        view = configured_session_catalog.get_view(thread_id)
        assert view is not None  # we just registered the row
        return {"thread": _session_view_to_thread_dict(view, configured_codex_projection_store)}

    @app.post("/api/analysis/tasks")
    def create_analysis_task(body: AnalysisThreadBody = Body(...)) -> dict[str, Any]:
        """Compatibility endpoint for task-first frontend bundles.

        The canonical domain object is still an analysis thread. Older
        frontend builds call this endpoint and expect a ``task`` envelope.
        Keep the behavior aligned with ``POST /api/analysis/threads`` so
        restoring or rebuilding either side does not break task creation.
        """

        created = create_waiting_analysis_thread(body)
        return {"task": created["thread"]}

    @app.post("/api/analysis/sessions/turns")
    async def start_session_first_turn(body: AnalysisSessionStartBody = Body(...)) -> dict[str, Any]:
        """The single entry point for starting a new analysis session.

        Cancels the legacy ``waiting_for_question`` flow: this endpoint must
        be the *only* way a frontend can begin a new session. It drives
        Codex ``thread_start`` lazily (no pre-allocated analysis thread row)
        and returns the Codex-issued session id once the runtime emits
        ``genbi/thread/provisioned``. The frontend then routes from
        ``/analysis/new`` to ``/analysis/{sessionId}`` and continues the
        same stream for the first turn.
        """
        metadata = dict(body.metadata or {})
        metadata.setdefault("domain", "analysis_task")
        metadata.setdefault("thread_root", True)
        turn_request = AnalysisTurnRequest(
            question=body.message.strip(),
            thread_id=None,
            user_id=body.user_id,
            turn_kind="start",
            metadata=metadata,
        )
        return await _create_analysis_turn_payload(
            configured_analysis_runtime,
            configured_session_catalog, configured_codex_projection_store,
            configured_interactive_report_store,
            turn_request,
            thread_id="",
            emit_session_created=True,
        )

    @app.post("/api/analysis/sessions/turns/stream")
    async def stream_session_first_turn(body: AnalysisSessionStartBody = Body(...)) -> StreamingResponse:
        """Streaming variant of ``POST /api/analysis/sessions/turns``.

        Emits a ``session/created`` event with the Codex-issued id as the
        first business event so the frontend can immediately navigate to
        ``/analysis/{sessionId}`` while the rest of the turn keeps
        streaming.
        """
        metadata = dict(body.metadata or {})
        metadata.setdefault("domain", "analysis_task")
        metadata.setdefault("thread_root", True)
        turn_request = AnalysisTurnRequest(
            question=body.message.strip(),
            thread_id=None,
            user_id=body.user_id,
            turn_kind="start",
            metadata=metadata,
        )
        return _stream_session_first_turn_response(
            configured_analysis_runtime,
            configured_session_catalog, configured_codex_projection_store,
            configured_interactive_report_store,
            turn_request,
        )

    @app.post("/api/analysis/sessions/{session_id}/turns/stream")
    def stream_existing_session_turn(session_id: str, body: AnalysisSessionContinuationBody = Body(default_factory=AnalysisSessionContinuationBody)) -> StreamingResponse:
        """Continuation turn on an existing session.

        ``session_id`` is the Codex-issued id from the initial
        ``session/created`` event. The route param is the only durable
        id we use here: we do NOT trust a thread id supplied in the
        body, and we do NOT carry any prior state. If the body omits
        ``sessionId`` the URL param is enforced; if the body supplies a
        conflicting id the request is rejected.
        """
        if not session_id.strip():
            raise HTTPException(status_code=400, detail="session_id_required")
        body_session_id = _string_or_none(body.sessionId)
        if body_session_id and body_session_id != session_id:
            raise HTTPException(
                status_code=400,
                detail="session_id_mismatch: body sessionId does not match URL session_id",
            )
        request = AnalysisTurnRequest(
            question=body.message.strip(),
            thread_id=session_id,
            user_id=body.user_id,
            turn_kind=str(body.turn_kind or "message").strip().lower() or "message",  # type: ignore[arg-type]
            metadata={**(body.metadata or {}), "domain": "analysis_task", "thread_id": session_id, "codex_thread_id": session_id},
        )
        return _stream_analysis_turn_response(
            configured_analysis_runtime,
            configured_session_catalog, configured_codex_projection_store,
            configured_interactive_report_store,
            request,
            thread_id=session_id,
        )

    @app.post("/api/analysis/threads/turns")
    async def create_analysis_thread_turn(body: AnalysisTurnBody = Body(...)) -> dict[str, Any]:
        try:
            thread_id = body.thread_id or body.conversation_id or await _provision_codex_thread_id(
                analysis_runtime=configured_analysis_runtime,
                body=body,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return await _create_analysis_turn_payload(configured_analysis_runtime, configured_session_catalog, configured_codex_projection_store, configured_interactive_report_store, body, thread_id=thread_id)

    @app.post("/api/analysis/threads/turns/stream")
    def stream_new_analysis_thread_turn(body: AnalysisTurnBody = Body(...)) -> StreamingResponse:
        # The actual Codex-issued thread id is observed in the first
        # ``genbi/thread/provisioned`` event. Until then we use the caller-
        # supplied thread id (which equals the Codex thread id once Codex is
        # running) or fall back to a Codex-preflight probe.
        initial_thread_id = body.thread_id or body.conversation_id
        return _stream_analysis_turn_response(configured_analysis_runtime, configured_session_catalog, configured_codex_projection_store, configured_interactive_report_store, body, thread_id=initial_thread_id)

    @app.post("/api/analysis/threads/{thread_id}/turns")
    async def create_existing_analysis_thread_turn(thread_id: str, body: AnalysisTurnBody = Body(...)) -> dict[str, Any]:
        return await _create_analysis_turn_payload(configured_analysis_runtime, configured_session_catalog, configured_codex_projection_store, configured_interactive_report_store, body, thread_id=thread_id)

    @app.post("/api/analysis/threads/{thread_id}/turns/stream")
    def stream_existing_analysis_thread_turn(thread_id: str, body: AnalysisTurnBody = Body(...)) -> StreamingResponse:
        return _stream_analysis_turn_response(configured_analysis_runtime, configured_session_catalog, configured_codex_projection_store, configured_interactive_report_store, body, thread_id=thread_id)

    @app.get("/api/analysis/threads/{thread_id}")
    def get_analysis_thread(thread_id: str) -> dict[str, Any]:
        view = configured_session_catalog.get_view(thread_id)
        if view is None:
            raise HTTPException(status_code=404, detail="analysis_thread_not_found")
        return _build_thread_detail(
            view,
            configured_session_catalog,
            configured_codex_projection_store,
        )

    @app.delete("/api/analysis/threads/{thread_id}")
    def delete_analysis_thread(thread_id: str) -> dict[str, Any]:
        deleted = configured_session_catalog.delete_session(thread_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="analysis_thread_not_found")
        return {"deleted": True, "thread_id": thread_id}

    @app.get("/api/analysis/threads/{thread_id}/turns/{turn_id}")
    def get_analysis_thread_turn(thread_id: str, turn_id: str) -> dict[str, Any]:
        turn = configured_codex_projection_store.get_turn(thread_id, turn_id)
        if turn is None:
            raise HTTPException(status_code=404, detail="analysis_turn_not_found")
        projections = configured_codex_projection_store.list_items(
            session_id=thread_id, turn_id=turn_id
        )
        session = configured_session_catalog.get_session(thread_id)
        return {
            "thread": asdict(session) if session is not None else None,
            "turn": asdict(turn),
            "codexItemProjections": [asdict(p) for p in projections],
        }

    @app.get("/api/analysis/assets")
    def list_analysis_assets(
        limit: int = Query(default=50, ge=1, le=200),
        source_task_id: str | None = None,
        q: str = "",
    ) -> dict[str, Any]:
        return {
            "assets": [
                asdict(item)
                for item in configured_analysis_asset_store.list_assets(
                    limit=limit,
                    source_task_id=source_task_id,
                    q=q,
                )
            ]
        }

    @app.post("/api/analysis/assets")
    def save_analysis_asset(body: AnalysisAssetBody = Body(...)) -> dict[str, Any]:
        context = AnalysisAssetReopenContext(
            sourceTaskId=body.reopenContext.sourceTaskId,
            sourceConversationId=body.reopenContext.sourceConversationId,
            continuationPrompt=body.reopenContext.continuationPrompt,
            targetFileId=body.reopenContext.targetFileId,
            sourceCodexThreadId=body.reopenContext.sourceCodexThreadId,
            sourceCodexTurnId=body.reopenContext.sourceCodexTurnId,
            sourceCodexItemId=body.reopenContext.sourceCodexItemId,
        )
        try:
            record = configured_analysis_asset_store.save_asset(
                asset_id=body.assetId,
                artifact_version_id=body.artifactVersionId,
                source_task_id=body.sourceTaskId,
                source_task_title=body.sourceTaskTitle,
                source_conversation_id=body.sourceConversationId,
                source_codex_thread_id=body.sourceCodexThreadId,
                source_codex_turn_id=body.sourceCodexTurnId,
                source_codex_item_id=body.sourceCodexItemId,
                asset_type=body.assetType,
                title=body.title,
                label=body.label or body.assetType,
                description=body.description or body.title,
                visibility=body.visibility,
                status=body.status,
                latest_version=body.latestVersion,
                file_id=body.fileId or body.reopenContext.targetFileId,
                reopen_context=context,
                metadata={**body.metadata, **({"saveReason": body.saveReason} if body.saveReason else {})},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"asset": asdict(record), "savedAt": record.updatedAt}

    @app.get("/api/analysis/assets/{asset_id}")
    def get_analysis_asset(asset_id: str) -> dict[str, Any]:
        record = configured_analysis_asset_store.get_asset(asset_id)
        if not record:
            raise HTTPException(status_code=404, detail="analysis_asset_not_found")
        return {"asset": asdict(record)}

    @app.get("/api/analysis/artifact-lineage")
    def list_artifact_lineage(
        artifact_id: str | None = None,
        codex_thread_id: str | None = None,
        codex_turn_id: str | None = None,
        codex_item_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return {
            "lineage": [
                asdict(record)
                for record in configured_analysis_asset_store.list_artifact_lineage(
                    artifact_id=artifact_id,
                    codex_thread_id=codex_thread_id,
                    codex_turn_id=codex_turn_id,
                    codex_item_id=codex_item_id,
                    limit=limit,
                )
            ]
        }

    @app.get("/api/analysis/assets/{asset_id}/lineage")
    def get_analysis_asset_lineage(asset_id: str) -> dict[str, Any]:
        record = configured_analysis_asset_store.get_asset(asset_id)
        if not record:
            raise HTTPException(status_code=404, detail="analysis_asset_not_found")
        lineage = configured_analysis_asset_store.list_artifact_lineage(artifact_id=record.assetId, limit=1)
        return {"lineage": asdict(lineage[0]) if lineage else None}

    @app.post("/api/analysis/assets/{asset_id}/reopen")
    def reopen_analysis_asset(asset_id: str) -> dict[str, Any]:
        result = configured_analysis_asset_store.reopen_asset(asset_id)
        if not result:
            raise HTTPException(status_code=404, detail="analysis_asset_not_found")
        return result

    @app.get("/api/analysis/reports")
    def list_interactive_reports(
        owner_id: str | None = None,
        source_thread_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        reports = configured_interactive_report_store.list_reports(owner_id=owner_id, limit=limit)
        if source_thread_id:
            reports = [report for report in reports if report.sourceThreadId == source_thread_id]
        return {"reports": [asdict_report(report) for report in reports]}

    @app.get("/api/analysis/report-center")
    def list_report_center(
        user_id: str = Query(min_length=1),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        return configured_interactive_report_store.list_report_center(user_id=user_id, limit=limit)

    @app.post("/api/analysis/reports")
    def save_interactive_report(body: InteractiveReportBody = Body(...)) -> dict[str, Any]:
        try:
            report, version = configured_interactive_report_store.save_report(body.model_dump())
        except InteractiveReportVersionConflict as exc:
            raise HTTPException(status_code=409, detail="interactive_report_version_conflict") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"report": asdict_report(report), "version": asdict(version)}

    @app.get("/api/analysis/reports/{report_id}")
    def get_interactive_report(report_id: str) -> dict[str, Any]:
        result = configured_interactive_report_store.get_report(report_id)
        if not result:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        report, version = result
        return {"report": asdict_report(report), "version": asdict(version)}

    @app.post("/api/analysis/reports/{report_id}/analysis-thread")
    async def create_analysis_thread_from_report(report_id: str, body: ReportAnalysisThreadBody = Body(default_factory=ReportAnalysisThreadBody)) -> dict[str, Any]:
        result = configured_interactive_report_store.get_report(report_id)
        if not result:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        report, version = result
        title = (body.title or f"{report.title} 新分析").strip()
        existing = _find_waiting_analysis_session(
            configured_session_catalog,
            configured_codex_projection_store,
            title=title,
            user_id=body.userId,
            metadata_match={"source_report_id": report.id},
        )
        report_payload = _interactive_report_payload(report, version)
        if existing:
            return {
                "thread": _session_view_to_thread_dict(existing, configured_codex_projection_store),
                "report": {
                    "report": asdict_report(report),
                    "version": asdict(version),
                },
            }
        thread_id = await _provision_codex_thread_id(
            analysis_runtime=configured_analysis_runtime,
            body=body,
        )
        configured_session_catalog.register_session(
            session_id=thread_id,
            product_kind="analysis_task",
            title=title,
            user_id=body.userId,
            status="active",
            codex_session_id=thread_id,
            metadata={
                "domain": "analysis_task",
                "thread_id": thread_id,
                "codex_session_id": thread_id,
                "source_report_id": report.id,
                "initial_report_id": report.id,
                "initial_report_version": version.version,
                "initial_report_artifact": report_payload,
            },
        )
        view = configured_session_catalog.get_view(thread_id)
        assert view is not None  # we just registered the row
        return {
            "thread": _session_view_to_thread_dict(view, configured_codex_projection_store),
            "report": {
                "report": asdict_report(report),
                "version": asdict(version),
            },
        }

    @app.patch("/api/analysis/reports/{report_id}")
    def rename_interactive_report(report_id: str, body: InteractiveReportRenameBody = Body(...)) -> dict[str, Any]:
        report = configured_interactive_report_store.rename_report(report_id, owner_id=body.ownerId, title=body.title)
        if not report:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        return {"report": asdict_report(report)}

    @app.delete("/api/analysis/reports/{report_id}")
    def delete_interactive_report(report_id: str, owner_id: str = Query(min_length=1)) -> dict[str, Any]:
        deleted = configured_interactive_report_store.delete_report(report_id, owner_id=owner_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        return {"deleted": True, "report_id": report_id}

    @app.post("/api/analysis/reports/{report_id}/shares")
    def share_interactive_report(report_id: str, body: ReportShareBody = Body(...)) -> dict[str, Any]:
        share = configured_interactive_report_store.share_report(
            report_id,
            owner_id=body.ownerId,
            recipient_user_id=body.recipientUserId,
            permission=body.permission,
        )
        if not share:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        return {"share": asdict(share)}

    @app.delete("/api/analysis/reports/{report_id}/shares/{recipient_user_id}")
    def revoke_interactive_report_share(
        report_id: str,
        recipient_user_id: str,
        owner_id: str = Query(min_length=1),
    ) -> dict[str, Any]:
        revoked = configured_interactive_report_store.revoke_report_share(
            report_id,
            owner_id=owner_id,
            recipient_user_id=recipient_user_id,
        )
        if not revoked:
            raise HTTPException(status_code=404, detail="report_share_not_found")
        return {"revoked": True, "report_id": report_id, "recipient_user_id": recipient_user_id}

    @app.get("/api/analysis/reports/{report_id}/versions")
    def list_interactive_report_versions(report_id: str) -> dict[str, Any]:
        versions = configured_interactive_report_store.list_versions(report_id)
        if versions is None:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        return {"versions": [asdict(version) for version in versions]}

    @app.get("/api/analysis/reports/{report_id}/versions/{version_number}")
    def get_interactive_report_version(report_id: str, version_number: int) -> dict[str, Any]:
        result = configured_interactive_report_store.get_report(report_id, version=version_number)
        if not result:
            raise HTTPException(status_code=404, detail="interactive_report_version_not_found")
        report, version = result
        return {"report": asdict(report), "version": asdict(version)}

    @app.get("/api/knowledge")
    def list_knowledge(
        limit: int = 50,
        q: str = "",
        type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        owner: str | None = None,
    ) -> dict[str, Any]:
        return {
            "records": [
                asdict(item)
                for item in configured_knowledge_store.search_knowledge(
                    query=q,
                    item_type=type,
                    status=status,
                    tag=tag,
                    owner=owner,
                    limit=limit,
                )
            ]
        }

    @app.get("/api/knowledge/tags")
    def list_knowledge_tags() -> dict[str, Any]:
        return {"tags": configured_knowledge_store.list_tags()}

    @app.post("/api/knowledge")
    def save_knowledge(body: KnowledgeBody = Body(...)) -> dict[str, Any]:
        record = configured_knowledge_store.save_verified_knowledge(
            title=body.title,
            question=body.question,
            conclusion=body.conclusion,
            scope=body.scope,
            verification=body.verification,
            evidence_refs=body.evidence_refs,
            turn_id=body.turn_id,
            metadata=_knowledge_metadata_from_body(body),
        )
        return asdict(record)

    @app.patch("/api/knowledge/{record_id}")
    def update_knowledge(record_id: str, body: KnowledgeUpdateBody = Body(...)) -> dict[str, Any]:
        record = configured_knowledge_store.update_knowledge(
            record_id,
            title=body.title,
            question=body.question,
            conclusion=body.conclusion,
            scope=body.scope,
            verification=body.verification,
            evidence_refs=body.evidence_refs,
            turn_id=body.turn_id,
            metadata=_knowledge_metadata_from_body(body, partial=True),
        )
        if not record:
            raise HTTPException(status_code=404, detail="knowledge_not_found")
        return asdict(record)

    @app.delete("/api/knowledge/{record_id}")
    def delete_knowledge(record_id: str) -> dict[str, Any]:
        deleted = configured_knowledge_store.delete_knowledge(record_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="knowledge_not_found")
        return {"deleted": True, "id": record_id}

    @app.delete("/api/knowledge")
    def clear_knowledge() -> dict[str, Any]:
        return {"deleted_count": configured_knowledge_store.clear_knowledge()}

    return app


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


async def _create_analysis_turn_payload(
    analysis_runtime: CodexSdkAnalysisRuntime,
    session_catalog: SessionCatalog,
    codex_projection_store: CodexProjectionStore,
    interactive_report_store: Any,
    body: Any,
    *,
    thread_id: str,
    emit_session_created: bool = False,
) -> dict[str, Any]:
    request = _analysis_request_from_body(body, thread_id=thread_id)
    # ``turn_id`` and ``thread_id`` are assigned dynamically from the
    # ``genbi/thread/provisioned`` / ``genbi/turn/provisioned`` events emitted
    # by the Codex runtime (see ``codex_sdk_runner._iter_streamed``). The
    # new-session contract forbids allocating them locally: ``analysis_turns.id``
    # must equal the Codex-issued ``codex_turn_id``.
    turn_id = ""
    events: list[AgentEvent] = []
    # We pass ``thread_id=""`` to ``_astream_runtime_events`` so the
    # session is registered lazily from the
    # ``genbi/thread/provisioned`` event (the Runtime owns that
    # write). The caller-supplied thread_id is still used to
    # resolve the final row in the response below.
    async for event in _astream_runtime_events(
        analysis_runtime,
        session_catalog,
        codex_projection_store,
        interactive_report_store,
        request,
        thread_id="",
        turn_id=turn_id,
    ):
        if not turn_id and event.type == "genbi/turn/provisioned":
            turn_id = _string_or_none(event.payload.get("codex_turn_id")) or _string_or_none(event.payload.get("turn_id")) or ""
        events.append(event)
    if not turn_id:
        raise RuntimeError(
            "codex_runtime_did_not_emit_turn_id: cannot persist turn without Codex-issued turn id."
        )
    request = _analysis_request_from_body(body, thread_id=thread_id)
    # The session id is whatever the Runtime actually issued.
    # We never let a caller-supplied ``thread_id`` override the
    # Runtime's authoritative ``genbi/thread/provisioned`` event.
    runtime_thread_id = _first_event_codex_thread_id(events)
    resolved_thread_id = runtime_thread_id or thread_id
    _save_analysis_turn(
        session_catalog,
        codex_projection_store,
        request,
        thread_id=resolved_thread_id,
        turn_id=turn_id,
        events=events,
    )
    response_events: list[dict[str, Any]] = []
    if emit_session_created:
        # Prepend a synthetic ``session/created`` event so the frontend can
        # learn the Codex-issued id without waiting for ``turn/completed``.
        if resolved_thread_id:
            response_events.append(
                asdict(
                    AgentEvent(
                        type="session/created",
                        turn_id=turn_id,
                        payload={
                            "eventSource": "genbi",
                            "runtime": "openai-codex",
                            "sessionId": resolved_thread_id,
                            "codexThreadId": resolved_thread_id,
                            "codexTurnId": turn_id,
                            "threadId": resolved_thread_id,
                            "turnId": turn_id,
                        },
                    )
                )
            )
    if emit_session_created:
        # Internal marker events. Never forward them to the client; the
        # sessionless flow only exposes ``session/created`` plus the
        # downstream business events. The legacy turn endpoints keep the
        # markers in the response because older clients still parse them.
        for event in events:
            if event.type in {"genbi/thread/provisioned", "genbi/turn/provisioned"}:
                continue
            response_events.append(asdict(event))
    else:
        response_events.extend(asdict(event) for event in events)
    return {
        "thread_id": resolved_thread_id,
        "turn_id": turn_id,
        "events_url": f"/api/analysis/threads/{resolved_thread_id or ''}/turns/{turn_id}",
        "events": response_events,
    }


def _first_event_payload_value(events: list[Any], key: str) -> str | None:
    for event in events:
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict) and payload.get(key):
            return str(payload[key])
    return None


def _first_event_codex_thread_id(events: list[Any]) -> str:
    """Return the Codex-issued thread id from the first provisioned event.

    The new sessionless flow always yields ``genbi/thread/provisioned`` as
    the first business event before any turn work begins. This helper
    pulls the id out so we can synthesise a ``session/created`` envelope
    and resolve the eventual ``thread_id`` for the response.
    """
    for event in events:
        if getattr(event, "type", None) != "genbi/thread/provisioned":
            continue
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue
        codex_thread_id = _string_or_none(payload.get("codex_thread_id")) or _string_or_none(payload.get("thread_id"))
        if codex_thread_id:
            return codex_thread_id
    return ""


def _stream_session_first_turn_response(
    analysis_runtime: CodexSdkAnalysisRuntime,
    session_catalog: SessionCatalog,
    codex_projection_store: CodexProjectionStore,
    interactive_report_store: Any,
    request: AnalysisTurnRequest,
) -> Any:
    """Stream the very first turn of a brand-new analysis session.

    The first business event emitted to the client is ``session/created``
    with ``sessionId == codex_thread_id`` so the frontend can navigate
    from ``/analysis/new`` to ``/analysis/{codex_thread_id}`` while the
    rest of the turn keeps streaming. No pre-allocated analysis thread
    row exists before the call returns; the thread row is created from
    the first ``genbi/thread/provisioned`` event inside the stream.
    """
    from fastapi.responses import StreamingResponse

    async def event_stream() -> Any:
        events: list[AgentEvent] = []
        resolved_turn_id = ""
        resolved_thread_id = ""
        session_event_emitted = False
        try:
            async for event in _astream_runtime_events(
                analysis_runtime,
                session_catalog,
                codex_projection_store,
                interactive_report_store,
                request,
                thread_id="",
                turn_id=resolved_turn_id,
            ):
                if event.type == "genbi/thread/provisioned":
                    codex_thread_id = (
                        _string_or_none(event.payload.get("codex_thread_id"))
                        or _string_or_none(event.payload.get("thread_id"))
                        or ""
                    )
                    if codex_thread_id:
                        resolved_thread_id = codex_thread_id
                if not resolved_turn_id and event.type == "genbi/turn/provisioned":
                    resolved_turn_id = (
                        _string_or_none(event.payload.get("codex_turn_id"))
                        or _string_or_none(event.payload.get("turn_id"))
                        or ""
                    )
                if event.type in {"genbi/thread/provisioned", "genbi/turn/provisioned"}:
                    # Internal marker events. Never forward them to the
                    # client; we only use them to resolve session/turn ids.
                    continue
                if not session_event_emitted and resolved_thread_id and resolved_turn_id:
                    session_event = AgentEvent(
                        type="session/created",
                        turn_id=resolved_turn_id,
                        payload={
                            "eventSource": "genbi",
                            "runtime": "openai-codex",
                            "sessionId": resolved_thread_id,
                            "codexThreadId": resolved_thread_id,
                            "codexTurnId": resolved_turn_id,
                            "threadId": resolved_thread_id,
                            "turnId": resolved_turn_id,
                        },
                    )
                    events.append(session_event)
                    yield session_event.to_sse()
                    session_event_emitted = True
                events.append(event)
                yield event.to_sse()
        except asyncio.CancelledError:
            if not _has_terminal_turn_event(events):
                fallback_turn_id = resolved_turn_id or resolved_thread_id
                events.append(
                    _interrupted_terminal_event(
                        thread_id=resolved_thread_id or "codex_session_pending",
                        turn_id=fallback_turn_id,
                    )
                )
            raise
        finally:
            if events and resolved_turn_id and resolved_thread_id:
                _save_analysis_turn(
                    session_catalog,
                    codex_projection_store,
                    request,
                    thread_id=resolved_thread_id,
                    turn_id=resolved_turn_id,
                    events=events,
                )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _stream_analysis_turn_response(
    analysis_runtime: CodexSdkAnalysisRuntime,
    session_catalog: SessionCatalog,
    codex_projection_store: CodexProjectionStore,
    interactive_report_store: Any,
    body: Any,
    *,
    thread_id: str,
) -> Any:
    from fastapi.responses import StreamingResponse

    request = _analysis_request_from_body(body, thread_id=thread_id)

    async def event_stream() -> Any:
        events: list[AgentEvent] = []
        resolved_turn_id = ""
        resolved_thread_id = thread_id
        try:
            async for event in _astream_runtime_events(
                analysis_runtime,
                session_catalog,
                codex_projection_store,
                interactive_report_store,
                request,
                thread_id=thread_id,
                turn_id=resolved_turn_id,
            ):
                if not resolved_thread_id and event.type == "genbi/thread/provisioned":
                    resolved_thread_id = (
                        _string_or_none(event.payload.get("codex_thread_id"))
                        or _string_or_none(event.payload.get("codex_session_id"))
                        or _string_or_none(event.payload.get("thread_id"))
                        or ""
                    )
                if not resolved_turn_id and event.type == "genbi/turn/provisioned":
                    resolved_turn_id = (
                        _string_or_none(event.payload.get("codex_turn_id"))
                        or _string_or_none(event.payload.get("turn_id"))
                        or ""
                    )
                events.append(event)
                yield event.to_sse()
        except asyncio.CancelledError:
            if not _has_terminal_turn_event(events):
                fallback_turn_id = resolved_turn_id or thread_id
                events.append(_interrupted_terminal_event(thread_id=thread_id, turn_id=fallback_turn_id))
            raise
        finally:
            if events and resolved_turn_id:
                # Lazy-register the session using the Codex-issued id
                # so the stream endpoint also satisfies the
                # new-session contract (``session_id ==
                # codex_session_id``).
                if resolved_thread_id and session_catalog.get_session(resolved_thread_id) is None:
                    try:
                        session_catalog.register_session(
                            session_id=resolved_thread_id,
                            product_kind="analysis_task",
                            title=request.question.strip()[:32] or None,
                            user_id=request.user_id,
                            status="active",
                            codex_session_id=resolved_thread_id,
                            metadata={**(request.metadata or {}), "domain": "analysis_task", "session_id": resolved_thread_id, "codex_session_id": resolved_thread_id},
                        )
                    except ValueError:
                        pass
                _save_analysis_turn(
                    session_catalog,
                    codex_projection_store,
                    request,
                    thread_id=resolved_thread_id,
                    turn_id=resolved_turn_id,
                    events=events,
                )

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _astream_runtime_events(
    analysis_runtime: CodexSdkAnalysisRuntime,
    session_catalog: SessionCatalog,
    codex_projection_store: CodexProjectionStore,
    interactive_report_store: Any,
    request: AnalysisTurnRequest,
    *,
    thread_id: str,
    turn_id: str,
) -> Any:
    """Async stream the Codex Runtime and emit the events downstream.

    The runtime is the only thing that talks to Codex; here we just
    pull events off the stream, fold them into the projection store
    on the fly, and yield each one to the API consumer. Session +
    turn rows are written by the Runtime itself.
    """
    saw_terminal_event = False
    effective_thread_id = thread_id
    runtime = InMemoryCodexAnalysisRuntime(codex_projection_store)
    async for event in analysis_runtime.async_stream(
        request.question.strip(),
        context=_runtime_context(session_catalog, request, thread_id=thread_id, turn_id=turn_id),
    ):
        if not effective_thread_id and event.type == "genbi/thread/provisioned":
            effective_thread_id = (
                _string_or_none(event.payload.get("codex_thread_id"))
                or _string_or_none(event.payload.get("codex_session_id"))
                or _string_or_none(event.payload.get("thread_id"))
                or ""
            )
            thread_id = effective_thread_id
        # ``thread_start``: the catalog owns the session row. We
        # register on the first time we observe the runtime-issued
        # id, regardless of whether we entered this branch above
        # (i.e. a preflight id was supplied).
        if (
            event.type == "genbi/thread/provisioned"
            and effective_thread_id
            and session_catalog.get_session(effective_thread_id) is None
        ):
            try:
                await runtime.thread_start(
                    session_id=effective_thread_id,
                    catalog=session_catalog,
                )
            except Exception:
                LOGGER.warning("session_registration_failed", extra={"session_id": effective_thread_id})
        # The Runtime uses ``save_turn`` for the final turn row; the
        # streaming path here folds projections through the Runtime's
        # accumulator as a side effect so a partial replay already
        # has the projection timeline.
        if (
            effective_thread_id
            and event.type == "genbi/turn/provisioned"
        ):
            provisioned_turn_id = (
                _string_or_none(event.payload.get("codex_turn_id"))
                or _string_or_none(event.payload.get("turn_id"))
                or ""
            )
            if provisioned_turn_id and codex_projection_store.get_turn(effective_thread_id, provisioned_turn_id) is None:
                # Pre-create the turn row in the canonical
                # ``running`` state. The final write through
                # ``save_turn`` will overwrite the status to
                # whatever the Runtime computed.
                codex_projection_store.save_turn(
                    session_id=effective_thread_id,
                    turn_id=provisioned_turn_id,
                    input_kind="start" if request.turn_kind == "start" else "message",
                    input_text=request.question.strip(),
                    status="running",
                    started_at=event.created_at,
                    codex_session_id=effective_thread_id,
                    codex_turn_id=provisioned_turn_id,
                )
        # Fold the projection as we observe it so the store is
        # in sync with the stream. The Runtime owns the
        # accumulation rules; we hand it a fresh TurnStream and
        # ask it to absorb the event.
        if effective_thread_id and turn_id:
            _accumulate_projection(runtime, effective_thread_id, turn_id, request, event)
        enriched = _enrich_analysis_event(event, thread_id=effective_thread_id, turn_id=turn_id, question=request.question.strip())
        if enriched.type == "turn/completed":
            saw_terminal_event = True
        yield enriched
        artifact_event = _interactive_report_artifact_event(enriched, thread_id=thread_id, turn_id=turn_id, interactive_report_store=interactive_report_store)
        if artifact_event:
            yield artifact_event
    if not saw_terminal_event:
        yield _missing_terminal_event(thread_id=thread_id, turn_id=turn_id)


def _accumulate_projection(
    runtime: InMemoryCodexAnalysisRuntime,
    session_id: str,
    turn_id: str,
    request: AnalysisTurnRequest,
    event: AgentEvent,
) -> None:
    """Fold a single AgentEvent into the projection store.

    The Runtime owns the projection accumulator. The streaming path
    has the API feed events one at a time; we reuse the Runtime's
    accumulator so the live and replay paths share the same shape.
    """
    stream = runtime.turn_stream(
        session_id=session_id,
        turn_id=turn_id,
        catalog=runtime.projection_store,  # placeholder; unused for the side effect
        projection_store=runtime.projection_store,
        input_text=request.question.strip(),
        turn_kind=request.turn_kind,
        events=[event],
    )
    stream._persist_projections()


def _missing_terminal_event(*, thread_id: str, turn_id: str) -> AgentEvent:
    return AgentEvent(
        type="turn/completed",
        turn_id=turn_id,
        payload={
            "eventSource": "genbi",
            "thread_id": thread_id,
            "turn_id": turn_id,
            "status": "failed",
            "error": "codex_stream_ended_without_turn_completed",
            "detail": "Codex stream ended without a terminal turn/completed event.",
        },
    )


def _interrupted_terminal_event(*, thread_id: str, turn_id: str) -> AgentEvent:
    return AgentEvent(
        type="turn/completed",
        turn_id=turn_id,
        payload={
            "eventSource": "genbi",
            "thread_id": thread_id,
            "turn_id": turn_id,
            "status": "interrupted",
            "error": "client_disconnected",
            "detail": "Analysis stream was interrupted before Codex returned a terminal event.",
        },
    )


def _has_terminal_turn_event(events: list[AgentEvent]) -> bool:
    return any(event.type == "turn/completed" for event in events)


def _enrich_analysis_event(event: AgentEvent, *, thread_id: str, turn_id: str, question: str | None = None) -> AgentEvent:
    payload = dict(event.payload)
    payload.setdefault("thread_id", thread_id)
    payload.setdefault("turn_id", turn_id)
    if event.type == "turn/started" and question:
        payload.setdefault("question", question)
    if payload.get("codex_item_type") == "userMessage" and question:
        payload.setdefault("content", question)
    return AgentEvent(type=event.type, turn_id=turn_id, payload=payload, created_at=event.created_at)


def _interactive_report_artifact_event(event: AgentEvent, *, thread_id: str, turn_id: str, interactive_report_store: Any | None = None) -> AgentEvent | None:
    payload = dict(event.payload)
    if (
        event.type != "item/completed"
        or payload.get("codex_item_type") != "mcpToolCall"
        or payload.get("mcp_status") not in ("completed", "success", None)
    ):
        return None
    report = _extract_interactive_report(payload)
    is_named_report_tool = payload.get("mcp_server") == "GenBI_report" and payload.get("mcp_tool") == "create_interactive_report"
    if report is None and not is_named_report_tool:
        return None
    if report is None:
        report = compile_interactive_report(
            dict(payload.get("mcp_arguments") or {}),
            thread_id=thread_id,
            turn_id=turn_id,
        )
    else:
        report = normalize_report_artifact(report)
    source = dict(report.get("source") or {})
    source["threadId"] = thread_id
    source["turnId"] = turn_id
    report["source"] = source
    report = normalize_report_artifact(report)
    if validate_report_artifact(report):
        return None
    version_number = None
    if interactive_report_store is not None:
        try:
            _, version = interactive_report_store.save_report(report)
            version_number = version.version
        except (InteractiveReportVersionConflict, ValueError):
            version_number = None
    return AgentEvent(
        type="genbi/artifact/updated",
        turn_id=turn_id,
        payload={
            **report,
            **({"version": version_number} if version_number is not None else {}),
            "eventSource": "genbi_projection",
            "codex_thread_id": payload.get("codex_thread_id"),
            "codex_turn_id": payload.get("codex_turn_id"),
            "codex_item_id": payload.get("codex_item_id"),
        },
    )


def _extract_interactive_report(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("mcp_result", "mcp_output", "result", "output"):
        candidate = _maybe_report_payload(payload.get(key))
        if candidate:
            return candidate
    return None


def _maybe_report_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        content_candidate = _maybe_report_payload(value.get("content"))
        if content_candidate:
            return content_candidate
        nested = value.get("interactive_report") or value.get("report") or value
        return dict(nested) if isinstance(nested, dict) and nested.get("artifactType") == "interactive_report" else None
    if isinstance(value, str):
        try:
            return _maybe_report_payload(json.loads(value))
        except json.JSONDecodeError:
            return None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("type") == "text":
                candidate = _maybe_report_payload(item.get("text"))
            else:
                candidate = _maybe_report_payload(item)
            if candidate:
                return candidate
    return None


def _runtime_context(
    session_catalog: SessionCatalog,
    request: AnalysisTurnRequest,
    *,
    thread_id: str,
    turn_id: str,
) -> dict[str, Any]:
    metadata = dict(request.metadata or {})
    session = session_catalog.get_session(thread_id) if thread_id else None
    codex_session_id = (
        metadata.get("codex_session_id")
        or metadata.get("codexThreadId")
        or metadata.get("codex_thread_id")
        or (session.codexSessionId if session else None)
    )
    return {
        "genbi_thread_id": thread_id,
        "genbi_turn_id": turn_id,
        "turn_id": turn_id,
        "codex_session_id": codex_session_id,
        "codex_thread_id": codex_session_id,
    }


def _save_analysis_turn(
    session_catalog: SessionCatalog,
    codex_projection_store: CodexProjectionStore,
    request: AnalysisTurnRequest,
    *,
    thread_id: str,
    turn_id: str,
    events: list[AgentEvent],
) -> None:
    """Run the Runtime to fold events into Codex projection + turn state.

    The Runtime is the only thing that knows the state machine and
    the AgentEvent → projection translation. The API layer hands the
    events over and the Runtime does the rest.
    """
    runtime = InMemoryCodexAnalysisRuntime(codex_projection_store)
    stream = runtime.turn_stream(
        session_id=thread_id,
        turn_id=turn_id,
        catalog=session_catalog,
        projection_store=codex_projection_store,
        input_text=request.question.strip(),
        turn_kind=request.turn_kind,
        events=events,
    )
    # ``collect`` is the synchronous path used by the one-shot
    # turn endpoint. It persists projections + the final turn row.
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We are already inside a running event loop; persist
            # synchronously. ``_persist_*`` are CPU-only and do not
            # require awaiting.
            stream._persist_projections()
            stream._persist_turn(turn_status_from_events(events))
            return
    except RuntimeError:
        pass
    stream._persist_projections()
    stream._persist_turn(turn_status_from_events(events))


def _last_event_payload_value(events: list[AgentEvent], key: str) -> str | None:
    for event in reversed(events):
        value = event.payload.get(key)
        if value:
            return str(value)
    return None


def _analysis_request_from_body(body: Any, *, thread_id: str) -> AnalysisTurnRequest:
    turn_kind = str(getattr(body, "turn_kind", "start") or "start").strip().lower()
    if turn_kind not in {"start", "message", "reply"}:
        turn_kind = "message"
    metadata = dict(getattr(body, "metadata", {}) or {})
    metadata.pop("data_egress_authorized", None)
    metadata.pop("semantic_context_egress_authorized", None)
    metadata.setdefault("domain", "analysis_task")
    metadata.setdefault("thread_id", thread_id)
    metadata.setdefault("thread_root", not bool(getattr(body, "thread_id", None) or getattr(body, "conversation_id", None)))
    return AnalysisTurnRequest(
        question=body.question,
        thread_id=thread_id,
        user_id=getattr(body, "user_id", None),
        turn_kind=turn_kind,  # type: ignore[arg-type]
        metadata=metadata,
    )


async def _provision_codex_thread_id(
    *,
    analysis_runtime: CodexSdkAnalysisRuntime,
    body: Any,
) -> str:
    """Open a Codex thread and return the Codex-issued thread id.

    Synchronous endpoints (POST ``/api/analysis/threads``,
    ``/api/analysis/reports/{id}/analysis-thread``) need a ``thread_id``
    before they can persist anything, but the new-session contract
    forbids allocating one locally: ``analysis_threads.id`` must equal
    ``analysis_threads.codex_thread_id``. This helper opens a Codex
    thread and returns its id, persisting nothing itself; the caller is
    expected to immediately call ``ThreadStore.create_thread`` with the
    returned id.

    The caller may pre-supply a ``codex_thread_id`` via
    ``body.metadata["codex_thread_id"]`` (for example, when the frontend
    is restoring a previously-used Codex thread). That short-circuits the
    preflight call.

    When the runtime is disabled (``CodexSdkAnalysisRuntime.disabled()``)
    or the caller passes an explicit ``codex_thread_id``, the helper
    returns that id without contacting Codex.
    """
    metadata = dict(getattr(body, "metadata", None) or {})
    preflight = _string_or_none(metadata.get("codex_thread_id")) or _string_or_none(getattr(body, "thread_id", None)) or _string_or_none(getattr(body, "conversation_id", None))
    if preflight:
        return preflight
    if not getattr(analysis_runtime, "enabled", False):
        # No Codex available: fall back to a caller-supplied id (must be
        # provided in metadata) so unit tests and dev workflows can still
        # exercise the contract path.
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
    # Re-use the runtime's internal preflight by running an empty stream
    # that we break out of as soon as we observe ``genbi/thread/provisioned``.
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


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_default_analysis_runtime() -> CodexSdkAnalysisRuntime:
    load_project_env()
    analysis_runtime = os.getenv("GENBI_ANALYSIS_RUNTIME", "codex").lower()
    if analysis_runtime == "codex":
        return CodexSdkAnalysisRuntime.from_env()
    elif analysis_runtime not in {"", "local", "mock"}:
        raise RuntimeError("GENBI_ANALYSIS_RUNTIME only supports codex, local, or mock.")
    return CodexSdkAnalysisRuntime.disabled()


def _session_view_to_thread_dict(
    view_or_session: SessionView | SessionRecord,
    codex_projection_store: CodexProjectionStore,
) -> dict[str, Any]:
    """Render a catalog row (or view) as the legacy ``thread`` dict.

    The frontend sidebar still expects the snake_case + camelCase
    fields it has used since the first generation ``ThreadStore``. We rebuild
    that shape from the catalog + projection store.
    """
    if isinstance(view_or_session, SessionView):
        session = view_or_session.session
        latest_turn_status = view_or_session.latestTurnStatus
        latest_turn_id = view_or_session.latestTurnId
    else:
        session = view_or_session
        latest_turn_status = codex_projection_store.latest_turn_status(session.id)
        latest_turn_id = codex_projection_store.latest_turn_id(session.id)
    turns = codex_projection_store.list_turns(session.id)
    latest_turn = turns[-1] if turns else None
    latest_question = (latest_turn.inputText if latest_turn else "") or ""
    row = asdict(session)
    # The legacy column name was ``codexThreadId``; we keep it for
    # back-compat with the frontend bundle that still surfaces the
    # field. The catalog writes it through ``codexSessionId``.
    row.setdefault("codexThreadId", session.codexSessionId)
    row.setdefault("codex_thread_id", session.codexSessionId)
    return {
        **row,
        "title": _repair_text_encoding(row.get("title")),
        "latestQuestion": _repair_text_encoding(latest_question) or None,
        "latestTurnStatus": latest_turn_status,
        "latestTurnId": latest_turn_id,
        "latest_turn_status": latest_turn_status,
        "latest_turn_id": latest_turn_id,
    }


def _build_thread_detail(
    view: SessionView,
    session_catalog: SessionCatalog,
    codex_projection_store: CodexProjectionStore,
) -> dict[str, Any]:
    """Build the full ``/api/analysis/threads/{id}`` response body.

    Combines the catalog session row with the projection store's
    turns and Codex item projections. The latest-turn signal is
    computed once on the catalog's view.
    """
    turns = codex_projection_store.list_turns(view.session.id)
    projections = codex_projection_store.list_items(session_id=view.session.id)
    repaired_turns = [
        {**asdict(t), "question": _repair_text_encoding(t.inputText)} for t in turns
    ]
    thread_row = asdict(view.session)
    thread_row.setdefault("codexThreadId", view.session.codexSessionId)
    thread_row.setdefault("codex_thread_id", view.session.codexSessionId)
    thread_row["title"] = _repair_text_encoding(view.session.title)
    thread_row["latest_turn_status"] = view.latestTurnStatus
    thread_row["latest_turn_id"] = view.latestTurnId
    thread_row["latestTurnStatus"] = view.latestTurnStatus
    thread_row["latestTurnId"] = view.latestTurnId
    return {
        "thread": thread_row,
        "turns": repaired_turns,
        "codexItemProjections": [asdict(p) for p in projections],
    }


def _find_waiting_analysis_session(
    session_catalog: SessionCatalog,
    codex_projection_store: CodexProjectionStore,
    *,
    title: str,
    user_id: str | None,
    metadata_match: dict[str, str | None],
) -> SessionView | None:
    # The ``waiting_for_question`` session state no longer exists. The
    # legacy compatibility endpoint (``POST /api/analysis/threads``)
    # now always provisions a fresh ``active`` session, so the lookup
    # never returns anything. We still keep the function around in case
    # an older frontend bundle reaches for it; it just yields ``None``.
    for view in session_catalog.list_views(limit=200, product_kind="analysis_task"):
        if view.session.title != title:
            continue
        if user_id is not None and view.session.userId != user_id:
            continue
        metadata = view.session.metadata or {}
        if any(metadata.get(key) != value for key, value in metadata_match.items()):
            continue
        # No more "waiting for question" state; the only legacy
        # behaviour we preserve is the empty-question check.
        if not view.session.codexSessionId:
            return view
    return None


def _interactive_report_payload(report: Any, version: Any) -> dict[str, Any]:
    return {
        "id": report.id,
        "title": report.title,
        "subtitle": report.subtitle,
        "artifactType": report.artifactType,
        "schemaVersion": "1.0",
        "renderer": report.renderer,
        "document": version.document,
        "filters": version.filters,
        "queries": version.queries,
        "chartSpecs": version.chartSpecs,
        "gridSpecs": version.gridSpecs,
        "datasets": version.datasets,
        "source": {
            "threadId": version.sourceThreadId,
            "turnId": version.sourceTurnId,
        },
    }


def _repair_thread_detail_text(detail: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(detail)
    thread = dict(repaired.get("thread") or {})
    thread["title"] = _repair_text_encoding(thread.get("title"))
    repaired["thread"] = thread
    repaired["turns"] = [
        {**turn, "question": _repair_text_encoding(turn.get("question"))}
        for turn in list(repaired.get("turns") or [])
        if isinstance(turn, dict)
    ]
    return repaired


def _repair_text_encoding(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if _is_unreadable_legacy_text(value):
        return None
    try:
        repaired = value.encode("latin1").decode("utf-8")
    except UnicodeError:
        return value
    return repaired if _looks_more_readable(repaired, value) else value


def _looks_more_readable(candidate: str, original: str) -> bool:
    return _cjk_count(candidate) > _cjk_count(original) and _mojibake_marker_count(original) > 0


def _cjk_count(value: str) -> int:
    return sum(1 for char in value if "\u4e00" <= char <= "\u9fff")


def _mojibake_marker_count(value: str) -> int:
    return sum(value.count(marker) for marker in ("Ã", "Â", "ä", "å", "æ", "è", "é", "ç", "ï"))


def _is_unreadable_legacy_text(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    question_marks = stripped.count("?")
    return question_marks >= 3 and question_marks / max(len(stripped), 1) >= 0.25


def _build_default_knowledge_store() -> KnowledgeStore:
    load_project_env()
    if postgres_persistence_enabled():
        try:
            return build_postgres_stores()
        except Exception:
            if os.getenv("GENBI_PERSISTENCE", "").strip():
                raise
    return KnowledgeStore()


def build_postgres_thread_store() -> Any:
    """Legacy alias kept for external callers and the test suite.

    Returns a ``_TestStores``-shaped object that bundles the
    SessionCatalog + CodexProjectionStore built from Postgres.
    """
    if not postgres_persistence_enabled():
        return None
    backend_catalog = PostgresSessionCatalogBackend(get_postgres_database_url())  # type: ignore[arg-type]
    backend_projection = PostgresCodexProjectionBackend(get_postgres_database_url())  # type: ignore[arg-type]
    from backend.harness.session_catalog import SessionCatalog as _SessionCatalog
    from backend.harness.codex_projection_store import CodexProjectionStore as _CodexProjectionStore

    catalog = _SessionCatalog(backend=backend_catalog)
    projection = _CodexProjectionStore(backend=backend_projection)
    catalog.bind_latest_turn_provider(projection)
    projection.bind_session_touch(catalog)
    return _wrap_legacy_stores(catalog, projection)


def _wrap_legacy_stores(catalog: SessionCatalog, projection: CodexProjectionStore) -> Any:
    """Bundle a (SessionCatalog, CodexProjectionStore) pair into a
    legacy ``ThreadStore``-shaped object for back-compat callers.
    """

    class _LegacyThreadStore:
        session_catalog = catalog
        codex_projection_store = projection

    return _LegacyThreadStore()


def _build_default_session_catalog() -> SessionCatalog:
    if postgres_persistence_enabled():
        try:
            return build_postgres_session_catalog()
        except Exception:
            if os.getenv("GENBI_PERSISTENCE", "").strip():
                raise
    return SessionCatalog(path=Path(".resource-index/session-catalog.jsonl"))


def _build_default_codex_projection_store() -> CodexProjectionStore:
    if postgres_persistence_enabled():
        try:
            return build_postgres_codex_projection_store()
        except Exception:
            if os.getenv("GENBI_PERSISTENCE", "").strip():
                raise
    return CodexProjectionStore(path=Path(".resource-index/codex-projection-store.jsonl"))


def _build_default_analysis_asset_store() -> AnalysisAssetStore:
    if postgres_persistence_enabled():
        try:
            return build_postgres_analysis_asset_store()
        except Exception:
            if os.getenv("GENBI_PERSISTENCE", "").strip():
                raise
    return AnalysisAssetStore()


def _build_default_interactive_report_store() -> Any:
    if postgres_persistence_enabled():
        from backend.persistence.postgres_stores import build_postgres_interactive_report_store

        return build_postgres_interactive_report_store()
    return InteractiveReportStore()


def main() -> None:
    app = create_app()
    print(json.dumps({"app": app.title}, ensure_ascii=False))


if __name__ == "__main__":
    main()

