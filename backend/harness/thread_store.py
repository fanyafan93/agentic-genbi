from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from backend.harness.events import AgentEvent


DEFAULT_THREAD_STORE_PATH = Path(".resource-index/thread-store.jsonl")

ThreadProductKind = Literal["analysis_task", "asset_continuation"]
TurnInputKind = Literal["start", "message", "reply"]


@dataclass(frozen=True)
class ThreadRecord:
    id: str
    productKind: ThreadProductKind
    title: str | None
    userId: str | None
    status: str
    createdAt: str
    updatedAt: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tenantId: str | None = None
    workspaceId: str | None = None
    codexThreadId: str | None = None


@dataclass(frozen=True)
class TurnRecord:
    id: str
    threadId: str
    inputKind: TurnInputKind
    question: str
    status: str
    createdAt: str
    updatedAt: str
    metadata: dict[str, Any] = field(default_factory=dict)
    codexThreadId: str | None = None
    codexTurnId: str | None = None


@dataclass(frozen=True)
class ItemRecord:
    id: str
    threadId: str
    turnId: str
    kind: str
    eventType: str
    payload: dict[str, Any]
    createdAt: str


@dataclass(frozen=True)
class CodexItemProjectionRecord:
    codexItemId: str
    codexThreadId: str | None
    codexTurnId: str | None
    itemType: str
    status: str
    payload: dict[str, Any]
    createdAt: str
    completedAt: str | None = None
    genbiThreadId: str | None = None
    genbiTurnId: str | None = None


