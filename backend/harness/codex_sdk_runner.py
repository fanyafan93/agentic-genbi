from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterable

from backend.config import load_project_env
from backend.harness.events import AgentEvent


CODEX_ANALYSIS_INSTRUCTIONS = """
你是 Agentic GenBI 的分析任务 Agent。
围绕用户提出的业务问题推进分析：必要时说明应检索业务语义库、确认口径、调用受控数据工具，并产出可复用分析资产。
当前最小接入阶段还没有开放真实业务工具；不能编造表、字段、指标、数据结果或权限。
输出中文，明确下一步建议生成或更新哪些分析资产。
""".strip()


@dataclass(frozen=True)
class CodexSdkRunnerContext:
    genbi_thread_id: str | None = None
    genbi_turn_id: str | None = None
    codex_thread_id: str | None = None
    cwd: str | None = None


class CodexSdkAnalysisRuntime:
    """Thin adapter from the official openai-codex SDK to GenBI persistence."""

    runtime_name = "openai-codex"

    def __init__(
        self,
        *,
        model: str | None = None,
        cwd: str | None = None,
        codex_factory: Callable[[], Any] | None = None,
        async_codex_factory: Callable[[], Any] | None = None,
    ) -> None:
        load_project_env()
        self.provider = _codex_provider_from_env()
        self.model = model or _codex_model_from_env(self.provider)
        self.cwd = cwd or os.getenv("GENBI_CODEX_CWD", "").strip() or str(Path.cwd())
        self.api_key = _codex_api_key_from_env(self.provider)
        self.base_url = _codex_base_url_from_env(self.provider)
        self._codex_factory = codex_factory
        self._async_codex_factory = async_codex_factory
        self.enabled = True

    @classmethod
    def from_env(cls) -> "CodexSdkAnalysisRuntime":
        load_project_env()
        return cls()

    @classmethod
    def disabled(cls) -> "CodexSdkAnalysisRuntime":
        runtime = cls(codex_factory=lambda: None, async_codex_factory=lambda: None)
        runtime.enabled = False
        return runtime

    def stream(
        self,
        question: str,
        *,
        context: dict[str, Any] | CodexSdkRunnerContext | None = None,
    ) -> Iterable[AgentEvent]:
        return asyncio.run(self._collect_stream(question, context=context))

    async def async_stream(
        self,
        question: str,
        *,
        context: dict[str, Any] | CodexSdkRunnerContext | None = None,
    ) -> AsyncIterator[AgentEvent]:
        async for item in self._iter_streamed(question, context=context):
            yield item

    async def _collect_stream(
        self,
        question: str,
        *,
        context: dict[str, Any] | CodexSdkRunnerContext | None = None,
    ) -> list[AgentEvent]:
        items: list[AgentEvent] = []
        async for item in self._iter_streamed(question, context=context):
            items.append(item)
        return items

    async def _iter_streamed(
        self,
        question: str,
        *,
        context: dict[str, Any] | CodexSdkRunnerContext | None = None,
    ) -> AsyncIterator[AgentEvent]:
        if not self.enabled:
            yield AgentEvent(
                type="turn/completed",
                turn_id=_context_turn_id(context),
                payload={
                    "eventSource": "codex",
                    "status": "failed",
                    "error": "codex_runtime_not_configured",
                },
            )
            return
        runner_context = _normalize_context(context, default_cwd=self.cwd)
        codex_thread_id: str | None = runner_context.codex_thread_id

        try:
            async with self._make_async_codex() as codex:
                await self._login_if_configured(codex)
                thread = await self._open_thread(codex, runner_context)
                codex_thread_id = str(getattr(thread, "id", codex_thread_id or ""))

                turn = await thread.turn(question, **self._turn_kwargs(runner_context))
                async for notification in turn.stream():
                    event = self._notification_to_event(notification, codex_thread_id=codex_thread_id)
                    if event:
                        yield event
        except ImportError as exc:
            raise RuntimeError("Install the `openai-codex` Python package to use GENBI_ANALYSIS_RUNTIME=codex.") from exc

    def _make_async_codex(self) -> Any:
        if self._async_codex_factory:
            return self._async_codex_factory()
        from openai_codex import AsyncCodex, CodexConfig

        return AsyncCodex(
            CodexConfig(
                config_overrides=tuple(self._config_overrides()),
                cwd=self.cwd,
                env=self._codex_env() or None,
            )
        )

    async def _login_if_configured(self, codex: Any) -> None:
        if self.provider != "openai" or not self.api_key:
            return
        login_api_key = getattr(codex, "login_api_key", None)
        if not callable(login_api_key):
            return
        await login_api_key(self.api_key)

    async def _open_thread(self, codex: Any, context: CodexSdkRunnerContext) -> Any:
        thread_kwargs = self._thread_kwargs(context)
        if context.codex_thread_id:
            return await codex.thread_resume(context.codex_thread_id, **thread_kwargs)
        return await codex.thread_start(**thread_kwargs)

    def _thread_kwargs(self, context: CodexSdkRunnerContext) -> dict[str, Any]:
        from openai_codex import ApprovalMode, Sandbox

        kwargs: dict[str, Any] = {
            "approval_mode": ApprovalMode.deny_all,
            "developer_instructions": CODEX_ANALYSIS_INSTRUCTIONS,
            "cwd": context.cwd,
            "sandbox": Sandbox.read_only,
        }
        if self.model:
            kwargs["model"] = self.model
        if self.provider != "openai":
            kwargs["model_provider"] = self.provider
        return kwargs

    def _turn_kwargs(self, context: CodexSdkRunnerContext) -> dict[str, Any]:
        from openai_codex import ApprovalMode, Sandbox

        kwargs: dict[str, Any] = {
            "approval_mode": ApprovalMode.deny_all,
            "cwd": context.cwd,
            "sandbox": Sandbox.read_only,
        }
        if self.model:
            kwargs["model"] = self.model
        return kwargs

    def _config_overrides(self) -> list[str]:
        if self.provider == "openai":
            return []
        env_key = _provider_env_key(self.provider)
        return [
            f"model_providers.{self.provider}.name={_toml_string(self.provider)}",
            f"model_providers.{self.provider}.base_url={_toml_string(self.base_url)}",
            f"model_providers.{self.provider}.env_key={_toml_string(env_key)}",
            f"model_providers.{self.provider}.wire_api=\"responses\"",
        ]

    def _codex_env(self) -> dict[str, str]:
        if self.provider == "openai" or not self.api_key:
            return {}
        return {_provider_env_key(self.provider): self.api_key}

    def _notification_to_event(self, notification: Any, *, codex_thread_id: str | None) -> AgentEvent | None:
        method = str(getattr(notification, "method", "") or "")
        payload = getattr(notification, "payload", None)
        turn_id = _payload_turn_id(payload) or "codex_turn_pending"
        if method == "turn/started":
            return AgentEvent(
                type="turn/started",
                turn_id=turn_id,
                payload={
                    "runtime": "openai-codex",
                    "eventSource": "codex",
                    "codex_method": method,
                    "codex_thread_id": codex_thread_id,
                    "codex_turn_id": _payload_turn_id(payload),
                },
            )
        if method == "item/agentMessage/delta":
            delta = str(getattr(payload, "delta", "") or "")
            if not delta:
                return None
            return AgentEvent(
                type="item/agentMessage/delta",
                turn_id=turn_id,
                payload={
                    "role": "assistant",
                    "eventSource": "codex",
                    "delta": delta,
                    "codex_method": method,
                    "codex_thread_id": codex_thread_id,
                    "codex_turn_id": _payload_turn_id(payload),
                    "codex_item_id": _payload_item_id(payload),
                },
            )
        if method == "item/completed":
            item = _payload_item(payload)
            root = getattr(item, "root", item)
            root_type = _item_type(root)
            codex_item_id = _item_id(root)
            if _is_agent_message(root):
                text = _item_text(root)
                if text:
                    return AgentEvent(
                        type="item/completed",
                        turn_id=turn_id,
                        payload={
                            "runtime": "openai-codex",
                            "eventSource": "codex",
                            "codex_method": method,
                            "role": "assistant",
                            "content": text,
                            "codex_thread_id": codex_thread_id,
                            "codex_turn_id": _payload_turn_id(payload),
                            "codex_item_id": codex_item_id,
                            "codex_item_type": root_type,
                        },
                )
            return AgentEvent(
                type="item/completed",
                turn_id=turn_id,
                payload={
                    "runtime": "openai-codex",
                    "eventSource": "codex",
                    "codex_method": method,
                    "codex_thread_id": codex_thread_id,
                    "codex_turn_id": _payload_turn_id(payload),
                    "codex_item_id": codex_item_id,
                    "codex_item_type": root_type,
                },
            )
        if method == "turn/completed":
            status = _turn_status(payload) or ""
            error = _turn_error(payload)
            completed_payload = {
                "runtime": "openai-codex",
                "eventSource": "codex",
                "codex_method": method,
                "codex_thread_id": codex_thread_id,
                "codex_turn_id": _payload_turn_id(payload),
                "status": status,
            }
            if error:
                completed_payload["error"] = error
            return AgentEvent(
                type="turn/completed",
                turn_id=turn_id,
                payload=completed_payload,
            )
        return None


