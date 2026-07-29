from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, AsyncIterator, Iterable
from uuid import uuid4

from backend.exploration.agent_runner import ExplorationAgentRunResult, ExplorationAgentRunner, ExplorationAgentRunnerEvent
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_trace_store import RunTraceStore
from backend.resource_library.database_tools import ReadonlyDatabaseTools
from backend.resource_library.tools import ResourceLibrary


@dataclass(frozen=True)
class ExplorationRunRequest:
    question: str
    conversation_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExplorationRunEvent:
    type: str
    run_id: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_sse(self) -> str:
        data = json.dumps(asdict(self), ensure_ascii=False, default=str)
        return f"event: {self.type}\ndata: {data}\n\n"


class ExplorationRunService:
    def __init__(
        self,
        *,
        resource_library: ResourceLibrary | None = None,
        db_tools: ReadonlyDatabaseTools | None = None,
        agent_runner: ExplorationAgentRunner | None = None,
        trace_store: RunTraceStore | None = None,
        event_store: RunEventStore | None = None,
        max_resource_results: int = 5,
    ) -> None:
        self.resource_library = resource_library
        self.db_tools = db_tools
        self.agent_runner = agent_runner
        self.trace_store = trace_store
        self.event_store = event_store
        self.max_resource_results = max_resource_results
        self._requests: dict[str, ExplorationRunRequest] = {}

    def create_run(self, request: ExplorationRunRequest) -> str:
        run_id = f"run_{uuid4().hex[:12]}"
        self._requests[run_id] = request
        return run_id

    def run(self, request: ExplorationRunRequest) -> list[ExplorationRunEvent]:
        run_id = self.create_run(request)
        return list(self.stream_events(request, run_id=run_id))

    def stream_run_events(self, run_id: str) -> Iterable[ExplorationRunEvent]:
        stored_events = self.event_store.list_events(run_id) if self.event_store else []
        if stored_events:
            yield from stored_events
            return
        request = self._requests.get(run_id)
        if not request:
            yield self._event(run_id, "run.failed", {"error": "run_not_found"})
            return
        yield from self.stream_events(request, run_id=run_id)

    async def astream_run_events(self, run_id: str) -> AsyncIterator[ExplorationRunEvent]:
        stored_events = self.event_store.list_events(run_id) if self.event_store else []
        if stored_events:
            for event in stored_events:
                yield event
            return
        request = self._requests.get(run_id)
        if not request:
            yield self._event(run_id, "run.failed", {"error": "run_not_found"})
            return
        async for event in self.astream_events(request, run_id=run_id):
            yield event

    def stream_events(self, request: ExplorationRunRequest, *, run_id: str | None = None) -> Iterable[ExplorationRunEvent]:
        events = []
        actual_run_id = run_id or f"run_{uuid4().hex[:12]}"
        for event in self._stream_events_unrecorded(request, run_id=actual_run_id):
            events.append(event)
            yield event
        self._save_run_artifacts(actual_run_id, request, events)

    async def astream_events(
        self,
        request: ExplorationRunRequest,
        *,
        run_id: str | None = None,
    ) -> AsyncIterator[ExplorationRunEvent]:
        events = []
        actual_run_id = run_id or f"run_{uuid4().hex[:12]}"
        async for event in self._astream_events_unrecorded(request, run_id=actual_run_id):
            events.append(event)
            yield event
        self._save_run_artifacts(actual_run_id, request, events)

    def _stream_events_unrecorded(
        self,
        request: ExplorationRunRequest,
        *,
        run_id: str,
    ) -> Iterable[ExplorationRunEvent]:
        actual_run_id = run_id or f"run_{uuid4().hex[:12]}"
        question = request.question.strip()
        if not question:
            yield self._event(actual_run_id, "run.failed", {"error": "question_required"})
            return

        title = generate_exploration_title(question)
        yield from self._start_events(request, actual_run_id, question, title)
        runner_question = self._build_runner_question(request, question)

        if self.agent_runner:
            yield self._event(
                actual_run_id,
                "agent.runner.started",
                {"runtime": "openai-agents-sdk", "max_resource_results": self.max_resource_results},
            )
            try:
                result = None
                for item in self._run_agent_runner(runner_question):
                    if isinstance(item, ExplorationAgentRunResult):
                        result = item
                    else:
                        yield self._event(actual_run_id, item.type, item.payload)
                if result is None:
                    raise RuntimeError("Agent runner did not return a final result.")
            except Exception as exc:  # pragma: no cover - defensive runtime boundary
                yield self._event(
                    actual_run_id,
                    "agent.runner.failed",
                    {"runtime": "openai-agents-sdk", "error": str(exc)},
                )
                yield self._event(actual_run_id, "run.failed", {"error": "agent_runner_failed", "detail": str(exc)})
                return
            yield self._event(
                actual_run_id,
                "agent.runner.completed",
                {"runtime": "openai-agents-sdk", "raw_result_type": result.raw_result_type},
            )
            yield self._event(
                actual_run_id,
                "agent.message.created",
                {
                    "role": "assistant",
                    "title": "探索结论",
                    "content": result.final_output,
                },
            )
            yield self._event(
                actual_run_id,
                "run.completed",
                {
                    "title": title,
                    "status": "completed",
                    "next_action": "已由真实 Agent Runtime 完成探索；如结论需要固化，可继续沉淀为知识。",
                },
            )
            return

        yield self._event(
            actual_run_id,
            "agent.runner.failed",
            {"runtime": "openai-agents-sdk", "error": "agent_runner_not_configured"},
        )
        yield self._event(
            actual_run_id,
            "run.failed",
            {
                "error": "agent_runner_not_configured",
                "detail": "真实 Agent Runtime 未配置，已停止探索。",
            },
        )

    async def _astream_events_unrecorded(
        self,
        request: ExplorationRunRequest,
        *,
        run_id: str,
    ) -> AsyncIterator[ExplorationRunEvent]:
        actual_run_id = run_id or f"run_{uuid4().hex[:12]}"
        question = request.question.strip()
        if not question:
            yield self._event(actual_run_id, "run.failed", {"error": "question_required"})
            return

        title = generate_exploration_title(question)
        for event in self._start_events(request, actual_run_id, question, title):
            yield event
        runner_question = self._build_runner_question(request, question)

        if self.agent_runner:
            yield self._event(
                actual_run_id,
                "agent.runner.started",
                {"runtime": "openai-agents-sdk", "max_resource_results": self.max_resource_results},
            )
            try:
                result = None
                async for item in self._run_agent_runner_async(runner_question):
                    if isinstance(item, ExplorationAgentRunResult):
                        result = item
                    else:
                        yield self._event(actual_run_id, item.type, item.payload)
                if result is None:
                    raise RuntimeError("Agent runner did not return a final result.")
            except Exception as exc:  # pragma: no cover - defensive runtime boundary
                yield self._event(
                    actual_run_id,
                    "agent.runner.failed",
                    {"runtime": "openai-agents-sdk", "error": str(exc)},
                )
                yield self._event(actual_run_id, "run.failed", {"error": "agent_runner_failed", "detail": str(exc)})
                return
            yield self._event(
                actual_run_id,
                "agent.runner.completed",
                {"runtime": "openai-agents-sdk", "raw_result_type": result.raw_result_type},
            )
            yield self._event(
                actual_run_id,
                "agent.message.created",
                {
                    "role": "assistant",
                    "title": "探索结论",
                    "content": result.final_output,
                },
            )
            yield self._event(
                actual_run_id,
                "run.completed",
                {
                    "title": title,
                    "status": "completed",
                    "next_action": "已由真实 Agent Runtime 完成探索；如结论需要固化，可继续沉淀为知识。",
                },
            )
            return

        yield self._event(
            actual_run_id,
            "agent.runner.failed",
            {"runtime": "openai-agents-sdk", "error": "agent_runner_not_configured"},
        )
        yield self._event(
            actual_run_id,
            "run.failed",
            {
                "error": "agent_runner_not_configured",
                "detail": "真实 Agent Runtime 未配置，已停止探索。",
            },
        )

    def _start_events(
        self,
        request: ExplorationRunRequest,
        run_id: str,
        question: str,
        title: str,
    ) -> Iterable[ExplorationRunEvent]:
        yield self._event(
            run_id,
            "run.created",
            {
                "conversation_id": request.conversation_id,
                "user_id": request.user_id,
                "question": question,
            },
        )
        yield self._event(run_id, "agent.title.generated", {"title": title})

    def _event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> ExplorationRunEvent:
        return ExplorationRunEvent(type=event_type, run_id=run_id, payload=_sanitize_event_payload(event_type, payload))

    def _save_run_artifacts(self, run_id: str, request: ExplorationRunRequest, events: list[ExplorationRunEvent]) -> None:
        if self.event_store:
            try:
                self.event_store.save_events(run_id=run_id, events=events)
            except Exception:
                pass
        if self.trace_store:
            try:
                self.trace_store.save_trace(run_id=run_id, request=request, events=events, metadata=request.metadata)
            except Exception:
                pass

    def _run_agent_runner(self, question: str) -> Iterable[ExplorationAgentRunnerEvent | ExplorationAgentRunResult]:
        if not self.agent_runner:
            return []
        stream = getattr(self.agent_runner, "stream", None)
        if callable(stream):
            return stream(question)
        return [self.agent_runner.run(question)]

    async def _run_agent_runner_async(
        self,
        question: str,
    ) -> AsyncIterator[ExplorationAgentRunnerEvent | ExplorationAgentRunResult]:
        if not self.agent_runner:
            return
        async_stream = getattr(self.agent_runner, "async_stream", None)
        if callable(async_stream):
            async for item in async_stream(question):
                yield item
            return
        for item in self._run_agent_runner(question):
            yield item

    def _build_runner_question(self, request: ExplorationRunRequest, question: str) -> str:
        if not request.conversation_id or not self.trace_store or not self.event_store:
            return question
        run_ids = self.trace_store.list_conversation_run_ids(request.conversation_id, limit=8)
        history_events = []
        for history_run_id in run_ids:
            history_events.extend(self.event_store.list_events(history_run_id))
        if not history_events:
            return question
        return build_conversation_turn_prompt(question, history_events)


