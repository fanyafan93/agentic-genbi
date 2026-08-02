from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Protocol


@dataclass(frozen=True)
class AnalysisAgentRunnerEvent:
    type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class AnalysisAgentResult:
    final_output: str
    raw_result_type: str
    events: list[AnalysisAgentRunnerEvent] = field(default_factory=list)


class AnalysisAgentRunner(Protocol):
    def run(self, prompt: str) -> AnalysisAgentResult: ...

    def stream(self, prompt: str) -> Iterable[AnalysisAgentRunnerEvent | AnalysisAgentResult]: ...

    def async_stream(self, prompt: str) -> AsyncIterator[AnalysisAgentRunnerEvent | AnalysisAgentResult]: ...


def build_analysis_runner_prompt(
    *,
    question: str,
    problem_label: str,
    semantic_model_labels: list[str],
) -> str:
    return "\n".join(
        [
            f"用户问题：{question}",
            f"初步问题类型：{problem_label}",
            "可参考的语义模型：",
            *[f"- {label}" for label in semantic_model_labels],
            "请输出适合分析任务前端展示的中文回复。",
            "没有真实工具结果时，不得编造表、字段、指标、金额、占比或增长结论。",
            "分析资产只能由已注册工具创建或更新；不要在回复中输出报告 JSON、工具参数或伪造的资产内容。",
        ]
    )


def final_output_to_text(value: Any) -> str:
    if isinstance(value, str):
        return strip_reasoning_tags(value)
    if hasattr(value, "model_dump_json"):
        return strip_reasoning_tags(value.model_dump_json())
    return strip_reasoning_tags(str(value))


def bounded_value(value: Any, *, max_chars: int = 2000) -> str:
    text = final_output_to_text(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated]"


def strip_reasoning_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
