from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.runner_contracts import bounded_value, final_output_to_text


class AgentRunnerContractTest(unittest.TestCase):
    def test_final_output_to_text_handles_string_and_model_like_value(self) -> None:
        class Value:
            def model_dump_json(self) -> str:
                return '{"title":"t"}'

        self.assertEqual(final_output_to_text("ok"), "ok")
        self.assertEqual(final_output_to_text(Value()), '{"title":"t"}')
        self.assertEqual(final_output_to_text("<think>hidden</think>\n\nconnected"), "connected")

    def test_bounded_value_truncates_long_text(self) -> None:
        text = bounded_value("x" * 12, max_chars=5)

        self.assertEqual(text, "xxxxx... [truncated]")


if __name__ == "__main__":
    unittest.main()

