from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import StringIO

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config.env import check_runtime_env, load_project_env, main
from backend.resource_library.database_tools import DatabaseConfig


class EnvConfigTest(unittest.TestCase):
    def test_load_project_env_reads_explicit_file_without_overriding_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "GENBI_DB_HOST=10.0.0.9",
                        "GENBI_DB_PORT=3310",
                        "GENBI_DB_USER=readonly",
                        "GENBI_DB_PASSWORD=secret",
                        "GENBI_DB_DATABASE=dm",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"GENBI_ENV_FILE": str(env_path), "GENBI_DB_HOST": "existing"}, clear=True):
                loaded = load_project_env()
                config = DatabaseConfig.from_env()

            self.assertTrue(loaded)
            self.assertEqual(config.host, "existing")
            self.assertEqual(config.port, 3310)
            self.assertEqual(config.user, "readonly")
            self.assertEqual(config.password, "secret")
            self.assertEqual(config.database, "dm")

    def test_check_runtime_env_reports_missing_required_runtime_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "GENBI_ENV_FILE": str(Path(temp_dir) / "missing.env"),
                    "GENBI_RESOURCE_LIBRARY_ROOT": str(Path(temp_dir) / "missing"),
                },
                clear=True,
            ):
                payload = check_runtime_env()

        checks = {item["name"]: item for item in payload["checks"]}
        self.assertFalse(payload["ready"])
        self.assertFalse(payload["env_loaded"])
        self.assertFalse(checks["mysql"]["ok"])
        self.assertFalse(checks["resource_library"]["ok"])
        self.assertTrue(checks["llm"]["ok"])

    def test_check_runtime_env_accepts_complete_local_runtime_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resource_root = Path(temp_dir) / "资源库"
            resource_root.mkdir()
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        f"GENBI_RESOURCE_LIBRARY_ROOT={resource_root}",
                        "GENBI_EXPLORATION_RUNTIME=local",
                        "GENBI_DB_HOST=127.0.0.1",
                        "GENBI_DB_PORT=3306",
                        "GENBI_DB_USER=readonly",
                        "GENBI_DB_PASSWORD=secret",
                        "NEXT_PUBLIC_GENBI_API_BASE_URL=http://localhost:8000",
                        "GENBI_MODEL_INPUT_USD_PER_1M=0.4",
                        "GENBI_MODEL_OUTPUT_USD_PER_1M=1.6",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                payload = check_runtime_env(str(env_path))

        checks = {item["name"]: item for item in payload["checks"]}
        self.assertTrue(payload["ready"])
        self.assertTrue(payload["env_loaded"])
        self.assertTrue(checks["mysql"]["ok"])
        self.assertTrue(checks["resource_library"]["ok"])
        self.assertTrue(checks["frontend_api_base"]["ok"])
        self.assertTrue(checks["cost_config"]["ok"])

    def test_check_runtime_env_accepts_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resource_root = Path(temp_dir) / "资源库"
            resource_root.mkdir()
            with patch.dict(
                os.environ,
                {
                    "GENBI_ENV_FILE": str(Path(temp_dir) / "missing.env"),
                    "GENBI_RESOURCE_LIBRARY_ROOT": str(resource_root),
                    "DATABASE_URL": "mysql+pymysql://readonly_user:liran%402026@8.134.63.30:3306/dm",
                },
                clear=True,
            ):
                payload = check_runtime_env()

        mysql = {item["name"]: item for item in payload["checks"]}["mysql"]
        self.assertTrue(mysql["ok"])
        self.assertIn("host=8.134.63.30", mysql["detail"])
        self.assertIn("database=dm", mysql["detail"])
        self.assertNotIn("liran", mysql["detail"])

    def test_check_runtime_env_masks_llm_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resource_root = Path(temp_dir) / "resources"
            resource_root.mkdir()
            with patch.dict(
                os.environ,
                {
                    "GENBI_RESOURCE_LIBRARY_ROOT": str(resource_root),
                    "GENBI_EXPLORATION_RUNTIME": "openai",
                    "GENBI_ENV_FILE": str(Path(temp_dir) / "missing.env"),
                    "OPENAI_API_KEY": "sk-test-1234567890",
                    "GENBI_DB_HOST": "127.0.0.1",
                    "GENBI_DB_USER": "readonly",
                    "GENBI_DB_PASSWORD": "secret",
                },
                clear=True,
            ):
                payload = check_runtime_env()

        llm = {item["name"]: item for item in payload["checks"]}["llm"]
        self.assertTrue(llm["ok"])
        self.assertIn("sk-t", llm["detail"])
        self.assertNotIn("123456", llm["detail"])

    def test_check_runtime_env_accepts_minimax_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resource_root = Path(temp_dir) / "resources"
            resource_root.mkdir()
            with patch.dict(
                os.environ,
                {
                    "GENBI_RESOURCE_LIBRARY_ROOT": str(resource_root),
                    "GENBI_EXPLORATION_RUNTIME": "llm",
                    "GENBI_LLM_PROVIDER": "minimax",
                    "GENBI_EXPLORATION_MODEL": "minimax-test-model",
                    "GENBI_ENV_FILE": str(Path(temp_dir) / "missing.env"),
                    "MINIMAX_API_KEY": "mini-test-1234567890",
                    "MINIMAX_BASE_URL": "https://api.minimax.example/v1",
                    "GENBI_DB_HOST": "127.0.0.1",
                    "GENBI_DB_USER": "readonly",
                    "GENBI_DB_PASSWORD": "secret",
                },
                clear=True,
            ):
                payload = check_runtime_env()

        llm = {item["name"]: item for item in payload["checks"]}["llm"]
        self.assertTrue(payload["ready"])
        self.assertTrue(llm["ok"])
        self.assertIn("provider=minimax", llm["detail"])
        self.assertIn("base_url=https://api.minimax.example/v1", llm["detail"])

    def test_env_doctor_no_fail_exits_zero_for_missing_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("sys.stdout", new_callable=StringIO):
            code = main(["doctor", "--json", "--no-fail"])

        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
