from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_sdk_runner import (
    CODEX_ANALYSIS_INSTRUCTIONS,
    CodexSdkAnalysisRuntime,
    CodexSdkRunnerContext,
)
from backend.system_management.model_connections import ModelRuntimeConnection


class _FakeAsyncCodex:
    def __init__(self) -> None:
        self.started_kwargs = None
        self.resumed = None
        self.login_api_key_value = None
        self.last_thread = None

    async def __aenter__(self) -> "_FakeAsyncCodex":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def thread_start(self, **kwargs):
        self.started_kwargs = kwargs
        self.last_thread = _FakeThread("codex_thread_started")
        return self.last_thread

    async def thread_resume(self, thread_id: str, **kwargs):
        self.resumed = (thread_id, kwargs)
        self.last_thread = _FakeThread(thread_id)
        return self.last_thread

    async def login_api_key(self, api_key: str) -> None:
        self.login_api_key_value = api_key


class _FakeThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id
        self.turn_input = None

    async def turn(self, question, **kwargs):
        self.turn_input = question
        return _FakeTurn("codex_turn_1", kwargs)


class _FakeTurn:
    def __init__(self, turn_id: str, kwargs: dict) -> None:
        self.id = turn_id
        self.question = kwargs.get("question", "")
        self.kwargs = kwargs

    async def stream(self):
        yield SimpleNamespace(method="turn/started", payload=SimpleNamespace(turn=SimpleNamespace(id="codex_turn_1")))
        yield SimpleNamespace(
            method="item/agentMessage/delta",
            payload=SimpleNamespace(turn=SimpleNamespace(id="codex_turn_1"), item=SimpleNamespace(root=SimpleNamespace(id="codex_item_msg")), delta="part 1"),
        )
        yield SimpleNamespace(
            method="item/completed",
            payload=SimpleNamespace(
                turn=SimpleNamespace(id="codex_turn_1"),
                item=SimpleNamespace(root=SimpleNamespace(id="codex_item_msg", type="agentMessage", text="complete text")),
            ),
        )
        yield SimpleNamespace(
            method="turn/completed",
            payload=SimpleNamespace(turn=SimpleNamespace(id="codex_turn_1", status=SimpleNamespace(value="completed"))),
        )


class _RecordingReportToolRegistry:
    def __init__(self, *, incomplete: bool = False) -> None:
        self.reserved = None
        self.bound = None
        self.released = None
        self.incomplete = incomplete

    def reserve(self, **kwargs):
        self.reserved = kwargs
        return "signed-report-tool-token"

    def execution_id(self, token: str) -> str:
        return "report-execution-1"

    def bind(self, token: str, *, session_id: str, turn_id: str) -> None:
        self.bound = (token, session_id, turn_id)

    def has_incomplete_report_build(self, execution_id: str) -> bool:
        return self.incomplete

    def release(self, token: str) -> None:
        self.released = token


