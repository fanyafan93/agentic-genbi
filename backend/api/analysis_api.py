import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from backend.config import check_runtime_env, load_project_env
from backend.analysis.report_compiler import compile_interactive_report
from backend.analysis.asset_store import AnalysisAssetReopenContext, AnalysisAssetStore
from backend.analysis.interactive_report_store import InteractiveReportStore, InteractiveReportVersionConflict
from backend.business_semantics.finereport_reports import FineReportReportRepository
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime
from backend.harness.codex_mcp_config import codex_mcp_server_status_payload, test_codex_mcp_server
from backend.harness.events import AgentEvent
from backend.harness.minimax_codex_adapter import proxy_minimax_response
from backend.harness.thread_store import ThreadStore
from backend.persistence.postgres_stores import (
    build_postgres_analysis_asset_store,
    build_postgres_stores,
    build_postgres_thread_store,
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
    thread_store: ThreadStore | None = None,
    finereport_repository: FineReportReportRepository | None = None,
) -> Any:
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
    configured_thread_store = thread_store or _build_default_thread_store()
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
        threads = configured_thread_store.list_threads(limit=limit, product_kind="analysis_task")
        return {"threads": [_with_latest_thread_question(configured_thread_store, item) for item in threads]}

    @app.post("/api/analysis/threads/turns")
    async def create_analysis_thread_turn(body: AnalysisTurnBody = Body(...)) -> dict[str, Any]:
        thread_id = body.thread_id or body.conversation_id or _new_analysis_thread_id()
        return await _create_analysis_turn_payload(configured_analysis_runtime, configured_thread_store, configured_interactive_report_store, body, thread_id=thread_id)

    @app.post("/api/analysis/threads/turns/stream")
    def stream_new_analysis_thread_turn(body: AnalysisTurnBody = Body(...)) -> StreamingResponse:
        thread_id = body.thread_id or body.conversation_id or _new_analysis_thread_id()
        return _stream_analysis_turn_response(configured_analysis_runtime, configured_thread_store, configured_interactive_report_store, body, thread_id=thread_id)

    @app.post("/api/analysis/threads/{thread_id}/turns")
    async def create_existing_analysis_thread_turn(thread_id: str, body: AnalysisTurnBody = Body(...)) -> dict[str, Any]:
        return await _create_analysis_turn_payload(configured_analysis_runtime, configured_thread_store, configured_interactive_report_store, body, thread_id=thread_id)

    @app.post("/api/analysis/threads/{thread_id}/turns/stream")
    def stream_existing_analysis_thread_turn(thread_id: str, body: AnalysisTurnBody = Body(...)) -> StreamingResponse:
        return _stream_analysis_turn_response(configured_analysis_runtime, configured_thread_store, configured_interactive_report_store, body, thread_id=thread_id)

    @app.get("/api/analysis/threads/{thread_id}")
    def get_analysis_thread(thread_id: str) -> dict[str, Any]:
        thread = configured_thread_store.get_thread(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="analysis_thread_not_found")
        return _repair_thread_detail_text(thread)

    @app.delete("/api/analysis/threads/{thread_id}")
    def delete_analysis_thread(thread_id: str) -> dict[str, Any]:
        deleted = configured_thread_store.delete_thread(thread_id, product_kind="analysis_task")
        if not deleted:
            raise HTTPException(status_code=404, detail="analysis_thread_not_found")
        return {"deleted": True, "thread_id": thread_id}

    @app.get("/api/analysis/threads/{thread_id}/turns/{turn_id}")
    def get_analysis_thread_turn(thread_id: str, turn_id: str) -> dict[str, Any]:
        turn = configured_thread_store.get_turn(thread_id, turn_id)
        if not turn:
            raise HTTPException(status_code=404, detail="analysis_turn_not_found")
        return turn

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
        return {"reports": [asdict(report) for report in reports]}

    @app.post("/api/analysis/reports")
    def save_interactive_report(body: InteractiveReportBody = Body(...)) -> dict[str, Any]:
        try:
            report, version = configured_interactive_report_store.save_report(body.model_dump())
        except InteractiveReportVersionConflict as exc:
            raise HTTPException(status_code=409, detail="interactive_report_version_conflict") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"report": asdict(report), "version": asdict(version)}

    @app.get("/api/analysis/reports/{report_id}")
    def get_interactive_report(report_id: str) -> dict[str, Any]:
        result = configured_interactive_report_store.get_report(report_id)
        if not result:
            raise HTTPException(status_code=404, detail="interactive_report_not_found")
        report, version = result
        return {"report": asdict(report), "version": asdict(version)}

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
    thread_store: ThreadStore,
    interactive_report_store: Any,
    body: Any,
    *,
    thread_id: str,
) -> dict[str, Any]:
    request = _analysis_request_from_body(body, thread_id=thread_id)
    turn_id = _new_analysis_turn_id()
    events = [
        event
        async for event in _astream_runtime_events(
            analysis_runtime,
            thread_store,
            interactive_report_store,
            request,
            thread_id=thread_id,
            turn_id=turn_id,
        )
    ]
    _save_analysis_turn(thread_store, request, thread_id=thread_id, turn_id=turn_id, events=events)
    return {
        "thread_id": thread_id,
        "turn_id": turn_id,
        "events_url": f"/api/analysis/threads/{thread_id}/turns/{turn_id}",
        "events": [asdict(event) for event in events],
    }


