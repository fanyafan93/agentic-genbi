from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.exploration.run_service import ExplorationRunEvent, ExplorationRunRequest


DEFAULT_RUN_TRACE_STORE_PATH = Path(".resource-index/run-traces.jsonl")


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class RunCost:
    input_usd: float | None = None
    output_usd: float | None = None
    total_usd: float | None = None
    pricing: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RunTrace:
    run_id: str
    title: str | None
    status: str
    question: str
    conversation_id: str | None
    user_id: str | None
    started_at: str | None
    completed_at: str | None
    duration_ms: int | None
    event_count: int
    tool_call_count: int
    failed_tool_call_count: int
    agent_message_count: int
    token_usage: TokenUsage
    cost: RunCost
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RunTraceStore:
    def __init__(self, path: Path = DEFAULT_RUN_TRACE_STORE_PATH) -> None:
        self.path = path

    def save_trace(
        self,
        *,
        run_id: str,
        request: "ExplorationRunRequest",
        events: list["ExplorationRunEvent"],
        metadata: dict[str, Any] | None = None,
    ) -> RunTrace:
        trace = build_run_trace(run_id=run_id, request=request, events=events, metadata=metadata or {})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as file:
            file.write(json.dumps(asdict(trace), ensure_ascii=False, default=str))
            file.write("\n")
        return trace

    def list_traces(self, *, limit: int = 50) -> list[RunTrace]:
        records = self._read_all()
        records.sort(key=lambda item: item.completed_at or item.started_at or "", reverse=True)
        return records[:limit]

    def get_trace(self, run_id: str) -> RunTrace | None:
        for record in self._read_all():
            if record.run_id == run_id:
                return record
        return None

    def list_conversation_run_ids(self, conversation_id: str, *, limit: int = 8) -> list[str]:
        records = [
            record
            for record in self._read_all()
            if record.run_id == conversation_id
            or record.conversation_id == conversation_id
            or record.metadata.get("continuation_of") == conversation_id
        ]
        records.sort(key=lambda item: item.started_at or item.completed_at or "")
        run_ids = []
        seen = set()
        for record in records[-limit:]:
            if record.run_id in seen:
                continue
            seen.add(record.run_id)
            run_ids.append(record.run_id)
        return run_ids

    def delete_trace(self, run_id: str) -> int:
        records = self._read_all()
        remaining = [item for item in records if item.run_id != run_id]
        deleted_count = len(records) - len(remaining)
        if deleted_count == 0:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as file:
            for record in remaining:
                file.write(json.dumps(asdict(record), ensure_ascii=False, default=str))
                file.write("\n")
        return deleted_count

    def clear_traces(self) -> int:
        count = len(self._read_all())
        if self.path.exists():
            self.path.unlink()
        return count

    def _read_all(self) -> list[RunTrace]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            payload["token_usage"] = TokenUsage(**payload.get("token_usage", {}))
            payload["cost"] = RunCost(**payload.get("cost", {}))
            records.append(RunTrace(**payload))
        return records


def build_run_trace(
    *,
    run_id: str,
    request: "ExplorationRunRequest",
    events: list["ExplorationRunEvent"],
    metadata: dict[str, Any] | None = None,
) -> RunTrace:
    started_at = events[0].created_at if events else None
    completed_at = events[-1].created_at if events else None
    status = _run_status(events)
    title = _first_payload_value(events, "agent.title.generated", "title")
    duration_ms = _duration_ms(started_at, completed_at)
    usage = _sum_usage(events)
    cost = _calculate_cost(usage)
    return RunTrace(
        run_id=run_id,
        title=str(title) if title else None,
        status=status,
        question=request.question.strip(),
        conversation_id=request.conversation_id,
        user_id=request.user_id,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        event_count=len(events),
        tool_call_count=sum(1 for event in events if event.type == "tool.call.started"),
        failed_tool_call_count=sum(1 for event in events if event.type == "tool.call.failed"),
        agent_message_count=sum(1 for event in events if event.type == "agent.message.created"),
        token_usage=usage,
        cost=cost,
        error=_run_error(events),
        metadata=metadata or {},
    )


def _run_status(events: list["ExplorationRunEvent"]) -> str:
    if any(event.type == "run.failed" for event in events):
        return "failed"
    completed = next((event for event in reversed(events) if event.type == "run.completed"), None)
    if completed:
        return str(completed.payload.get("status") or "completed")
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


def _duration_ms(started_at: str | None, completed_at: str | None) -> int | None:
    if not started_at or not completed_at:
        return None
    started = datetime.fromisoformat(started_at)
    completed = datetime.fromisoformat(completed_at)
    return max(0, int((completed - started).total_seconds() * 1000))


def _sum_usage(events: list["ExplorationRunEvent"]) -> TokenUsage:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    for event in events:
        usage = event.payload.get("usage")
        if not isinstance(usage, dict):
            continue
        current_input = _int_usage(usage, "input_tokens", "prompt_tokens")
        current_output = _int_usage(usage, "output_tokens", "completion_tokens")
        current_total = _int_usage(usage, "total_tokens")
        input_tokens += current_input
        output_tokens += current_output
        total_tokens += current_total or current_input + current_output
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens or input_tokens + output_tokens,
    )


def _int_usage(usage: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def _calculate_cost(usage: TokenUsage) -> RunCost:
    input_rate = _env_float("GENBI_MODEL_INPUT_USD_PER_1M")
    output_rate = _env_float("GENBI_MODEL_OUTPUT_USD_PER_1M")
    if input_rate is None and output_rate is None:
        return RunCost()

    input_usd = (usage.input_tokens / 1_000_000) * input_rate if input_rate is not None else None
    output_usd = (usage.output_tokens / 1_000_000) * output_rate if output_rate is not None else None
    total_usd = (input_usd or 0) + (output_usd or 0)
    return RunCost(
        input_usd=round(input_usd, 8) if input_usd is not None else None,
        output_usd=round(output_usd, 8) if output_usd is not None else None,
        total_usd=round(total_usd, 8),
        pricing={
            key: value
            for key, value in {
                "input_usd_per_1m": input_rate,
                "output_usd_per_1m": output_rate,
            }.items()
            if value is not None
        },
    )


def _env_float(name: str) -> float | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_json(value: Any) -> str:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    elif isinstance(value, list):
        value = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in value]
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local exploration run trace store.")
    parser.add_argument("--path", default=str(DEFAULT_RUN_TRACE_STORE_PATH))
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_cmd = subparsers.add_parser("list", help="List recent run traces.")
    list_cmd.add_argument("--limit", type=int, default=50)

    get_cmd = subparsers.add_parser("get", help="Get one run trace.")
    get_cmd.add_argument("run_id")

    subparsers.add_parser("clear", help="Delete all run traces.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    store = RunTraceStore(Path(args.path))
    if args.command == "list":
        print(_to_json(store.list_traces(limit=args.limit)))
    elif args.command == "get":
        print(_to_json(store.get_trace(args.run_id)))
    elif args.command == "clear":
        print(_to_json({"deleted_count": store.clear_traces()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
