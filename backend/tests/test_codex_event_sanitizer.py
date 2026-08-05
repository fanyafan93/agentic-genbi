from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_event_sanitizer import REDACTED, sanitize_codex_value


class CodexEventSanitizerTest(unittest.TestCase):
    def test_redacts_sensitive_keys_without_removing_sql(self) -> None:
        value = {
            "sql": "select * from dm.sales where channel = '京东'",
            "api_key": "sk-secret",
            "nested": {"Authorization": "Bearer abc", "page": 3},
        }

        self.assertEqual(
            sanitize_codex_value(value),
            {
                "sql": "select * from dm.sales where channel = '京东'",
                "api_key": REDACTED,
                "nested": {"Authorization": REDACTED, "page": 3},
            },
        )

    def test_redacts_credentials_embedded_in_text_and_connection_urls(self) -> None:
        value = {
            "stdout": "Authorization: Bearer abc123",
            "headers": "Cookie: session_id=private-cookie",
            "dsn": "postgresql://analyst:password@db.internal:5432/genbi",
        }

        sanitized = sanitize_codex_value(value)

        self.assertNotIn("abc123", sanitized["stdout"])
        self.assertNotIn("private-cookie", sanitized["headers"])
        self.assertNotIn("analyst:password", sanitized["dsn"])

    def test_truncates_long_strings_with_an_explicit_marker(self) -> None:
        sanitized = sanitize_codex_value({"stdout": "x" * 25_000})

        self.assertLess(len(sanitized["stdout"]), 25_000)
        self.assertTrue(sanitized["stdout"].endswith("...[truncated]"))


if __name__ == "__main__":
    unittest.main()