def generate_exploration_title(question: str) -> str:
    text = re.sub(r"\s+", " ", question).strip(" \t\r\n。！？!?")
    if not text:
        return "未命名探索"
    text = re.sub(r"^(请|帮我|麻烦|先|看看|查一下|问一下)[，,：:\s]*", "", text)
    text = re.sub(r"(现在应该怎么计算|应该怎么计算|怎么计算|如何计算|先看看公司里有没有已有实现)", "", text)
    text = text.strip(" ，,。！？!?")
    if len(text) > 24:
        text = text[:24].rstrip()
    return text or "未命名探索"


def build_conversation_turn_prompt(question: str, history_events: list[ExplorationRunEvent]) -> str:
    history = _conversation_history_lines(history_events)
    if not history:
        return question
    return "\n\n".join(
        [
            "这是同一个知识探索会话中的继续追问或补充。请基于已有上下文继续，不要重新自我介绍，不要当成全新的探索。",
            "已有对话：",
            "\n".join(history[-12:]),
            "本轮用户追问：",
            question,
        ]
    )


def _conversation_history_lines(events: list[ExplorationRunEvent]) -> list[str]:
    lines = []
    for event in events:
        if event.type == "run.created":
            question = str(event.payload.get("question") or "").strip()
            if question and not question.startswith("这是同一个知识探索会话中的继续追问或补充"):
                lines.append(f"用户：{_truncate_context_text(question)}")
        elif event.type == "agent.message.created":
            content = str(event.payload.get("content") or "").strip()
            if not content:
                continue
            title = str(event.payload.get("title") or "").strip()
            prefix = f"Agent（{title}）" if title else "Agent"
            lines.append(f"{prefix}：{_truncate_context_text(content)}")
        elif event.type == "agent.question.requested":
            content = str(event.payload.get("question") or "").strip()
            if content:
                lines.append(f"Agent（追问用户）：{_truncate_context_text(content)}")
    return lines


def _truncate_context_text(text: str, limit: int = 1200) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}..."


def _sanitize_event_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if event_type != "agent.message.created":
        return payload
    content = payload.get("content")
    if not isinstance(content, str):
        return payload
    return {**payload, "content": content.replace("数据探索 Agent", "知识探索 Agent")}


def extract_search_keywords(question: str) -> list[str]:
    normalized = question.strip()
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", normalized)
    candidates = []
    if normalized:
        candidates.append(normalized)
    candidates.extend(_extract_metric_phrases(normalized))
    candidates.extend(token for token in tokens if len(token) >= 2)
    return _dedupe(candidates)[:3] or ["探索"]


def _extract_metric_phrases(text: str) -> list[str]:
    phrases = []
    for suffix in ("复购率", "周转率", "销售额", "销售占比", "同比增长", "GMV", "ROI"):
        if suffix in text:
            phrases.append(suffix)
    return phrases


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