class CodexSdkAnalysisRuntimeTest(unittest.TestCase):
    def test_analysis_instructions_do_not_duplicate_codex_identity_or_mcp_catalog(self) -> None:
        self.assertNotIn("openai-codex", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("BI_doris", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("mysql_query", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("8.134.63.30", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("dm.dm_channel_mtsg_sale_total", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn("涉及真实业务数据时，必须先查证", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn("不能编造表、字段、指标、金额、占比或增长结论", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn("start_report_build", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn("publish_report_build", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn(
            "不要单独输出计划或进度文本",
            CODEX_ANALYSIS_INSTRUCTIONS,
        )
        self.assertIn(
            "dataSource 只使用 doris 或 mysql",
            CODEX_ANALYSIS_INSTRUCTIONS,
        )
        self.assertIn(
            "publish_report_build 成功前不得结束当前 Turn",
            CODEX_ANALYSIS_INSTRUCTIONS,
        )
        self.assertNotIn("create_report", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("update_report", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("report_json", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn("输出中文", CODEX_ANALYSIS_INSTRUCTIONS)

    def test_thread_uses_the_current_managed_context_instructions(self) -> None:
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=_FakeAsyncCodex,
            base_instructions_resolver=lambda: "由系统管理保存的基础指令",
            system_prompt_resolver=lambda: "由系统管理保存的系统提示词",
        )

        kwargs = runtime._thread_kwargs(
            CodexSdkRunnerContext(genbi_thread_id="thread_1", genbi_turn_id="turn_1")
        )

        self.assertEqual(kwargs["base_instructions"], "由系统管理保存的基础指令")
        self.assertEqual(kwargs["developer_instructions"], "由系统管理保存的系统提示词")

    def test_thread_keeps_codex_native_base_when_no_custom_base_is_saved(self) -> None:
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=_FakeAsyncCodex,
            base_instructions_resolver=lambda: None,
            system_prompt_resolver=lambda: "系统提示词",
        )

        kwargs = runtime._thread_kwargs(CodexSdkRunnerContext())

        self.assertNotIn("base_instructions", kwargs)
        self.assertEqual(kwargs["developer_instructions"], "系统提示词")

    def test_thread_uses_the_current_managed_runtime_policy(self) -> None:
        connection = ModelRuntimeConnection(
            name="managed",
            display_name="Managed",
            provider_type="openai_compatible",
            model="managed-model",
            base_url="https://models.example.test/v1",
            api_key="managed-key",
        )
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=_FakeAsyncCodex,
            model_connection_resolver=lambda: connection,
            runtime_policy_resolver=lambda: {
                "model": "legacy-policy-model",
                "approval_mode": "deny_all",
                "sandbox": "workspace_write",
                "default_tools_enabled": True,
            },
        )

        kwargs = runtime._thread_kwargs(CodexSdkRunnerContext())

        self.assertEqual(kwargs["model"], "managed-model")
        self.assertEqual(kwargs["model_provider"], "genbi_managed")
        self.assertEqual(kwargs["approval_mode"].value, "deny_all")
        self.assertEqual(kwargs["sandbox"].value, "workspace-write")
        self.assertEqual(kwargs["config"], {"default_tools_enabled": True})

    def test_each_turn_uses_one_current_model_connection_snapshot(self) -> None:
        first = ModelRuntimeConnection(
            name="first",
            display_name="First",
            provider_type="openai_compatible",
            model="model-first",
            base_url="https://first.example.test/v1",
            api_key="first-key",
        )
        second = ModelRuntimeConnection(
            name="second",
            display_name="Second",
            provider_type="openai_compatible",
            model="model-second",
            base_url="https://second.example.test/v1",
            api_key="second-key",
        )
        current = [first]
        resolver_calls: list[str] = []
        codex_runs: list[_FakeAsyncCodex] = []

        def resolve() -> ModelRuntimeConnection:
            resolver_calls.append(current[0].name)
            return current[0]

        def factory() -> _FakeAsyncCodex:
            codex = _FakeAsyncCodex()
            codex_runs.append(codex)
            return codex

        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=factory,
            model_connection_resolver=resolve,
        )

        list(runtime.stream("first turn"))
        current[0] = second
        list(runtime.stream("second turn"))

        self.assertEqual(resolver_calls, ["first", "second"])
        self.assertEqual(
            [run.started_kwargs["model"] for run in codex_runs],
            ["model-first", "model-second"],
        )
        self.assertEqual(
            [run.started_kwargs["model_provider"] for run in codex_runs],
            ["genbi_first", "genbi_second"],
        )

    def test_managed_connection_builds_custom_provider_config_and_secret_env(
        self,
    ) -> None:
        connection = ModelRuntimeConnection(
            name="custom-primary",
            display_name="Custom",
            provider_type="openai_compatible",
            model="custom-model",
            base_url="https://models.example.test/v1",
            api_key="plain-model-key",
        )
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=_FakeAsyncCodex,
            model_connection_resolver=lambda: connection,
        )

        overrides = runtime._config_overrides(connection)
        environment = runtime._codex_env(connection)

        self.assertIn(
            'model_providers.genbi_custom_primary.base_url="https://models.example.test/v1"',
            overrides,
        )
        self.assertIn(
            'model_providers.genbi_custom_primary.wire_api="responses"',
            overrides,
        )
        self.assertEqual(
            environment["GENBI_MANAGED_MODEL_API_KEY"],
            "plain-model-key",
        )

    def test_managed_minimax_connection_uses_its_named_local_adapter(
        self,
    ) -> None:
        connection = ModelRuntimeConnection(
            name="minimax-primary",
            display_name="MiniMax Primary",
            provider_type="minimax",
            model="MiniMax-M3",
            base_url="https://api.minimaxi.com/v1",
            api_key="plain-model-key",
        )
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=_FakeAsyncCodex,
            model_connection_resolver=lambda: connection,
        )

        overrides = runtime._config_overrides(connection)

        self.assertIn(
            (
                "model_providers.genbi_minimax_primary.base_url="
                '"http://127.0.0.1:8000/api/codex-minimax/'
                'minimax-primary/v1"'
            ),
            overrides,
        )
        self.assertIn(
            (
                "model_providers.genbi_minimax_primary.env_key="
                '"GENBI_MANAGED_MODEL_API_KEY"'
            ),
            overrides,
        )

    def test_refreshes_runtime_home_after_mcp_enabled_policy_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ",
            {
                "GENBI_ENV_FILE": "missing-test.env",
                "GENBI_CODEX_HOME": temp_dir,
                "GENBI_CODEX_MCP_COUNT": "1",
                "GENBI_CODEX_MCP_1_NAME": "BI_doris",
                "GENBI_CODEX_MCP_1_COMMAND": "npx",
            },
            clear=True,
        ):
            runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)
            config_path = Path(temp_dir) / "config.toml"
            self.assertIn("mcp_servers.BI_doris", config_path.read_text(encoding="utf-8"))

            with patch(
                "backend.system_management.mcp_enabled_overrides",
                return_value={"BI_doris": False},
            ):
                runtime._sync_codex_home_config()

            self.assertNotIn(
                "mcp_servers.BI_doris",
                config_path.read_text(encoding="utf-8"),
            )

    def test_stream_maps_codex_notifications_to_agent_events(self) -> None:
        runtime = CodexSdkAnalysisRuntime(
            model="codex-test-model",
            cwd="E:/my_repo/agentic genbi",
            async_codex_factory=_FakeAsyncCodex,
        )

        events = list(
            runtime.stream(
                "analyze GMV drop",
                context={"genbi_thread_id": "thread_1", "genbi_turn_id": "turn_1"},
            )
        )

        event_types = [event.type for event in events]
        item_events = [event for event in events if event.type == "item/completed"]
        delta_events = [event for event in events if event.type == "item/agentMessage/delta"]

        self.assertEqual(event_types, ["genbi/thread/provisioned", "genbi/turn/provisioned", "turn/started", "item/agentMessage/delta", "item/completed", "turn/completed"])
        # ``genbi/thread/provisioned`` and ``genbi/turn/provisioned`` are emitted
        # by GenBI runtime (eventSource=genbi) to surface the Codex-issued
        # ids before any Codex-originated event. The remaining events are
        # Codex-originated.
        event_sources = {event.payload.get("eventSource") for event in events}
        self.assertIn("codex", event_sources)
        self.assertIn("genbi", event_sources)
        self.assertEqual(delta_events[0].payload["delta"], "part 1")
        self.assertEqual(item_events[0].payload["content"], "complete text")
        self.assertEqual(item_events[0].payload["codex_item_id"], "codex_item_msg")
        self.assertEqual(events[-1].payload["status"], "completed")

    def test_stream_binds_and_releases_signed_report_tool_context(self) -> None:
        registry = _RecordingReportToolRegistry()
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=_FakeAsyncCodex,
            report_tool_execution_registry=registry,
        )

        list(
            runtime.stream(
                "生成报表",
                context={
                    "report_tool_owner_id": "user-1",
                    "report_tool_tenant_id": "tenant-1",
                    "report_tool_workspace_id": "workspace-1",
                    "report_tool_roles": ["analyst"],
                },
            )
        )

        self.assertEqual(
            registry.reserved,
            {
                "owner_id": "user-1",
                "tenant_id": "tenant-1",
                "workspace_id": "workspace-1",
                "roles": ("analyst",),
            },
        )
        self.assertEqual(
            registry.bound,
            (
                "signed-report-tool-token",
                "codex_thread_started",
                "codex_turn_1",
            ),
        )
        self.assertEqual(
            registry.released,
            "signed-report-tool-token",
        )

    def test_stream_marks_completed_turn_failed_when_build_is_unpublished(
        self,
    ) -> None:
        registry = _RecordingReportToolRegistry(incomplete=True)
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=_FakeAsyncCodex,
            report_tool_execution_registry=registry,
        )

        events = list(
            runtime.stream(
                "生成报表",
                context={"report_tool_owner_id": "user-1"},
            )
        )

        terminal = events[-1]
        self.assertEqual(terminal.type, "turn/completed")
        self.assertEqual(terminal.payload["status"], "failed")
        self.assertEqual(
            terminal.payload["error"]["code"],
            "report_build_incomplete",
        )

    def test_mcp_tool_call_includes_result_payload(self) -> None:
        from backend.harness.codex_sdk_runner import _mcp_tool_call_payload

        payload = _mcp_tool_call_payload(
            SimpleNamespace(
                type="mcpToolCall",
                server="GenBI_report",
                tool="create_report",
                status=SimpleNamespace(value="completed"),
                arguments={"title": "report"},
                result={"content": [{"type": "text", "text": "{\"ok\":true}"}]},
            )
        )

        self.assertEqual(payload["mcp_server"], "GenBI_report")
        self.assertEqual(payload["mcp_result"]["content"][0]["text"], "{\"ok\":true}")

    def test_maps_reasoning_summary_delta_but_not_raw_reasoning_text(self) -> None:
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)

        summary = runtime._notification_to_event(
            SimpleNamespace(
                method="item/reasoning/summaryTextDelta",
                payload=SimpleNamespace(
                    turn_id="codex_turn_1",
                    item_id="reasoning_1",
                    summary_index=0,
                    delta="正在检查渠道口径。",
                ),
            ),
            codex_thread_id="codex_thread_1",
        )
        raw = runtime._notification_to_event(
            SimpleNamespace(
                method="item/reasoning/textDelta",
                payload=SimpleNamespace(
                    turn_id="codex_turn_1",
                    item_id="reasoning_1",
                    content_index=0,
                    delta="hidden chain of thought",
                ),
            ),
            codex_thread_id="codex_thread_1",
        )

        self.assertIsNotNone(summary)
        self.assertEqual(summary.type, "item/reasoning/summaryTextDelta")
        self.assertEqual(summary.payload["delta"], "正在检查渠道口径。")
        self.assertEqual(summary.payload["summary_index"], 0)
        self.assertEqual(summary.payload["codex_item_id"], "reasoning_1")
        self.assertIsNone(raw)

    def test_maps_started_and_completed_tool_items_with_sanitized_details(self) -> None:
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)
        item = SimpleNamespace(
            id="tool_1",
            type="mcpToolCall",
            server="BI_doris",
            tool="mysql_query",
            status=SimpleNamespace(value="completed"),
            arguments={"sql": "select 1", "api_key": "secret-value"},
            result={"content": [{"type": "text", "text": "one row"}]},
            duration_ms=1250,
        )

        started = runtime._notification_to_event(
            SimpleNamespace(
                method="item/started",
                payload=SimpleNamespace(turn_id="turn_1", item=SimpleNamespace(root=item)),
            ),
            codex_thread_id="session_1",
        )
        completed = runtime._notification_to_event(
            SimpleNamespace(
                method="item/completed",
                payload=SimpleNamespace(turn_id="turn_1", item=SimpleNamespace(root=item)),
            ),
            codex_thread_id="session_1",
        )

        self.assertIsNotNone(started)
        self.assertEqual(started.payload["codex_item_id"], "tool_1")
        self.assertEqual(started.payload["codex_method"], "item/started")
        self.assertEqual(completed.payload["mcp_arguments"]["sql"], "select 1")
        self.assertEqual(completed.payload["mcp_arguments"]["api_key"], "[REDACTED]")
        self.assertNotIn("secret-value", repr(completed.payload))

    def test_completed_reasoning_item_contains_display_summary_only(self) -> None:
        summary_part = SimpleNamespace(root=SimpleNamespace(text="正在核验数据。"))
        root = SimpleNamespace(
            id="reasoning_1",
            type="reasoning",
            summary=[summary_part],
            content=[SimpleNamespace(root=SimpleNamespace(text="hidden reasoning"))],
        )
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)

        event = runtime._notification_to_event(
            SimpleNamespace(
                method="item/completed",
                payload=SimpleNamespace(turn_id="turn_1", item=SimpleNamespace(root=root)),
            ),
            codex_thread_id="session_1",
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.payload["summary"], "正在核验数据。")
        self.assertNotIn("hidden reasoning", repr(event.payload))

    def test_maps_command_output_and_mcp_progress_notifications(self) -> None:
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)

        command_output = runtime._notification_to_event(
            SimpleNamespace(
                method="item/commandExecution/outputDelta",
                payload=SimpleNamespace(
                    turn_id="turn_1",
                    item_id="command_1",
                    delta="line 1\n",
                ),
            ),
            codex_thread_id="session_1",
        )
        mcp_progress = runtime._notification_to_event(
            SimpleNamespace(
                method="item/mcpToolCall/progress",
                payload=SimpleNamespace(
                    turn_id="turn_1",
                    item_id="tool_1",
                    message="Fetched page 1",
                ),
            ),
            codex_thread_id="session_1",
        )

        self.assertEqual(command_output.type, "item/commandExecution/outputDelta")
        self.assertEqual(command_output.payload["delta"], "line 1\n")
        self.assertEqual(command_output.payload["codex_item_id"], "command_1")
        self.assertEqual(mcp_progress.type, "item/mcpToolCall/progress")
        self.assertEqual(mcp_progress.payload["message"], "Fetched page 1")

    def test_async_stream_resumes_codex_thread_when_context_has_codex_thread_id(self) -> None:
        fake_codex = _FakeAsyncCodex()
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=lambda: fake_codex)

        async def collect() -> list:
            output = []
            async for event in runtime.async_stream("continue analysis", context={"codex_thread_id": "codex_existing"}):
                output.append(event)
            return output

        events = asyncio.run(collect())

        self.assertEqual(fake_codex.resumed[0], "codex_existing")
        self.assertEqual(events[-1].type, "turn/completed")

    def test_async_stream_passes_the_referenced_report_as_native_turn_input(self) -> None:
        fake_codex = _FakeAsyncCodex()
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=lambda: fake_codex)

        async def collect() -> list:
            output = []
            async for event in runtime.async_stream(
                "哪一天的 GMV 最高？",
                context={
                    "initial_report": {
                        "id": "report_context",
                        "title": "抖音销售日报",
                        "subtitle": "当前配置",
                        "layout": {},
                        "filters": {},
                        "charts": {},
                        "tables": {},
                        "queries": {},
                    },
                },
            ):
                output.append(event)
            return output

        asyncio.run(collect())

        assert fake_codex.last_thread is not None
        turn_input = fake_codex.last_thread.turn_input
        self.assertIsInstance(turn_input, list)
        self.assertEqual(turn_input[0].text, "哪一天的 GMV 最高？")
        self.assertIn('"id":"report_context"', turn_input[1].text)
        self.assertIn('"queries":{}', turn_input[1].text)
        self.assertNotIn("datasets", turn_input[1].text)

    def test_interrupt_turn_awaits_async_sdk_interrupt(self) -> None:
        class _AsyncInterruptTurn:
            def __init__(self) -> None:
                self.awaited = False

            async def interrupt(self) -> None:
                self.awaited = True

        turn = _AsyncInterruptTurn()
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)
        runtime._active_turns[("codex_thread_1", "codex_turn_1")] = turn

        interrupted = asyncio.run(runtime.interrupt_turn("codex_thread_1", "codex_turn_1"))

        self.assertTrue(interrupted)
        self.assertTrue(turn.awaited)
        self.assertEqual(runtime._active_turns, {})

    def test_interrupt_turn_keeps_handle_when_interrupt_fails(self) -> None:
        class _FailingInterruptTurn:
            def interrupt(self) -> None:
                raise RuntimeError("sdk interrupt failed")

        turn = _FailingInterruptTurn()
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)
        runtime._active_turns[("codex_thread_1", "codex_turn_1")] = turn

        interrupted = asyncio.run(runtime.interrupt_turn("codex_thread_1", "codex_turn_1"))

        self.assertFalse(interrupted)
        self.assertIs(runtime._active_turns[("codex_thread_1", "codex_turn_1")], turn)

    def test_thread_start_receives_default_tools_disabled_config(self) -> None:
        fake_codex = _FakeAsyncCodex()
        with patch.dict(
            "os.environ",
            {
                "GENBI_ENV_FILE": "missing-test.env",
                "GENBI_CODEX_DEFAULT_TOOLS_ENABLED": "false",
            },
            clear=True,
        ):
            runtime = CodexSdkAnalysisRuntime(async_codex_factory=lambda: fake_codex)

        list(runtime.stream("analyze"))

        self.assertEqual(fake_codex.started_kwargs["config"], {"default_tools_enabled": False})

    def test_config_overrides_include_default_tools_disabled(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GENBI_ENV_FILE": "missing-test.env",
                "GENBI_CODEX_DEFAULT_TOOLS_ENABLED": "false",
            },
            clear=True,
        ):
            runtime = CodexSdkAnalysisRuntime(
                codex_factory=lambda: None,
                async_codex_factory=lambda: None,
            )

        self.assertIn("default_tools_enabled=false", runtime._config_overrides())

    def test_disabled_runtime_returns_failed_turn_event(self) -> None:
        events = list(CodexSdkAnalysisRuntime.disabled().stream("analyze", context={"genbi_turn_id": "turn_disabled"}))

        self.assertEqual(events[0].type, "turn/completed")
        self.assertEqual(events[0].turn_id, "turn_disabled")
        self.assertEqual(events[0].payload["error"], "codex_runtime_not_configured")

    def test_runtime_logs_in_with_configured_api_key(self) -> None:
        fake_codex = _FakeAsyncCodex()
        runtime = CodexSdkAnalysisRuntime(async_codex_factory=lambda: fake_codex)
        runtime.provider = "openai"
        runtime.api_key = "sk-test"

        list(runtime.stream("analyze"))

        self.assertEqual(fake_codex.login_api_key_value, "sk-test")

    def test_minimax_provider_uses_codex_model_provider_config(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GENBI_ENV_FILE": "missing-test.env",
                "GENBI_LLM_PROVIDER": "minimax",
                "GENBI_ANALYSIS_MODEL": "MiniMax-M3",
                "GENBI_LLM_BASE_URL": "https://api.minimaxi.com/v1",
                "MINIMAX_API_KEY": "minimax-test-key",
                "GENBI_CODEX_MINIMAX_ADAPTER_ENABLED": "false",
            },
            clear=True,
        ):
            runtime = CodexSdkAnalysisRuntime()

        self.assertEqual(runtime.provider, "minimax")
        self.assertEqual(runtime.model, "MiniMax-M3")
        self.assertEqual(runtime.base_url, "https://api.minimaxi.com/v1")
        self.assertEqual(runtime._codex_env(), {"MINIMAX_API_KEY": "minimax-test-key"})
        self.assertIn('model_providers.minimax.wire_api="responses"', runtime._config_overrides())
        self.assertIn('model_providers.minimax.base_url="https://api.minimaxi.com/v1"', runtime._config_overrides())

    def test_minimax_provider_uses_local_adapter_by_default(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GENBI_ENV_FILE": "missing-test.env",
                "GENBI_LLM_PROVIDER": "minimax",
                "GENBI_ANALYSIS_MODEL": "MiniMax-M3",
                "MINIMAX_API_KEY": "minimax-test-key",
            },
            clear=True,
        ):
            runtime = CodexSdkAnalysisRuntime()

        self.assertEqual(runtime.provider, "minimax")
        self.assertEqual(runtime.base_url, "http://127.0.0.1:8000/api/codex-minimax/v1")
        self.assertIn(
            'model_providers.minimax.base_url="http://127.0.0.1:8000/api/codex-minimax/v1"',
            runtime._config_overrides(),
        )

    def test_minimax_turn_scopes_adapter_to_report_execution(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GENBI_ENV_FILE": "missing-test.env",
                "GENBI_LLM_PROVIDER": "minimax",
                "GENBI_ANALYSIS_MODEL": "MiniMax-M3",
                "MINIMAX_API_KEY": "minimax-test-key",
            },
            clear=True,
        ):
            runtime = CodexSdkAnalysisRuntime()

        self.assertIn(
            (
                "model_providers.minimax.base_url="
                '"http://127.0.0.1:8000/api/codex-minimax/v1/'
                'executions/report-execution-1"'
            ),
            runtime._config_overrides(
                provider_base_url=(
                    "http://127.0.0.1:8000/api/codex-minimax/v1/"
                    "executions/report-execution-1"
                )
            ),
        )

    def test_stream_passes_execution_scoped_minimax_base_url(
        self,
    ) -> None:
        registry = _RecordingReportToolRegistry()
        fake_codex = _FakeAsyncCodex()
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=lambda: fake_codex,
            model_connection_resolver=lambda: None,
            report_tool_execution_registry=registry,
        )
        runtime.provider = "minimax"
        runtime.model = None
        runtime.base_url = (
            "http://127.0.0.1:8000/api/codex-minimax/v1"
        )
        original_make = runtime._make_async_codex

        with patch(
            "backend.harness.codex_sdk_runner.adapter_enabled",
            return_value=True,
        ), patch.object(
            runtime,
            "_make_async_codex",
            wraps=original_make,
        ) as make_codex:
            list(
                runtime.stream(
                    "生成报表",
                    context={
                        "report_tool_owner_id": "user-1",
                    },
                )
            )

        self.assertEqual(
            make_codex.call_args.kwargs["provider_base_url"],
            (
                "http://127.0.0.1:8000/api/codex-minimax/v1/"
                "executions/report-execution-1"
            ),
        )

    def test_managed_minimax_stream_uses_scoped_adapter_path(
        self,
    ) -> None:
        registry = _RecordingReportToolRegistry()
        fake_codex = _FakeAsyncCodex()
        managed_connection = ModelRuntimeConnection(
            name="minimax",
            display_name="MiniMax",
            provider_type="minimax",
            model="MiniMax-M3",
            base_url="https://api.minimaxi.com/v1",
            api_key="managed-key",
            source="managed",
        )
        runtime = CodexSdkAnalysisRuntime(
            async_codex_factory=lambda: fake_codex,
            model_connection_resolver=lambda: managed_connection,
            report_tool_execution_registry=registry,
        )
        original_make = runtime._make_async_codex

        with patch(
            "backend.harness.codex_sdk_runner.adapter_enabled",
            return_value=True,
        ), patch.object(
            runtime,
            "_make_async_codex",
            wraps=original_make,
        ) as make_codex:
            list(
                runtime.stream(
                    "生成报表",
                    context={
                        "report_tool_owner_id": "user-1",
                    },
                )
            )

        self.assertEqual(
            make_codex.call_args.kwargs["provider_base_url"],
            (
                "http://127.0.0.1:8000/api/codex-minimax/"
                "minimax/v1/executions/report-execution-1"
            ),
        )

    def test_missing_codex_bin_env_falls_back_to_path_resolution(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GENBI_ENV_FILE": "missing-test.env",
                "GENBI_CODEX_BIN": "/usr/local/bin/codex",
            },
            clear=True,
        ), patch("backend.harness.codex_sdk_runner.shutil.which", side_effect=["C:/Codex/codex.exe", None]):
            runtime = CodexSdkAnalysisRuntime(
                codex_factory=lambda: None,
                async_codex_factory=lambda: None,
            )

        self.assertEqual(runtime.codex_bin, "C:/Codex/codex.exe")


if __name__ == "__main__":
    unittest.main()
