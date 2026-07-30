from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Protocol

from backend.config import load_project_env
from backend.exploration.agent_runner import (
    ExplorationAgentRunnerEvent,
    LLMProviderConfig,
    _final_output_to_text,
    normalize_agents_sdk_stream_event,
)


ANALYSIS_AGENT_NAME = "Analysis Task Agent"

ANALYSIS_AGENT_INSTRUCTIONS = """
你的固定身份名称是：Agentic GenBI 分析任务 Agent。
服务对象是 BI 分析师和运营人员。

你的任务是围绕一个待解决的业务问题推进分析任务：
1. 先判断问题类型和需要的业务口径。
2. 根据快速分析或深度分析模式决定是否先追问。
3. 需要时调用语义模型、知识库、历史 SQL、元数据和受控数据工具。
4. 产出或更新可复用分析资产，包括报告、SQL、图表、指标口径、业务规则、分析路径、dashboard 片段或 SKILL.md。
5. 对未确认的业务口径必须标注假设和风险；深度分析应优先追问。
6. 不编造表、字段、报表、指标、数据结果或权限。
7. 不能绕过服务端权限、SQL 安全和数据源访问边界。

当前如果没有可用工具或证据，请明确说明还需要检索语义模型或向用户确认，不要伪造已经查询的数据。
""".strip()


@dataclass(frozen=True)
class AnalysisAgentRunResult:
    final_output: str
    raw_result_type: str
    events: list[ExplorationAgentRunnerEvent] = field(default_factory=list)


class AnalysisAgentRunner(Protocol):
    def run(self, prompt: str) -> AnalysisAgentRunResult: ...

    def stream(self, prompt: str) -> Iterable[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]: ...

    def async_stream(self, prompt: str) -> AsyncIterator[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]: ...


@dataclass(frozen=True)
class AnalysisLLMProviderConfig:
    provider_config: LLMProviderConfig

    @classmethod
    def from_env(cls) -> "AnalysisLLMProviderConfig":
        load_project_env()
        config = LLMProviderConfig.from_env()
        analysis_model = os.getenv("GENBI_ANALYSIS_MODEL", "").strip()
        if analysis_model:
            config = LLMProviderConfig(
                provider=config.provider,
                model=analysis_model,
                api_key=config.api_key,
                base_url=config.base_url,
            )
        return cls(provider_config=config)

    def validate(self) -> None:
        try:
            self.provider_config.validate()
        except RuntimeError as exc:
            raise RuntimeError(str(exc).replace("GENBI_EXPLORATION", "GENBI_ANALYSIS")) from exc


class OpenAIAnalysisAgentRunner:
    def __init__(
        self,
        *,
        provider_config: AnalysisLLMProviderConfig | None = None,
        max_turns: int = 30,
    ) -> None:
        self.provider_config = provider_config or AnalysisLLMProviderConfig.from_env()
        self.max_turns = max_turns

    @classmethod
    def from_env(cls) -> "OpenAIAnalysisAgentRunner":
        load_project_env()
        return cls(
            provider_config=AnalysisLLMProviderConfig.from_env(),
            max_turns=int(os.getenv("GENBI_ANALYSIS_MAX_TURNS", "30")),
        )

    def run(self, prompt: str) -> AnalysisAgentRunResult:
        load_project_env()
        self.provider_config.validate()
        return asyncio.run(self._run(prompt))

    def stream(self, prompt: str) -> Iterable[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]:
        load_project_env()
        self.provider_config.validate()
        result = asyncio.run(self._run_streamed(prompt))
        yield from result.events
        yield result

    async def async_stream(self, prompt: str) -> AsyncIterator[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]:
        load_project_env()
        self.provider_config.validate()
        async for item in self._iter_streamed(prompt):
            yield item

    async def _run(self, prompt: str) -> AnalysisAgentRunResult:
        from agents import Runner

        agent = build_analysis_agent(model=self._build_agent_model())
        result = await Runner.run(agent, prompt, max_turns=self.max_turns)
        return AnalysisAgentRunResult(
            final_output=_final_output_to_text(getattr(result, "final_output", result)),
            raw_result_type=type(result).__name__,
        )

    async def _run_streamed(self, prompt: str) -> AnalysisAgentRunResult:
        events = []
        result = None
        async for item in self._iter_streamed(prompt):
            if isinstance(item, AnalysisAgentRunResult):
                result = item
            else:
                events.append(item)
        if result is None:
            raise RuntimeError("OpenAI Agents SDK streamed analysis run did not return a final result.")
        return AnalysisAgentRunResult(
            final_output=result.final_output,
            raw_result_type=result.raw_result_type,
            events=events,
        )

    async def _iter_streamed(self, prompt: str) -> AsyncIterator[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]:
        from agents import Runner

        agent = build_analysis_agent(model=self._build_agent_model())
        result = Runner.run_streamed(agent, prompt, max_turns=self.max_turns)
        tool_names_by_call_id: dict[str, str] = {}
        async for event in result.stream_events():
            normalized = normalize_agents_sdk_stream_event(event, tool_names_by_call_id=tool_names_by_call_id)
            if normalized:
                yield normalized
        yield AnalysisAgentRunResult(
            final_output=_final_output_to_text(getattr(result, "final_output", "")),
            raw_result_type=type(result).__name__,
        )

    def _build_agent_model(self) -> Any:
        config = self.provider_config.provider_config
        if config.provider == "openai" and not config.base_url:
            return config.model

        from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
        from openai import AsyncOpenAI

        return OpenAIChatCompletionsModel(
            model=config.model,
            openai_client=AsyncOpenAI(api_key=config.api_key, base_url=config.base_url),
        )


def build_analysis_agent(*, model: Any = "gpt-4.1-mini") -> Any:
    try:
        from agents import Agent
    except ImportError as exc:
        raise RuntimeError("Install the OpenAI Agents SDK package `openai-agents` to build the analysis agent.") from exc
    return Agent(
        name=ANALYSIS_AGENT_NAME,
        instructions=ANALYSIS_AGENT_INSTRUCTIONS,
        model=model,
    )


def build_analysis_runner_prompt(
    *,
    question: str,
    analysis_mode: str,
    problem_label: str,
    semantic_model_labels: list[str],
) -> str:
    mode_description = "快速分析：少追问，先给可用初稿并标注假设。" if analysis_mode == "quick" else "深度分析：先补齐业务口径和验证范围，再产出可靠资产。"
    return "\n".join(
        [
            f"用户问题：{question}",
            f"分析模式：{mode_description}",
            f"初步问题类型：{problem_label}",
            "可参考的语义模型：",
            *[f"- {label}" for label in semantic_model_labels],
            "请输出适合分析任务前端展示的中文回复，并明确下一步需要生成或更新的分析资产。",
        ]
    )

