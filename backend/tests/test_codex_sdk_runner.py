from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime


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
        return _FakeTurn(question, kwargs)


class _FakeTurn:
    def __init__(self, question: str, kwargs: dict) -> None:
        self.question = question
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

        self.assertEqual(event_types, ["turn/started", "item/agentMessage/delta", "item/completed", "turn/completed"])
        self.assertTrue(all(event.payload.get("eventSource") == "codex" for event in events))
        self.assertEqual(delta_events[0].payload["delta"], "part 1")
        self.assertEqual(item_events[0].payload["content"], "complete text")
        self.assertEqual(item_events[0].payload["codex_item_id"], "codex_item_msg")
        self.assertEqual(events[-1].payload["status"], "completed")

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


if __name__ == "__main__":
    unittest.main()
