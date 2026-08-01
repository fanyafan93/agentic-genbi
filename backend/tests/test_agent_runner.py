from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.exploration.agent_runner import _bounded_value, _final_output_to_text


class AgentRunnerContractTest(unittest.TestCase):
    def test_final_output_to_text_handles_string_and_model_like_value(self) -> None:
        class Value:
            def model_dump_json(self) -> str:
                return '{"title":"t"}'

        self.assertEqual(_final_output_to_text("ok"), "ok")
        self.assertEqual(_final_output_to_text(Value()), '{"title":"t"}')
        self.assertEqual(_final_output_to_text("<think>hidden</think>\n\n已连接。"), "已连接。")
        self.assertEqual(_final_output_to_text("我是数据探索 Agent。"), "我是知识探索 Agent。")

    def test_bounded_value_truncates_long_text(self) -> None:
        text = _bounded_value("x" * 12, max_chars=5)

        self.assertEqual(text, "xxxxx... [truncated]")


if __name__ == "__main__":
    unittest.main()
