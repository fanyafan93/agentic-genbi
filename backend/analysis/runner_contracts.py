from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Iterable, Protocol

from backend.exploration.agent_runner import ExplorationAgentRunnerEvent


@dataclass(frozen=True)
class AnalysisAgentRunResult:
    final_output: str
    raw_result_type: str
    events: list[ExplorationAgentRunnerEvent] = field(default_factory=list)


class AnalysisAgentRunner(Protocol):
    def run(self, prompt: str) -> AnalysisAgentRunResult: ...

    def stream(self, prompt: str) -> Iterable[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]: ...

    def async_stream(self, prompt: str) -> AsyncIterator[ExplorationAgentRunnerEvent | AnalysisAgentRunResult]: ...


def build_analysis_runner_prompt(
    *,
    question: str,
    analysis_mode: str,
    problem_label: str,
    semantic_model_labels: list[str],
) -> str:
    mode_description = (
        "快速分析：少追问，先给可用初稿并标注假设。"
        if analysis_mode == "quick"
        else "深度分析：先补齐业务口径和验证范围，再产出可靠资产。"
    )
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