class ThreadStore:
    def __init__(self, path: Path = DEFAULT_THREAD_STORE_PATH) -> None:
        self.path = path

    def save_turn(
        self,
        *,
        thread_id: str,
        turn_id: str,
        question: str,
        input_kind: TurnInputKind,
        product_kind: ThreadProductKind,
        user_id: str | None,
        events: list["AgentEvent"],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not thread_id.strip():
            raise ValueError("thread_id is required.")
        if not turn_id.strip():
            raise ValueError("turn_id is required.")
        state = self._read_state()
        existing_thread = state["threads"].get(thread_id)
        existing_turn = state["turns"].get(turn_id)
        started_at = events[0].created_at if events else None
        completed_at = events[-1].created_at if events else started_at
        status = _turn_status(events)
        thread_status = "needs_input" if any(_is_agent_question_event(event) for event in events) else status
        merged_metadata = {**(existing_thread.metadata if existing_thread else {}), **(metadata or {})}
        codex_thread_id = _thread_codex_thread_id(
            merged_metadata,
            existing_thread=existing_thread,
        )
        codex_turn_id = _latest_payload_value(events, "codex_turn_id") or _string_or_none(merged_metadata.get("codex_turn_id"))
        if codex_thread_id:
            merged_metadata["codex_thread_id"] = codex_thread_id
        if codex_turn_id:
            merged_metadata["codex_turn_id"] = codex_turn_id
        item_records = _items_from_events(events, thread_id=thread_id, turn_id=turn_id)
        codex_item_projections = _codex_item_projections_from_events(
            events,
            thread_id=thread_id,
            turn_id=turn_id,
            default_codex_thread_id=codex_thread_id,
        )
        title = _first_payload_value(events, "turn/started", "title") or (existing_thread.title if existing_thread else None)
        now = completed_at or started_at or ""

        thread = ThreadRecord(
            id=thread_id,
            productKind=product_kind,
            title=str(title) if title else None,
            userId=user_id,
            status=thread_status,
            createdAt=existing_thread.createdAt if existing_thread else (started_at or now),
            updatedAt=now,
            metadata=merged_metadata,
            tenantId=_thread_scope_value(merged_metadata, "tenant_id", "tenantId", existing_value=existing_thread.tenantId if existing_thread else None),
            workspaceId=_thread_scope_value(merged_metadata, "workspace_id", "workspaceId", existing_value=existing_thread.workspaceId if existing_thread else None),
            codexThreadId=codex_thread_id,
        )
        turn = TurnRecord(
            id=turn_id,
            threadId=thread_id,
            inputKind=input_kind,
            question=question,
            status=thread_status,
            createdAt=existing_turn.createdAt if existing_turn else (started_at or now),
            updatedAt=now,
            metadata={**(existing_turn.metadata if existing_turn else {}), **merged_metadata},
            codexThreadId=codex_thread_id or (existing_turn.codexThreadId if existing_turn else None),
            codexTurnId=codex_turn_id or (existing_turn.codexTurnId if existing_turn else None),
        )
        state["threads"][thread_id] = thread
        state["turns"][turn_id] = turn
        state["items"] = [item for item in state["items"] if not (item.threadId == thread_id and item.turnId == turn_id)]
        state["items"].extend(item_records)
        state["codex_item_projections"] = [
            item for item in state["codex_item_projections"] if not (item.genbiThreadId == thread_id and item.genbiTurnId == turn_id)
        ]
        state["codex_item_projections"].extend(codex_item_projections)
        self._write_state(state)
        return {
            "thread": asdict(thread),
            "turn": asdict(turn),
            "items": [asdict(item) for item in item_records],
            "codexItemProjections": [asdict(item) for item in codex_item_projections],
        }

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread:
            return None
        turns = [turn for turn in state["turns"].values() if turn.threadId == thread_id]
        turns.sort(key=lambda item: item.createdAt)
        items = [item for item in state["items"] if item.threadId == thread_id]
        items.sort(key=lambda item: item.createdAt)
        codex_item_projections = [item for item in state["codex_item_projections"] if item.genbiThreadId == thread_id]
        codex_item_projections.sort(key=lambda item: item.createdAt)
        return {
            "thread": asdict(thread),
            "turns": [asdict(item) for item in turns],
            "items": [asdict(item) for item in items],
            "codexItemProjections": [asdict(item) for item in codex_item_projections],
        }

    def get_turn(self, thread_id: str, turn_id: str) -> dict[str, Any] | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        turn = state["turns"].get(turn_id)
        if not thread or not turn or turn.threadId != thread_id:
            return None
        items = [item for item in state["items"] if item.turnId == turn_id and item.threadId == thread_id]
        items.sort(key=lambda item: item.createdAt)
        codex_item_projections = [
            item
            for item in state["codex_item_projections"]
            if item.genbiTurnId == turn_id and item.genbiThreadId == thread_id
        ]
        codex_item_projections.sort(key=lambda item: item.createdAt)
        return {
            "thread": asdict(thread),
            "turn": asdict(turn),
            "items": [asdict(item) for item in items],
            "codexItemProjections": [asdict(item) for item in codex_item_projections],
        }

    def get_thread_metadata(self, thread_id: str) -> dict[str, Any]:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread:
            return {}
        metadata = dict(thread.metadata or {})
        if thread.codexThreadId:
            metadata.setdefault("codex_thread_id", thread.codexThreadId)
        if thread.tenantId:
            metadata.setdefault("tenant_id", thread.tenantId)
        if thread.workspaceId:
            metadata.setdefault("workspace_id", thread.workspaceId)
        return metadata

    def get_runtime_thread_id(self, thread_id: str, runtime: str) -> str | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if runtime == "openai-codex" and thread and thread.codexThreadId:
            return thread.codexThreadId
        metadata = self.get_thread_metadata(thread_id)
        if runtime == "openai-codex":
            return _string_or_none(metadata.get("codex_thread_id"))
        runtime_threads = metadata.get("runtime_threads")
        if isinstance(runtime_threads, dict):
            return _string_or_none(runtime_threads.get(runtime))
        return None

    def get_analysis_thread_mapping(self, thread_id: str) -> dict[str, Any] | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread:
            return None
        return {
            "id": thread.id,
            "tenantId": thread.tenantId,
            "userId": thread.userId,
            "workspaceId": thread.workspaceId,
            "codexThreadId": thread.codexThreadId,
            "title": thread.title,
            "status": thread.status,
            "createdAt": thread.createdAt,
            "updatedAt": thread.updatedAt,
        }

    def get_turn_events(self, turn_id: str) -> list[dict[str, Any]]:
        state = self._read_state()
        items = [item for item in state["items"] if item.turnId == turn_id]
        items.sort(key=lambda item: item.createdAt)
        return [
            {
                "type": item["eventType"],
                "turn_id": item["turnId"],
                "payload": item["payload"],
                "created_at": item["createdAt"],
            }
            for item in [asdict(item) for item in items]
        ]

    def list_threads(self, *, limit: int = 50, product_kind: ThreadProductKind | None = None) -> list[dict[str, Any]]:
        threads = list(self._read_state()["threads"].values())
        if product_kind:
            threads = [item for item in threads if item.productKind == product_kind]
        threads.sort(key=lambda item: item.updatedAt, reverse=True)
        return [asdict(item) for item in threads[:limit]]

    def clear(self) -> int:
        count = len(self._read_raw())
        if self.path.exists():
            self.path.unlink()
        return count

    def _read_state(self) -> dict[str, Any]:
        state = {"threads": {}, "turns": {}, "items": [], "codex_item_projections": []}
        for record in self._read_raw():
            record_type = record.get("record_type")
            payload = dict(record.get("payload") or {})
            if record_type == "thread":
                payload = _normalize_thread_payload(payload)
                item = ThreadRecord(**payload)
                state["threads"][item.id] = item
            elif record_type == "turn":
                payload = _normalize_turn_payload(payload)
                item = TurnRecord(**payload)
                state["turns"][item.id] = item
            elif record_type == "item":
                state["items"].append(ItemRecord(**payload))
            elif record_type == "codex_item_projection":
                state["codex_item_projections"].append(CodexItemProjectionRecord(**payload))
        return state

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def _write_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for item in sorted(state["threads"].values(), key=lambda value: value.updatedAt):
                _write_record(file, "thread", asdict(item))
            for item in sorted(state["turns"].values(), key=lambda value: value.createdAt):
                _write_record(file, "turn", asdict(item))
            for item in sorted(state["items"], key=lambda value: value.createdAt):
                _write_record(file, "item", asdict(item))
            for item in sorted(state["codex_item_projections"], key=lambda value: value.createdAt):
                _write_record(file, "codex_item_projection", asdict(item))


def _write_record(file: Any, record_type: str, payload: dict[str, Any]) -> None:
    file.write(json.dumps({"record_type": record_type, "payload": payload}, ensure_ascii=False, default=str))
    file.write("\n")


def _items_from_events(
    events: list["AgentEvent"],
    *,
    thread_id: str,
    turn_id: str,
) -> list[ItemRecord]:
    items = []
    for event in events:
        item_id = event.payload.get("item_id")
        item_kind = event.payload.get("item_kind")
        if not item_id or not item_kind:
            continue
        items.append(
            ItemRecord(
                id=str(item_id),
                threadId=str(event.payload.get("thread_id") or thread_id),
                turnId=str(event.payload.get("turn_id") or turn_id),
                kind=str(item_kind),
                eventType=event.type,
                payload=dict(event.payload),
                createdAt=event.created_at,
            )
        )
    return items


def _codex_item_projections_from_events(
    events: list["AgentEvent"],
    *,
    thread_id: str,
    turn_id: str,
    default_codex_thread_id: str | None,
) -> list[CodexItemProjectionRecord]:
    projections: dict[str, CodexItemProjectionRecord] = {}
    for event in events:
        codex_item_id = _string_or_none(event.payload.get("codex_item_id"))
        if not codex_item_id:
            continue
        existing = projections.get(codex_item_id)
        payload = dict(event.payload)
        item_type = _string_or_none(payload.get("codex_item_type")) or (existing.itemType if existing else "unknown")
        codex_thread_id = _string_or_none(payload.get("codex_thread_id")) or (existing.codexThreadId if existing else default_codex_thread_id)
        codex_turn_id = _string_or_none(payload.get("codex_turn_id")) or (existing.codexTurnId if existing else None)
        completed = payload.get("codex_method") == "item/completed" or payload.get("phase") in {"item.completed", "agent_message.completed"}
        status = "completed" if completed else (existing.status if existing else "streaming")
        projections[codex_item_id] = CodexItemProjectionRecord(
            codexItemId=codex_item_id,
            codexThreadId=codex_thread_id,
            codexTurnId=codex_turn_id,
            itemType=item_type,
            status=status,
            payload=payload,
            createdAt=existing.createdAt if existing else event.created_at,
            completedAt=event.created_at if completed else (existing.completedAt if existing else None),
            genbiThreadId=thread_id,
            genbiTurnId=turn_id,
        )
    return list(projections.values())


def _turn_status(events: list["AgentEvent"]) -> str:
    if any(_is_agent_question_event(event) for event in events):
        return "needs_input"
    completed = next((event for event in reversed(events) if event.type == "turn/completed"), None)
    if completed:
        return str(completed.payload.get("status") or "complete")
    return "running"


def _is_agent_question_event(event: "AgentEvent") -> bool:
    return event.type == "item/completed" and event.payload.get("codex_item_type") == "agentQuestion"


def _first_payload_value(events: list["AgentEvent"], event_type: str, key: str) -> Any:
    for event in events:
        if event.type == event_type and key in event.payload:
            return event.payload[key]
    return None


def _latest_payload_value(events: list["AgentEvent"], key: str) -> Any:
    for event in reversed(events):
        if key in event.payload:
            return event.payload[key]
    return None


def _normalize_thread_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    payload.setdefault("tenantId", _thread_scope_value(metadata, "tenant_id", "tenantId"))
    payload.setdefault("workspaceId", _thread_scope_value(metadata, "workspace_id", "workspaceId"))
    payload.setdefault("codexThreadId", _thread_codex_thread_id(metadata))
    return payload


def _normalize_turn_payload(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(payload.get("metadata") or {})
    payload.setdefault("codexThreadId", _thread_codex_thread_id(metadata))
    payload.setdefault("codexTurnId", _string_or_none(metadata.get("codex_turn_id") or metadata.get("codexTurnId")))
    return payload


def _thread_scope_value(
    metadata: dict[str, Any],
    snake_key: str,
    camel_key: str,
    *,
    existing_value: str | None = None,
) -> str | None:
    return _string_or_none(metadata.get(snake_key) or metadata.get(camel_key) or existing_value)


def _thread_codex_thread_id(
    metadata: dict[str, Any],
    *,
    existing_thread: ThreadRecord | None = None,
) -> str | None:
    explicit = _string_or_none(metadata.get("codex_thread_id") or metadata.get("codexThreadId"))
    if explicit:
        return explicit
    runtime_threads = metadata.get("runtime_threads") or metadata.get("runtimeThreads")
    if isinstance(runtime_threads, dict):
        resolved = _string_or_none(runtime_threads.get("openai-codex"))
        if resolved:
            return resolved
    if existing_thread:
        return existing_thread.codexThreadId
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
