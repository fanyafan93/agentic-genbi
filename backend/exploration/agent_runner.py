from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Protocol

from backend.config import load_project_env
from backend.resource_library.database_tools import ReadonlyDatabaseTools
from backend.resource_library.exploration_agent import build_data_exploration_agent
from backend.resource_library.knowledge_store import KnowledgeStore
from backend.resource_library.tools import ResourceLibrary


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


SUPPORTED_LLM_PROVIDERS = {"openai", "minimax"}
OPENAI_COMPATIBLE_PROVIDERS = {"minimax"}


@dataclass(frozen=True)
class LLMProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str | None = None

    @classmethod
    def from_env(cls) -> "LLMProviderConfig":
        load_project_env()
        provider = os.getenv("GENBI_LLM_PROVIDER", "openai").strip().lower() or "openai"
        model = _provider_model(provider)
        api_key = _provider_api_key(provider)
        base_url = _provider_base_url(provider)
        return cls(provider=provider, model=model, api_key=api_key, base_url=base_url)

    def validate(self) -> None:
        if self.provider not in SUPPORTED_LLM_PROVIDERS:
            raise RuntimeError(f"Unsupported GENBI_LLM_PROVIDER={self.provider}. Supported providers: {', '.join(sorted(SUPPORTED_LLM_PROVIDERS))}.")
        if not self.api_key:
            raise RuntimeError(f"{_provider_key_env_name(self.provider)} is required when GENBI_EXPLORATION_RUNTIME enables the LLM runner.")
        if not self.model:
            raise RuntimeError("GENBI_EXPLORATION_MODEL is required for the selected LLM provider.")
        if self.provider in OPENAI_COMPATIBLE_PROVIDERS and not self.base_url:
            raise RuntimeError(f"{_provider_base_url_env_name(self.provider)} is required for GENBI_LLM_PROVIDER={self.provider}.")


class LLMAgentRunner:
    def __init__(
        self,
        *,
        resource_library: ResourceLibrary | None = None,
        db_tools: ReadonlyDatabaseTools | None = None,
        knowledge_store: KnowledgeStore | None = None,
        model: str | None = None,
        provider_config: LLMProviderConfig | None = None,
        max_turns: int = 30,
    ) -> None:
        self.resource_library = resource_library
        self.db_tools = db_tools
        self.knowledge_store = knowledge_store
        config = provider_config or LLMProviderConfig.from_env()
        if model:
            config = LLMProviderConfig(
                provider=config.provider,
                model=model,
                api_key=config.api_key,
                base_url=config.base_url,
            )
        self.provider_config = config
        self.max_turns = max_turns

    @classmethod
    def from_env(
        cls,
        *,
        resource_library: ResourceLibrary | None = None,
        db_tools: ReadonlyDatabaseTools | None = None,
        knowledge_store: KnowledgeStore | None = None,
    ) -> "LLMAgentRunner":
        load_project_env()
        return cls(
            resource_library=resource_library,
            db_tools=db_tools,
            knowledge_store=knowledge_store,
            provider_config=LLMProviderConfig.from_env(),
            max_turns=int(os.getenv("GENBI_EXPLORATION_MAX_TURNS", "30")),
        )

    def run(self, question: str) -> ExplorationAgentRunResult:
        load_project_env()
        self.provider_config.validate()
        return asyncio.run(self._run(question))

    def stream(self, question: str) -> Iterable[ExplorationAgentRunnerEvent | ExplorationAgentRunResult]:
        load_project_env()
        self.provider_config.validate()
        result = asyncio.run(self._run_streamed(question))
        yield from result.events
        yield result

    async def async_stream(self, question: str) -> AsyncIterator[ExplorationAgentRunnerEvent | ExplorationAgentRunResult]:
        load_project_env()
        self.provider_config.validate()
        async for item in self._iter_streamed(question):
            yield item

    async def _run(self, question: str) -> ExplorationAgentRunResult:
        from agents import Runner

        agent = build_data_exploration_agent(
            resource_library=self.resource_library,
            db_tools=self.db_tools,
            knowledge_store=self.knowledge_store,
            model=self._build_agent_model(),
        )
        result = await Runner.run(agent, question, max_turns=self.max_turns)
        return ExplorationAgentRunResult(
            final_output=_final_output_to_text(getattr(result, "final_output", result)),
            raw_result_type=type(result).__name__,
        )

    async def _run_streamed(self, question: str) -> ExplorationAgentRunResult:
        events = []
        result = None
        async for item in self._iter_streamed(question):
            if isinstance(item, ExplorationAgentRunResult):
                result = item
            else:
                events.append(item)
        if result is None:
            raise RuntimeError("OpenAI Agents SDK streamed run did not return a final result.")
        return ExplorationAgentRunResult(
            final_output=result.final_output,
            raw_result_type=result.raw_result_type,
            events=events,
        )

    async def _iter_streamed(self, question: str) -> AsyncIterator[ExplorationAgentRunnerEvent | ExplorationAgentRunResult]:
        from agents import Runner

        agent = build_data_exploration_agent(
            resource_library=self.resource_library,
            db_tools=self.db_tools,
            knowledge_store=self.knowledge_store,
            model=self._build_agent_model(),
        )
        result = Runner.run_streamed(agent, question, max_turns=self.max_turns)
        tool_names_by_call_id: dict[str, str] = {}
        async for event in result.stream_events():
            normalized = normalize_agents_sdk_stream_event(event, tool_names_by_call_id=tool_names_by_call_id)
            if normalized:
                yield normalized
        yield ExplorationAgentRunResult(
            final_output=_final_output_to_text(getattr(result, "final_output", "")),
            raw_result_type=type(result).__name__,
        )

    def _build_agent_model(self) -> Any:
        config = self.provider_config
        if config.provider == "openai" and not config.base_url:
            return config.model

        from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
        from openai import AsyncOpenAI

        return OpenAIChatCompletionsModel(
            model=config.model,
            openai_client=AsyncOpenAI(api_key=config.api_key, base_url=config.base_url),
        )


