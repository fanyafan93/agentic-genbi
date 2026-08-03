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


if __name__ == "__main__":
    unittest.main()
