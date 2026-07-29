import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.config import check_runtime_env, load_project_env
from backend.exploration.agent_runner import LLMAgentRunner
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_service import ExplorationRunRequest, ExplorationRunService
from backend.exploration.run_trace_store import RunTraceStore
from backend.persistence.postgres_stores import build_postgres_stores, postgres_persistence_enabled
from backend.resource_library.database_tools import DatabaseConfig, ReadonlyDatabaseTools
from backend.resource_library.indexer import ResourceIndexer
from backend.resource_library.inspector import inspect_index
from backend.resource_library.knowledge_store import KnowledgeStore
from backend.resource_library.tools import (
    DEFAULT_EXCERPT_MAX_BYTES,
    DEFAULT_EXCERPT_MAX_LINES,
    DEFAULT_INDEX_PATH,
    DEFAULT_SUMMARY_PATH,
    ResourceLibrary,
)


def create_app(service: ExplorationRunService | None = None, knowledge_store: KnowledgeStore | None = None) -> Any:
    load_project_env()
    try:
        from fastapi import Body, FastAPI, HTTPException, Query
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import StreamingResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError("Install FastAPI dependencies from backend/requirements.txt to start the API.") from exc

    class ExplorationRunBody(BaseModel):
        question: str = Field(min_length=1)
        conversation_id: str | None = None
        user_id: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)

    class ResourceReindexBody(BaseModel):
        root: str | None = None

    class KnowledgeBody(BaseModel):
        title: str = Field(min_length=1)
        question: str = Field(min_length=1)
        conclusion: str = Field(min_length=1)
        scope: str = Field(min_length=1)
        verification: str = Field(min_length=1)
        evidence_refs: list[str] = Field(min_length=1)
        run_id: str | None = None
        metadata: dict[str, Any] = Field(default_factory=dict)

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
    if service:
        run_service = service
        configured_knowledge_store = knowledge_store or KnowledgeStore()
    else:
        run_service, configured_knowledge_store = build_default_service_with_stores()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/runtime/status")
    def runtime_status() -> dict[str, Any]:
        return check_runtime_env()

    @app.post("/api/explorations/conversations")
    def create_exploration_conversation_turn(body: ExplorationRunBody = Body(...)) -> dict[str, Any]:
        conversation_id = body.conversation_id or _new_conversation_id()
        result = _create_exploration_run_payload(run_service, body, conversation_id=conversation_id)
        return {
            "conversation_id": conversation_id,
            "latest_run_id": result["run_id"],
            "events_url": result["events_url"],
            "events": result["events"],
        }

    @app.get("/api/explorations/conversations")
    def list_exploration_conversations(limit: int = 50, user_id: str | None = None) -> dict[str, Any]:
        return {"conversations": _list_root_run_traces(run_service, limit=limit, user_id=user_id)}

    @app.get("/api/explorations/conversations/{conversation_id}")
    def get_exploration_conversation(conversation_id: str) -> dict[str, Any]:
        run_ids = _conversation_run_ids(run_service, conversation_id)
        if not run_ids:
            raise HTTPException(status_code=404, detail="exploration_conversation_not_found")
        events = _conversation_events(run_service, run_ids)
        trace = run_service.trace_store.get_trace(run_ids[0]) if run_service.trace_store else None
        return {
            "conversation_id": conversation_id,
            "latest_run_id": run_ids[-1],
            "run": asdict(trace) if trace else None,
            "events": [asdict(event) for event in events],
        }

    @app.delete("/api/explorations/conversations/{conversation_id}")
    def delete_exploration_conversation(conversation_id: str) -> dict[str, Any]:
        run_ids = _conversation_run_ids(run_service, conversation_id)
        if not run_ids:
            raise HTTPException(status_code=404, detail="exploration_conversation_not_found")
        trace_deleted = 0
        events_deleted = 0
        for run_id in run_ids:
            trace_deleted += run_service.trace_store.delete_trace(run_id) if run_service.trace_store else 0
            events_deleted += run_service.event_store.delete_events(run_id) if run_service.event_store else 0
        return {
            "conversation_id": conversation_id,
            "deleted": True,
            "run_ids": run_ids,
            "trace_deleted": trace_deleted,
            "events_deleted": events_deleted,
        }

    @app.post("/api/explorations/conversations/stream")
    def stream_exploration_conversation_turn(body: ExplorationRunBody = Body(...)) -> StreamingResponse:
        conversation_id = body.conversation_id or _new_conversation_id()
        request = ExplorationRunRequest(
            question=body.question,
            conversation_id=conversation_id,
            user_id=body.user_id,
            metadata=_conversation_metadata(body.metadata, conversation_id=conversation_id, is_root=not body.conversation_id),
        )

        async def event_stream() -> Any:
            async for event in run_service.astream_events(request):
                yield event.to_sse()

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/explorations/runs")
    def create_exploration_run(body: ExplorationRunBody = Body(...)) -> dict[str, Any]:
        return _create_exploration_run_payload(run_service, body)

    @app.get("/api/explorations/runs")
    def list_exploration_runs(limit: int = 50, include_continuations: bool = False, user_id: str | None = None) -> dict[str, Any]:
        if include_continuations:
            if not run_service.trace_store:
                return {"runs": []}
            runs = run_service.trace_store.list_traces(limit=limit)
            if user_id:
                runs = [item for item in runs if item.user_id == user_id]
            return {"runs": [asdict(item) for item in runs[:limit]]}
        return {"runs": _list_root_run_traces(run_service, limit=limit, user_id=user_id)}

    @app.get("/api/explorations/runs/{run_id}")
    def get_exploration_run(run_id: str) -> dict[str, Any]:
        trace = run_service.trace_store.get_trace(run_id) if run_service.trace_store else None
        events = run_service.event_store.list_events(run_id) if run_service.event_store else []
        if not trace and not events:
            raise HTTPException(status_code=404, detail="exploration_run_not_found")
        return {
            "run": asdict(trace) if trace else None,
            "events_url": f"/api/explorations/runs/{run_id}/events",
            "events": [asdict(event) for event in events],
        }

    @app.delete("/api/explorations/runs/{run_id}")
    def delete_exploration_run(run_id: str) -> dict[str, Any]:
        trace_deleted = run_service.trace_store.delete_trace(run_id) if run_service.trace_store else 0
        events_deleted = run_service.event_store.delete_events(run_id) if run_service.event_store else 0
        if trace_deleted == 0 and events_deleted == 0:
            raise HTTPException(status_code=404, detail="exploration_run_not_found")
        return {"run_id": run_id, "deleted": True, "trace_deleted": trace_deleted, "events_deleted": events_deleted}

    @app.get("/api/explorations/runs/{run_id}/events")
    def get_exploration_run_events(run_id: str) -> StreamingResponse:
        async def event_stream() -> Any:
            async for event in run_service.astream_run_events(run_id):
                yield event.to_sse()

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/explorations/runs/stream")
    def stream_exploration_run(body: ExplorationRunBody = Body(...)) -> StreamingResponse:
        request = ExplorationRunRequest(
            question=body.question,
            conversation_id=body.conversation_id,
            user_id=body.user_id,
            metadata=body.metadata,
        )

        async def event_stream() -> Any:
            async for event in run_service.astream_events(request):
                yield event.to_sse()

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/explorations/run-traces")
    def list_run_traces(limit: int = 50) -> dict[str, Any]:
        if not run_service.trace_store:
            return {"traces": []}
        return {"traces": [asdict(item) for item in run_service.trace_store.list_traces(limit=limit)]}

    @app.get("/api/explorations/run-traces/{run_id}")
    def get_run_trace(run_id: str) -> dict[str, Any]:
        if not run_service.trace_store:
            raise HTTPException(status_code=404, detail="run_trace_store_not_configured")
        trace = run_service.trace_store.get_trace(run_id)
        if not trace:
            raise HTTPException(status_code=404, detail="run_trace_not_found")
        return asdict(trace)

    @app.get("/api/resources/search")
    def search_resources(q: str = Query(min_length=1), resource_type: str | None = None, limit: int = 20) -> dict[str, Any]:
        if not run_service.resource_library:
            return {"results": []}
        results = run_service.resource_library.search_resources(q, resource_type=resource_type, limit=limit)
        return {"results": [asdict(item) for item in results]}

    @app.get("/api/resources/status")
    def resource_status() -> dict[str, Any]:
        library = run_service.resource_library
        index_path = library.index_path if library else Path(DEFAULT_INDEX_PATH)
        summary_path = library.summary_path if library else Path(DEFAULT_SUMMARY_PATH)
        index_exists = index_path.exists()
        summary_exists = summary_path.exists()
        resource_count = 0
        type_counts: dict[str, int] = {}
        root = None
        if library:
            payload = library.index
        elif index_exists:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            payload = None
        if payload:
            root = payload.get("root")
            resources = payload.get("resources", [])
            resource_count = len(resources)
            for resource in resources:
                resource_type = str(resource.get("type", "unknown"))
                type_counts[resource_type] = type_counts.get(resource_type, 0) + 1
        return {
            "indexed": bool(library and index_exists and summary_exists),
            "root": root,
            "index_path": str(index_path),
            "summary_path": str(summary_path),
            "resource_count": resource_count,
            "type_counts": type_counts,
            "index_modified_at": _modified_at(index_path) if index_exists else None,
            "summary_modified_at": _modified_at(summary_path) if summary_exists else None,
        }

    @app.get("/api/resources/{resource_id}/excerpt")
    def read_resource_excerpt(
        resource_id: str,
        section: str = Query(default="head", pattern="^(head|tail|match)$"),
        q: str | None = None,
        max_lines: int = Query(default=80, ge=1, le=DEFAULT_EXCERPT_MAX_LINES),
        max_bytes: int = Query(default=DEFAULT_EXCERPT_MAX_BYTES, ge=1024, le=DEFAULT_EXCERPT_MAX_BYTES),
    ) -> dict[str, Any]:
        if not run_service.resource_library:
            raise HTTPException(status_code=404, detail="resource_library_not_indexed")
        try:
            excerpt = run_service.resource_library.read_resource_excerpt(
                resource_id,
                section=section,
                query=q,
                max_lines=max_lines,
                max_bytes=max_bytes,
            )
            return asdict(excerpt)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/resources/{resource_id}")
    def inspect_resource(resource_id: str) -> dict[str, Any]:
        if not run_service.resource_library:
            raise HTTPException(status_code=404, detail="resource_library_not_indexed")
        try:
            return asdict(run_service.resource_library.inspect_resource(resource_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/resources/reindex")
    def reindex_resources(body: ResourceReindexBody = Body(default_factory=ResourceReindexBody)) -> dict[str, Any]:
        root = Path(body.root or os.getenv("GENBI_RESOURCE_LIBRARY_ROOT", "资源库"))
        if not root.exists():
            raise HTTPException(status_code=400, detail=f"resource_root_not_found: {root}")
        index = ResourceIndexer(root).write(DEFAULT_INDEX_PATH)
        summary = inspect_index(DEFAULT_INDEX_PATH, DEFAULT_SUMMARY_PATH)
        run_service.resource_library = ResourceLibrary(index_path=DEFAULT_INDEX_PATH, summary_path=DEFAULT_SUMMARY_PATH)
        return {
            "resource_count": len(index.resources),
            "summary_count": len(summary["summaries"]),
            "index_path": str(DEFAULT_INDEX_PATH),
            "summary_path": str(DEFAULT_SUMMARY_PATH),
        }

    @app.get("/api/knowledge")
    def list_knowledge(limit: int = 50) -> dict[str, Any]:
        return {"records": [asdict(item) for item in configured_knowledge_store.list_knowledge(limit=limit)]}

    @app.post("/api/knowledge")
    def save_knowledge(body: KnowledgeBody = Body(...)) -> dict[str, Any]:
        record = configured_knowledge_store.save_verified_knowledge(
            title=body.title,
            question=body.question,
            conclusion=body.conclusion,
            scope=body.scope,
            verification=body.verification,
            evidence_refs=body.evidence_refs,
            run_id=body.run_id,
            metadata=body.metadata,
        )
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


def _is_continuation_trace(trace: Any) -> bool:
    metadata = getattr(trace, "metadata", {}) or {}
    question = str(getattr(trace, "question", "") or "")
    conversation_id = str(getattr(trace, "conversation_id", "") or "")
    if metadata.get("conversation_root"):
        return False
    return bool(
        conversation_id
        or metadata.get("continuation_of")
        or question.startswith("这是同一个知识探索会话中的继续追问或补充")
    )


def _create_exploration_run_payload(run_service: ExplorationRunService, body: Any, *, conversation_id: str | None = None) -> dict[str, Any]:
    resolved_conversation_id = conversation_id if conversation_id is not None else body.conversation_id
    request = ExplorationRunRequest(
        question=body.question,
        conversation_id=resolved_conversation_id,
        user_id=body.user_id,
        metadata=_conversation_metadata(body.metadata, conversation_id=resolved_conversation_id, is_root=conversation_id is not None and not body.conversation_id),
    )
    run_id = run_service.create_run(request)
    events = list(run_service.stream_run_events(run_id))
    return {
        "run_id": run_id,
        "events_url": f"/api/explorations/runs/{run_id}/events",
        "events": [asdict(event) for event in events],
    }


def _list_root_run_traces(run_service: ExplorationRunService, *, limit: int, user_id: str | None = None) -> list[dict[str, Any]]:
    if not run_service.trace_store:
        return []
    runs = run_service.trace_store.list_traces(limit=max(limit * 5, limit))
    if user_id:
        runs = [item for item in runs if item.user_id == user_id]
    roots = [item for item in runs if not _is_continuation_trace(item)]
    return [asdict(item) for item in roots[:limit]]


def _conversation_run_ids(run_service: ExplorationRunService, conversation_id: str) -> list[str]:
    if not run_service.trace_store:
        return []
    run_ids = run_service.trace_store.list_conversation_run_ids(conversation_id, limit=50)
    if not run_ids and run_service.trace_store.get_trace(conversation_id):
        return [conversation_id]
    return run_ids


def _conversation_events(run_service: ExplorationRunService, run_ids: list[str]) -> list[Any]:
    if not run_service.event_store:
        return []
    events = []
    for run_id in run_ids:
        events.extend(run_service.event_store.list_events(run_id))
    return events


def _new_conversation_id() -> str:
    return f"conv_{uuid4().hex[:12]}"


def _conversation_metadata(metadata: dict[str, Any] | None, *, conversation_id: str | None, is_root: bool) -> dict[str, Any]:
    next_metadata = dict(metadata or {})
    if conversation_id and is_root:
        next_metadata.setdefault("conversation_root", True)
    return next_metadata


def _modified_at(path: Path) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()


def build_default_service() -> ExplorationRunService:
    service, _knowledge_store = build_default_service_with_stores()
    return service


def build_default_service_with_stores() -> tuple[ExplorationRunService, KnowledgeStore]:
    load_project_env()
    trace_store, event_store, knowledge_store = _build_default_persistence_stores()
    library = None
    if Path(DEFAULT_INDEX_PATH).exists() and Path(DEFAULT_SUMMARY_PATH).exists():
        library = ResourceLibrary(index_path=DEFAULT_INDEX_PATH, summary_path=DEFAULT_SUMMARY_PATH)
    db_tools = ReadonlyDatabaseTools(DatabaseConfig.from_env())
    agent_runner = None
    if os.getenv("GENBI_EXPLORATION_RUNTIME", "local").lower() in {"openai", "llm"}:
        agent_runner = LLMAgentRunner.from_env(
            resource_library=library,
            db_tools=db_tools,
            knowledge_store=knowledge_store,
        )
    service = ExplorationRunService(
        resource_library=library,
        db_tools=db_tools,
        agent_runner=agent_runner,
        trace_store=trace_store,
        event_store=event_store,
    )
    return service, knowledge_store


def _build_default_persistence_stores() -> tuple[RunTraceStore, RunEventStore, KnowledgeStore]:
    if postgres_persistence_enabled():
        try:
            return build_postgres_stores()
        except Exception:
            if os.getenv("GENBI_PERSISTENCE", "").strip():
                raise
    return RunTraceStore(), RunEventStore(), KnowledgeStore()


def main() -> None:
    app = create_app()
    print(json.dumps({"app": app.title}, ensure_ascii=False))


if __name__ == "__main__":
    main()