class OpenAIAgentsSdkRunner(LLMAgentRunner):
    """Backward-compatible name for the default OpenAI Agents SDK runner."""

    @classmethod
    def from_env(
        cls,
        *,
        resource_library: ResourceLibrary | None = None,
        db_tools: ReadonlyDatabaseTools | None = None,
        knowledge_store: KnowledgeStore | None = None,
    ) -> "OpenAIAgentsSdkRunner":
        load_project_env()
        return cls(
            resource_library=resource_library,
            db_tools=db_tools,
            knowledge_store=knowledge_store,
            provider_config=LLMProviderConfig.from_env(),
            max_turns=int(os.getenv("GENBI_EXPLORATION_MAX_TURNS", "30")),
        )


def _final_output_to_text(value: Any) -> str:
    if isinstance(value, str):
        return _strip_reasoning_tags(value)
    if hasattr(value, "model_dump_json"):
        return _strip_reasoning_tags(value.model_dump_json())
    return _strip_reasoning_tags(str(value))


def _extract_message_text(value: Any) -> str:
    """提取 OpenAI Responses/Chat message 中的纯文本 content。

    OpenAI SDK 的 message 对象结构是 `content: [{"type": "output_text", "text": "..."}, ...]`。
    我们要拿到所有 text 字段拼起来，不要把整个对象 JSON 化推给前端。
    """
    parts: list[str] = []
    content = getattr(value, "content", None)
    if content is None and isinstance(value, dict):
        content = value.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            else:
                text = getattr(item, "text", None)
                if isinstance(text, str):
                    parts.append(text)
    elif content is not None:
        text = getattr(content, "text", None)
        if isinstance(text, str):
            parts.append(text)
    if not parts:
        return _final_output_to_text(value)
    return _strip_reasoning_tags("\n".join(parts))


TOOL_LABELS = {
    "search_resources": "搜索资源库",
    "inspect_resource": "查看资源结构",
    "read_resource_excerpt": "读取资源片段",
    "search_db_tables": "搜索数据表",
    "get_table_schema": "查看表结构",
    "inspect_table_profile": "查看表画像",
    "run_readonly_query": "执行只读 SQL",
    "save_verified_knowledge": "沉淀知识",
}


