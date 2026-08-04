from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Iterable

from backend.config import load_project_env
from backend.harness.codex_mcp_config import (
    load_runtime_codex_mcp_servers_from_env,
    to_codex_config_overrides,
)
from backend.harness.events import AgentEvent
from backend.harness.minimax_codex_adapter import adapter_base_url, adapter_enabled


CODEX_ANALYSIS_INSTRUCTIONS = """
围绕用户提出的业务问题推进分析。

- 涉及真实业务数据时，必须先查证，不能编造表、字段、指标、金额、占比或增长结论。
- 报告里只输出有据可查的数据和明确的下一步建议。
- 输出中文。
""".strip()


CODEX_ANALYSIS_INSTRUCTIONS = """
围绕用户提出的业务问题推进分析。
- 涉及真实业务数据时，必须先查证，不能编造表、字段、指标、金额、占比或增长结论。
- 报告只输出有据可查的数据和明确下一步建议。
- 需要生成右侧交互式报告时，先用数据工具取得真实聚合数据，再调用 GenBI_report.create_interactive_report；不要把完整报告正文写在聊天回复中。
- 输出中文。
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
        codex_bin: str | None = None,
        codex_factory: Callable[[], Any] | None = None,
        async_codex_factory: Callable[[], Any] | None = None,
    ) -> None:
        load_project_env()
        self.provider = _codex_provider_from_env()
        self.model = model or _codex_model_from_env(self.provider)
        self.cwd = cwd or os.getenv("GENBI_CODEX_CWD", "").strip() or str(Path.cwd())
        self.api_key = _codex_api_key_from_env(self.provider)
        self.base_url = _codex_base_url_from_env(self.provider)
        self.codex_bin = (
            codex_bin
            if codex_bin is not None
            else _resolve_configured_codex_bin(os.getenv("GENBI_CODEX_BIN", "").strip())
        )
        # Codex CLI reads config from $CODEX_HOME/config.toml at startup. Render
        # provider + MCP config into a runtime-only directory so deploys that
        # lack a baked-in ~/.codex/config.toml still pick up our overrides.
        raw_mcp_servers = load_runtime_codex_mcp_servers_from_env()
        default_tools_enabled = _codex_default_tools_enabled_from_env()
        self.codex_home = os.getenv("GENBI_CODEX_HOME", "").strip() or None
        if not self.codex_home and (self.provider != "openai" or raw_mcp_servers):
            self.codex_home = tempfile.mkdtemp(prefix="genbi-codex-home-")
        if self.codex_home:
            _render_codex_home_config(
                self.codex_home,
                provider=self.provider,
                base_url=self.base_url,
                api_key_env=_provider_env_key(self.provider),
                mcp_servers=raw_mcp_servers,
                default_tools_enabled=default_tools_enabled,
            )
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
        provisioned_turn_id = _context_turn_id(context)

        try:
            async with self._make_async_codex() as codex:
                await self._login_if_configured(codex)
                thread = await self._open_thread(codex, runner_context)
                codex_thread_id = str(getattr(thread, "id", codex_thread_id or ""))
                # Emit the provisioned-thread marker BEFORE any other event so
                # GenBI Runtime can persist the analysis thread with the
                # Codex-issued id as its primary key. ``id == codex_thread_id``
                # is the new-session contract.
                yield AgentEvent(
                    type="genbi/thread/provisioned",
                    turn_id=provisioned_turn_id,
                    payload={
                        "eventSource": "genbi",
                        "runtime": "openai-codex",
                        "codex_thread_id": codex_thread_id,
                        "thread_id": codex_thread_id,
                    },
                )

                turn = await thread.turn(question, **self._turn_kwargs(runner_context))
                provisioned_codex_turn_id = _string_or_none(getattr(turn, "id", None))
                if provisioned_codex_turn_id:
                    # Surface the Codex-issued turn id BEFORE the first turn
                    # notification so downstream code can use it as the turn
                    # primary key (``analysis_turns.id == codex_turn_id``).
                    yield AgentEvent(
                        type="genbi/turn/provisioned",
                        turn_id=provisioned_codex_turn_id,
                        payload={
                            "eventSource": "genbi",
                            "runtime": "openai-codex",
                            "codex_thread_id": codex_thread_id,
                            "codex_turn_id": provisioned_codex_turn_id,
                            "thread_id": codex_thread_id,
                            "turn_id": provisioned_codex_turn_id,
                        },
                    )
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

        env = self._codex_env() or {}
        if self.codex_home:
            env["CODEX_HOME"] = self.codex_home
        return AsyncCodex(
            CodexConfig(
                codex_bin=self.codex_bin,
                config_overrides=tuple(self._config_overrides()),
                cwd=self.cwd,
                env=env or None,
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
            "approval_mode": ApprovalMode.auto_review,
            "developer_instructions": CODEX_ANALYSIS_INSTRUCTIONS,
            "cwd": context.cwd,
            "sandbox": Sandbox.read_only,
        }
        if self.model:
            kwargs["model"] = self.model
        if self.provider != "openai":
            kwargs["model_provider"] = self.provider
        thread_config = _analysis_thread_config()
        if thread_config:
            kwargs["config"] = thread_config
        return kwargs

    def _turn_kwargs(self, context: CodexSdkRunnerContext) -> dict[str, Any]:
        from openai_codex import ApprovalMode, Sandbox

        kwargs: dict[str, Any] = {
            "approval_mode": ApprovalMode.auto_review,
            "cwd": context.cwd,
            "sandbox": Sandbox.read_only,
        }
        if self.model:
            kwargs["model"] = self.model
        return kwargs

    def _config_overrides(self) -> list[str]:
        overrides: list[str] = []
        if self.provider != "openai":
            env_key = _provider_env_key(self.provider)
            overrides.extend(
                [
                    f"model_providers.{self.provider}.name={_toml_string(self.provider)}",
                    f"model_providers.{self.provider}.base_url={_toml_string(self.base_url)}",
                    f"model_providers.{self.provider}.env_key={_toml_string(env_key)}",
                    f"model_providers.{self.provider}.wire_api=\"responses\"",
                ]
            )
        default_tools_enabled = _codex_default_tools_enabled_from_env()
        if default_tools_enabled is not None:
            overrides.append(f"default_tools_enabled={_toml_bool(default_tools_enabled)}")
        raw_mcp_servers = load_runtime_codex_mcp_servers_from_env()
        overrides.extend(to_codex_config_overrides(raw_mcp_servers))
        return overrides

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
                    **_mcp_tool_call_payload(root),
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


def _mcp_tool_call_payload(root: Any) -> dict[str, Any]:
    if _item_type(root) != "mcpToolCall":
        return {}
    error = getattr(root, "error", None)
    error_message = _string_or_none(getattr(error, "message", None) or error)
    out: dict[str, Any] = {
        "mcp_server": _string_or_none(getattr(root, "server", None)),
        "mcp_tool": _string_or_none(getattr(root, "tool", None)),
        "mcp_status": _string_or_none(getattr(getattr(root, "status", None), "value", None) or getattr(root, "status", None)),
        "mcp_arguments": getattr(root, "arguments", None),
    }
    result = _mcp_tool_result(root)
    if result is not None:
        out["mcp_result"] = result
    if error_message:
        out["mcp_error"] = error_message
    return out


def _mcp_tool_result(root: Any) -> Any:
    for name in ("result", "output", "content"):
        value = getattr(root, name, None)
        if value is not None:
            return _jsonable(value)
    return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


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
        if adapter_enabled():
            return adapter_base_url()
        return (
            os.getenv("GENBI_CODEX_BASE_URL", "").strip()
            or os.getenv("GENBI_LLM_BASE_URL", "").strip()
            or os.getenv("MINIMAX_BASE_URL", "").strip()
            or "https://api.minimaxi.com/v1"
        )
    return os.getenv("GENBI_CODEX_BASE_URL", "").strip() or "https://api.openai.com/v1"


def _resolve_configured_codex_bin(value: str | None) -> str | None:
    if value:
        path = Path(value)
        if path.exists():
            return value
    for candidate in (shutil.which("codex.exe"), shutil.which("codex")):
        if candidate and "WindowsApps" not in candidate:
            return candidate
    return None


def _provider_env_key(provider: str) -> str:
    if provider == "minimax":
        return "MINIMAX_API_KEY"
    return f"{provider.upper()}_API_KEY"


def _analysis_thread_config() -> dict[str, Any]:
    default_tools_enabled = _codex_default_tools_enabled_from_env()
    if default_tools_enabled is None:
        return {}
    return {"default_tools_enabled": default_tools_enabled}


def _codex_default_tools_enabled_from_env() -> bool | None:
    raw_value = os.getenv("GENBI_CODEX_DEFAULT_TOOLS_ENABLED", "false").strip().lower()
    if not raw_value or raw_value in {"unset", "default"}:
        return None
    return raw_value not in {"0", "false", "off", "no", "disabled"}


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_codex_home_config(
    codex_home: str,
    *,
    provider: str,
    base_url: str,
    api_key_env: str,
    mcp_servers: list[Any],
    default_tools_enabled: bool | None = None,
) -> None:
    """Write $CODEX_HOME/config.toml from current runtime configuration.

    Codex CLI always reads $CODEX_HOME/config.toml at startup. We render a
    minimal but valid file containing model provider overrides and any
    configured MCP servers so the SDK does not need to rely on the
    ``CodexConfig.config_overrides`` injection path.
    """
    home = Path(codex_home)
    home.mkdir(parents=True, exist_ok=True)
    config_path = home / "config.toml"
    lines: list[str] = []
    if default_tools_enabled is not None:
        lines.extend([f"default_tools_enabled={_toml_bool(default_tools_enabled)}", ""])
    if provider and provider != "openai":
        lines.extend(
            [
                f"model_providers.{provider}.name={_toml_string(provider)}",
                f"model_providers.{provider}.base_url={_toml_string(base_url)}",
                f"model_providers.{provider}.env_key={_toml_string(api_key_env)}",
                f'model_providers.{provider}.wire_api="responses"',
                "",
            ]
        )
    for server in mcp_servers:
        lines.append(f"mcp_servers.{server.name}.command={_toml_string(server.command)}")
        if server.args:
            lines.append(f"mcp_servers.{server.name}.args={_toml_array(server.args)}")
        for env_key, env_value in server.env.items():
            lines.append(
                f"mcp_servers.{server.name}.env.{env_key}={_toml_string(env_value)}"
            )
        lines.append("")
    config_path.write_text("\n".join(lines), encoding="utf-8")


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(item) for item in values) + "]"


