from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.system_management.mcp_registry import McpSecretCipher
from backend.system_management.model_connections import (
    MemoryModelConnectionRepository,
    ModelConnectionConflict,
    ModelConnectionRegistry,
    legacy_model_connection_from_env,
)


class ModelConnectionRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = MemoryModelConnectionRepository()
        self.registry = ModelConnectionRegistry(
            repository=self.repository,
            cipher=McpSecretCipher("unit-test-master-key"),
        )

    def test_first_connection_is_default_and_secret_is_encrypted(self) -> None:
        created = self.registry.create(
            {
                "name": "minimax_primary",
                "displayName": "MiniMax 主连接",
                "providerType": "minimax",
                "model": "MiniMax-M3",
                "baseUrl": "https://api.minimaxi.com/v1",
                "apiKey": "plain-model-key",
                "enabled": True,
            },
            actor_id="admin-1",
        )

        self.assertTrue(created["isDefault"])
        self.assertTrue(created["apiKeyConfigured"])
        self.assertNotIn("plain-model-key", str(created))
        self.assertNotIn(
            "plain-model-key",
            self.repository.records["minimax_primary"].encrypted_api_key,
        )
        self.assertEqual(
            self.registry.reveal_secret("minimax_primary"),
            "plain-model-key",
        )

        runtime = self.registry.default_runtime_connection()
        self.assertIsNotNone(runtime)
        assert runtime is not None
        self.assertEqual(runtime.name, "minimax_primary")
        self.assertEqual(runtime.provider_type, "minimax")
        self.assertEqual(runtime.model, "MiniMax-M3")
        self.assertEqual(runtime.api_key, "plain-model-key")

    def test_switching_default_is_explicit_and_protects_active_default(self) -> None:
        self.registry.create(
            {
                "name": "openai_primary",
                "displayName": "OpenAI",
                "providerType": "openai",
                "model": "gpt-test",
                "baseUrl": "https://api.openai.com/v1",
                "apiKey": "openai-key",
                "enabled": True,
            },
            actor_id="admin-1",
        )
        self.registry.create(
            {
                "name": "minimax_backup",
                "displayName": "MiniMax",
                "providerType": "minimax",
                "model": "MiniMax-M3",
                "baseUrl": "https://api.minimaxi.com/v1",
                "apiKey": "minimax-key",
                "enabled": True,
            },
            actor_id="admin-1",
        )

        selected = self.registry.set_default(
            "minimax_backup",
            actor_id="admin-2",
        )

        self.assertTrue(selected["isDefault"])
        self.assertFalse(self.registry.get("openai_primary")["isDefault"])
        with self.assertRaises(ModelConnectionConflict):
            self.registry.update(
                "minimax_backup",
                {"enabled": False},
                actor_id="admin-2",
            )
        with self.assertRaises(ModelConnectionConflict):
            self.registry.delete("minimax_backup")

    def test_blank_secret_update_preserves_existing_key(self) -> None:
        self.registry.create(
            {
                "name": "custom",
                "displayName": "内部网关",
                "providerType": "openai_compatible",
                "model": "internal-model",
                "baseUrl": "https://models.example.test/v1",
                "apiKey": "first-key",
                "enabled": True,
            },
            actor_id="admin-1",
        )

        self.registry.update(
            "custom",
            {
                "displayName": "内部模型网关",
                "apiKey": "",
            },
            actor_id="admin-2",
        )

        self.assertEqual(self.registry.reveal_secret("custom"), "first-key")
        self.assertEqual(
            self.registry.get("custom")["displayName"],
            "内部模型网关",
        )

    def test_disabled_connection_cannot_become_default(self) -> None:
        self.registry.create(
            {
                "name": "disabled",
                "displayName": "Disabled",
                "providerType": "openai_compatible",
                "model": "test-model",
                "baseUrl": "https://models.example.test/v1",
                "apiKey": "test-key",
                "enabled": False,
            },
            actor_id="admin-1",
        )

        with self.assertRaises(ModelConnectionConflict):
            self.registry.set_default("disabled", actor_id="admin-1")

    def test_legacy_environment_can_seed_the_first_connection(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GENBI_CODEX_PROVIDER": "minimax",
                "GENBI_ANALYSIS_MODEL": "MiniMax-M3",
                "MINIMAX_BASE_URL": "https://api.minimaxi.com/v1",
                "MINIMAX_API_KEY": "legacy-minimax-key",
            },
            clear=False,
        ):
            payload = legacy_model_connection_from_env()

        self.assertEqual(payload["name"], "minimax")
        self.assertEqual(payload["providerType"], "minimax")
        self.assertEqual(payload["model"], "MiniMax-M3")
        self.assertEqual(payload["apiKey"], "legacy-minimax-key")


if __name__ == "__main__":
    unittest.main()
