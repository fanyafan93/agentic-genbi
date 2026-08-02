from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Literal
from uuid import uuid4

from backend.analysis.runner_contracts import (
    AnalysisAgentResult,
    AnalysisAgentRunner,
    build_analysis_runner_prompt,
)
from backend.harness.events import AgentEvent
from backend.harness.thread_store import ThreadStore
from backend.business_semantics.finereport_reports import FineReportReportRepository

AnalysisTurnKind = Literal["start", "message", "reply"]


@dataclass(frozen=True)
class AnalysisTurnRequest:
    question: str
    conversation_id: str | None = None
    user_id: str | None = None
    turn_kind: AnalysisTurnKind = "start"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnalysisTurnSubmission:
    thread_id: str
    turn_id: str


@dataclass(frozen=True)
class ProblemClassification:
    type: str
    label: str
    confidence: float


@dataclass(frozen=True)
class SemanticModelCandidate:
    id: str
    label: str
    model_type: str
    source: str
    purpose: str


class AnalysisTurnService:
    def __init__(
        self,
        *,
        agent_runner: AnalysisAgentRunner | None = None,
        thread_store: ThreadStore | None = None,
        finereport_repository: FineReportReportRepository | None = None,
    ) -> None:
        self.agent_runner = agent_runner
        self.thread_store = thread_store
        self.finereport_repository = finereport_repository or FineReportReportRepository()
        self._turn_requests_by_turn: dict[str, AnalysisTurnRequest] = {}
        self._turn_contexts_by_turn: dict[str, dict[str, str]] = {}
        self._item_counts_by_turn: dict[str, int] = {}
        self._events_by_turn: dict[str, list[AgentEvent]] = {}

    def submit_turn(self, request: AnalysisTurnRequest) -> AnalysisTurnSubmission:
        thread_id = request.conversation_id or f"conv_analysis_{uuid4().hex[:12]}"
        turn_id = f"analysis_turn_{uuid4().hex[:12]}"
        request_metadata = dict(request.metadata or {})
        request_metadata.setdefault("turn_id", turn_id)
        turn_id = _requested_turn_id(request_metadata) or f"analysis_turn_{uuid4().hex[:12]}"
        turn_request = AnalysisTurnRequest(
            question=request.question,
            conversation_id=thread_id,
            user_id=request.user_id,
            turn_kind=request.turn_kind,
            metadata={**request_metadata, "turn_id": turn_id},
        )
        self._turn_requests_by_turn[turn_id] = turn_request
        return AnalysisTurnSubmission(
            thread_id=thread_id,
            turn_id=turn_id,
        )

    def run(self, request: AnalysisTurnRequest) -> list[AgentEvent]:
        submission = self.submit_turn(request)
        return list(self.stream_turn_events(submission.turn_id))

    def stream_turn_events(self, turn_id: str) -> Iterable[AgentEvent]:
        if turn_id in self._events_by_turn:
            yield from self._events_by_turn[turn_id]
            return
        if self.thread_store:
            stored_items = self.thread_store.get_turn_events(turn_id)
            if stored_items:
                for item in stored_items:
                    yield AgentEvent(
                        type=str(item["type"]),
                        turn_id=str(item["turn_id"]),
                        payload=dict(item.get("payload") or {}),
                        created_at=str(item["created_at"]),
                    )
                return
        request = self._turn_requests_by_turn.get(turn_id)
        if not request:
            yield self._failed_turn_event(turn_id, "turn_not_found")
            return
        yield from self.stream_events(request, turn_id=turn_id)

    async def astream_turn_events(self, turn_id: str) -> AsyncIterator[AgentEvent]:
        if turn_id in self._events_by_turn:
            for event in self._events_by_turn[turn_id]:
                yield event
            return
        if self.thread_store:
            stored_items = self.thread_store.get_turn_events(turn_id)
            if stored_items:
                for item in stored_items:
                    yield AgentEvent(
                        type=str(item["type"]),
                        turn_id=str(item["turn_id"]),
                        payload=dict(item.get("payload") or {}),
                        created_at=str(item["created_at"]),
                    )
                return
        request = self._turn_requests_by_turn.get(turn_id)
        if not request:
            yield self._failed_turn_event(turn_id, "turn_not_found")
            return
        async for event in self.astream_events(request, turn_id=turn_id):
            yield event

    def stream_events(
        self,
        request: AnalysisTurnRequest,
        *,
        turn_id: str | None = None,
    ) -> Iterable[AgentEvent]:
        events = []
        actual_turn_id = turn_id or f"analysis_turn_{uuid4().hex[:12]}"
        for event in self._stream_events_unrecorded(request, turn_id=actual_turn_id):
            for projected_event in self._project_codex_style_events(actual_turn_id, event):
                events.append(projected_event)
                yield projected_event
        self._save_turn_projection(actual_turn_id, request, events)

    async def astream_events(
        self,
        request: AnalysisTurnRequest,
        *,
        turn_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        events = []
        actual_turn_id = turn_id or f"analysis_turn_{uuid4().hex[:12]}"
        async for event in self._astream_events_unrecorded(request, turn_id=actual_turn_id):
            for projected_event in self._project_codex_style_events(actual_turn_id, event):
                events.append(projected_event)
                yield projected_event
        self._save_turn_projection(actual_turn_id, request, events)

    async def _astream_events_unrecorded(
        self,
        request: AnalysisTurnRequest,
        *,
        turn_id: str,
    ) -> AsyncIterator[AgentEvent]:
        if not self.agent_runner:
            for event in self._stream_events_unrecorded(request, turn_id=turn_id):
                yield event
            return

        question = request.question.strip()
        if not question:
            yield self._failed_turn_event(turn_id, "question_required")
            return

        conversation_id = request.conversation_id or f"conv_analysis_{uuid4().hex[:12]}"
        title = generate_analysis_title(question)
        classification = classify_analysis_problem(question)
        semantic_models = build_semantic_model_plan(classification)

        for event in self._analysis_start_events(
            request=request,
            turn_id=turn_id,
            question=question,
            conversation_id=conversation_id,
            title=title,
            classification=classification,
            semantic_models=semantic_models,
        ):
            yield event
        run_failed = False
        runner_events: list[AgentEvent] = []
        async for event in self._agent_runner_events_async(turn_id, request, classification, semantic_models):
            runner_events.append(event)
            if _is_failed_turn_event(event):
                run_failed = True
            yield event
        if run_failed:
            return
        for event in self._complete_projection_if_needed(turn_id, title, events=runner_events):
            yield event

    def _stream_events_unrecorded(
        self,
        request: AnalysisTurnRequest,
        *,
        turn_id: str,
    ) -> Iterable[AgentEvent]:
        question = request.question.strip()
        if not question:
            yield self._failed_turn_event(turn_id, "question_required")
            return

        conversation_id = request.conversation_id or f"conv_analysis_{uuid4().hex[:12]}"
        title = generate_analysis_title(question)
        classification = classify_analysis_problem(question)
        semantic_models = build_semantic_model_plan(classification)

        yield from self._analysis_start_events(
            request=request,
            turn_id=turn_id,
            question=question,
            conversation_id=conversation_id,
            title=title,
            classification=classification,
            semantic_models=semantic_models,
        )

        if not self.agent_runner:
            yield self._failed_turn_event(turn_id, "analysis_agent_runner_not_configured")
            return
        branch_events = list(self._agent_runner_events(turn_id, request, classification, semantic_models))
        yield from branch_events
        if any(_is_failed_turn_event(event) for event in branch_events):
            return

        yield from self._complete_projection_if_needed(turn_id, title, events=branch_events)

    def _analysis_start_events(
        self,
        *,
        request: AnalysisTurnRequest,
        turn_id: str,
        question: str,
        conversation_id: str,
        title: str,
        classification: ProblemClassification,
        semantic_models: list[SemanticModelCandidate],
    ) -> Iterable[AgentEvent]:
        self._register_turn_context(turn_id, conversation_id, request)
        yield self._event(
            turn_id,
            "turn/started",
            {
                "conversation_id": conversation_id,
                "thread_id": conversation_id,
                "user_id": request.user_id,
                "question": question,
                "turn_kind": request.turn_kind,
                "domain": "analysis_task",
                "codex_method": "turn/started",
            },
        )

    def _agent_runner_events(
        self,
        turn_id: str,
        request: AnalysisTurnRequest,
        classification: ProblemClassification,
        semantic_models: list[SemanticModelCandidate],
    ) -> Iterable[AgentEvent]:
        prompt = build_analysis_runner_prompt(
            question=request.question.strip(),
            problem_label=classification.label,
            semantic_model_labels=[item.label for item in semantic_models],
        )
        try:
            result = None
            for item in self._run_agent_runner(prompt, turn_id=turn_id, request=request):
                if isinstance(item, AnalysisAgentResult):
                    result = item
                else:
                    yield self._event(turn_id, item.type, item.payload)
            if result is None:
                raise RuntimeError("Analysis agent runner did not return a final result.")
        except Exception as exc:  # pragma: no cover - runtime boundary
            yield self._failed_turn_event(turn_id, "analysis_agent_runner_failed", detail=str(exc))
            return
        yield from self._final_result_events(turn_id, result)

    async def _agent_runner_events_async(
        self,
        turn_id: str,
        request: AnalysisTurnRequest,
        classification: ProblemClassification,
        semantic_models: list[SemanticModelCandidate],
    ) -> AsyncIterator[AgentEvent]:
        prompt = build_analysis_runner_prompt(
            question=request.question.strip(),
            problem_label=classification.label,
            semantic_model_labels=[item.label for item in semantic_models],
        )
        try:
            result = None
            async for item in self._run_agent_runner_async(prompt, turn_id=turn_id, request=request):
                if isinstance(item, AnalysisAgentResult):
                    result = item
                else:
                    yield self._event(turn_id, item.type, item.payload)
            if result is None:
                raise RuntimeError("Analysis agent runner did not return a final result.")
        except Exception as exc:  # pragma: no cover - runtime boundary
            yield self._failed_turn_event(turn_id, "analysis_agent_runner_failed", detail=str(exc))
            return
        for event in self._final_result_events(turn_id, result):
            yield event

    def _final_result_events(
        self,
        turn_id: str,
        result: AnalysisAgentResult,
    ) -> Iterable[AgentEvent]:
        message = result.final_output.strip()
        if message:
            yield self._event(
                turn_id,
                "item/completed",
                {
                    "role": "assistant",
                    "title": "分析结果",
                    "content": message,
                    "codex_item_type": "agentMessage",
                    "codex_method": "item/completed",
                },
            )

    def _event(self, turn_id: str, event_type: str, payload: dict[str, Any]) -> AgentEvent:
        enriched_payload = dict(payload)
        enriched_payload.setdefault("eventSource", "genbi_projection")
        enriched_payload.setdefault("turn_id", turn_id)
        context = self._turn_contexts_by_turn.get(turn_id)
        if context:
            enriched_payload.setdefault("thread_id", context["thread_id"])
            enriched_payload.setdefault("turn_id", context["turn_id"])
            enriched_payload.setdefault("conversation_id", context["thread_id"])
        item_kind = item_kind_for_event(event_type, enriched_payload)
        if item_kind:
            enriched_payload.setdefault("item_kind", item_kind)
            enriched_payload.setdefault("item_id", self._next_item_id(turn_id, item_kind))
        return AgentEvent(type=event_type, turn_id=turn_id, payload=enriched_payload)

    def _failed_turn_event(self, turn_id: str, error: str, *, detail: str | None = None) -> AgentEvent:
        payload: dict[str, Any] = {
            "status": "failed",
            "error": error,
            "domain": "analysis_task",
            "codex_method": "turn/completed",
        }
        if detail:
            payload["detail"] = detail
        return self._event(turn_id, "turn/completed", payload)

    def _complete_projection_if_needed(
        self,
        turn_id: str,
        title: str,
        *,
        events: Iterable[AgentEvent] = (),
    ) -> Iterable[AgentEvent]:
        if any(event.type == "turn/completed" for event in events):
            return
        yield self._event(
            turn_id,
            "turn/completed",
            {
                "title": title,
                "status": "completed",
                "domain": "analysis_task",
                "codex_method": "turn/completed",
            },
        )

    def _project_codex_style_events(self, turn_id: str, event: AgentEvent) -> list[AgentEvent]:
        return [event]

    def _register_turn_context(self, turn_id: str, thread_id: str, request: AnalysisTurnRequest) -> None:
        codex_turn_id = _requested_turn_id(request.metadata) or turn_id
        self._turn_contexts_by_turn[turn_id] = {"thread_id": thread_id, "turn_id": codex_turn_id}

    def _next_item_id(self, turn_id: str, item_kind: str) -> str:
        next_index = self._item_counts_by_turn.get(turn_id, 0) + 1
        self._item_counts_by_turn[turn_id] = next_index
        return f"item_{turn_id.removeprefix('analysis_turn_')}_{next_index:04d}_{item_kind}"

    def _run_agent_runner(self, prompt: str, *, turn_id: str, request: AnalysisTurnRequest) -> Iterable[Any]:
        if not self.agent_runner:
            return []
        stream = getattr(self.agent_runner, "stream", None)
        if callable(stream):
            try:
                return stream(prompt, context=self._agent_runner_context(turn_id, request))
            except TypeError:
                return stream(prompt)
        return [self.agent_runner.run(prompt)]

    async def _run_agent_runner_async(self, prompt: str, *, turn_id: str, request: AnalysisTurnRequest) -> AsyncIterator[Any]:
        if not self.agent_runner:
            return
        async_stream = getattr(self.agent_runner, "async_stream", None)
        if callable(async_stream):
            try:
                async_items = async_stream(prompt, context=self._agent_runner_context(turn_id, request))
            except TypeError:
                async_items = async_stream(prompt)
            async for item in async_items:
                yield item
            return
        for item in self._run_agent_runner(prompt, turn_id=turn_id, request=request):
            yield item

    def _agent_runner_context(self, turn_id: str, request: AnalysisTurnRequest) -> dict[str, Any]:
        context = self._turn_contexts_by_turn.get(turn_id, {})
        thread_id = context.get("thread_id")
        return {
            "genbi_thread_id": thread_id,
            "genbi_turn_id": context.get("turn_id") or turn_id,
            "turn_id": turn_id,
            "codex_thread_id": self._resolve_runtime_thread_id(
                request,
                thread_id=thread_id,
                runtime=self._agent_runner_runtime(),
            ),
        }

    def _agent_runner_runtime(self) -> str:
        if not self.agent_runner:
            return "local"
        return str(getattr(self.agent_runner, "runtime_name", "") or self.agent_runner.__class__.__name__)

    def _save_turn_projection(self, turn_id: str, request: AnalysisTurnRequest, events: list[AgentEvent]) -> None:
        context = self._turn_contexts_by_turn.get(turn_id, {})
        runtime = self._agent_runner_runtime()
        codex_thread_id = _latest_payload_value(events, "codex_thread_id") or self._resolve_runtime_thread_id(
            request,
            thread_id=context.get("thread_id"),
            runtime=runtime,
        )
        metadata = {
            "domain": "analysis_task",
            "thread_id": context.get("thread_id"),
            "turn_id": context.get("turn_id"),
            **(request.metadata or {}),
        }
        if codex_thread_id:
            metadata["codex_thread_id"] = codex_thread_id
            runtime_threads = dict(metadata.get("runtime_threads") or {})
            runtime_threads[runtime] = codex_thread_id
            metadata["runtime_threads"] = runtime_threads
        self._events_by_turn[turn_id] = list(events)
        if self.thread_store and context.get("thread_id") and context.get("turn_id"):
            try:
                self.thread_store.save_turn(
                    thread_id=context["thread_id"],
                    turn_id=context["turn_id"],
                    question=request.question.strip(),
                    input_kind=request.turn_kind,
                    product_kind="analysis_task",
                    user_id=request.user_id,
                    events=events,
                    metadata=metadata,
                )
            except Exception:
                pass

    def _resolve_runtime_thread_id(
        self,
        request: AnalysisTurnRequest,
        *,
        thread_id: str | None,
        runtime: str,
    ) -> str | None:
        explicit = _string_or_none(request.metadata.get("codex_thread_id"))
        if explicit:
            return explicit
        if not self.thread_store or not thread_id:
            return None
        try:
            return self.thread_store.get_runtime_thread_id(thread_id, runtime)
        except Exception:
            return None


AnalysisThreadService = AnalysisTurnService


def generate_analysis_title(question: str) -> str:
    text = re.sub(r"\s+", " ", question).strip(" \t\r\n。！？?！")
    if not text:
        return "untitled analysis"
    if len(text) > 24:
        text = text[:24].rstrip()
    return text or "untitled analysis"


def classify_analysis_problem(question: str) -> ProblemClassification:
    normalized = question.lower()
    if re.search(r"anomaly|drop|growth|reason|diagnos|异常|下滑|上涨|原因|归因|波动", normalized):
        return ProblemClassification(type="metric_diagnosis", label="metric diagnosis", confidence=0.84)
    if re.search(r"definition|formula|metric|复购|留存|口径|定义|怎么算|指标", normalized):
        return ProblemClassification(type="metric_definition", label="metric definition", confidence=0.82)
    if re.search(r"report|finereport|field|报表|字段|解释", normalized):
        return ProblemClassification(type="report_understanding", label="report understanding", confidence=0.78)
    if re.search(r"review|gmv|sales|channel|经营|月度|季度|销售|渠道", normalized):
        return ProblemClassification(type="business_review", label="business review", confidence=0.8)
    return ProblemClassification(type="business_analysis", label="business analysis", confidence=0.72)


def build_semantic_model_plan(classification: ProblemClassification) -> list[SemanticModelCandidate]:
    return [
        SemanticModelCandidate(
            id="semantic_finereport_report",
            label="FineReport semantic model",
            model_type="report_semantic_model",
            source="FineReport parser",
            purpose="Understand report metrics, dimensions, data access, and interaction logic.",
        ),
        SemanticModelCandidate(
            id="semantic_sql_examples",
            label="SQL example semantic model",
            model_type="query_semantic_model",
            source="verified SQL examples",
            purpose="Reuse known query patterns and metric definitions.",
        ),
        SemanticModelCandidate(
            id="semantic_mysql_doris_metadata",
            label="MySQL / Doris metadata semantic model",
            model_type="metadata_semantic_model",
            source="catalog metadata",
            purpose="Confirm tables, fields, types, and query scope.",
        ),
        SemanticModelCandidate(
            id="knowledge_confirmed_experience",
            label="verified business knowledge",
            model_type="knowledge_semantic_model",
            source="knowledge store",
            purpose="Reuse verified definitions, exclusions, and business rules.",
        ),
        SemanticModelCandidate(
            id=f"analysis_context_{classification.type}",
            label="historical analysis assets",
            model_type="analysis_asset_model",
            source="artifact library",
            purpose="Reuse similar reports, SQL, charts, and skills.",
        ),
    ]

def item_kind_for_event(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == "turn/started" and payload.get("question"):
        return "message"
    if event_type == "item/agentMessage/delta":
        return "message"
    if event_type in {"item/started", "item/completed"}:
        codex_item_type = str(payload.get("codex_item_type") or "")
        if codex_item_type == "agentMessage":
            return "message"
        if codex_item_type == "agentQuestion":
            return "question"
        if codex_item_type == "toolCall":
            return "tool_call"
        if codex_item_type == "toolResult":
            return "tool_result"
    if event_type in {"genbi/artifact/created", "genbi/artifact/updated"}:
        if payload.get("artifactType") == "interactive_report":
            return "report"
        kind = str(payload.get("kind") or "")
        if kind == "sql":
            return "sql"
        if kind == "json" and ".chart." in str(payload.get("path") or ""):
            return "chart"
        if kind == "html" or "report" in str(payload.get("path") or ""):
            return "report"
        return "artifact"
    return None


def _latest_payload_value(events: list[AgentEvent], key: str) -> str | None:
    for event in reversed(events):
        value = _string_or_none(event.payload.get(key))
        if value:
            return value
    return None


def _is_failed_turn_event(event: AgentEvent) -> bool:
    return event.type == "turn/completed" and event.payload.get("status") == "failed"


def _requested_turn_id(metadata: dict[str, Any]) -> str | None:
    return _string_or_none(
        metadata.get("codex_turn_id")
        or metadata.get("codexTurnId")
        or metadata.get("turn_id")
        or metadata.get("turnId")
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_follow_up_question(classification: ProblemClassification) -> str:
    if classification.type == "metric_definition":
        return "Please confirm the metric entity, deduplication rule, and exclusion scope before I finalize the definition."
    if classification.type == "metric_diagnosis":
        return "Which dimension should I prioritize for diagnosis: channel, store, SKU, region, or customer cohort?"
    if classification.type == "report_understanding":
        return "Should I explain the business definition, data logic, or filter interaction rules first?"
    return "Should this analysis prioritize a fast draft or a stricter business-scope validation first?"

