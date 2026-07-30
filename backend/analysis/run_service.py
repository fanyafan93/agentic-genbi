from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Literal
from uuid import uuid4

from backend.analysis.agent_runner import AnalysisAgentRunResult, AnalysisAgentRunner, build_analysis_runner_prompt
from backend.exploration.run_event_store import RunEventStore
from backend.exploration.run_service import ExplorationRunEvent
from backend.exploration.run_trace_store import RunTraceStore

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
    ) -> None:
        self.agent_runner = agent_runner
        self.trace_store = trace_store
        self.event_store = event_store
        self._requests: dict[str, AnalysisRunRequest] = {}

    def create_run(self, request: AnalysisRunRequest) -> str:
        run_id = f"run_analysis_{uuid4().hex[:12]}"
        self._requests[run_id] = request
        return run_id

    def run(self, request: AnalysisRunRequest) -> list[ExplorationRunEvent]:
        run_id = self.create_run(request)
        return list(self.stream_run_events(run_id))

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
        prompt = build_analysis_runner_prompt(
            question=request.question.strip(),
            analysis_mode=request.analysis_mode,
            problem_label=classification.label,
            semantic_model_labels=[item.label for item in semantic_models],
        )
        yield self._event(
            run_id,
            "agent.runner.started",
            {"runtime": "openai-agents-sdk", "domain": "analysis_task"},
        )
        try:
            result = None
            for item in self._run_agent_runner(prompt):
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
                {"runtime": "openai-agents-sdk", "domain": "analysis_task", "error": str(exc)},
            )
            yield self._event(run_id, "run.failed", {"error": "analysis_agent_runner_failed", "detail": str(exc)})
            return
        yield self._event(
            run_id,
            "agent.runner.completed",
            {"runtime": "openai-agents-sdk", "domain": "analysis_task", "raw_result_type": result.raw_result_type},
        )
        yield self._event(
            run_id,
            "agent.message.created",
            {"role": "assistant", "title": "分析结果", "content": result.final_output},
        )
        yield from self._post_runner_events(run_id, request, classification)

    async def _agent_runner_events_async(
        self,
        run_id: str,
        request: AnalysisRunRequest,
        classification: ProblemClassification,
        semantic_models: list[SemanticModelCandidate],
    ) -> AsyncIterator[ExplorationRunEvent]:
        prompt = build_analysis_runner_prompt(
            question=request.question.strip(),
            analysis_mode=request.analysis_mode,
            problem_label=classification.label,
            semantic_model_labels=[item.label for item in semantic_models],
        )
        yield self._event(
            run_id,
            "agent.runner.started",
            {"runtime": "openai-agents-sdk", "domain": "analysis_task"},
        )
        try:
            result = None
            async for item in self._run_agent_runner_async(prompt):
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
                {"runtime": "openai-agents-sdk", "domain": "analysis_task", "error": str(exc)},
            )
            yield self._event(run_id, "run.failed", {"error": "analysis_agent_runner_failed", "detail": str(exc)})
            return
        yield self._event(
            run_id,
            "agent.runner.completed",
            {"runtime": "openai-agents-sdk", "domain": "analysis_task", "raw_result_type": result.raw_result_type},
        )
        yield self._event(
            run_id,
            "agent.message.created",
            {"role": "assistant", "title": "分析结果", "content": result.final_output},
        )
        for event in self._post_runner_events(run_id, request, classification):
            yield event

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
        return ExplorationRunEvent(type=event_type, run_id=run_id, payload=payload)

    def _run_agent_runner(self, prompt: str) -> Iterable[Any]:
        if not self.agent_runner:
            return []
        stream = getattr(self.agent_runner, "stream", None)
        if callable(stream):
            return stream(prompt)
        return [self.agent_runner.run(prompt)]

    async def _run_agent_runner_async(self, prompt: str) -> AsyncIterator[Any]:
        if not self.agent_runner:
            return
        async_stream = getattr(self.agent_runner, "async_stream", None)
        if callable(async_stream):
            async for item in async_stream(prompt):
                yield item
            return
        for item in self._run_agent_runner(prompt):
            yield item

    def _save_run_artifacts(self, run_id: str, request: AnalysisRunRequest, events: list[ExplorationRunEvent]) -> None:
        metadata = {"domain": "analysis_task", "analysis_mode": request.analysis_mode, **(request.metadata or {})}
        if self.event_store:
            try:
                self.event_store.save_events(run_id=run_id, events=events)
            except Exception:
                pass
        if self.trace_store:
            try:
                self.trace_store.save_trace(run_id=run_id, request=request, events=events, metadata=metadata)
            except Exception:
                pass


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
