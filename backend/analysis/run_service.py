from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Literal
from uuid import uuid4

from backend.analysis.runner_contracts import (
    AnalysisAgentRunResult,
    AnalysisAgentRunner,
    build_analysis_runner_prompt,
    extract_interactive_report_draft,
    sanitize_interactive_report_context,
)
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_service import ExplorationRunEvent
from backend.exploration.run_trace_store import RunTraceStore
from backend.harness.thread_store import ThreadStore
from backend.analysis.report_query_service import (
    CHANNEL_SALES_QUERY_REF,
    REGION_CHANNEL_SALES_QUERY_REF,
    ReportQueryFilterError,
    ReportQueryService,
    response_to_dict,
)
from backend.business_semantics.finereport_reports import FineReportReportRepository

AnalysisMode = Literal["quick", "deep"]
AnalysisTurnKind = Literal["start", "message", "reply"]


@dataclass(frozen=True)
class AnalysisRunRequest:
    question: str
    conversation_id: str | None = None
    user_id: str | None = None
    analysis_mode: AnalysisMode = "quick"
    turn_kind: AnalysisTurnKind = "start"
    metadata: dict[str, Any] = field(default_factory=dict)


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


class AnalysisRunService:
    def __init__(
        self,
        *,
        agent_runner: AnalysisAgentRunner | None = None,
        trace_store: RunTraceStore | None = None,
        event_store: RunEventStore | None = None,
        thread_store: ThreadStore | None = None,
        report_query_service: ReportQueryService | None = None,
        finereport_repository: FineReportReportRepository | None = None,
    ) -> None:
        self.agent_runner = agent_runner
        self.trace_store = trace_store
        self.event_store = event_store
        self.thread_store = thread_store
        self.report_query_service = report_query_service
        self.finereport_repository = finereport_repository or FineReportReportRepository()
        self._requests: dict[str, AnalysisRunRequest] = {}
        self._run_contexts: dict[str, dict[str, str]] = {}
        self._run_item_counts: dict[str, int] = {}
        self._run_events: dict[str, list[ExplorationRunEvent]] = {}

    def create_run(self, request: AnalysisRunRequest) -> str:
        run_id = f"run_analysis_{uuid4().hex[:12]}"
        self._requests[run_id] = request
        return run_id

    def run(self, request: AnalysisRunRequest) -> list[ExplorationRunEvent]:
        run_id = self.create_run(request)
        return list(self.stream_run_events(run_id))

    def stream_run_events(self, run_id: str) -> Iterable[ExplorationRunEvent]:
        if run_id in self._run_events:
            yield from self._run_events[run_id]
            return
        if self.thread_store:
            stored_items = self.thread_store.get_run_events(run_id)
            if stored_items:
                for item in stored_items:
                    yield ExplorationRunEvent(
                        type=str(item["type"]),
                        run_id=str(item["run_id"]),
                        payload=dict(item.get("payload") or {}),
                        created_at=str(item["created_at"]),
                    )
                return
        request = self._requests.get(run_id)
        if not request:
            yield self._event(run_id, "run.failed", {"error": "run_not_found"})
            return
        yield from self.stream_events(request, run_id=run_id)

    async def astream_run_events(self, run_id: str) -> AsyncIterator[ExplorationRunEvent]:
        for event in self.stream_run_events(run_id):
            yield event

    def stream_events(self, request: AnalysisRunRequest, *, run_id: str | None = None) -> Iterable[ExplorationRunEvent]:
        events = []
        actual_run_id = run_id or f"run_analysis_{uuid4().hex[:12]}"
        for event in self._stream_events_unrecorded(request, run_id=actual_run_id):
            events.append(event)
            yield event
        self._save_run_artifacts(actual_run_id, request, events)

    async def astream_events(
        self,
        request: AnalysisRunRequest,
        *,
        run_id: str | None = None,
    ) -> AsyncIterator[ExplorationRunEvent]:
        events = []
        actual_run_id = run_id or f"run_analysis_{uuid4().hex[:12]}"
        async for event in self._astream_events_unrecorded(request, run_id=actual_run_id):
            events.append(event)
            yield event
        self._save_run_artifacts(actual_run_id, request, events)

    async def _astream_events_unrecorded(
        self,
        request: AnalysisRunRequest,
        *,
        run_id: str,
    ) -> AsyncIterator[ExplorationRunEvent]:
        if not self.agent_runner:
            for event in self._stream_events_unrecorded(request, run_id=run_id):
                yield event
            return

        question = request.question.strip()
        if not question:
            yield self._event(run_id, "run.failed", {"error": "question_required"})
            return

        conversation_id = request.conversation_id or f"conv_analysis_{uuid4().hex[:12]}"
        title = generate_analysis_title(question)
        classification = classify_analysis_problem(question)
        semantic_models = build_semantic_model_plan(classification, request.analysis_mode)

        for event in self._analysis_start_events(
            request=request,
            run_id=run_id,
            question=question,
            conversation_id=conversation_id,
            title=title,
            classification=classification,
            semantic_models=semantic_models,
        ):
            yield event
        run_failed = False
        async for event in self._agent_runner_events_async(run_id, request, classification, semantic_models):
            if event.type == "run.failed":
                run_failed = True
            yield event
        if run_failed:
            return
        yield self._event(
            run_id,
            "run.completed",
            {
                "title": title,
                "status": "completed",
                "analysis_mode": request.analysis_mode,
                "domain": "analysis_task",
            },
        )

    def _stream_events_unrecorded(
        self,
        request: AnalysisRunRequest,
        *,
        run_id: str,
    ) -> Iterable[ExplorationRunEvent]:
        question = request.question.strip()
        if not question:
            yield self._event(run_id, "run.failed", {"error": "question_required"})
            return

        conversation_id = request.conversation_id or f"conv_analysis_{uuid4().hex[:12]}"
        title = generate_analysis_title(question)
        classification = classify_analysis_problem(question)
        semantic_models = build_semantic_model_plan(classification, request.analysis_mode)

        yield from self._analysis_start_events(
            request=request,
            run_id=run_id,
            question=question,
            conversation_id=conversation_id,
            title=title,
            classification=classification,
            semantic_models=semantic_models,
        )

        if self.agent_runner:
            branch_events = list(self._agent_runner_events(run_id, request, classification, semantic_models))
        elif _is_skill_request(question):
            branch_events = list(self._skill_events(run_id, title))
        elif request.turn_kind in {"message", "reply"}:
            branch_events = list(self._continuation_events(run_id, title, request.analysis_mode, question))
        elif request.analysis_mode == "deep":
            branch_events = list(self._deep_analysis_events(run_id, classification))
        else:
            branch_events = list(self._quick_analysis_events(run_id, classification))
        yield from branch_events
        if any(event.type == "run.failed" for event in branch_events):
            return

        yield self._event(
            run_id,
            "run.completed",
            {
                "title": title,
                "status": "completed",
                "analysis_mode": request.analysis_mode,
                "domain": "analysis_task",
            },
        )

    def _analysis_start_events(
        self,
        *,
        request: AnalysisRunRequest,
        run_id: str,
        question: str,
        conversation_id: str,
        title: str,
        classification: ProblemClassification,
        semantic_models: list[SemanticModelCandidate],
    ) -> Iterable[ExplorationRunEvent]:
        self._register_run_context(run_id, conversation_id, request)
        yield self._event(
            run_id,
            "run.created",
            {
                "conversation_id": conversation_id,
                "user_id": request.user_id,
                "question": question,
                "analysis_mode": request.analysis_mode,
                "turn_kind": request.turn_kind,
                "domain": "analysis_task",
            },
        )
        yield self._event(run_id, "agent.title.generated", {"title": title})
        yield self._event(
            run_id,
            "analysis.problem.classified",
            {
                "problem_type": classification.type,
                "label": classification.label,
                "confidence": classification.confidence,
            },
        )
        yield self._event(
            run_id,
            "analysis.retrieval.plan",
            {
                "analysis_mode": request.analysis_mode,
                "items": [candidate.__dict__ for candidate in semantic_models],
            },
        )

    def _agent_runner_events(
        self,
        run_id: str,
        request: AnalysisRunRequest,
        classification: ProblemClassification,
        semantic_models: list[SemanticModelCandidate],
    ) -> Iterable[ExplorationRunEvent]:
        snapshot = self._authorized_data_snapshot(request, run_id=run_id)
        if snapshot:
            yield self._event(run_id, "agent.evidence.available", {"kind": "authorized_aggregate_snapshot", **snapshot})
        report_context = self._authorized_report_context(request)
        semantic_context = self._authorized_semantic_context(request)
        if semantic_context:
            yield self._event(
                run_id,
                "agent.evidence.available",
                {
                    "kind": "authorized_finereport_semantic_summary",
                    "reportCount": len(semantic_context["reports"]),
                    "reportIds": [report["id"] for report in semantic_context["reports"]],
                },
            )
        prompt = build_analysis_runner_prompt(
            question=request.question.strip(),
            analysis_mode=request.analysis_mode,
            problem_label=classification.label,
            semantic_model_labels=[item.label for item in semantic_models],
            authorized_data_snapshot=snapshot,
            authorized_semantic_context=semantic_context,
            current_report_context=report_context,
        )
        yield self._event(
            run_id,
            "agent.runner.started",
            {"runtime": self._agent_runner_runtime(), "domain": "analysis_task"},
        )
        try:
            result = None
            for item in self._run_agent_runner(prompt, run_id=run_id, request=request):
                if isinstance(item, AnalysisAgentRunResult):
                    result = item
                else:
                    yield self._event(run_id, item.type, item.payload)
            if result is None:
                raise RuntimeError("Analysis agent runner did not return a final result.")
        except Exception as exc:  # pragma: no cover - runtime boundary
            yield self._event(
                run_id,
                "agent.runner.failed",
                {"runtime": self._agent_runner_runtime(), "domain": "analysis_task", "error": str(exc)},
            )
            yield self._event(run_id, "run.failed", {"error": "analysis_agent_runner_failed", "detail": str(exc)})
            return
        yield self._event(
            run_id,
            "agent.runner.completed",
            {"runtime": self._agent_runner_runtime(), "domain": "analysis_task", "raw_result_type": result.raw_result_type},
        )
        yield from self._final_result_events(run_id, result, current_report_context=report_context, authorized_data_snapshot=snapshot)
        yield from self._post_runner_events(run_id, request, classification)

    async def _agent_runner_events_async(
        self,
        run_id: str,
        request: AnalysisRunRequest,
        classification: ProblemClassification,
        semantic_models: list[SemanticModelCandidate],
    ) -> AsyncIterator[ExplorationRunEvent]:
        snapshot = self._authorized_data_snapshot(request, run_id=run_id)
        if snapshot:
            yield self._event(run_id, "agent.evidence.available", {"kind": "authorized_aggregate_snapshot", **snapshot})
        report_context = self._authorized_report_context(request)
        semantic_context = self._authorized_semantic_context(request)
        if semantic_context:
            yield self._event(
                run_id,
                "agent.evidence.available",
                {
                    "kind": "authorized_finereport_semantic_summary",
                    "reportCount": len(semantic_context["reports"]),
                    "reportIds": [report["id"] for report in semantic_context["reports"]],
                },
            )
        prompt = build_analysis_runner_prompt(
            question=request.question.strip(),
            analysis_mode=request.analysis_mode,
            problem_label=classification.label,
            semantic_model_labels=[item.label for item in semantic_models],
            authorized_data_snapshot=snapshot,
            authorized_semantic_context=semantic_context,
            current_report_context=report_context,
        )
        yield self._event(
            run_id,
            "agent.runner.started",
            {"runtime": self._agent_runner_runtime(), "domain": "analysis_task"},
        )
        try:
            result = None
            async for item in self._run_agent_runner_async(prompt, run_id=run_id, request=request):
                if isinstance(item, AnalysisAgentRunResult):
                    result = item
                else:
                    yield self._event(run_id, item.type, item.payload)
            if result is None:
                raise RuntimeError("Analysis agent runner did not return a final result.")
        except Exception as exc:  # pragma: no cover - runtime boundary
            yield self._event(
                run_id,
                "agent.runner.failed",
                {"runtime": self._agent_runner_runtime(), "domain": "analysis_task", "error": str(exc)},
            )
            yield self._event(run_id, "run.failed", {"error": "analysis_agent_runner_failed", "detail": str(exc)})
            return
        yield self._event(
            run_id,
            "agent.runner.completed",
            {"runtime": self._agent_runner_runtime(), "domain": "analysis_task", "raw_result_type": result.raw_result_type},
        )
        for event in self._final_result_events(run_id, result, current_report_context=report_context, authorized_data_snapshot=snapshot):
            yield event
        for event in self._post_runner_events(run_id, request, classification):
            yield event

    def _final_result_events(
        self,
        run_id: str,
        result: AnalysisAgentRunResult,
        *,
        current_report_context: dict[str, Any] | None = None,
        authorized_data_snapshot: dict[str, Any] | None = None,
    ) -> Iterable[ExplorationRunEvent]:
        message, draft = extract_interactive_report_draft(result.final_output)
        if message:
            yield self._event(
                run_id,
                "agent.message.created",
                {"role": "assistant", "title": "分析结果", "content": message},
            )
        draft = draft or _fallback_report_draft(current_report_context, authorized_data_snapshot)
        if draft:
            context = self._run_contexts.get(run_id, {})
            draft["artifactType"] = "interactive_report"
            draft["schemaVersion"] = "1.0"
            draft["renderer"] = "puck"
            inherited_report_id = str((current_report_context or {}).get("id") or "").strip()
            draft["id"] = inherited_report_id or f"report_draft_{run_id}"
            draft["source"] = {
                "threadId": context.get("thread_id", ""),
                "turnId": context.get("turn_id", ""),
                "runId": run_id,
            }
            yield self._event(run_id, "interactive_report.draft", draft)

    def _authorized_data_snapshot(self, request: AnalysisRunRequest, *, run_id: str) -> dict[str, Any] | None:
        """Return only a bounded, server-owned aggregate snapshot after explicit per-run consent."""

        if not self.report_query_service or request.metadata.get("data_egress_authorized") is not True:
            return None
        question = request.question
        if not re.search(r"渠道.*(销售|占比)|销售.*渠道", question):
            return None
        month_match = re.search(r"\b(20\d{2}-(?:0[1-9]|1[0-2]))\b", question)
        if not month_match:
            return None
        try:
            query_ref = REGION_CHANNEL_SALES_QUERY_REF if re.search(r"按区域|区域.*(拆|分|渠道)", question) else CHANNEL_SALES_QUERY_REF
            response = self.report_query_service.run(
                query_ref,
                {"month": month_match.group(1)},
                audit_context={
                    "source": "codex_authorized_snapshot",
                    "thread_id": request.conversation_id,
                    "run_id": run_id,
                    "user_id": request.user_id,
                    "data_egress_authorized": True,
                },
            )
        except ReportQueryFilterError:
            return None
        payload = response_to_dict(response)
        return {
            "queryRef": payload["queryRef"],
            "filters": payload["filters"],
            "columns": payload["columns"],
            "rows": payload["rows"],
            "rowCount": payload["rowCount"],
            "truncated": payload["truncated"],
        }

    def _authorized_semantic_context(self, request: AnalysisRunRequest) -> dict[str, Any] | None:
        """Export only the repository's safe semantic summary after per-run consent."""

        if request.metadata.get("semantic_context_egress_authorized") is not True:
            return None
        return self.finereport_repository.build_agent_semantic_context()

    @staticmethod
    def _authorized_report_context(request: AnalysisRunRequest) -> dict[str, Any] | None:
        if request.metadata.get("data_egress_authorized") is not True:
            return None
        return sanitize_interactive_report_context(request.metadata.get("interactive_report_context"))

    def _post_runner_events(
        self,
        run_id: str,
        request: AnalysisRunRequest,
        classification: ProblemClassification,
    ) -> Iterable[ExplorationRunEvent]:
        question = request.question.strip()
        if _is_skill_request(question):
            yield self._event(run_id, "artifact.created", {"path": "skills/analysis_skill.md", "kind": "markdown"})
            return
        if request.turn_kind in {"message", "reply"}:
            yield self._event(run_id, "artifact.updated", {"path": "reports/updated_report.html", "kind": "html"})
            yield self._event(run_id, "artifact.updated", {"path": "queries/revised_query.sql", "kind": "sql"})
            yield self._event(run_id, "artifact.updated", {"path": "paths/channel_analysis_path.md", "kind": "markdown"})
            if re.search(r"python|预测|异常|聚类|相关", question, flags=re.IGNORECASE):
                yield self._event(run_id, "artifact.created", {"path": "scripts/analysis_notebook.py", "kind": "python"})
            return
        if request.analysis_mode == "deep":
            yield self._event(
                run_id,
                "agent.question.requested",
                {
                    "question": build_follow_up_question(classification),
                    "options": [
                        {"id": "member_id", "label": "按会员 ID 去重"},
                        {"id": "phone", "label": "按手机号去重"},
                        {"id": "need_compare", "label": "先对比两种口径"},
                    ],
                },
            )
            return
        for asset in _quick_assets():
            yield self._event(run_id, "artifact.created", asset)

    def _quick_analysis_events(
        self,
        run_id: str,
        classification: ProblemClassification,
    ) -> Iterable[ExplorationRunEvent]:
        yield self._event(
            run_id,
            "agent.message.created",
            {
                "role": "assistant",
                "title": "快速分析初稿",
                "content": (
                    f"我先按快速分析推进：这个问题更像「{classification.label}」。"
                    "我会先复用语义模型、知识库和历史 SQL 示例生成可用初稿，"
                    "并把未确认口径作为假设标注到报告里。"
                ),
            },
        )
        for asset in _quick_assets():
            yield self._event(run_id, "artifact.created", asset)

    def _deep_analysis_events(
        self,
        run_id: str,
        classification: ProblemClassification,
    ) -> Iterable[ExplorationRunEvent]:
        yield self._event(
            run_id,
            "agent.message.created",
            {
                "role": "assistant",
                "title": "深度分析准备",
                "content": (
                    f"我会按深度分析推进：先确认「{classification.label}」的业务口径，"
                    "再生成 SQL、图表、报告和可复用资产。"
                ),
            },
        )
        yield self._event(
            run_id,
            "agent.question.requested",
            {
                "question": build_follow_up_question(classification),
                "options": [
                    {"id": "member_id", "label": "按会员 ID 去重"},
                    {"id": "phone", "label": "按手机号去重"},
                    {"id": "need_compare", "label": "先对比两种口径"},
                ],
            },
        )

    def _continuation_events(
        self,
        run_id: str,
        title: str,
        analysis_mode: AnalysisMode,
        question: str,
    ) -> Iterable[ExplorationRunEvent]:
        if analysis_mode == "deep":
            content = "我会基于当前分析任务继续改资产：保留已有版本，补充证据，再更新报告、SQL 和可复用方法。"
        else:
            content = "我会先直接更新当前资产草稿，并继续把未确认业务假设保留在说明里。"
        yield self._event(run_id, "agent.message.created", {"role": "assistant", "title": title, "content": content})
        yield self._event(run_id, "artifact.updated", {"path": "reports/updated_report.html", "kind": "html"})
        yield self._event(run_id, "artifact.updated", {"path": "queries/revised_query.sql", "kind": "sql"})
        yield self._event(run_id, "artifact.updated", {"path": "paths/channel_analysis_path.md", "kind": "markdown"})
        if re.search(r"python|预测|异常|聚类|相关", question, flags=re.IGNORECASE):
            yield self._event(run_id, "artifact.created", {"path": "scripts/analysis_notebook.py", "kind": "python"})

    def _skill_events(self, run_id: str, title: str) -> Iterable[ExplorationRunEvent]:
        yield self._event(
            run_id,
            "agent.message.created",
            {
                "role": "assistant",
                "title": title,
                "content": (
                    "我会把这次成功分析整理成 Skill.md 草稿：包含适用场景、必须确认的业务口径、"
                    "推荐步骤、引用资产和复用权限。"
                ),
            },
        )
        yield self._event(run_id, "artifact.created", {"path": "skills/analysis_skill.md", "kind": "markdown"})

    def _event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> ExplorationRunEvent:
        enriched_payload = dict(payload)
        enriched_payload.setdefault("run_id", run_id)
        context = self._run_contexts.get(run_id)
        if context:
            enriched_payload.setdefault("thread_id", context["thread_id"])
            enriched_payload.setdefault("turn_id", context["turn_id"])
            enriched_payload.setdefault("conversation_id", context["thread_id"])
        item_kind = item_kind_for_event(event_type, enriched_payload)
        if item_kind:
            enriched_payload.setdefault("item_kind", item_kind)
            enriched_payload.setdefault("item_id", self._next_item_id(run_id, item_kind))
        return ExplorationRunEvent(type=event_type, run_id=run_id, payload=enriched_payload)

    def _register_run_context(self, run_id: str, thread_id: str, request: AnalysisRunRequest) -> None:
        turn_id = str(request.metadata.get("turn_id") or f"turn_{run_id.removeprefix('run_')}")
        self._run_contexts[run_id] = {"thread_id": thread_id, "turn_id": turn_id}

    def _next_item_id(self, run_id: str, item_kind: str) -> str:
        next_index = self._run_item_counts.get(run_id, 0) + 1
        self._run_item_counts[run_id] = next_index
        return f"item_{run_id.removeprefix('run_')}_{next_index:04d}_{item_kind}"

    def _run_agent_runner(self, prompt: str, *, run_id: str, request: AnalysisRunRequest) -> Iterable[Any]:
        if not self.agent_runner:
            return []
        stream = getattr(self.agent_runner, "stream", None)
        if callable(stream):
            try:
                return stream(prompt, context=self._agent_runner_context(run_id, request))
            except TypeError:
                return stream(prompt)
        return [self.agent_runner.run(prompt)]

    async def _run_agent_runner_async(self, prompt: str, *, run_id: str, request: AnalysisRunRequest) -> AsyncIterator[Any]:
        if not self.agent_runner:
            return
        async_stream = getattr(self.agent_runner, "async_stream", None)
        if callable(async_stream):
            try:
                async_items = async_stream(prompt, context=self._agent_runner_context(run_id, request))
            except TypeError:
                async_items = async_stream(prompt)
            async for item in async_items:
                yield item
            return
        for item in self._run_agent_runner(prompt, run_id=run_id, request=request):
            yield item

    def _agent_runner_context(self, run_id: str, request: AnalysisRunRequest) -> dict[str, Any]:
        context = self._run_contexts.get(run_id, {})
        thread_id = context.get("thread_id")
        return {
            "genbi_thread_id": thread_id,
            "genbi_turn_id": context.get("turn_id"),
            "genbi_run_id": run_id,
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

    def _save_run_artifacts(self, run_id: str, request: AnalysisRunRequest, events: list[ExplorationRunEvent]) -> None:
        context = self._run_contexts.get(run_id, {})
        runtime = self._agent_runner_runtime()
        codex_thread_id = _latest_payload_value(events, "codex_thread_id") or self._resolve_runtime_thread_id(
            request,
            thread_id=context.get("thread_id"),
            runtime=runtime,
        )
        metadata = {
            "domain": "analysis_task",
            "analysis_mode": request.analysis_mode,
            "thread_id": context.get("thread_id"),
            "turn_id": context.get("turn_id"),
            **(request.metadata or {}),
        }
        if codex_thread_id:
            metadata["codex_thread_id"] = codex_thread_id
            runtime_threads = dict(metadata.get("runtime_threads") or {})
            runtime_threads[runtime] = codex_thread_id
            metadata["runtime_threads"] = runtime_threads
        self._run_events[run_id] = list(events)
        if self.thread_store and context.get("thread_id") and context.get("turn_id"):
            try:
                self.thread_store.save_run(
                    thread_id=context["thread_id"],
                    turn_id=context["turn_id"],
                    run_id=run_id,
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
        request: AnalysisRunRequest,
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


def generate_analysis_title(question: str) -> str:
    text = re.sub(r"\s+", " ", question).strip(" \t\r\n。！？!?")
    if not text:
        return "未命名分析"
    text = re.sub(r"^(请|帮我|麻烦|先|看看|分析一下|问一下)[，,：:\s]*", "", text)
    if len(text) > 24:
        text = text[:24].rstrip()
    return text or "未命名分析"


def classify_analysis_problem(question: str) -> ProblemClassification:
    normalized = question.lower()
    if re.search(r"异常|下滑|上涨|原因|归因|波动", normalized):
        return ProblemClassification(type="metric_diagnosis", label="异常归因", confidence=0.84)
    if re.search(r"复购|留存|口径|定义|怎么算|指标", normalized):
        return ProblemClassification(type="metric_definition", label="指标口径", confidence=0.82)
    if re.search(r"报表|finereport|看懂|解释|字段", normalized):
        return ProblemClassification(type="report_understanding", label="报表理解", confidence=0.78)
    if re.search(r"复盘|经营|月度|季度|gmv|销售占比|渠道", normalized):
        return ProblemClassification(type="business_review", label="经营复盘", confidence=0.8)
    return ProblemClassification(type="business_analysis", label="业务分析", confidence=0.72)


def build_semantic_model_plan(
    classification: ProblemClassification,
    analysis_mode: AnalysisMode,
) -> list[SemanticModelCandidate]:
    base = [
        SemanticModelCandidate(
            id="semantic_sql_examples",
            label="SQL 示例语义模型",
            model_type="query_semantic_model",
            source="历史 SQL / Vanna 候选样例",
            purpose="寻找可复用查询写法和字段口径",
        ),
        SemanticModelCandidate(
            id="semantic_mysql_doris_metadata",
            label="MySQL / Doris 元数据语义模型",
            model_type="metadata_semantic_model",
            source="information_schema / catalog",
            purpose="确认表、字段、类型和可查询范围",
        ),
        SemanticModelCandidate(
            id="knowledge_confirmed_experience",
            label="知识库已确认业务经验",
            model_type="knowledge_semantic_model",
            source="知识库",
            purpose="复用已确认口径、排除规则和业务解释",
        ),
    ]
    if analysis_mode == "quick":
        return base
    return [
        SemanticModelCandidate(
            id="semantic_finereport_report",
            label="FineReport 报表级语义模型",
            model_type="report_semantic_model",
            source="FineReport 解析器",
            purpose="理解报表如何组织指标、维度、取数和交互",
        ),
        *base,
        SemanticModelCandidate(
            id="semantic_kingdee_dictionary",
            label="金蝶数据字典语义模型",
            model_type="dictionary_semantic_model",
            source="金蝶数据字典",
            purpose="对齐业务实体和系统字段含义",
        ),
        SemanticModelCandidate(
            id="semantic_etl_lineage",
            label="ETL / Hop 血缘语义模型",
            model_type="lineage_semantic_model",
            source="Apache Hop / ETL",
            purpose="追踪字段来源、加工路径和刷新边界",
        ),
        SemanticModelCandidate(
            id=f"analysis_context_{classification.type}",
            label="历史分析资产",
            model_type="analysis_asset_model",
            source="分析资产库",
            purpose="复用相似问题的报告、SQL、图表和 Skill",
        ),
    ]


def _fallback_report_draft(
    current_report_context: dict[str, Any] | None,
    authorized_data_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep the right-side result continuous when a constrained Codex reply omits only its report envelope."""

    if not authorized_data_snapshot:
        return None
    query_ref = str(authorized_data_snapshot.get("queryRef") or "")
    if not current_report_context:
        return _initial_snapshot_report_draft(authorized_data_snapshot)
    if query_ref != REGION_CHANNEL_SALES_QUERY_REF:
        return None
    report = copy.deepcopy(current_report_context)
    report["title"] = f"{str(report['title']).strip()}（按区域拆分）"
    report["subtitle"] = "已切换为服务端登记的区域 × 渠道聚合视图；数值以本轮受控查询结果为准。"
    dataset_id = "region_channel_sales"
    report["queries"][query_ref] = {
        "datasetId": dataset_id,
        "filterBindings": ["month", "brand", "region"],
    }
    report["chartSpecs"]["region-channel-sales-chart"] = {
        "id": "region-channel-sales-chart",
        "datasetId": dataset_id,
        "type": "bar",
        "xField": "region",
        "title": "区域渠道销售额",
        "series": [{"field": "salesAmount", "label": "销售额", "format": "currency"}],
    }
    report["gridSpecs"]["region-channel-sales-grid"] = {
        "id": "region-channel-sales-grid",
        "datasetId": dataset_id,
        "pageSize": 12,
        "columns": [
            {"field": "region", "label": "区域"},
            {"field": "channel", "label": "渠道"},
            {"field": "salesAmount", "label": "销售额", "format": "currency"},
            {"field": "salesShare", "label": "销售占比", "format": "percent"},
            {"field": "netRevenue", "label": "收入净额", "format": "currency"},
            {"field": "refundAmount", "label": "退款金额", "format": "currency"},
        ],
    }
    content = report["document"].get("content", [])
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("props"), dict):
            continue
        if block.get("type") == "ChartBlock":
            block["props"]["chartSpecRef"] = "region-channel-sales-chart"
            block["props"]["queryRef"] = query_ref
        elif block.get("type") == "GridBlock":
            block["props"]["gridSpecRef"] = "region-channel-sales-grid"
            block["props"]["queryRef"] = query_ref
    return report


def _initial_snapshot_report_draft(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    """Create a minimal, server-owned report when an authorized first-run response omits its draft."""

    query_ref = str(snapshot.get("queryRef") or "")
    filters = snapshot.get("filters")
    if query_ref not in {CHANNEL_SALES_QUERY_REF, REGION_CHANNEL_SALES_QUERY_REF} or not isinstance(filters, dict):
        return None

    month = str(filters.get("month") or "本期")
    is_region_view = query_ref == REGION_CHANNEL_SALES_QUERY_REF
    dataset_id = "region_channel_sales" if is_region_view else "channel_sales"
    chart_id = "region-channel-sales-chart" if is_region_view else "channel-sales-chart"
    grid_id = "region-channel-sales-grid" if is_region_view else "channel-sales-grid"
    subject = "区域 × 渠道销售结构" if is_region_view else "渠道销售结构"
    chart_x_field = "region" if is_region_view else "channel"
    grid_columns = ([
        {"field": "region", "label": "区域"},
        {"field": "channel", "label": "渠道"},
    ] if is_region_view else [{"field": "channel", "label": "渠道"}]) + [
        {"field": "salesAmount", "label": "销售额", "format": "currency"},
        {"field": "salesShare", "label": "销售占比", "format": "percent"},
        {"field": "netRevenue", "label": "收入净额", "format": "currency"},
        {"field": "refundAmount", "label": "退款金额", "format": "currency"},
    ]
    return {
        "title": f"{month} {subject}",
        "subtitle": "基于服务端受控聚合查询生成；筛选仅改变运行时数据视图。",
        "document": {
            "root": {"props": {"title": f"{month} {subject}"}},
            "content": [
                {"type": "SectionBlock", "props": {"id": "summary-section", "title": "本期结论", "tone": "coral"}},
                {"type": "MarkdownBlock", "props": {"id": "summary-note", "content": "本报告使用本轮已授权的受控聚合数据。具体结论请结合左侧分析说明与下方明细复核。"}},
                {"type": "KpiBlock", "props": {"id": "kpi-sales", "metric": "sales"}},
                {"type": "KpiBlock", "props": {"id": "kpi-share", "metric": "share"}},
                {"type": "SectionBlock", "props": {"id": "contribution-section", "title": subject, "tone": "navy"}},
                {"type": "ChartBlock", "props": {"id": "sales-chart", "chartSpecRef": chart_id, "queryRef": query_ref}},
                {"type": "SectionBlock", "props": {"id": "detail-section", "title": "聚合明细", "tone": "navy"}},
                {"type": "GridBlock", "props": {"id": "sales-grid", "gridSpecRef": grid_id, "queryRef": query_ref}},
                {"type": "EvidenceBlock", "props": {"id": "evidence", "label": "数据证据", "content": "来源：FineReport 财务经营管报日报的服务端登记只读聚合查询。未读取业务明细，也未在浏览器提交 SQL。"}},
            ],
            "zones": {},
        },
        "filters": [
            {"id": "month", "label": "月份", "defaultValue": month, "options": [{"label": month, "value": month}]},
            {"id": "brand", "label": "品牌", "defaultValue": "all", "options": [{"label": "全部品牌", "value": "all"}]},
            {"id": "region", "label": "区域", "defaultValue": "all", "options": [{"label": "全部区域", "value": "all"}]},
        ],
        "queries": {query_ref: {"datasetId": dataset_id, "filterBindings": ["month", "brand", "region"]}},
        "chartSpecs": {
            chart_id: {
                "id": chart_id,
                "datasetId": dataset_id,
                "type": "bar",
                "xField": chart_x_field,
                "title": "销售额",
                "series": [{"field": "salesAmount", "label": "销售额", "format": "currency"}],
            }
        },
        "gridSpecs": {grid_id: {"id": grid_id, "datasetId": dataset_id, "pageSize": 12, "columns": grid_columns}},
    }


def item_kind_for_event(event_type: str, payload: dict[str, Any]) -> str | None:
    if event_type == "run.created" and payload.get("question"):
        return "message"
    if event_type == "analysis.retrieval.plan" or event_type == "run.plan.updated":
        return "plan"
    if event_type == "agent.question.requested":
        return "question"
    if event_type == "agent.message.created":
        return "message"
    if event_type == "interactive_report.draft":
        return "report"
    if event_type in {"tool.call.started", "tool.call.completed", "tool.call.failed"}:
        return "tool_call" if event_type == "tool.call.started" else "tool_result"
    if event_type in {"artifact.created", "artifact.updated"}:
        kind = str(payload.get("kind") or "")
        if kind == "sql":
            return "sql"
        if kind == "json" and ".chart." in str(payload.get("path") or ""):
            return "chart"
        if kind == "html" or "report" in str(payload.get("path") or ""):
            return "report"
        return "artifact"
    return None


def _latest_payload_value(events: list[ExplorationRunEvent], key: str) -> str | None:
    for event in reversed(events):
        value = _string_or_none(event.payload.get(key))
        if value:
            return value
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_follow_up_question(classification: ProblemClassification) -> str:
    if classification.type == "metric_definition":
        return "这个指标口径需要先确认：首购和复购按会员 ID、手机号，还是订单主体去重？退款和未支付订单是否排除？"
    if classification.type == "metric_diagnosis":
        return "这次归因要优先按哪个维度拆解：渠道、门店、SKU、区域，还是新老客？"
    if classification.type == "report_understanding":
        return "这张报表要优先解释业务口径、取数逻辑，还是交互筛选规则？"
    return "这次分析要优先保证速度，还是优先补齐业务口径和验证范围？"


def _is_skill_request(question: str) -> bool:
    return bool(
        re.search(
            r"skill\.md|skill|技能|沉淀成\s*skill|整理成\s*skill|生成\s*skill|复用方法|可复用方法",
            question,
            flags=re.IGNORECASE,
        )
    )


def _quick_assets() -> list[dict[str, str]]:
    return [
        {"path": "reports/quick_report.html", "kind": "html"},
        {"path": "queries/quick_candidate.sql", "kind": "sql"},
        {"path": "charts/channel_share.chart.json", "kind": "json"},
        {"path": "notes/assumptions.md", "kind": "markdown"},
        {"path": "definitions/channel_sales_metric.md", "kind": "markdown"},
        {"path": "rules/order_scope_rule.md", "kind": "markdown"},
        {"path": "paths/channel_analysis_path.md", "kind": "markdown"},
        {"path": "dashboards/channel_overview.dashboard.json", "kind": "json"},
    ]
