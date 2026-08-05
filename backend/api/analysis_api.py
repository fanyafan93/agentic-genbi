import json
import asyncio
import hmac
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

LOGGER = logging.getLogger(__name__)

from backend.config import check_runtime_env, load_project_env
from backend.analysis.asset_store import AnalysisAssetReopenContext, AnalysisAssetStore
from backend.analysis.interactive_report_store import (
    InteractiveReportStore,
    asdict_report,
)
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
from backend.persistence.postgres_stores import (
    build_postgres_analysis_asset_store,
    build_postgres_stores,
    build_postgres_session_catalog,
    build_postgres_codex_projection_store,
    postgres_persistence_enabled,
)
from backend.system_management import runtime_policy_overrides
from backend.business_semantics.knowledge_store import KnowledgeStore
# P2-3: responsibility split.
#
# ``analysis_api.py`` now owns **only**:
#   * Pydantic HTTP body schemas, CORS, TestClient wiring
#   * Route handlers: parameter validation, permission seams (future),
#     and HTTP/SSE envelope formatting.
#
# Business logic lives in three services:
#   * ``SessionService``          — sessions: list / detail / archive /
#                                   rename / reactivate / id resolution.
#   * ``CodexTurnRunner``         — turn orchestration: start / resume /
#                                   stream / cancel / projection fold /
#                                   terminal-event compensation.
#   * ``ArtifactProjector``       — artifact projection: interactive
#                                   reports saved + artifact events.
from backend.services.artifact_projector import ArtifactProjector, interactive_report_payload
from backend.services.codex_turn_runner import (
    AnalysisTurnRequest,
    CodexTurnRunner,
    _knowledge_metadata_from_body,
    _provision_codex_thread_id,
)
from backend.services.session_service import (
    ANALYSIS_PRODUCT_KIND,
    SessionArchivedError,
    SessionNotFoundError,
    SessionService,
)


