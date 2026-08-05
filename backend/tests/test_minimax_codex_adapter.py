from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.minimax_codex_adapter import (
    NamespaceToolMap,
    adapter_base_url,
    adapter_enabled,
    _iter_rewritten_sse,
    _rewrite_model_name,
    rewrite_request_body,
    rewrite_response_event,
    rewrite_sse_chunk_text,
)


class MinimaxCodexAdapterTest(unittest.TestCase):
    def test_adapter_enabled_defaults_true_and_honors_false(self) -> None:
        self.assertTrue(adapter_enabled({}))
        self.assertFalse(adapter_enabled({"GENBI_CODEX_MINIMAX_ADAPTER_ENABLED": "false"}))

    def test_adapter_base_url_can_be_overridden(self) -> None:
        self.assertEqual(
            adapter_base_url({"GENBI_CODEX_MINIMAX_ADAPTER_BASE_URL": "http://backend/proxy/v1"}),
            "http://backend/proxy/v1",
        )

    def test_rewrite_codex_auto_review_model_to_configured_minimax_model(self) -> None:
        self.assertEqual(_rewrite_model_name("codex-auto-review", {"GENBI_CODEX_AUTO_REVIEW_MODEL": "MiniMax-Review"}), "MiniMax-Review")
        self.assertEqual(_rewrite_model_name("codex-auto-review", {"GENBI_ANALYSIS_MODEL": "MiniMax-M3"}), "MiniMax-M3")
        self.assertEqual(_rewrite_model_name("codex-auto-review", {}), "MiniMax-M3")
        self.assertEqual(_rewrite_model_name("MiniMax-M3", {"GENBI_CODEX_AUTO_REVIEW_MODEL": "MiniMax-Review"}), "MiniMax-M3")

    def test_rewrite_request_maps_codex_auto_review_model(self) -> None:
        rewritten, maps = rewrite_request_body({"model": "codex-auto-review"})

        self.assertEqual(rewritten["model"], "MiniMax-M3")
        self.assertEqual(maps, [])

    def test_rewrite_request_flattens_namespace_tools(self) -> None:
        body = {
            "model": "MiniMax-M3",
            "tools": [
                {
                    "type": "namespace",
                    "name": "mcp__BI_doris__",
                    "tools": [
                        {
                            "type": "function",
                            "name": "mysql_query",
                            "description": "query Doris",
                            "parameters": {
                                "type": "object",
                                "properties": {"sql": {"type": "string"}},
                                "required": ["sql"],
                            },
                        }
                    ],
                }
            ],
        }

        rewritten, maps = rewrite_request_body(body)

        self.assertEqual(len(maps), 1)
        self.assertEqual(maps[0].namespace, "mcp__BI_doris__")
        self.assertEqual(maps[0].tool_names, frozenset({"mysql_query"}))
        self.assertEqual(rewritten["tools"][0]["type"], "function")
        self.assertEqual(rewritten["tools"][0]["name"], "mcp__BI_doris__mysql_query")

    def test_rewrite_response_splits_flat_function_call_back_to_namespace(self) -> None:
        event = {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "name": "mcp__BI_doris__mysql_query",
                "arguments": "{\"sql\":\"SELECT 1\"}",
            },
        }

        rewritten = rewrite_response_event(
            event,
            [NamespaceToolMap(namespace="mcp__BI_doris__", tool_names=frozenset({"mysql_query"}))],
        )

        self.assertEqual(rewritten["item"]["type"], "function_call")
        self.assertEqual(rewritten["item"]["namespace"], "mcp__BI_doris__")
        self.assertEqual(rewritten["item"]["name"], "mysql_query")

    def test_rewrite_response_normalizes_colon_separator(self) -> None:
        event = {
            "output": [
                {
                    "type": "function_call",
                    "name": "mcp:BI_doris:mysql_query",
                    "arguments": "{}",
                }
            ]
        }

        rewritten = rewrite_response_event(
            event,
            [NamespaceToolMap(namespace="mcp__BI_doris__", tool_names=frozenset({"mysql_query"}))],
        )

        self.assertEqual(rewritten["output"][0]["namespace"], "mcp__BI_doris__")
        self.assertEqual(rewritten["output"][0]["name"], "mysql_query")

    def test_rewrite_response_maps_unique_bare_tool_name_to_namespace(self) -> None:
        event = {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "name": "create_report",
                "arguments": "{}",
            },
        }

        rewritten = rewrite_response_event(
            event,
            [
                NamespaceToolMap(namespace="mcp__BI_doris__", tool_names=frozenset({"mysql_query"})),
                NamespaceToolMap(namespace="mcp__GenBI_report__", tool_names=frozenset({"create_report"})),
            ],
        )

        self.assertEqual(rewritten["item"]["namespace"], "mcp__GenBI_report__")
        self.assertEqual(rewritten["item"]["name"], "create_report")

    def test_rewrite_sse_chunk_text_rewrites_data_payloads(self) -> None:
        payload = {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "name": "mcp__BI_doris__mysql_query",
                "arguments": "{}",
            },
        }
        chunk = "event: response.output_item.done\n" + "data: " + json.dumps(payload) + "\n\n"

        rewritten = rewrite_sse_chunk_text(
            chunk,
            [NamespaceToolMap(namespace="mcp__BI_doris__", tool_names=frozenset({"mysql_query"}))],
        )

        self.assertIn('"namespace": "mcp__BI_doris__"', rewritten)
        self.assertIn('"name": "mysql_query"', rewritten)

    def test_iter_rewritten_sse_converts_timeout_to_failed_event(self) -> None:
        class TimeoutResponse:
            def __init__(self) -> None:
                self.closed = False

            def read(self, size: int) -> bytes:
                raise TimeoutError("timed out")

            def close(self) -> None:
                self.closed = True

        response = TimeoutResponse()

        chunks = list(_iter_rewritten_sse(response, []))

        self.assertTrue(response.closed)
        text = b"".join(chunks).decode("utf-8")
        self.assertIn("event: response.failed", text)
        self.assertIn("minimax_stream_timeout", text)

    def test_iter_rewritten_sse_preserves_utf8_split_across_read_chunks(self) -> None:
        payload = {
            "type": "response.output_text.delta",
            "delta": "你好！有什么我可以帮你的吗？随时告诉我。",
        }
        raw = ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
        split_at = raw.index("什".encode("utf-8")) + 1

        class SplitUtf8Response:
            def __init__(self) -> None:
                self.chunks = [raw[:split_at], raw[split_at:]]
                self.closed = False

            def read(self, size: int) -> bytes:
                return self.chunks.pop(0) if self.chunks else b""

            def close(self) -> None:
                self.closed = True

        response = SplitUtf8Response()

        chunks = list(_iter_rewritten_sse(response, []))

        self.assertTrue(response.closed)
        text = b"".join(chunks).decode("utf-8")
        self.assertNotIn("\ufffd", text)
        self.assertIn(payload["delta"], text)


if __name__ == "__main__":
    unittest.main()
