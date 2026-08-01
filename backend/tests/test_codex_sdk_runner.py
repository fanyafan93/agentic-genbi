from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.runner_contracts import AnalysisAgentRunResult
from backend.harness.codex_sdk_runner import CodexSdkAnalysisRunner


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

    async def turn(self, prompt: str, **kwargs):
        return _FakeTurn(prompt, kwargs)


class _FakeTurn:
    def __init__(self, prompt: str, kwargs: dict) -> None:
        self.prompt = prompt
        self.kwargs = kwargs

    async def stream(self):
        yield SimpleNamespace(method="turn/started", payload=SimpleNamespace())
        yield SimpleNamespace(method="item/agentMessage/delta", payload=SimpleNamespace(delta="第一段"))
        yield SimpleNamespace(method="item/agentMessage/delta", payload=SimpleNamespace(delta="第二段"))
        yield SimpleNamespace(
            method="item/completed",
            payload=SimpleNamespace(
                item=SimpleNamespace(root=SimpleNamespace(type="agentMessage", text="完整 Codex 输出")),
            ),
        )
        yield SimpleNamespace(
            method="turn/completed",
            payload=SimpleNamespace(turn=SimpleNamespace(status=SimpleNamespace(value="completed"))),
        )

    async def run(self):
        return SimpleNamespace(final_response="最终 Codex 结果", items=[])


class CodexSdkAnalysisRunnerTest(unittest.TestCase):
    def test_stream_maps_codex_notifications_to_analysis_runner_events(self) -> None:
        runner = CodexSdkAnalysisRunner(
            model="codex-test-model",
            cwd="E:/my_repo/agentic genbi",
            async_codex_factory=_FakeAsyncCodex,
        )

        items = list(
            runner.stream(
                "分析 GMV 下滑原因",
                context={"genbi_thread_id": "thread_1", "genbi_turn_id": "turn_1", "genbi_run_id": "run_1"},
            )
        )

        event_types = [item.type for item in items if not isinstance(item, AnalysisAgentRunResult)]
        result = next(item for item in items if isinstance(item, AnalysisAgentRunResult))
        raw_events = [item for item in items if not isinstance(item, AnalysisAgentRunResult) and item.type == "agent.runner.raw"]

        self.assertIn("agent.runner.raw", event_types)
        self.assertIn("agent.message.delta", event_types)
        self.assertNotIn("agent.message.created", event_types)
        self.assertTrue(any(item.payload.get("phase") == "agent_message.completed" for item in raw_events))
        self.assertEqual(result.final_output, "完整 Codex 输出")
        self.assertEqual(result.raw_result_type, "SimpleNamespace")

    def test_async_stream_resumes_codex_thread_when_context_has_codex_thread_id(self) -> None:
        fake_codex = _FakeAsyncCodex()
        runner = CodexSdkAnalysisRunner(async_codex_factory=lambda: fake_codex)

        async def collect() -> list:
            output = []
            async for item in runner.async_stream("继续分析", context={"codex_thread_id": "codex_existing"}):
                output.append(item)
            return output

        items = asyncio.run(collect())

        self.assertEqual(fake_codex.resumed[0], "codex_existing")
        self.assertTrue(any(isinstance(item, AnalysisAgentRunResult) for item in items))

    def test_runner_logs_in_with_configured_api_key(self) -> None:
        fake_codex = _FakeAsyncCodex()
        runner = CodexSdkAnalysisRunner(async_codex_factory=lambda: fake_codex)
        runner.provider = "openai"
        runner.api_key = "sk-test"

        list(runner.stream("分析问题"))

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
            runner = CodexSdkAnalysisRunner()

        self.assertEqual(runner.provider, "minimax")
        self.assertEqual(runner.model, "MiniMax-M3")
        self.assertEqual(runner.base_url, "https://api.minimaxi.com/v1")
        self.assertEqual(runner._codex_env(), {"MINIMAX_API_KEY": "minimax-test-key"})
        self.assertIn('model_providers.minimax.wire_api="responses"', runner._config_overrides())
        self.assertIn('model_providers.minimax.base_url="https://api.minimaxi.com/v1"', runner._config_overrides())


if __name__ == "__main__":
    unittest.main()
