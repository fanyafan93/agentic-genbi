from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.exploration.agent_runner import LLMProviderConfig, LLMAgentRunner, OpenAIAgentsSdkRunner, _final_output_to_text, normalize_agents_sdk_stream_event


class AgentRunnerTest(unittest.TestCase):
    def test_runner_requires_default_openai_api_key(self) -> None:
        with patch.dict(os.environ, {"GENBI_ENV_FILE": "missing-test.env"}, clear=True):
            runner = LLMAgentRunner()

            with self.assertRaises(RuntimeError):
                runner.run("首购后 30 天复购率怎么计算？")

    def test_async_runner_requires_default_openai_api_key(self) -> None:
        async def collect_first_event() -> None:
            async for _item in runner.async_stream("首购后 30 天复购率怎么计算？"):
                return

        with patch.dict(os.environ, {"GENBI_ENV_FILE": "missing-test.env"}, clear=True):
            runner = OpenAIAgentsSdkRunner()

            with self.assertRaises(RuntimeError):
                asyncio.run(collect_first_event())

    def test_minimax_provider_config_reads_openai_compatible_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GENBI_LLM_PROVIDER": "minimax",
                "GENBI_EXPLORATION_MODEL": "minimax-test-model",
                "MINIMAX_API_KEY": "minimax-key",
                "MINIMAX_BASE_URL": "https://api.minimax.example/v1",
                "GENBI_ENV_FILE": "missing-test.env",
            },
            clear=True,
        ):
            config = LLMProviderConfig.from_env()

        self.assertEqual(config.provider, "minimax")
        self.assertEqual(config.model, "minimax-test-model")
        self.assertEqual(config.api_key, "minimax-key")
        self.assertEqual(config.base_url, "https://api.minimax.example/v1")
        config.validate()

    def test_minimax_provider_requires_base_url(self) -> None:
        config = LLMProviderConfig(
            provider="minimax",
            model="minimax-test-model",
            api_key="minimax-key",
        )

        with self.assertRaisesRegex(RuntimeError, "MINIMAX_BASE_URL"):
            config.validate()

    def test_openai_provider_with_base_url_uses_chat_completions_model(self) -> None:
        runner = LLMAgentRunner(
            provider_config=LLMProviderConfig(
                provider="openai",
                model="gpt-test",
                api_key="sk-test",
                base_url="https://openai-compatible.example/v1",
            )
        )

        self.assertEqual(type(runner._build_agent_model()).__name__, "OpenAIChatCompletionsModel")

    def test_final_output_to_text_handles_string_and_model_like_value(self) -> None:
        class Value:
            def model_dump_json(self) -> str:
                return '{"title":"t"}'

        self.assertEqual(_final_output_to_text("ok"), "ok")
        self.assertEqual(_final_output_to_text(Value()), '{"title":"t"}')
        self.assertEqual(_final_output_to_text("<think>hidden</think>\n\n已连接。"), "已连接。")
        self.assertEqual(_final_output_to_text("我是数据探索 Agent。"), "我是知识探索 Agent。")

    def test_normalize_tool_stream_events(self) -> None:
        class ToolItem:
            type = "tool_call_item"
            tool_name = "search_resources"
            call_id = "call_1"

        class OutputItem:
            type = "tool_call_output_item"
            call_id = "call_1"
            output = {"results": [{"name": "复购分析.cpt"}]}

        class ToolEvent:
            type = "run_item_stream_event"
            name = "tool_called"
            item = ToolItem()

        class OutputEvent:
            type = "run_item_stream_event"
            name = "tool_output"
            item = OutputItem()

        tool_names: dict[str, str] = {}
        started = normalize_agents_sdk_stream_event(ToolEvent(), tool_names_by_call_id=tool_names)
        completed = normalize_agents_sdk_stream_event(OutputEvent(), tool_names_by_call_id=tool_names)

        self.assertEqual(started.type, "tool.call.started")
        self.assertEqual(started.payload["tool"], "search_resources")
        self.assertEqual(started.payload["tool_label_full"], "搜索资源库 search_resources")
        self.assertEqual(completed.type, "tool.call.completed")
        self.assertEqual(completed.payload["tool"], "search_resources")
        self.assertEqual(completed.payload["tool_label_full"], "搜索资源库 search_resources")
        self.assertIn("复购分析.cpt", completed.payload["output"])

    def test_normalize_raw_stream_event_keeps_usage(self) -> None:
        class Usage:
            input_tokens = 100
            output_tokens = 50
            total_tokens = 150

        class Data:
            type = "response.completed"
            usage = Usage()

        class RawEvent:
            type = "raw_response_event"
            data = Data()

        event = normalize_agents_sdk_stream_event(RawEvent())

        self.assertEqual(event.type, "agent.runner.raw")
        self.assertEqual(event.payload["usage"]["input_tokens"], 100)
        self.assertEqual(event.payload["usage"]["output_tokens"], 50)
        self.assertEqual(event.payload["usage"]["total_tokens"], 150)

    def test_normalize_empty_message_output_is_ignored(self) -> None:
        class RawItem:
            content = [{"type": "output_text", "text": "   "}]

        class Item:
            type = "message_output_item"
            raw_item = RawItem()

        class MessageEvent:
            type = "run_item_stream_event"
            name = "message_output_created"
            item = Item()

        event = normalize_agents_sdk_stream_event(MessageEvent())

        self.assertIsNone(event)

    def test_normalize_message_output_created_is_not_rendered_as_progress(self) -> None:
        class RawItem:
            content = [{"type": "output_text", "text": "最终回复"}]

        class Item:
            type = "message_output_item"
            raw_item = RawItem()

        class MessageEvent:
            type = "run_item_stream_event"
            name = "message_output_created"
            item = Item()

        event = normalize_agents_sdk_stream_event(MessageEvent())

        self.assertIsNone(event)


if __name__ == "__main__":
    unittest.main()