def normalize_agents_sdk_stream_event(event: Any, *, tool_names_by_call_id: dict[str, str] | None = None) -> ExplorationAgentRunnerEvent | None:
    event_type = getattr(event, "type", type(event).__name__)
    if event_type == "agent_updated_stream_event":
        agent = getattr(event, "new_agent", None)
        return ExplorationAgentRunnerEvent(
            type="agent.runner.agent_updated",
            payload={"agent": getattr(agent, "name", str(agent))},
        )
    if event_type == "run_item_stream_event":
        name = getattr(event, "name", "")
        item = getattr(event, "item", None)
        if name in {"tool_called", "tool_search_called"}:
            tool = _tool_name(item)
            call_id = _call_id(item)
            if tool_names_by_call_id is not None and call_id and tool != "unknown_tool":
                tool_names_by_call_id[call_id] = tool
            return ExplorationAgentRunnerEvent(
                type="tool.call.started",
                payload={
                    **_tool_payload(tool),
                    "call_id": call_id,
                    "sdk_event": name,
                    "raw_item_type": getattr(item, "type", type(item).__name__),
                },
            )
        if name in {"tool_output", "tool_search_output_created"}:
            call_id = _call_id(item)
            tool = _tool_name(item)
            if tool == "unknown_tool" and tool_names_by_call_id is not None and call_id:
                tool = tool_names_by_call_id.get(call_id, tool)
            return ExplorationAgentRunnerEvent(
                type="tool.call.completed",
                payload={
                    **_tool_payload(tool),
                    "call_id": call_id,
                    "sdk_event": name,
                    "output": _bounded_value(getattr(item, "output", None)),
                    "raw_item_type": getattr(item, "type", type(item).__name__),
                },
            )
        if name == "message_output_created":
            return None
        return ExplorationAgentRunnerEvent(
            type="agent.runner.item",
            payload={"sdk_event": name, "raw_item_type": getattr(item, "type", type(item).__name__)},
        )
    if event_type == "raw_response_event":
        data = getattr(event, "data", None)
        raw_type = getattr(data, "type", type(data).__name__)
        payload = {"sdk_event": raw_type}
        usage = _usage_payload(data)
        if usage:
            payload["usage"] = usage
        return ExplorationAgentRunnerEvent(
            type="agent.runner.raw",
            payload=payload,
        )
    return ExplorationAgentRunnerEvent(type="agent.runner.raw", payload={"sdk_event": str(event_type)})


def _tool_name(item: Any) -> str:
    value = getattr(item, "tool_name", None)
    if value:
        return str(value)
    raw_item = getattr(item, "raw_item", None)
    if isinstance(raw_item, dict):
        return str(raw_item.get("name") or "unknown_tool")
    return str(getattr(raw_item, "name", "unknown_tool"))


def _tool_payload(tool: str) -> dict[str, str]:
    label = TOOL_LABELS.get(tool, "未知工具" if tool == "unknown_tool" else tool)
    return {
        "tool": tool,
        "tool_label": label,
        "tool_label_full": f"{label} {tool}" if tool != label else tool,
    }


def _call_id(item: Any) -> str | None:
    value = getattr(item, "call_id", None)
    if value:
        return str(value)
    raw_item = getattr(item, "raw_item", None)
    if isinstance(raw_item, dict):
        value = raw_item.get("call_id") or raw_item.get("id")
        return str(value) if value is not None else None
    value = getattr(raw_item, "call_id", None) or getattr(raw_item, "id", None)
    return str(value) if value is not None else None


def _bounded_value(value: Any, *, max_chars: int = 2000) -> str:
    text = _final_output_to_text(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated]"


def _strip_reasoning_tags(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    return cleaned.replace("数据探索 Agent", "知识探索 Agent")


def _usage_payload(value: Any) -> dict[str, int]:
    usage = getattr(value, "usage", None)
    if usage is None:
        response = getattr(value, "response", None)
        usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    elif not isinstance(usage, dict):
        usage = {
            key: getattr(usage, key)
            for key in ("input_tokens", "output_tokens", "total_tokens", "prompt_tokens", "completion_tokens")
            if getattr(usage, key, None) is not None
        }
    result = {}
    for source, target in (
        ("input_tokens", "input_tokens"),
        ("prompt_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("completion_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        current = usage.get(source)
        if isinstance(current, int):
            result[target] = current
        elif isinstance(current, float):
            result[target] = int(current)
    return result


def _provider_model(provider: str) -> str:
    value = os.getenv("GENBI_EXPLORATION_MODEL", "").strip()
    if value:
        return value
    if provider == "openai":
        return "gpt-4.1-mini"
    return ""


def _provider_api_key(provider: str) -> str:
    generic = os.getenv("GENBI_LLM_API_KEY", "").strip()
    if generic:
        return generic
    if provider == "minimax":
        return os.getenv("MINIMAX_API_KEY", "").strip()
    return os.getenv("OPENAI_API_KEY", "").strip()


def _provider_base_url(provider: str) -> str | None:
    generic = os.getenv("GENBI_LLM_BASE_URL", "").strip()
    if generic:
        return generic
    if provider == "minimax":
        return os.getenv("MINIMAX_BASE_URL", "").strip() or None
    return os.getenv("OPENAI_BASE_URL", "").strip() or None


def _provider_key_env_name(provider: str) -> str:
    if provider == "minimax":
        return "MINIMAX_API_KEY or GENBI_LLM_API_KEY"
    return "OPENAI_API_KEY or GENBI_LLM_API_KEY"


def _provider_base_url_env_name(provider: str) -> str:
    if provider == "minimax":
        return "MINIMAX_BASE_URL or GENBI_LLM_BASE_URL"
    return "OPENAI_BASE_URL or GENBI_LLM_BASE_URL"
