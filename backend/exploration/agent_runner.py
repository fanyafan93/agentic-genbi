from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Protocol


@dataclass(frozen=True)
class ExplorationAgentRunResult:
    final_output: str
    raw_result_type: str
    events: list["ExplorationAgentRunnerEvent"] = field(default_factory=list)


@dataclass(frozen=True)
class ExplorationAgentRunnerEvent:
    type: str
    payload: dict[str, Any]


class ExplorationAgentRunner(Protocol):
    def run(self, question: str) -> ExplorationAgentRunResult: ...

    def stream(self, question: str) -> Iterable[ExplorationAgentRunnerEvent | ExplorationAgentRunResult]: ...

    def async_stream(self, question: str) -> AsyncIterator[ExplorationAgentRunnerEvent | ExplorationAgentRunResult]: ...


def _final_output_to_text(value: Any) -> str:
    if isinstance(value, str):
        return _strip_reasoning_tags(value)
    if hasattr(value, "model_dump_json"):
        return _strip_reasoning_tags(value.model_dump_json())
    return _strip_reasoning_tags(str(value))


def _bounded_value(value: Any, *, max_chars: int = 2000) -> str:
    text = _final_output_to_text(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated]"


def _strip_reasoning_tags(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    return cleaned.replace("数据探索 Agent", "知识探索 Agent")
