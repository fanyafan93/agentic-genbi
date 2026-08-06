from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.system_management.mcp_registry import (
    McpServerRecord,
    McpRegistry,
    McpRegistryConflict,
    McpSecretCipher,
    MemoryMcpServerRepository,
)
from backend.reports.build_service import REPORT_BUILD_TOOL_NAMES


class McpSecretCipherTest(unittest.TestCase):
    def test_encrypts_at_rest_and_can_reveal_plaintext(self) -> None:
        cipher = McpSecretCipher("unit-test-master-key")

        encrypted = cipher.encrypt(
            "BI_doris",
            {"MYSQL_PASSWORD": "plain-db-password"},
        )

        self.assertNotIn("plain-db-password", encrypted)
        self.assertEqual(
            cipher.decrypt("BI_doris", encrypted),
            {"MYSQL_PASSWORD": "plain-db-password"},
        )

    def test_ciphertext_is_bound_to_server_name(self) -> None:
        cipher = McpSecretCipher("unit-test-master-key")
        encrypted = cipher.encrypt("BI_doris", {"TOKEN": "secret"})

        with self.assertRaises(ValueError):
            cipher.decrypt("another_server", encrypted)


class McpRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = MemoryMcpServerRepository()
        self.registry = McpRegistry(
            repository=self.repository,
            cipher=McpSecretCipher("unit-test-master-key"),
        )

    def test_lists_code_owned_genbi_report_as_immutable_system_server(self) -> None:
        server = self.registry.get("GenBI_report")

        self.assertEqual(server["category"], "system")
        self.assertEqual(server["transport"], "stdio")
        self.assertFalse(server["mutable"])
        self.assertFalse(server["deletable"])
        self.assertEqual(
            [tool["name"] for tool in server["tools"]],
            list(REPORT_BUILD_TOOL_NAMES),
        )

    def test_system_server_cannot_be_created_updated_or_deleted(self) -> None:
        with self.assertRaises(McpRegistryConflict):
            self.registry.create(
                {
                    "name": "GenBI_report",
                    "displayName": "fake",
                    "transport": "stdio",
                    "command": "python",
                },
                actor_id="admin-1",
            )
        with self.assertRaises(McpRegistryConflict):
            self.registry.update(
                "GenBI_report",
                {"command": "unexpected-command"},
                actor_id="admin-1",
            )
        with self.assertRaises(McpRegistryConflict):
            self.registry.delete("GenBI_report")

    def test_external_stdio_server_is_masked_but_runtime_receives_plaintext(self) -> None:
        created = self.registry.create(
            {
                "name": "BI_doris",
                "displayName": "Doris 查询",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@benborla29/mcp-server-mysql"],
                "environment": [
                    {"key": "MYSQL_HOST", "value": "doris.internal", "secret": False},
                    {"key": "MYSQL_PASSWORD", "value": "plain-db-password", "secret": True},
                ],
                "enabled": True,
            },
            actor_id="admin-1",
        )

        password = next(
            item for item in created["environment"] if item["key"] == "MYSQL_PASSWORD"
        )
        self.assertEqual(password["value"], "••••••••")
        self.assertTrue(password["configured"])
        self.assertNotIn(
            "plain-db-password",
            self.repository.records["BI_doris"].encrypted_secrets,
        )

        runtime = self.registry.runtime_servers()
        external_runtime = next(item for item in runtime if item.name == "BI_doris")
        self.assertEqual(
            [item.name for item in runtime],
            ["GenBI_report", "BI_doris"],
        )
        self.assertEqual(
            external_runtime.env["MYSQL_PASSWORD"],
            "plain-db-password",
        )

    def test_blank_secret_update_preserves_existing_value(self) -> None:
        self.registry.create(
            {
                "name": "external_api",
                "displayName": "External API",
                "transport": "streamable_http",
                "url": "https://mcp.example.test/mcp",
                "bearerTokenEnvVar": "EXTERNAL_MCP_TOKEN",
                "bearerToken": "first-token",
                "enabled": True,
            },
            actor_id="admin-1",
        )

        self.registry.update(
            "external_api",
            {
                "displayName": "Renamed display label",
                "bearerToken": "",
            },
            actor_id="admin-2",
        )

        self.assertEqual(
            self.registry.reveal_secrets("external_api"),
            {"EXTERNAL_MCP_TOKEN": "first-token"},
        )

    def test_name_is_immutable_after_creation(self) -> None:
        self.registry.create(
            {
                "name": "external_api",
                "displayName": "External API",
                "transport": "streamable_http",
                "url": "https://mcp.example.test/mcp",
            },
            actor_id="admin-1",
        )

        with self.assertRaises(McpRegistryConflict):
            self.registry.update(
                "external_api",
                {"name": "renamed_api"},
                actor_id="admin-1",
            )

    def test_disabled_external_server_is_not_loaded_at_runtime(self) -> None:
        self.registry.create(
            {
                "name": "disabled_api",
                "displayName": "Disabled API",
                "transport": "streamable_http",
                "url": "https://mcp.example.test/mcp",
                "enabled": False,
            },
            actor_id="admin-1",
        )

        self.assertEqual(
            [item.name for item in self.registry.runtime_servers()],
            ["GenBI_report"],
        )

    def test_security_upgrade_moves_legacy_mysql_pass_out_of_plaintext_config(self) -> None:
        now = datetime.now(timezone.utc)
        self.repository.records["BI_doris"] = McpServerRecord(
            id="legacy",
            name="BI_doris",
            display_name="BI_doris",
            transport="stdio",
            config={
                "command": "npx",
                "args": [],
                "environment": {"MYSQL_PASS": "legacy-plain-password"},
                "secretKeys": [],
            },
            encrypted_secrets="",
            enabled=True,
            created_by_id="system-import",
            updated_by_id="system-import",
            created_at=now,
            updated_at=now,
        )

        self.registry.upgrade_plaintext_secret_fields()

        stored = self.repository.records["BI_doris"]
        self.assertNotIn("MYSQL_PASS", stored.config["environment"])
        self.assertEqual(stored.config["secretKeys"], ["MYSQL_PASS"])
        self.assertNotIn("legacy-plain-password", stored.encrypted_secrets)
        self.assertEqual(
            self.registry.reveal_secrets("BI_doris"),
            {"MYSQL_PASS": "legacy-plain-password"},
        )


if __name__ == "__main__":
    unittest.main()
