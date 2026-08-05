from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_sdk_runner import CODEX_ANALYSIS_INSTRUCTIONS, CodexSdkAnalysisRuntime


class _FakeAsyncCodex:
    def __init__(self) -> None:
        self.started_kwargs = None
        self.resumed = None
        self.login_api_key_value = None

    async def __aenter__(self) -> "_FakeAsyncCodex":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def thread_start(self, **kwargs):
        self.started_kwargs = kwargs
        return _FakeThread("codex_thread_started")

    async def thread_resume(self, thread_id: str, **kwargs):
        self.resumed = (thread_id, kwargs)
        return _FakeThread(thread_id)

    async def login_api_key(self, api_key: str) -> None:
        self.login_api_key_value = api_key


class _FakeThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id

    async def turn(self, question: str, **kwargs):
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


class CodexSdkAnalysisRuntimeTest(unittest.TestCase):
    def test_analysis_instructions_do_not_duplicate_codex_identity_or_mcp_catalog(self) -> None:
        self.assertNotIn("openai-codex", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("BI_doris", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("mysql_query", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("8.134.63.30", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertNotIn("dm.dm_channel_mtsg_sale_total", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn("涉及真实业务数据时，必须先查证", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn("不能编造表、字段、指标、金额、占比或增长结论", CODEX_ANALYSIS_INSTRUCTIONS)
        self.assertIn("输出中文", CODEX_ANALYSIS_INSTRUCTIONS)

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

    def test_mcp_tool_call_includes_result_payload(self) -> None:
        from backend.harness.codex_sdk_runner import _mcp_tool_call_payload

        payload = _mcp_tool_call_payload(
            SimpleNamespace(
                type="mcpToolCall",
                server="GenBI_report",
                tool="create_interactive_report",
                status=SimpleNamespace(value="completed"),
                arguments={"title": "report"},
                result={"content": [{"type": "text", "text": "{\"ok\":true}"}]},
            )
        )

        self.assertEqual(payload["mcp_server"], "GenBI_report")
        self.assertEqual(payload["mcp_result"]["content"][0]["text"], "{\"ok\":true}")

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