def _first_event_payload_value(events: list[Any], key: str) -> str | None:
    for event in events:
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict) and payload.get(key):
            return str(payload[key])
    return None


def _stream_analysis_turn_response(
    analysis_runtime: CodexSdkAnalysisRuntime,
    thread_store: ThreadStore,
    interactive_report_store: Any,
    body: Any,
    *,
    thread_id: str,
) -> Any:
    from fastapi.responses import StreamingResponse

    request = _analysis_request_from_body(body, thread_id=thread_id)
    turn_id = _new_analysis_turn_id()

    async def event_stream() -> Any:
        events: list[AgentEvent] = []
        try:
            async for event in _astream_runtime_events(analysis_runtime, thread_store, interactive_report_store, request, thread_id=thread_id, turn_id=turn_id):
                events.append(event)
                yield event.to_sse()
        finally:
            if events:
                _save_analysis_turn(thread_store, request, thread_id=thread_id, turn_id=turn_id, events=events)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def _astream_runtime_events(
    analysis_runtime: CodexSdkAnalysisRuntime,
    thread_store: ThreadStore,
    interactive_report_store: Any,
    request: AnalysisTurnRequest,
    *,
    thread_id: str,
    turn_id: str,
) -> Any:
    saw_terminal_event = False
    async for event in analysis_runtime.async_stream(
        request.question.strip(),
        context=_runtime_context(thread_store, request, thread_id=thread_id, turn_id=turn_id),
    ):
        enriched = _enrich_analysis_event(event, thread_id=thread_id, turn_id=turn_id, question=request.question.strip())
        if enriched.type == "turn/completed":
            saw_terminal_event = True
        yield enriched
        artifact_event = _interactive_report_artifact_event(enriched, thread_id=thread_id, turn_id=turn_id, interactive_report_store=interactive_report_store)
        if artifact_event:
            yield artifact_event
    if not saw_terminal_event:
        yield _missing_terminal_event(thread_id=thread_id, turn_id=turn_id)


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
    source = dict(report.get("source") or {})
    source["threadId"] = thread_id
    source["turnId"] = turn_id
    report["source"] = source
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


def _runtime_context(thread_store: ThreadStore, request: AnalysisTurnRequest, *, thread_id: str, turn_id: str) -> dict[str, Any]:
    metadata = dict(request.metadata or {})
    codex_thread_id = (
        metadata.get("codex_thread_id")
        or metadata.get("codexThreadId")
        or thread_store.get_runtime_thread_id(thread_id, "openai-codex")
    )
    return {
        "genbi_thread_id": thread_id,
        "genbi_turn_id": turn_id,
        "turn_id": turn_id,
        "codex_thread_id": codex_thread_id,
    }


def _save_analysis_turn(
    thread_store: ThreadStore,
    request: AnalysisTurnRequest,
    *,
    thread_id: str,
    turn_id: str,
    events: list[AgentEvent],
) -> None:
    metadata = {**(request.metadata or {}), "domain": "analysis_task", "thread_id": thread_id, "turn_id": turn_id}
    codex_thread_id = _last_event_payload_value(events, "codex_thread_id")
    codex_turn_id = _last_event_payload_value(events, "codex_turn_id")
    if codex_thread_id:
        metadata["codex_thread_id"] = codex_thread_id
    if codex_turn_id:
        metadata["codex_turn_id"] = codex_turn_id
    thread_store.save_turn(
        thread_id=thread_id,
        turn_id=turn_id,
        question=request.question.strip(),
        input_kind=request.turn_kind,  # type: ignore[arg-type]
        product_kind="analysis_task",
        user_id=request.user_id,
        events=events,
        metadata=metadata,
    )


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


def _new_analysis_thread_id() -> str:
    return f"analysis_thread_{uuid4().hex[:12]}"


def _new_analysis_turn_id() -> str:
    return f"analysis_turn_{uuid4().hex[:12]}"


def build_default_analysis_runtime() -> CodexSdkAnalysisRuntime:
    load_project_env()
    analysis_runtime = os.getenv("GENBI_ANALYSIS_RUNTIME", "codex").lower()
    if analysis_runtime == "codex":
        return CodexSdkAnalysisRuntime.from_env()
    elif analysis_runtime not in {"", "local", "mock"}:
        raise RuntimeError("GENBI_ANALYSIS_RUNTIME only supports codex, local, or mock.")
    return CodexSdkAnalysisRuntime.disabled()


def _with_latest_thread_question(thread_store: ThreadStore, thread: dict[str, Any]) -> dict[str, Any]:
    detail = thread_store.get_thread(str(thread.get("id", "")))
    turns = list((detail or {}).get("turns") or [])
    latest_turn = turns[-1] if turns else None
    latest_question = str(latest_turn.get("question", "")).strip() if isinstance(latest_turn, dict) else ""
    return {**thread, "title": _repair_text_encoding(thread.get("title")), "latestQuestion": _repair_text_encoding(latest_question) or None}


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


def _build_default_thread_store() -> ThreadStore:
    if postgres_persistence_enabled():
        try:
            return build_postgres_thread_store()
        except Exception:
            if os.getenv("GENBI_PERSISTENCE", "").strip():
                raise
    return ThreadStore()


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