def _normalize_context(
    context: dict[str, Any] | CodexSdkRunnerContext | None,
    *,
    default_cwd: str | None,
) -> CodexSdkRunnerContext:
    if isinstance(context, CodexSdkRunnerContext):
        return context
    data = dict(context or {})
    return CodexSdkRunnerContext(
        genbi_thread_id=_string_or_none(data.get("genbi_thread_id") or data.get("thread_id")),
        genbi_turn_id=_string_or_none(data.get("genbi_turn_id") or data.get("turn_id")),
                codex_thread_id=_string_or_none(data.get("codex_thread_id")),
        cwd=_string_or_none(data.get("cwd")) or default_cwd,
    )


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _context_turn_id(context: dict[str, Any] | CodexSdkRunnerContext | None) -> str:
    if isinstance(context, CodexSdkRunnerContext):
        return context.genbi_turn_id or "codex_turn_unavailable"
    data = dict(context or {})
    return _string_or_none(data.get("genbi_turn_id") or data.get("turn_id")) or "codex_turn_unavailable"


def _collect_agent_text(items: Iterable[Any]) -> str:
    texts: list[str] = []
    for item in items:
        root = getattr(item, "root", item)
        if _is_agent_message(root):
            text = _item_text(root)
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _payload_item(payload: Any) -> Any | None:
    if payload is None:
        return None
    return getattr(payload, "item", None)


