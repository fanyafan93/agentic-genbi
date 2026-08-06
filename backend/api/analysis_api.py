import json
import asyncio
import hmac
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from uuid import uuid4

LOGGER = logging.getLogger(__name__)

from backend.config import check_runtime_env, load_project_env
from backend.analysis.asset_store import AnalysisAssetReopenContext, AnalysisAssetStore
from backend.business_semantics.finereport_reports import FineReportReportRepository
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.codex_mcp_config import codex_mcp_server_status_payload, test_codex_mcp_server
from backend.harness.events import AgentEvent
from backend.harness.minimax_codex_adapter import (
    proxy_minimax_response,
    report_build_no_progress_response,
)
from backend.harness.session_catalog import SessionCatalog, SessionRecord, SessionView
from backend.harness.codex_projection_store import (
    CodexItemProjectionRecord,
    CodexProjectionStore,
    TurnRecord,
)
from backend.persistence.postgres_stores import (
    build_postgres_analysis_asset_store,
    build_postgres_report_build_store,
    build_postgres_report_store,
    build_postgres_stores,
    build_postgres_session_catalog,
    build_postgres_codex_projection_store,
    postgres_persistence_enabled,
)
from backend.reports.models import report_to_payload, share_to_payload
from backend.reports.excel_export import (
    ReportTableNotExportable,
    create_report_excel_export,
    remove_export_file,
)
from backend.reports.build_context import (
    ReportToolExecutionRegistry,
    ReportToolTokenError,
)
from backend.reports.build_models import (
    renderable_report_from_build,
    report_build_to_payload,
)
from backend.reports.build_service import (
    REPORT_BUILD_TOOL_NAMES,
    ReportBuildService,
)
from backend.reports.build_store import ReportBuildStore
from backend.reports.query_service import (
    MySqlQueryRunner,
    ReportExportLimitExceeded,
    ReportFilterError,
    ReportQueryExecutionError,
    ReportQueryNotFound,
    ReportQueryService,
)
from backend.reports.schema import ReportValidationError
from backend.reports.store import ReportStore
from backend.system_management import runtime_policy_overrides
from backend.system_management.context_status import list_installed_skills
from backend.system_management.mcp_registry import (
    McpRegistry,
    McpRegistryConflict,
    McpRegistryError,
    McpRegistryNotFound,
    build_mcp_registry,
)
from backend.system_management.settings_store import set_mcp_enabled_override
from backend.system_management.mcp_probe import probe_mcp_server
from backend.system_management.model_connections import (
    ModelConnectionConflict,
    ModelConnectionError,
    ModelConnectionNotFound,
    build_model_connection_registry,
)
from backend.system_management.model_probe import probe_model_connection
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
from backend.services.report_projector import ReportProjector
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
    report_store: Any | None = None,
    report_build_store: Any | None = None,
    report_tool_execution_registry: (
        ReportToolExecutionRegistry | None
    ) = None,
    report_query_service: ReportQueryService | None = None,
    session_catalog: SessionCatalog | None = None,
    codex_projection_store: CodexProjectionStore | None = None,
    # Legacy shim: older tests (and external callers) still pass a
    # single ``thread_store`` keyword. If we see one, we split it
    # into the new pair; this is the only place the legacy alias
    # is recognised.
    thread_store: Any | None = None,
    finereport_repository: FineReportReportRepository | None = None,
    mcp_registry: McpRegistry | None = None,
    model_connection_registry: Any | None = None,
) -> Any:
    _enforce_single_worker_runtime()
    if thread_store is not None and (session_catalog is None or codex_projection_store is None):
        session_catalog = session_catalog or getattr(thread_store, "session_catalog", None)
        codex_projection_store = codex_projection_store or getattr(thread_store, "codex_projection_store", None)
    load_project_env()
    try:
        from fastapi import Body, FastAPI, HTTPException, Query, Request
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, Response, StreamingResponse
        from starlette.background import BackgroundTask
        from pydantic import (
            BaseModel,
            ConfigDict,
            Field,
            ValidationError as PydanticValidationError,
        )
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

    class ReportConfigBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ownerId: str = Field(default="local-user", min_length=1)
        title: str = Field(min_length=1)
        subtitle: str = Field(min_length=1)
        layout: dict[str, Any]
        filters: dict[str, Any] = Field(default_factory=dict)
        charts: dict[str, Any] = Field(default_factory=dict)
        tables: dict[str, Any] = Field(default_factory=dict)
        queries: dict[str, Any] = Field(default_factory=dict)

    class ReportShareBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ownerId: str = Field(default="local-user", min_length=1)
        recipientUserId: str = Field(min_length=1)
        permission: Literal["view", "view_and_reuse"]

    class ReportExampleBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        ownerId: str = Field(min_length=1)
        isExample: bool

    class ReportSortBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        field: str = Field(min_length=1)
        direction: Literal["asc", "desc"]

    class ReportQueryBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        filters: dict[str, Any] = Field(default_factory=dict)
        page: int = Field(default=1, ge=1)
        pageSize: int = Field(default=50, ge=1, le=500)
        sort: ReportSortBody | None = None
        columnFilters: dict[str, list[str]] = Field(default_factory=dict)

    class ReportTableExportBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        filters: dict[str, Any] = Field(default_factory=dict)
        sort: ReportSortBody | None = None
        columnFilters: dict[str, list[str]] = Field(default_factory=dict)

    class StartReportBuildBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        title: str = Field(min_length=1)
        subtitle: str = Field(min_length=1)

    class GetReportBuildBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        build_id: str = Field(min_length=1)

    class SetReportFiltersBody(GetReportBuildBody):
        filters: dict[str, Any]

    class UpsertReportQueryBody(GetReportBuildBody):
        query_id: str = Field(min_length=1)
        query: dict[str, Any]

    class UpsertReportChartBody(GetReportBuildBody):
        chart_id: str = Field(min_length=1)
        chart: dict[str, Any]

    class UpsertReportTableBody(GetReportBuildBody):
        table_id: str = Field(min_length=1)
        table: dict[str, Any]

    class SetReportLayoutBody(GetReportBuildBody):
        layout: dict[str, Any]

    report_build_body_models = {
        "start_report_build": StartReportBuildBody,
        "get_report_build": GetReportBuildBody,
        "set_report_filters": SetReportFiltersBody,
        "upsert_report_query": UpsertReportQueryBody,
        "upsert_report_chart": UpsertReportChartBody,
        "upsert_report_table": UpsertReportTableBody,
        "set_report_layout": SetReportLayoutBody,
        "validate_report_build": GetReportBuildBody,
        "publish_report_build": GetReportBuildBody,
    }

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

    def _require_model_management_token(request: Request) -> None:
        expected = os.getenv("GENBI_SYSTEM_API_TOKEN", "").strip()
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="system_api_token_not_configured",
            )
        actual = _header_text(request, "X-GenBI-System-Token") or ""
        if not hmac.compare_digest(actual, expected):
            raise HTTPException(
                status_code=401,
                detail="system_api_token_required",
            )

    def _managed_mcp_registry() -> McpRegistry:
        if mcp_registry is not None:
            return mcp_registry
        try:
            return build_mcp_registry()
        except Exception as error:
            LOGGER.error("mcp_registry_unavailable error=%s", error)
            raise HTTPException(
                status_code=503,
                detail="mcp_registry_unavailable",
            ) from error

    def _mcp_actor_id(request: Request) -> str:
        return _header_text(request, "X-GenBI-Actor-Id") or "system"

    def _managed_model_connection_registry() -> Any:
        if model_connection_registry is not None:
            return model_connection_registry
        try:
            return build_model_connection_registry()
        except Exception as error:
            LOGGER.error(
                "model_connection_registry_unavailable error=%s",
                error,
            )
            raise HTTPException(
                status_code=503,
                detail="model_connection_registry_unavailable",
            ) from error

    def _raise_mcp_http_error(error: McpRegistryError) -> None:
        if isinstance(error, McpRegistryNotFound):
            raise HTTPException(status_code=404, detail=str(error)) from error
        if isinstance(error, McpRegistryConflict):
            raise HTTPException(status_code=409, detail=str(error)) from error
        raise HTTPException(status_code=422, detail=str(error)) from error

    def _raise_model_connection_http_error(
        error: ModelConnectionError,
    ) -> None:
        if isinstance(error, ModelConnectionNotFound):
            raise HTTPException(status_code=404, detail=str(error)) from error
        if isinstance(error, ModelConnectionConflict):
            raise HTTPException(status_code=409, detail=str(error)) from error
        raise HTTPException(status_code=422, detail=str(error)) from error

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
        expose_headers=["Content-Disposition"],
    )
    configured_knowledge_store = knowledge_store or _build_default_knowledge_store()
    configured_analysis_runtime = analysis_runtime or build_default_analysis_runtime()
    configured_analysis_asset_store = analysis_asset_store or _build_default_analysis_asset_store()
    configured_report_store = (
        report_store
        or _build_default_report_store()
    )
    configured_report_query_service = (
        report_query_service
        or ReportQueryService(MySqlQueryRunner())
    )
    configured_session_catalog = session_catalog or _build_default_session_catalog()
    configured_codex_projection_store = codex_projection_store or _build_default_codex_projection_store()
    configured_report_build_store = (
        report_build_store
        or _build_default_report_build_store(
            configured_report_store
        )
    )
    configured_report_build_service = ReportBuildService(
        configured_report_build_store
    )
    configured_report_tool_registry = (
        report_tool_execution_registry
        or ReportToolExecutionRegistry()
    )
    bind_active_build_resolver = getattr(
        configured_report_tool_registry,
        "bind_active_build_resolver",
        None,
    )
    if callable(bind_active_build_resolver):
        bind_active_build_resolver(
            lambda owner_id, session_id: (
                configured_report_build_store.get_active_for_session(
                    session_id,
                    owner_id=owner_id,
                )
                is not None
            )
        )
    bind_report_registry = getattr(
        configured_analysis_runtime,
        "bind_report_tool_execution_registry",
        None,
    )
    if callable(bind_report_registry):
        bind_report_registry(configured_report_tool_registry)
    # P2-3: instantiate the service triad once per app. The rest of the
    # routes only touch the services, not the raw stores directly.
    configured_report_projector = ReportProjector(configured_report_store)
    configured_turn_runner = CodexTurnRunner(
        analysis_runtime=configured_analysis_runtime,
        session_catalog=configured_session_catalog,
        codex_projection_store=configured_codex_projection_store,
        report_projector=configured_report_projector,
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
            "initial_report",
            "session_title",
        ):
            metadata.pop(key, None)
        if source_report_id:
            report = configured_report_store.get_report(source_report_id)
            if not report:
                raise HTTPException(status_code=404, detail="report_not_found")
            metadata.update({
                "source_report_id": report.id,
                "initial_report": report_to_payload(report),
                "session_title": f"{report.title} 新会话",
            })
        metadata = _metadata_with_principal(metadata, principal)
        metadata.setdefault("domain", ANALYSIS_PRODUCT_KIND)
        metadata.setdefault("thread_root", True)
        return metadata

    def _require_report_build(
        build_id: str,
        principal: Principal | None,
    ) -> Any:
        build = configured_report_build_store.get_build(build_id)
        if build is None:
            raise HTTPException(
                status_code=404,
                detail="report_build_not_found",
            )
        if (
            principal is not None
            and "admin" not in principal.roles
            and build.ownerId != principal.user_id
        ):
            raise HTTPException(
                status_code=404,
                detail="report_build_not_found",
            )
        return build

    def _report_build_response(build: Any) -> dict[str, Any]:
        return {
            "build": report_build_to_payload(build),
            "report": renderable_report_from_build(build),
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/internal/report-build-tools/{tool_name}")
    def invoke_internal_report_build_tool(
        tool_name: str,
        request: Request,
        payload: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        if tool_name not in REPORT_BUILD_TOOL_NAMES:
            raise HTTPException(
                status_code=404,
                detail="report_build_tool_not_found",
            )
        authorization = str(
            request.headers.get("Authorization") or ""
        )
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=401,
                detail="report_tool_token_required",
            )
        try:
            context = configured_report_tool_registry.resolve(
                token.strip()
            )
        except ReportToolTokenError as error:
            raise HTTPException(
                status_code=401,
                detail=str(error),
            ) from error
        model_type = report_build_body_models[tool_name]
        try:
            body = model_type.model_validate(payload)
        except PydanticValidationError as error:
            failed_result = (
                configured_report_build_service
                .record_argument_validation_failure(
                    tool_name,
                    payload,
                    context,
                    error.errors(),
                )
            )
            if (
                failed_result is not None
                and isinstance(
                    failed_result.get("revision"),
                    int,
                )
            ):
                configured_report_tool_registry.record_report_mutation_result(
                    token.strip(),
                    tool_name,
                    retryable=bool(
                        failed_result.get("retryable", True)
                    ),
                    failed=True,
                )
                return failed_result
            raise HTTPException(
                status_code=422,
                detail=error.errors(),
            ) from error
        result = configured_report_build_service.invoke(
            tool_name,
            body.model_dump(),
            context,
        )
        # Successful updates and retryable persisted validation failures
        # advance the build revision and open a fresh correction window.
        # A third failed attempt exhausts that window immediately;
        # access/not-found errors have no revision and leave it unchanged.
        if isinstance(result.get("revision"), int):
            configured_report_tool_registry.record_report_mutation_result(
                token.strip(),
                tool_name,
                retryable=bool(result.get("retryable", True)),
                failed=result.get("ok") is False,
            )
        return result

    @app.get("/api/report-builds/{build_id}")
    def get_report_build(
        build_id: str,
        request: Request,
    ) -> dict[str, Any]:
        return _report_build_response(
            _require_report_build(
                build_id,
                _principal_from_request(request),
            )
        )

    @app.get(
        "/api/analysis/sessions/{session_id}/report-builds/active"
    )
    def get_active_report_build(
        session_id: str,
        request: Request,
    ) -> dict[str, Any]:
        principal = _principal_from_request(request)
        try:
            view = _require_principal_view(session_id, principal)
        except SessionNotFoundError:
            raise HTTPException(
                status_code=404,
                detail="analysis_session_not_found",
            )
        owner_id = (
            None
            if principal is not None and "admin" in principal.roles
            else (
                principal.user_id
                if principal is not None
                else view.session.userId
            )
        )
        build = configured_report_build_store.get_active_for_session(
            view.session.id,
            owner_id=owner_id,
        )
        if build is None:
            return {"build": None, "report": None}
        return _report_build_response(build)

    @app.post(
        "/api/report-builds/{build_id}/queries/{query_id}"
    )
    def execute_report_build_query(
        build_id: str,
        query_id: str,
        request: Request,
        body: ReportQueryBody = Body(...),
    ) -> dict[str, Any]:
        build = _require_report_build(
            build_id,
            _principal_from_request(request),
        )
        source = SimpleNamespace(
            queries=build.content.get("queries", {})
        )
        try:
            return configured_report_query_service.execute(
                source,
                query_id,
                filters=body.filters,
                page=body.page,
                page_size=body.pageSize,
                sort=(
                    body.sort.model_dump()
                    if body.sort is not None
                    else None
                ),
                column_filters=body.columnFilters,
            )
        except ReportQueryNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="report_query_not_found",
            ) from exc
        except ReportFilterError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc
        except ReportQueryExecutionError as exc:
            LOGGER.exception(
                "report_build_query_failed",
                extra={
                    "build_id": build_id,
                    "query_id": query_id,
                },
            )
            raise HTTPException(
                status_code=500,
                detail="report_query_failed",
            ) from exc

    @app.get("/api/runtime/status")
    def runtime_status() -> dict[str, Any]:
        return check_runtime_env()

    @app.get("/api/system/mcp/servers")
    def list_mcp_servers(request: Request) -> dict[str, Any]:
        _require_system_api_token(request)
        if mcp_registry is None:
            try:
                return {"servers": build_mcp_registry().list()}
            except Exception:
                return codex_mcp_server_status_payload()
        return {"servers": mcp_registry.list()}

    @app.post("/api/system/mcp/servers", status_code=201)
    def create_mcp_server(
        request: Request,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        _require_system_api_token(request)
        try:
            server = _managed_mcp_registry().create(
                body,
                actor_id=_mcp_actor_id(request),
            )
        except McpRegistryError as error:
            _raise_mcp_http_error(error)
        return {"server": server}

    @app.patch("/api/system/mcp/servers/{server_name}")
    def update_mcp_server(
        server_name: str,
        request: Request,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        _require_system_api_token(request)
        registry = _managed_mcp_registry()
        actor_id = _mcp_actor_id(request)
        try:
            if set(body.keys()) == {"enabled"}:
                enabled = body.get("enabled")
                if not isinstance(enabled, bool):
                    raise McpRegistryError("enabled must be a boolean.")
                server = registry.set_enabled(
                    server_name,
                    enabled,
                    actor_id=actor_id,
                )
                if server_name == "GenBI_report":
                    set_mcp_enabled_override(
                        server_name,
                        enabled,
                        actor_id=actor_id,
                    )
            else:
                server = registry.update(
                    server_name,
                    body,
                    actor_id=actor_id,
                )
        except McpRegistryError as error:
            _raise_mcp_http_error(error)
        return {"server": server}

    @app.delete("/api/system/mcp/servers/{server_name}", status_code=204)
    def delete_mcp_server(server_name: str, request: Request) -> Response:
        _require_system_api_token(request)
        try:
            _managed_mcp_registry().delete(server_name)
        except McpRegistryError as error:
            _raise_mcp_http_error(error)
        return Response(status_code=204)

    @app.get("/api/system/mcp/servers/{server_name}/secrets")
    def reveal_mcp_server_secrets(
        server_name: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_system_api_token(request)
        try:
            secrets = _managed_mcp_registry().reveal_secrets(server_name)
        except McpRegistryError as error:
            _raise_mcp_http_error(error)
        return {"secrets": secrets}

    @app.post("/api/system/mcp/servers/{server_name}/test")
    def test_mcp_server(server_name: str, request: Request) -> dict[str, Any]:
        _require_system_api_token(request)
        registry: McpRegistry | None = mcp_registry
        if registry is None:
            try:
                registry = build_mcp_registry()
            except Exception:
                registry = None
        if registry is not None:
            try:
                result = probe_mcp_server(registry.runtime_server(server_name))
                registry.record_test_result(
                    server_name,
                    result,
                    actor_id=_mcp_actor_id(request),
                )
                return result
            except McpRegistryError as error:
                _raise_mcp_http_error(error)
        return test_codex_mcp_server(server_name)

    @app.get("/api/system/model-connections")
    def list_model_connections(request: Request) -> dict[str, Any]:
        _require_model_management_token(request)
        return {"connections": _managed_model_connection_registry().list()}

    @app.post("/api/system/model-connections", status_code=201)
    def create_model_connection(
        request: Request,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        _require_model_management_token(request)
        try:
            connection = _managed_model_connection_registry().create(
                body,
                actor_id=_mcp_actor_id(request),
            )
        except ModelConnectionError as error:
            _raise_model_connection_http_error(error)
        return {"connection": connection}

    @app.patch("/api/system/model-connections/{connection_name}")
    def update_model_connection(
        connection_name: str,
        request: Request,
        body: dict[str, Any] = Body(...),
    ) -> dict[str, Any]:
        _require_model_management_token(request)
        try:
            connection = _managed_model_connection_registry().update(
                connection_name,
                body,
                actor_id=_mcp_actor_id(request),
            )
        except ModelConnectionError as error:
            _raise_model_connection_http_error(error)
        return {"connection": connection}

    @app.delete(
        "/api/system/model-connections/{connection_name}",
        status_code=204,
    )
    def delete_model_connection(
        connection_name: str,
        request: Request,
    ) -> Response:
        _require_model_management_token(request)
        try:
            _managed_model_connection_registry().delete(connection_name)
        except ModelConnectionError as error:
            _raise_model_connection_http_error(error)
        return Response(status_code=204)

    @app.get("/api/system/model-connections/{connection_name}/secret")
    def reveal_model_connection_secret(
        connection_name: str,
        request: Request,
    ) -> Response:
        _require_model_management_token(request)
        try:
            api_key = _managed_model_connection_registry().reveal_secret(
                connection_name
            )
        except ModelConnectionError as error:
            _raise_model_connection_http_error(error)
        return Response(
            content=json.dumps({"apiKey": api_key}, ensure_ascii=False),
            status_code=200,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
            },
        )

    @app.post("/api/system/model-connections/{connection_name}/test")
    def test_model_connection(
        connection_name: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_model_management_token(request)
        registry = _managed_model_connection_registry()
        try:
            result = probe_model_connection(
                registry.runtime_connection(connection_name)
            )
            registry.record_test_result(
                connection_name,
                result,
                actor_id=_mcp_actor_id(request),
            )
        except ModelConnectionError as error:
            _raise_model_connection_http_error(error)
        return result

    @app.post("/api/system/model-connections/{connection_name}/default")
    def set_default_model_connection(
        connection_name: str,
        request: Request,
    ) -> dict[str, Any]:
        _require_model_management_token(request)
        try:
            connection = _managed_model_connection_registry().set_default(
                connection_name,
                actor_id=_mcp_actor_id(request),
            )
        except ModelConnectionError as error:
            _raise_model_connection_http_error(error)
        return {"connection": connection}

    @app.get("/api/system/runtime/policy")
    def system_runtime_policy(request: Request) -> dict[str, Any]:
        _require_system_api_token(request)
        managed = runtime_policy_overrides()
        resolve_model_connection = getattr(
            configured_analysis_runtime,
            "_resolve_model_connection",
            None,
        )
        try:
            model_connection = (
                resolve_model_connection()
                if callable(resolve_model_connection)
                else None
            )
        except Exception:
            LOGGER.exception("runtime_model_connection_status_failed")
            model_connection = None
        default_tools = os.getenv("GENBI_CODEX_DEFAULT_TOOLS_ENABLED", "true").strip().lower()
        return {
            "provider": str(
                getattr(model_connection, "provider_type", "")
                or getattr(configured_analysis_runtime, "provider", "")
                or "local"
            ),
            "enabled": bool(getattr(configured_analysis_runtime, "enabled", False)),
            "model": str(
                getattr(model_connection, "model", "")
                or getattr(configured_analysis_runtime, "model", "")
                or ""
            ),
            "connectionName": (
                str(getattr(model_connection, "name", "") or "") or None
            ),
            "connectionSource": (
                str(getattr(model_connection, "source", "") or "") or None
            ),
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

    def _codex_minimax_response(body: dict[str, Any]) -> Any:
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

    @app.post(
        "/api/codex-minimax/v1/executions/{execution_id}/responses"
    )
    async def scoped_codex_minimax_responses(
        execution_id: str,
        body: dict[str, Any] = Body(...),
    ) -> Any:
        if not configured_report_tool_registry.begin_model_round(
            execution_id
        ):
            status, headers, payload = (
                report_build_no_progress_response()
            )
            return Response(
                content=payload,
                status_code=status,
                media_type=headers["content-type"],
            )
        return _codex_minimax_response(body)

    @app.post("/api/codex-minimax/v1/responses")
    async def codex_minimax_responses(
        body: dict[str, Any] = Body(...),
    ) -> Any:
        return _codex_minimax_response(body)

    def _managed_codex_minimax_response(
        connection_name: str,
        request: Request,
        body: dict[str, Any],
        *,
        execution_id: str | None = None,
    ) -> Any:
        authorization = str(request.headers.get("authorization") or "")
        scheme, _, supplied_api_key = authorization.partition(" ")
        if scheme.lower() != "bearer" or not supplied_api_key:
            raise HTTPException(
                status_code=401,
                detail="model_connection_api_key_required",
            )
        try:
            registry = _managed_model_connection_registry()
            public_connection = registry.get(connection_name)
            connection = registry.runtime_connection(connection_name)
        except ModelConnectionError as error:
            _raise_model_connection_http_error(error)
        if (
            connection.provider_type != "minimax"
            or not bool(public_connection.get("enabled"))
        ):
            raise HTTPException(
                status_code=409,
                detail="model_connection_is_not_an_enabled_minimax_connection",
            )
        if not hmac.compare_digest(
            supplied_api_key,
            connection.api_key,
        ):
            raise HTTPException(
                status_code=401,
                detail="model_connection_api_key_invalid",
            )
        if (
            execution_id is not None
            and not configured_report_tool_registry.begin_model_round(
                execution_id
            )
        ):
            status, headers, payload = (
                report_build_no_progress_response()
            )
            return Response(
                content=payload,
                status_code=status,
                media_type=headers["content-type"],
            )
        raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        status, headers, payload = proxy_minimax_response(
            raw_body,
            stream=bool(body.get("stream")),
            upstream_base_url=connection.base_url,
            upstream_api_key=supplied_api_key,
        )
        media_type = headers.get("content-type", "application/json")
        if bool(body.get("stream")) and not isinstance(payload, bytes):
            return StreamingResponse(
                payload,
                status_code=status,
                media_type=media_type,
            )
        return Response(
            content=(
                payload
                if isinstance(payload, bytes)
                else b"".join(payload)
            ),
            status_code=status,
            media_type=media_type,
        )

    @app.post("/api/codex-minimax/{connection_name}/v1/responses")
    async def managed_codex_minimax_responses(
        connection_name: str,
        request: Request,
        body: dict[str, Any] = Body(...),
    ) -> Any:
        return _managed_codex_minimax_response(
            connection_name,
            request,
            body,
        )

    @app.post(
        "/api/codex-minimax/{connection_name}/v1/"
        "executions/{execution_id}/responses"
    )
    async def scoped_managed_codex_minimax_responses(
        connection_name: str,
        execution_id: str,
        request: Request,
        body: dict[str, Any] = Body(...),
    ) -> Any:
        return _managed_codex_minimax_response(
            connection_name,
            request,
            body,
            execution_id=execution_id,
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

    def report_response_payload(report: Any) -> dict[str, Any]:
        source_session_id = None
        if report.turnId:
            turn = configured_codex_projection_store.get_turn_by_id(
                report.turnId
            )
            source_session_id = turn.sessionId if turn else None
        return report_to_payload(
            report,
            source_session_id=source_session_id,
        )

    @app.get("/api/reports")
    def list_reports(
        owner_id: str | None = None,
        session_id: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        turn_ids = None
        if session_id:
            turn_ids = {
                turn.id
                for turn in configured_codex_projection_store.list_turns(
                    session_id
                )
            }
        reports = configured_report_store.list_reports(
            owner_id=owner_id,
            turn_ids=turn_ids,
            limit=limit,
        )
        return {
            "reports": [
                report_response_payload(report)
                for report in reports
            ]
        }

    @app.get("/api/system/context/skills")
    def system_context_skills(request: Request) -> dict[str, Any]:
        _require_system_api_token(request)
        codex_home = getattr(configured_analysis_runtime, "codex_home", None)
        return {"skills": list_installed_skills(codex_home)}

    @app.get("/api/report-center")
    def list_report_center(
        user_id: str = Query(min_length=1),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        center = configured_report_store.list_report_center(
            user_id=user_id,
            limit=limit,
        )
        return {
            "mine": [
                {
                    "report": report_response_payload(
                        configured_report_store.get_report(
                            item["report"]["id"]
                        )
                    )
                }
                for item in center["mine"]
            ],
            "sharedWithMe": [
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key != "report"
                    },
                    "report": report_response_payload(
                        configured_report_store.get_report(
                            item["report"]["id"]
                        )
                    ),
                }
                for item in center["sharedWithMe"]
            ],
            "examples": [
                {
                    "report": report_response_payload(
                        configured_report_store.get_report(
                            item["report"]["id"]
                        )
                    )
                }
                for item in center["examples"]
            ],
        }

    @app.put("/api/internal/reports/{report_id}/example")
    def set_report_example(
        report_id: str,
        request: Request,
        body: ReportExampleBody = Body(...),
    ) -> dict[str, Any]:
        _require_system_api_token(request)
        report = configured_report_store.set_report_example(
            report_id,
            owner_id=body.ownerId,
            is_example=body.isExample,
        )
        if report is None:
            raise HTTPException(status_code=404, detail="report_not_found")
        return {"report": report_response_payload(report)}

    @app.post("/api/reports", status_code=201)
    def create_report(
        body: ReportConfigBody = Body(...),
    ) -> dict[str, Any]:
        payload = body.model_dump()
        owner_id = payload.pop("ownerId")
        try:
            report = configured_report_store.create_report(
                payload,
                owner_id=owner_id,
            )
        except ReportValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"path": exc.path, "message": exc.message},
            ) from exc
        return {"report": report_response_payload(report)}

    @app.get("/api/reports/{report_id}")
    def get_report(report_id: str) -> dict[str, Any]:
        result = configured_report_store.get_report(report_id)
        if not result:
            raise HTTPException(status_code=404, detail="report_not_found")
        return {"report": report_response_payload(result)}

    @app.put("/api/reports/{report_id}")
    def update_report(
        report_id: str,
        body: ReportConfigBody = Body(...),
    ) -> dict[str, Any]:
        payload = body.model_dump()
        owner_id = payload.pop("ownerId")
        try:
            report = configured_report_store.update_report(
                report_id,
                payload,
                owner_id=owner_id,
            )
        except ReportValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"path": exc.path, "message": exc.message},
            ) from exc
        if not report:
            raise HTTPException(status_code=404, detail="report_not_found")
        return {"report": report_response_payload(report)}

    @app.delete("/api/reports/{report_id}")
    def delete_report(
        report_id: str,
        owner_id: str = Query(min_length=1),
    ) -> dict[str, Any]:
        deleted = configured_report_store.delete_report(
            report_id,
            owner_id=owner_id,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="report_not_found")
        return {"deleted": True, "report_id": report_id}

    @app.post("/api/reports/{report_id}/shares")
    def share_report(
        report_id: str,
        body: ReportShareBody = Body(...),
    ) -> dict[str, Any]:
        share = configured_report_store.share_report(
            report_id,
            owner_id=body.ownerId,
            recipient_user_id=body.recipientUserId,
            permission=body.permission,
        )
        if not share:
            raise HTTPException(status_code=404, detail="report_not_found")
        return {"share": share_to_payload(share)}

    @app.delete("/api/reports/{report_id}/shares/{recipient_user_id}")
    def revoke_report_share(
        report_id: str,
        recipient_user_id: str,
        owner_id: str = Query(min_length=1),
    ) -> dict[str, Any]:
        revoked = configured_report_store.revoke_report_share(
            report_id,
            owner_id=owner_id,
            recipient_user_id=recipient_user_id,
        )
        if not revoked:
            raise HTTPException(status_code=404, detail="report_share_not_found")
        return {"revoked": True, "report_id": report_id, "recipient_user_id": recipient_user_id}

    @app.post("/api/reports/{report_id}/queries/{query_id}")
    def execute_report_query(
        report_id: str,
        query_id: str,
        body: ReportQueryBody = Body(...),
    ) -> dict[str, Any]:
        report = configured_report_store.get_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="report_not_found")
        try:
            return configured_report_query_service.execute(
                report,
                query_id,
                filters=body.filters,
                page=body.page,
                page_size=body.pageSize,
                sort=body.sort.model_dump() if body.sort else None,
                column_filters=body.columnFilters,
            )
        except ReportQueryNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="report_query_not_found",
            ) from exc
        except ReportFilterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ReportQueryExecutionError as exc:
            LOGGER.exception(
                "report_query_failed",
                extra={"report_id": report_id, "query_id": query_id},
            )
            raise HTTPException(
                status_code=500,
                detail="report_query_failed",
            ) from exc

    @app.post("/api/reports/{report_id}/tables/{table_id}/export")
    def export_report_table(
        report_id: str,
        table_id: str,
        body: ReportTableExportBody = Body(...),
    ) -> Any:
        report = configured_report_store.get_report(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="report_not_found")
        try:
            exported = create_report_excel_export(
                report,
                table_id,
                configured_report_query_service,
                filters=body.filters,
                sort=body.sort.model_dump() if body.sort else None,
                column_filters=body.columnFilters,
            )
        except ReportTableNotExportable as exc:
            raise HTTPException(
                status_code=404,
                detail="report_table_not_exportable",
            ) from exc
        except ReportQueryNotFound as exc:
            raise HTTPException(
                status_code=404,
                detail="report_query_not_found",
            ) from exc
        except ReportFilterError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ReportExportLimitExceeded as exc:
            raise HTTPException(
                status_code=413,
                detail="report_export_too_large",
            ) from exc
        except ReportQueryExecutionError as exc:
            LOGGER.exception(
                "report_export_failed",
                extra={"report_id": report_id, "table_id": table_id},
            )
            raise HTTPException(
                status_code=500,
                detail="report_export_failed",
            ) from exc
        return FileResponse(
            path=exported.path,
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            filename=exported.filename,
            background=BackgroundTask(remove_export_file, exported.path),
        )

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


def _build_default_report_store() -> Any:
    if postgres_persistence_enabled():
        return build_postgres_report_store()
    return ReportStore()


def _build_default_report_build_store(
    report_store: Any,
) -> Any:
    if postgres_persistence_enabled():
        return build_postgres_report_build_store()
    return ReportBuildStore(report_store=report_store)


def main() -> None:
    app = create_app()
    print(json.dumps({"app": app.title}, ensure_ascii=False))


if __name__ == "__main__":
    main()

