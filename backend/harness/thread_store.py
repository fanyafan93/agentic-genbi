from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from backend.exploration.run_service import ExplorationRunEvent


DEFAULT_THREAD_STORE_PATH = Path(".resource-index/thread-store.jsonl")

ThreadProductKind = Literal["analysis_task", "knowledge_exploration", "asset_continuation"]
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


@dataclass(frozen=True)
class TurnRecord:
    id: str
    threadId: str
    inputKind: TurnInputKind
    question: str
    status: str
    runIds: list[str]
    createdAt: str
    updatedAt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunRecord:
    id: str
    threadId: str
    turnId: str
    status: str
    startedAt: str | None
    completedAt: str | None
    eventCount: int
    itemCount: int
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ItemRecord:
    id: str
    threadId: str
    turnId: str
    runId: str
    kind: str
    eventType: str
    payload: dict[str, Any]
    createdAt: str


class ThreadStore:
    def __init__(self, path: Path = DEFAULT_THREAD_STORE_PATH) -> None:
        self.path = path

    def save_run(
        self,
        *,
        thread_id: str,
        turn_id: str,
        run_id: str,
        question: str,
        input_kind: TurnInputKind,
        product_kind: ThreadProductKind,
        user_id: str | None,
        events: list["ExplorationRunEvent"],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not thread_id.strip():
            raise ValueError("thread_id is required.")
        if not turn_id.strip():
            raise ValueError("turn_id is required.")
        if not run_id.strip():
            raise ValueError("run_id is required.")

        state = self._read_state()
        existing_thread = state["threads"].get(thread_id)
        existing_turn = state["turns"].get(turn_id)
        started_at = events[0].created_at if events else None
        completed_at = events[-1].created_at if events else started_at
        status = _run_status(events)
        thread_status = "needs_input" if any(event.type == "agent.question.requested" for event in events) else status
        item_records = _items_from_events(events, thread_id=thread_id, turn_id=turn_id, run_id=run_id)
        title = _first_payload_value(events, "agent.title.generated", "title") or (existing_thread.title if existing_thread else None)
        now = completed_at or started_at or ""

        thread = ThreadRecord(
            id=thread_id,
            productKind=product_kind,
            title=str(title) if title else None,
            userId=user_id,
            status=thread_status,
            createdAt=existing_thread.createdAt if existing_thread else (started_at or now),
            updatedAt=now,
            metadata={**(existing_thread.metadata if existing_thread else {}), **(metadata or {})},
        )
        run_ids = [*(existing_turn.runIds if existing_turn else [])]
        if run_id not in run_ids:
            run_ids.append(run_id)
        turn = TurnRecord(
            id=turn_id,
            threadId=thread_id,
            inputKind=input_kind,
            question=question,
            status=thread_status,
            runIds=run_ids,
            createdAt=existing_turn.createdAt if existing_turn else (started_at or now),
            updatedAt=now,
            metadata={**(existing_turn.metadata if existing_turn else {}), **(metadata or {})},
        )
        run = RunRecord(
            id=run_id,
            threadId=thread_id,
            turnId=turn_id,
            status=status,
            startedAt=started_at,
            completedAt=completed_at,
            eventCount=len(events),
            itemCount=len(item_records),
            error=_run_error(events),
            metadata=metadata or {},
        )

        state["threads"][thread_id] = thread
        state["turns"][turn_id] = turn
        state["runs"][run_id] = run
        state["items"] = [item for item in state["items"] if item.runId != run_id]
        state["items"].extend(item_records)
        self._write_state(state)
        return {
            "thread": asdict(thread),
            "turn": asdict(turn),
            "run": asdict(run),
            "items": [asdict(item) for item in item_records],
        }

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread:
            return None
        turns = [turn for turn in state["turns"].values() if turn.threadId == thread_id]
        turns.sort(key=lambda item: item.createdAt)
        runs = [run for run in state["runs"].values() if run.threadId == thread_id]
        runs.sort(key=lambda item: item.startedAt or "")
        items = [item for item in state["items"] if item.threadId == thread_id]
        items.sort(key=lambda item: item.createdAt)
        return {
            "thread": asdict(thread),
            "turns": [asdict(item) for item in turns],
            "runs": [asdict(item) for item in runs],
            "items": [asdict(item) for item in items],
        }

    def get_thread_metadata(self, thread_id: str) -> dict[str, Any]:
        state = self._read_state()
        thread = state["threads"].get(thread_id)
        if not thread:
            return {}
        return dict(thread.metadata or {})

    def get_runtime_thread_id(self, thread_id: str, runtime: str) -> str | None:
        metadata = self.get_thread_metadata(thread_id)
        if runtime == "openai-codex":
            return _string_or_none(metadata.get("codex_thread_id"))
        runtime_threads = metadata.get("runtime_threads")
        if isinstance(runtime_threads, dict):
            return _string_or_none(runtime_threads.get(runtime))
        return None

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        state = self._read_state()
        run = state["runs"].get(run_id)
        if not run:
            return None
        items = [item for item in state["items"] if item.runId == run_id]
        items.sort(key=lambda item: item.createdAt)
        return {"run": asdict(run), "items": [asdict(item) for item in items]}

    def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
        run = self.get_run(run_id)
        if not run:
            return []
        return [
            {
                "type": item["eventType"],
                "run_id": item["runId"],
                "payload": item["payload"],
                "created_at": item["createdAt"],
            }
            for item in run["items"]
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
        state = {"threads": {}, "turns": {}, "runs": {}, "items": []}
        for record in self._read_raw():
            record_type = record.get("record_type")
            payload = dict(record.get("payload") or {})
            if record_type == "thread":
                item = ThreadRecord(**payload)
                state["threads"][item.id] = item
            elif record_type == "turn":
                item = TurnRecord(**payload)
                state["turns"][item.id] = item
            elif record_type == "run":
                item = RunRecord(**payload)
                state["runs"][item.id] = item
            elif record_type == "item":
                state["items"].append(ItemRecord(**payload))
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
            for item in sorted(state["runs"].values(), key=lambda value: value.startedAt or ""):
                _write_record(file, "run", asdict(item))
            for item in sorted(state["items"], key=lambda value: value.createdAt):
                _write_record(file, "item", asdict(item))


def _write_record(file: Any, record_type: str, payload: dict[str, Any]) -> None:
    file.write(json.dumps({"record_type": record_type, "payload": payload}, ensure_ascii=False, default=str))
    file.write("\n")


def _items_from_events(
    events: list["ExplorationRunEvent"],
    *,
    thread_id: str,
    turn_id: str,
    run_id: str,
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
                runId=str(event.payload.get("run_id") or run_id),
                kind=str(item_kind),
                eventType=event.type,
                payload=dict(event.payload),
                createdAt=event.created_at,
            )
        )
    return items


def _run_status(events: list["ExplorationRunEvent"]) -> str:
    if any(event.type == "run.failed" for event in events):
        return "failed"
    if any(event.type == "agent.question.requested" for event in events):
        return "needs_input"
    completed = next((event for event in reversed(events) if event.type == "run.completed"), None)
    if completed:
        return str(completed.payload.get("status") or "complete")
    return "running"


def _run_error(events: list["ExplorationRunEvent"]) -> str | None:
    failed = next((event for event in reversed(events) if event.type in {"run.failed", "agent.runner.failed"}), None)
    if not failed:
        return None
    return str(failed.payload.get("detail") or failed.payload.get("error") or "unknown_error")


def _first_payload_value(events: list["ExplorationRunEvent"], event_type: str, key: str) -> Any:
    for event in events:
        if event.type == event_type and key in event.payload:
            return event.payload[key]
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