def _payload_turn_id(payload: Any) -> str | None:
    if payload is None:
        return None
    turn = getattr(payload, "turn", None)
    return _string_or_none(getattr(turn, "id", None) or getattr(payload, "turn_id", None) or getattr(payload, "turnId", None))


def _payload_item_id(payload: Any) -> str | None:
    item = _payload_item(payload)
    root = getattr(item, "root", item)
    return _item_id(root)


def _item_type(root: Any) -> str:
    explicit_type = str(getattr(root, "type", "") or "")
    if explicit_type:
        return explicit_type
    return type(root).__name__


def _item_id(root: Any) -> str | None:
    return _string_or_none(getattr(root, "id", None) or getattr(root, "item_id", None) or getattr(root, "itemId", None))


def _is_agent_message(root: Any) -> bool:
    root_type = _item_type(root)
    return root_type == "agentMessage" or "AgentMessage" in root_type


def _item_text(root: Any) -> str:
    return str(getattr(root, "text", "") or "")


def _turn_status(completed_payload: Any) -> str | None:
    turn = getattr(completed_payload, "turn", None)
    status = getattr(turn, "status", None)
    value = getattr(status, "value", None) or status
    if value is None:
        return None
    return str(value)


def _turn_error(completed_payload: Any) -> str | None:
    turn = getattr(completed_payload, "turn", None)
    error = getattr(turn, "error", None)
    message = getattr(error, "message", None) or error
    return _string_or_none(message)


def _codex_provider_from_env() -> str:
    explicit = os.getenv("GENBI_CODEX_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    provider = os.getenv("GENBI_LLM_PROVIDER", "").strip().lower()
    if provider == "minimax":
        return "minimax"
    return "openai"


def _codex_model_from_env(provider: str) -> str | None:
    for key in ("GENBI_CODEX_MODEL", "GENBI_ANALYSIS_MODEL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    if provider == "minimax":
        return os.getenv("MINIMAX_MODEL", "").strip() or "MiniMax-M3"
    return None


def _codex_api_key_from_env(provider: str) -> str | None:
    if provider == "minimax":
        return (
            os.getenv("GENBI_CODEX_API_KEY", "").strip()
            or os.getenv("MINIMAX_API_KEY", "").strip()
            or None
        )
    return (
        os.getenv("GENBI_CODEX_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
        or None
    )


def _codex_base_url_from_env(provider: str) -> str:
    if provider == "minimax":
        return (
            os.getenv("GENBI_CODEX_BASE_URL", "").strip()
            or os.getenv("GENBI_LLM_BASE_URL", "").strip()
            or os.getenv("MINIMAX_BASE_URL", "").strip()
            or "https://api.minimaxi.com/v1"
        )
    return os.getenv("GENBI_CODEX_BASE_URL", "").strip() or "https://api.openai.com/v1"


def _provider_env_key(provider: str) -> str:
    if provider == "minimax":
        return "MINIMAX_API_KEY"
    return f"{provider.upper()}_API_KEY"


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