# AnalysisTurnRequest dataclass has been hoisted to ``backend.services.codex_turn_runner``
# as part of the P2-3 refactor (boundary: analysis_api handles HTTP only, turn
# shape lives alongside the turn runner). We re-export the canonical class
# here so legacy imports (``backend.api.analysis_api.AnalysisTurnRequest``)
# continue to work for the existing test suite.
from backend.services.codex_turn_runner import AnalysisTurnRequest  # noqa: E402,F401


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
    _enforce_single_worker_runtime()
    if thread_store is not None and (session_catalog is None or codex_projection_store is None):
        session_catalog = session_catalog or getattr(thread_store, "session_catalog", None)
        codex_projection_store = codex_projection_store or getattr(thread_store, "codex_projection_store", None)
    load_project_env()
    try:
        from fastapi import Body, FastAPI, HTTPException, Query, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import Response, StreamingResponse
        from pydantic import BaseModel, ConfigDict, Field
    except ImportError as exc:
        raise RuntimeError("Install FastAPI dependencies from backend/requirements.txt to start the API.") from exc

    class AnalysisTurnBody(BaseModel):
        message: str = Field(min_length=1)
        user_id: str | None = None
        turn_kind: str = "start"
        metadata: dict[str, Any] = Field(default_factory=dict)

    class AnalysisSessionStartBody(BaseModel):
        """Request body for ``POST /api/analysis/sessions/turns``.

        The frontend must POST exactly this shape to begin a brand-new
        session. The endpoint lazily opens a Codex thread and returns
        the Codex-issued id as part of the first ``session/created``
        event.
        """
        model_config = ConfigDict(extra="forbid")
        message: str = Field(min_length=1)
        user_id: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)

    class AnalysisSessionContinuationBody(BaseModel):
        """Request body for ``POST /api/analysis/sessions/{sessionId}/turns``.

        The ``sessionId`` comes from the URL path; the body never
        re-asserts it (no ``sessionId`` / ``conversation_id`` /
        ``task_id`` field is accepted on this contract).
        ``turn_kind`` is restricted to ``message`` or ``reply``
        because the very first turn of a brand-new session uses
        the dedicated sessionless entry point, not this URL.
        """
        model_config = ConfigDict(extra="forbid")
        message: str = Field(min_length=1)
        turn_kind: Literal["message", "reply"] = "message"
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
        source: InteractiveReportSourceBody | None = None
        originType: Literal["codex", "seed", "import", "manual"] | None = None
        ownerId: str = Field(min_length=1)
        dataUpdatedAt: str | None = None
        derivedFromReportId: str | None = None

    class InteractiveReportRenameBody(BaseModel):
        ownerId: str = Field(min_length=1)
        title: str = Field(min_length=1)

    class ReportShareBody(BaseModel):
        ownerId: str = Field(default="local-user", min_length=1)
        recipientUserId: str = Field(min_length=1)
        permission: Literal["view", "view_and_reuse"]

    class ReportAnalysisSessionBody(BaseModel):
        userId: str | None = None
        title: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)

    class AnalysisSessionUpdateBody(BaseModel):
        """Request body for ``PATCH /api/analysis/sessions/{sessionId}``.

        Only fields the catalog knows about (title, status) are
        allowed. The session state machine only accepts
        ``active`` / ``archived``.
        """
        title: str | None = None
        status: str | None = None

    @dataclass(frozen=True)
    class Principal:
        tenant_id: str
        user_id: str
        workspace_id: str
        roles: tuple[str, ...] = ()

    def _header_text(request: Request, name: str) -> str | None:
        value = request.headers.get(name)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _require_system_api_token(request: Request) -> None:
        expected = os.getenv("GENBI_SYSTEM_API_TOKEN", "").strip()
        if not expected:
            return
        actual = _header_text(request, "X-GenBI-System-Token") or ""
        if not hmac.compare_digest(actual, expected):
            raise HTTPException(status_code=401, detail="system_api_token_required")

    def _principal_from_request(request: Request) -> Principal | None:
        tenant_id = _header_text(request, "X-GenBI-Tenant-Id")
        user_id = _header_text(request, "X-GenBI-User-Id")
        workspace_id = _header_text(request, "X-GenBI-Workspace-Id")
        roles_header = _header_text(request, "X-GenBI-Roles")
        if not any((tenant_id, user_id, workspace_id, roles_header)):
            return None
        if not tenant_id or not user_id or not workspace_id:
            raise HTTPException(
                status_code=401,
                detail="principal_required: tenant, user, and workspace headers are required.",
            )
        roles = tuple(
            role.strip().lower()
            for role in str(roles_header or "").replace(";", ",").split(",")
            if role.strip()
        )
        return Principal(
            tenant_id=tenant_id,
            user_id=user_id,
            workspace_id=workspace_id,
            roles=roles,
        )

    def _metadata_with_principal(metadata: dict[str, Any], principal: Principal | None) -> dict[str, Any]:
        merged = dict(metadata or {})
        if principal is None:
            return merged
        merged["tenant_id"] = principal.tenant_id
        merged["user_id"] = principal.user_id
        merged["workspace_id"] = principal.workspace_id
        merged["roles"] = list(principal.roles)
        return merged

    def _principal_can_access_session(principal: Principal | None, session: SessionRecord) -> bool:
        if principal is None:
            return True
        if "admin" in principal.roles:
            return True
        return (
            session.tenantId == principal.tenant_id
            and session.userId == principal.user_id
            and session.workspaceId == principal.workspace_id
        )

    def _require_principal_view(
        session_id: str,
        principal: Principal | None,
        *,
        active: bool = False,
    ) -> SessionView:
        view = (
            configured_session_service.require_active_view(session_id)
            if active
            else configured_session_service.require_view(session_id)
        )
        if not _principal_can_access_session(principal, view.session):
            raise SessionNotFoundError(session_id)
        return view


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
    # P2-3: instantiate the service triad once per app. The rest of the
    # routes only touch the services, not the raw stores directly.
    configured_artifact_projector = ArtifactProjector(configured_interactive_report_store)
    configured_turn_runner = CodexTurnRunner(
        analysis_runtime=configured_analysis_runtime,
        session_catalog=configured_session_catalog,
        codex_projection_store=configured_codex_projection_store,
        artifact_projector=configured_artifact_projector,
    )
    configured_session_service = SessionService(
        session_catalog=configured_session_catalog,
        codex_projection_store=configured_codex_projection_store,
    )
    # catalog → projection store bidirectional seams are now bound by
    # both SessionService and CodexTurnRunner; we still keep the
    # projection → session touch seam here so save_turn updates the
    # catalog's updatedAt without circular imports.
    configured_codex_projection_store.bind_session_touch(configured_session_catalog)
    configured_finereport_repository = finereport_repository or FineReportReportRepository()

    def first_turn_metadata(
        raw_metadata: dict[str, Any],
        principal: Principal | None,
    ) -> dict[str, Any]:
        metadata = dict(raw_metadata or {})
        source_report_id = str(metadata.get("source_report_id") or "").strip()
        for key in (
            "initial_report_id",
            "initial_report_artifact",
            "initial_report_saved_at",
            "session_title",
        ):
            metadata.pop(key, None)
        if source_report_id:
            report = configured_interactive_report_store.get_report(source_report_id)
            if not report:
                raise HTTPException(status_code=404, detail="interactive_report_not_found")
            metadata.update({
                "source_report_id": report.id,
                "initial_report_id": report.id,
                "initial_report_artifact": interactive_report_payload(report),
                "initial_report_saved_at": report.updatedAt,
                "session_title": f"{report.title} 新会话",
            })
        metadata = _metadata_with_principal(metadata, principal)
        metadata.setdefault("domain", ANALYSIS_PRODUCT_KIND)
        metadata.setdefault("thread_root", True)
        return metadata

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/runtime/status")
    def runtime_status() -> dict[str, Any]:
        return check_runtime_env()

    @app.get("/api/system/mcp/servers")
    def list_mcp_servers(request: Request) -> dict[str, Any]:
        _require_system_api_token(request)
        return codex_mcp_server_status_payload()

    @app.post("/api/system/mcp/servers/{server_name}/test")
    def test_mcp_server(server_name: str, request: Request) -> dict[str, Any]:
        _require_system_api_token(request)
        return test_codex_mcp_server(server_name)

    @app.get("/api/system/runtime/policy")
    def system_runtime_policy(request: Request) -> dict[str, Any]:
        _require_system_api_token(request)
        managed = runtime_policy_overrides()
        default_tools = os.getenv("GENBI_CODEX_DEFAULT_TOOLS_ENABLED", "true").strip().lower()
        return {
            "provider": str(getattr(configured_analysis_runtime, "provider", "") or "local"),
            "enabled": bool(getattr(configured_analysis_runtime, "enabled", False)),
            "model": str(managed.get("model") or getattr(configured_analysis_runtime, "model", "") or ""),
            "approvalMode": (
                "deny_all"
                if managed.get("approval_mode") == "deny_all"
                else "auto_review"
            ),
            "sandbox": (
                "workspace_write"
                if managed.get("sandbox") == "workspace_write"
                else "read_only"
            ),
            "defaultToolsEnabled": (
                managed["default_tools_enabled"]
                if isinstance(managed.get("default_tools_enabled"), bool)
                else default_tools not in {"0", "false", "off", "no", "disabled"}
            ),
        }

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

    @app.get("/api/analysis/sessions")
    def list_analysis_sessions(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        status: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """List sessions visible on the analysis sidebar.

        ``SessionService.list_sessions`` owns the filtering semantics:
        * default is **active** sessions only,
        * ``status=archived`` shows soft-deleted rows,
        * ``status=active`` is the explicit positive filter,
        * transient ``draft_`` prefix rows are hidden.

        The HTTP layer only validates the ``limit`` / ``status`` query
        parameters and maps ``ValueError`` from the service to 400.
        """
        principal = _principal_from_request(request)
        try:
            views = configured_session_service.list_sessions(
                limit=limit,
                status=None if status is None else status,  # type: ignore[arg-type]
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "sessions": [
                _session_view_to_thread_dict(view, configured_codex_projection_store)
                for view in views
                if _principal_can_access_session(principal, view.session)
            ]
        }

    @app.post("/api/analysis/sessions/turns")
    async def start_session_first_turn(
        request: Request,
        body: AnalysisSessionStartBody = Body(...),
    ) -> dict[str, Any]:
        """Start the very first turn of a brand-new session.

        The session id is allocated by the Codex Runtime (via
        ``CodexTurnRunner.run_turn_buffered``) — the HTTP layer never
        mints one. The runtime is *required* here; we do not fall back
        to writing a caller-supplied synthetic row.
        """
        principal = _principal_from_request(request)
        metadata = first_turn_metadata(dict(body.metadata or {}), principal)
        turn_request = AnalysisTurnRequest(
            question=body.message.strip(),
            session_id="",
            user_id=principal.user_id if principal is not None else body.user_id,
            turn_kind="start",
            metadata=metadata,
        )
        if not getattr(configured_analysis_runtime, "enabled", False):
            raise HTTPException(
                status_code=503,
                detail="codex_runtime_not_configured: /sessions/turns requires a streaming Codex runtime.",
            )
        # Turn ownership is now 100% inside CodexTurnRunner. The
        # runner decides the session id (from Codex provisioned
        # event), pre-creates the turn, folds projections, saves
        # the final row, and prepares the event envelope.
        return await configured_turn_runner.run_turn_buffered(
            turn_request,
            session_id="",
            emit_session_created=True,
        )

    @app.get("/api/analysis/sessions/{session_id}")
    def get_analysis_session(request: Request, session_id: str) -> dict[str, Any]:
        """Return the full session detail (turns + Codex item projections).

        ``SessionService.get_session_detail`` is authoritative; we only
        map ``SessionNotFoundError`` to HTTP 404 so the service layer
        stays HTTP-agnostic.
        """
        principal = _principal_from_request(request)
        try:
            _require_principal_view(session_id, principal)
            detail = configured_session_service.get_session_detail(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="analysis_session_not_found")
        # The legacy HTTP envelope wraps the session row into
        # ``session`` / ``thread``. Detail is already a flat dict with
        # ``turns`` inside. Strict UTF-8 contract: no runtime encoding
        # repair; if mojibake appears here the data-at-rest is corrupted.
        return {
            "session": {
                "id": detail["id"],
                "title": detail.get("title"),
                "status": detail["status"],
                "createdAt": detail["createdAt"],
                "updatedAt": detail["updatedAt"],
                "productKind": detail["productKind"],
                "codexSessionId": detail["codexSessionId"],
                "codexThreadId": detail["codexSessionId"],
                "codex_thread_id": detail["codexSessionId"],
                "metadata": detail.get("metadata", {}),
                "latestTurnId": detail["latestTurnId"],
                "latestTurnStatus": detail["latestTurnStatus"],
                "latest_turn_id": detail["latestTurnId"],
                "latest_turn_status": detail["latestTurnStatus"],
            },
            "thread": {
                "id": detail["id"],
                "title": detail.get("title"),
                "status": detail["status"],
                "createdAt": detail["createdAt"],
                "updatedAt": detail["updatedAt"],
                "productKind": detail["productKind"],
                "codexSessionId": detail["codexSessionId"],
                "codexThreadId": detail["codexSessionId"],
                "codex_thread_id": detail["codexSessionId"],
                "metadata": detail.get("metadata", {}),
                "latestTurnId": detail["latestTurnId"],
                "latestTurnStatus": detail["latestTurnStatus"],
                "latest_turn_id": detail["latestTurnId"],
                "latest_turn_status": detail["latestTurnStatus"],
            },
            "turns": [
                {**t, "question": t.get("inputText")}
                for t in detail["turns"]
            ],
            "codexItemProjections": detail.get("codexItemProjections", []),
        }

    @app.patch("/api/analysis/sessions/{session_id}")
    def patch_analysis_session(
        request: Request,
        session_id: str,
        body: AnalysisSessionUpdateBody = Body(default_factory=AnalysisSessionUpdateBody),
    ) -> dict[str, Any]:
        """Update session-level fields.

        Title / status mutations go through ``SessionService``; the
        HTTP layer validates the enum and maps
        ``SessionNotFoundError`` → 404.
        """
        principal = _principal_from_request(request)
        try:
            _require_principal_view(session_id, principal)
            if body.title is not None:
                configured_session_service.rename_session(session_id, title=body.title)
            if body.status is not None:
                if body.status not in {"active", "archived"}:
                    raise HTTPException(
                        status_code=400,
                        detail="session_status_invalid: only 'active' or 'archived' are accepted",
                    )
                configured_session_service.update_status(session_id, status=body.status)  # type: ignore[arg-type]
            refreshed = configured_session_service.require_view(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="analysis_session_not_found")
        return {"session": _session_view_to_thread_dict(refreshed, configured_codex_projection_store)}

    @app.delete("/api/analysis/sessions/{session_id}")
    def delete_analysis_session(request: Request, session_id: str) -> dict[str, Any]:
        """Soft-delete a session by archiving it.

        ``SessionService.archive_session`` owns the mutation; the
        route only maps ``SessionNotFoundError`` → 404 and formats
        the legacy ``{ deleted, session_id, session }`` envelope.
        See ``SessionService.archive_session`` for the "why no
        physical delete" rationale.
        """
        principal = _principal_from_request(request)
        try:
            _require_principal_view(session_id, principal)
            archived = configured_session_service.archive_session(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="analysis_session_not_found")
        return {
            "deleted": True,
            "session_id": archived.id,
            "session": {
                "id": archived.id,
                "status": archived.status,
                "codexSessionId": archived.codexSessionId,
                "updatedAt": archived.updatedAt,
            },
        }

    @app.post("/api/analysis/sessions/{session_id}/turns")
    async def create_session_turn(
        request: Request,
        session_id: str,
        body: AnalysisSessionContinuationBody = Body(default_factory=AnalysisSessionContinuationBody),
    ) -> dict[str, Any]:
        """Non-streaming continuation turn on an existing session.

        Contract is enforced in order by:
        1. URL must carry a non-blank id.
        2. ``SessionService.require_active_view`` must resolve to an
           ``active`` row → 404 / 409 otherwise.
        3. ``CodexTurnRunner.run_turn_buffered`` actually runs the
           Codex runtime and persists.
        """
        if not session_id.strip():
            raise HTTPException(status_code=400, detail="session_id_required")
        principal = _principal_from_request(request)
        try:
            view = _require_principal_view(session_id, principal, active=True)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="analysis_session_not_found")
        except SessionArchivedError:
            canonical_session_id = configured_session_service.resolve_session_id(session_id) or session_id
            raise HTTPException(
                status_code=409,
                detail=f"analysis_session_archived: session {canonical_session_id!r} is archived and cannot accept new turns.",
            )
        canonical_session_id = view.session.id
        codex_session_id = view.session.codexSessionId or view.session.id
        request = AnalysisTurnRequest(
            question=body.message.strip(),
            session_id=canonical_session_id,
            user_id=principal.user_id if principal is not None else body.user_id,
            turn_kind=str(body.turn_kind or "message").strip().lower() or "message",  # type: ignore[arg-type]
            metadata=_metadata_with_principal({
                **(body.metadata or {}),
                "domain": ANALYSIS_PRODUCT_KIND,
                "session_id": canonical_session_id,
                "codex_session_id": codex_session_id,
            }, principal),
        )
        return await configured_turn_runner.run_turn_buffered(
            request,
            session_id=canonical_session_id,
            codex_session_id=codex_session_id,
        )

    @app.post("/api/analysis/sessions/turns/stream")
    async def stream_session_first_turn(
        request: Request,
        body: AnalysisSessionStartBody = Body(...),
    ) -> Any:
        """Stream the very first turn of a brand-new session.

        Returns a ``StreamingResponse`` whose generator is built by
        ``CodexTurnRunner.stream_first_turn``. The generator owns
        event folding, session/turn id resolution, and the
        interrupted terminal event on cancel.
        """
        if not getattr(configured_analysis_runtime, "enabled", False):
            raise HTTPException(
                status_code=503,
                detail="codex_runtime_not_configured: /turns/stream requires a streaming Codex runtime.",
            )
        from fastapi.responses import StreamingResponse

        principal = _principal_from_request(request)
        metadata = first_turn_metadata(dict(body.metadata or {}), principal)
        turn_request = AnalysisTurnRequest(
            question=body.message.strip(),
            session_id="",
            user_id=principal.user_id if principal is not None else body.user_id,
            turn_kind="start",
            metadata=metadata,
        )
        stream_iter = configured_turn_runner.stream_first_turn(turn_request)

        async def _sse_iter() -> Any:
            async for event in stream_iter:
                yield event.to_sse()

        return StreamingResponse(_sse_iter(), media_type="text/event-stream")

    @app.post("/api/analysis/sessions/{session_id}/turns/stream")
    async def stream_session_continuation_turn(
        request: Request,
        session_id: str,
        body: AnalysisSessionContinuationBody = Body(default_factory=AnalysisSessionContinuationBody),
    ) -> Any:
        """Stream a continuation turn on an existing session.

        Mirrors the JSON endpoint contract: non-blank URL, resolved
        active session, canonical id + Codex id forwarded through
        ``CodexTurnRunner.stream_continuation_turn``.
        """
        if not session_id.strip():
            raise HTTPException(status_code=400, detail="session_id_required")
        principal = _principal_from_request(request)
        try:
            view = _require_principal_view(session_id, principal, active=True)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="analysis_session_not_found")
        except SessionArchivedError:
            canonical_session_id = configured_session_service.resolve_session_id(session_id) or session_id
            raise HTTPException(
                status_code=409,
                detail=f"analysis_session_archived: session {canonical_session_id!r} is archived and cannot accept new turns.",
            )
        from fastapi.responses import StreamingResponse

        canonical_session_id = view.session.id
        codex_session_id = view.session.codexSessionId or view.session.id
        turn_request = AnalysisTurnRequest(
            question=body.message.strip(),
            session_id=canonical_session_id,
            user_id=principal.user_id if principal is not None else body.user_id,
            turn_kind=str(body.turn_kind or "message").strip().lower() or "message",  # type: ignore[arg-type]
            metadata=_metadata_with_principal({
                **(body.metadata or {}),
                "domain": ANALYSIS_PRODUCT_KIND,
                "session_id": canonical_session_id,
                "codex_session_id": codex_session_id,
            }, principal),
        )
        stream_iter = configured_turn_runner.stream_continuation_turn(
            turn_request,
            session_id=canonical_session_id,
            codex_session_id=codex_session_id,
        )

        async def _sse_iter() -> Any:
            async for event in stream_iter:
                yield event.to_sse()

        return StreamingResponse(_sse_iter(), media_type="text/event-stream")

    @app.post("/api/analysis/sessions/{session_id}/cancel")
    def cancel_session(request: Request, session_id: str) -> dict[str, Any]:
        """Archive a session (legacy endpoint; does NOT cancel a turn).

        Maps 1:1 onto ``SessionService.archive_session`` (with
        require_view so even already-archived rows resolve) then
        renders the back-compat envelope. Turn-level interrupt uses
        the dedicated ``turns/{turn_id}/cancel`` endpoint below.
        """
        principal = _principal_from_request(request)
        try:
            _require_principal_view(session_id, principal)
            configured_session_service.archive_session(session_id)
            refreshed = configured_session_service.require_view(session_id)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="analysis_session_not_found")
        return {"session": _session_view_to_thread_dict(refreshed, configured_codex_projection_store)}

    @app.post("/api/analysis/sessions/{session_id}/turns/{turn_id}/cancel")
    async def cancel_session_turn(request: Request, session_id: str, turn_id: str) -> dict[str, Any]:
        """Interrupt the live Codex Turn for ``(session_id, turn_id)``.

        Owned by ``CodexTurnRunner.interrupt_turn``: it writes the
        terminal ``interrupted`` row *and* calls the Codex runtime's
        interrupt_turn. The route resolves ids, maps 4xx statuses,
        and returns the legacy ``{ session_id, turn_id, status,
        codex_runtime_interrupted }`` envelope.
        """
        if not turn_id.strip():
            raise HTTPException(status_code=400, detail="turn_id_required")
        principal = _principal_from_request(request)
        try:
            view = _require_principal_view(session_id, principal)
        except SessionNotFoundError:
            raise HTTPException(status_code=404, detail="analysis_session_not_found")
        canonical_session_id = view.session.id
        handled, info = await configured_turn_runner.interrupt_turn(
            session_id=canonical_session_id, turn_id=turn_id
        )
        return {
            "session_id": canonical_session_id,
            "turn_id": turn_id,
            "status": "cancelled" if handled else "no_such_turn_or_already_terminal",
            "turn_status_updated": handled,
            "codex_runtime_interrupted": bool(info.get("codex_runtime_interrupted")),
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
            report = configured_interactive_report_store.save_report(body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"report": asdict_report(report)}

    @app.get("/api/analysis/reports/{report_id}")
    def get_interactive_report(report_id: str) -> dict[str, Any]:
        result = configured_interactive_report_store.get_report(report_id)
        if not result:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        return {"report": asdict_report(result)}

    @app.post("/api/analysis/reports/{report_id}/sessions")
    async def create_session_from_report(
        request: Request,
        report_id: str,
        body: ReportAnalysisSessionBody = Body(default_factory=ReportAnalysisSessionBody),
    ) -> dict[str, Any]:
        """Create a brand-new analysis session anchored to a saved report.

        The session id comes from the Codex runtime; the body never
        carries a session id (no ``session_id`` / ``task_id`` aliases).
        """
        result = configured_interactive_report_store.get_report(report_id)
        if not result:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        principal = _principal_from_request(request)
        report = result
        title = (body.title or f"{report.title} 新分析").strip()
        report_payload = interactive_report_payload(report)
        try:
            session_id = await _provision_codex_thread_id(
                analysis_runtime=configured_analysis_runtime,
                body=body,
                allow_client_preflight=False,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        # Session creation routed through SessionService: the service
        # owns id canonicalization + latest-turn binding. Since the
        # service does not yet expose a raw ``register_session``
        # passthrough we call the underlying catalog here and then
        # touch through require_view so the binding is consistent.
        configured_session_service.raw_catalog.register_session(
            session_id=session_id,
            product_kind=ANALYSIS_PRODUCT_KIND,
            title=title,
            user_id=principal.user_id if principal is not None else body.userId,
            status="active",
            codex_session_id=session_id,
            metadata=_metadata_with_principal({
                "domain": ANALYSIS_PRODUCT_KIND,
                "session_id": session_id,
                "codex_session_id": session_id,
                "source_report_id": report.id,
                "initial_report_id": report.id,
                "initial_report_artifact": report_payload,
            }, principal),
        )
        view = configured_session_service.require_view(session_id)
        return {
            "session": _session_view_to_thread_dict(view, configured_codex_projection_store),
            "report": {"report": asdict_report(report)},
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




def build_default_analysis_runtime() -> CodexSdkAnalysisRuntime:
    load_project_env()
    analysis_runtime = os.getenv("GENBI_ANALYSIS_RUNTIME", "codex").lower()
    if analysis_runtime == "codex":
        return CodexSdkAnalysisRuntime.from_env()
    elif analysis_runtime not in {"", "local", "mock"}:
        raise RuntimeError("GENBI_ANALYSIS_RUNTIME only supports codex, local, or mock.")
    return CodexSdkAnalysisRuntime.disabled()


def _enforce_single_worker_runtime() -> None:
    """V1 safety guard: live Codex turn handles are process-local.

    Until the runtime has a cross-process turn registry, a backend
    configured with more than one worker can route cancel requests to
    a process that does not own the live SDK turn handle.
    """

    for env_name in ("GENBI_BACKEND_WORKERS", "WEB_CONCURRENCY", "UVICORN_WORKERS"):
        raw = os.getenv(env_name)
        if raw is None or not str(raw).strip():
            continue
        try:
            workers = int(str(raw).strip())
        except ValueError:
            continue
        if workers > 1:
            raise RuntimeError(
                f"backend_single_worker_required: {env_name}={workers}; "
                "Codex turn cancellation requires a single worker in V1."
            )


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
        "title": row.get("title"),
        "latestQuestion": latest_question or None,
        "latestTurnStatus": latest_turn_status,
        "latestTurnId": latest_turn_id,
        "latest_turn_status": latest_turn_status,
        "latest_turn_id": latest_turn_id,
    }




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

