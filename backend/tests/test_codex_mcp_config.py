from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_mcp_config import (
    CodexMcpServer,
    codex_mcp_server_status_payload,
    load_codex_mcp_servers_from_env,
    load_runtime_codex_mcp_servers_from_env,
    test_codex_mcp_server,
    to_codex_config_overrides,
)


class LoadCodexMcpServersFromEnvTest(unittest.TestCase):
    def test_returns_empty_list_when_count_unset(self) -> None:
        self.assertEqual(load_codex_mcp_servers_from_env({}), [])

    def test_returns_empty_list_when_count_invalid(self) -> None:
        self.assertEqual(load_codex_mcp_servers_from_env({"GENBI_CODEX_MCP_COUNT": "abc"}), [])

    def test_returns_empty_list_when_count_zero(self) -> None:
        self.assertEqual(load_codex_mcp_servers_from_env({"GENBI_CODEX_MCP_COUNT": "0"}), [])

    def test_skips_entries_missing_required_fields(self) -> None:
        env = {
            "GENBI_CODEX_MCP_COUNT": "2",
            "GENBI_CODEX_MCP_1_NAME": "BI_doris",
            "GENBI_CODEX_MCP_1_COMMAND": "npx",
            "GENBI_CODEX_MCP_1_ARGS": "-y @benborla29/mcp-server-mysql",
            # Entry 2 missing both NAME and COMMAND.
            "GENBI_CODEX_MCP_2_ARGS": "-y something",
        }
        servers = load_codex_mcp_servers_from_env(env)
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0].name, "BI_doris")
        self.assertEqual(servers[0].command, "npx")
        self.assertEqual(servers[0].args, ["-y", "@benborla29/mcp-server-mysql"])
        self.assertEqual(servers[0].env, {})

    def test_parses_full_entry_with_env_pairs(self) -> None:
        env = {
            "GENBI_CODEX_MCP_COUNT": "1",
            "GENBI_CODEX_MCP_1_NAME": "BI_doris",
            "GENBI_CODEX_MCP_1_COMMAND": "npx",
            "GENBI_CODEX_MCP_1_ARGS": "-y, @benborla29/mcp-server-mysql",
            "GENBI_CODEX_MCP_1_ENV_KEYS": "MYSQL_HOST MYSQL_PORT MYSQL_USER",
            "GENBI_CODEX_MCP_1_ENV_VALUES": "8.134.63.30 9030 readonly_user",
        }
        servers = load_codex_mcp_servers_from_env(env)
        self.assertEqual(len(servers), 1)
        self.assertEqual(
            servers[0].env,
            {"MYSQL_HOST": "8.134.63.30", "MYSQL_PORT": "9030", "MYSQL_USER": "readonly_user"},
        )

    def test_handles_multiple_servers(self) -> None:
        env = {
            "GENBI_CODEX_MCP_COUNT": "2",
            "GENBI_CODEX_MCP_1_NAME": "BI_doris",
            "GENBI_CODEX_MCP_1_COMMAND": "npx",
            "GENBI_CODEX_MCP_1_ARGS": "-y @benborla29/mcp-server-mysql",
            "GENBI_CODEX_MCP_2_NAME": "openmetadata",
            "GENBI_CODEX_MCP_2_COMMAND": "npx",
            "GENBI_CODEX_MCP_2_ARGS": "-y @openmetadata/mcp-server",
        }
        servers = load_codex_mcp_servers_from_env(env)
        self.assertEqual([s.name for s in servers], ["BI_doris", "openmetadata"])

    def test_runtime_loader_keeps_only_enabled_allowed_servers(self) -> None:
        env = {
            "GENBI_CODEX_MCP_COUNT": "4",
            "GENBI_CODEX_ALLOWED_MCP_SERVERS": "BI_doris GenBI_report",
            "GENBI_CODEX_MCP_BI_doris_ENABLED": "true",
            "GENBI_CODEX_MCP_GenBI_report_ENABLED": "true",
            "GENBI_CODEX_MCP_openmetadata_ENABLED": "true",
            "GENBI_CODEX_MCP_chrome_devtools_ENABLED": "false",
            "GENBI_CODEX_MCP_1_NAME": "BI_doris",
            "GENBI_CODEX_MCP_1_COMMAND": "npx",
            "GENBI_CODEX_MCP_2_NAME": "GenBI_report",
            "GENBI_CODEX_MCP_2_COMMAND": "python",
            "GENBI_CODEX_MCP_3_NAME": "openmetadata",
            "GENBI_CODEX_MCP_3_COMMAND": "npx",
            "GENBI_CODEX_MCP_4_NAME": "chrome_devtools",
            "GENBI_CODEX_MCP_4_COMMAND": "npx",
        }

        servers = load_runtime_codex_mcp_servers_from_env(env)

        self.assertEqual([server.name for server in servers], ["BI_doris", "GenBI_report"])

    def test_status_marks_genbi_report_as_trusted_internal_tool(self) -> None:
        payload = codex_mcp_server_status_payload({
            "GENBI_CODEX_MCP_COUNT": "1",
            "GENBI_CODEX_MCP_1_NAME": "GenBI_report",
            "GENBI_CODEX_MCP_1_COMMAND": "python",
            "GENBI_CODEX_MCP_1_ARGS": "-m backend.mcp_servers.genbi_report_server",
        })

        server = payload["servers"][0]  # type: ignore[index]
        self.assertEqual(server["name"], "GenBI_report")
        self.assertEqual(server["approval"], "trusted")
        self.assertEqual(server["permission"], "artifact.write")
        self.assertEqual(server["tools"][0]["name"], "create_interactive_report")

    def test_can_test_configured_mcp_server(self) -> None:
        result = test_codex_mcp_server("GenBI_report", {
            "GENBI_CODEX_MCP_COUNT": "1",
            "GENBI_CODEX_MCP_1_NAME": "GenBI_report",
            "GENBI_CODEX_MCP_1_COMMAND": "python",
            "GENBI_CODEX_MCP_1_ARGS": "-m backend.mcp_servers.genbi_report_server",
        })

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "trusted")


class ToCodexConfigOverridesTest(unittest.TestCase):
    def test_empty_iterable_returns_empty_list(self) -> None:
        self.assertEqual(to_codex_config_overrides([]), [])

    def test_command_only_server(self) -> None:
        server = CodexMcpServer(name="BI_doris", command="npx")
        overrides = to_codex_config_overrides([server])
        self.assertEqual(overrides, ['mcp_servers.BI_doris.command="npx"'])

    def test_server_with_args_and_env(self) -> None:
        server = CodexMcpServer(
            name="BI_doris",
            command="npx",
            args=["-y", "@benborla29/mcp-server-mysql"],
            env={
                "MYSQL_HOST": "8.134.63.30",
                "MYSQL_PORT": "9030",
                "MYSQL_USER": "readonly_user",
            },
        )
        overrides = to_codex_config_overrides([server])
        self.assertIn('mcp_servers.BI_doris.command="npx"', overrides)
        self.assertIn(
            'mcp_servers.BI_doris.args=["-y", "@benborla29/mcp-server-mysql"]',
            overrides,
        )
        self.assertIn('mcp_servers.BI_doris.env.MYSQL_HOST="8.134.63.30"', overrides)
        self.assertIn('mcp_servers.BI_doris.env.MYSQL_PORT="9030"', overrides)
        self.assertIn('mcp_servers.BI_doris.env.MYSQL_USER="readonly_user"', overrides)

    def test_escapes_special_characters_in_strings(self) -> None:
        server = CodexMcpServer(
            name="needs-quoting",
            command="sh",
            args=["-c", 'echo "hello"'],
        )
        overrides = to_codex_config_overrides([server])
        # The TOML string literal must backslash-escape any embedded double-quote,
        # so the produced line never contains an un-escaped `"hello"` substring.
        joined = "\n".join(overrides)
        self.assertIn(r"echo \"hello\"", joined)
        self.assertNotIn('echo "hello"', joined)


class CodexSdkAnalysisRuntimeMcpIntegrationTest(unittest.TestCase):
    def test_openai_provider_emits_native_mcp_overrides_from_env(self) -> None:
        import os
        from unittest.mock import patch

        from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime

        env = {
            "GENBI_CODEX_MCP_COUNT": "1",
            "GENBI_CODEX_MCP_1_NAME": "BI_doris",
            "GENBI_CODEX_MCP_1_COMMAND": "npx",
            "GENBI_CODEX_MCP_1_ARGS": "-y @benborla29/mcp-server-mysql",
            "GENBI_ENV_FILE": "missing-for-test.env",
        }
        runtime = CodexSdkAnalysisRuntime(
            codex_factory=lambda: None,
            async_codex_factory=lambda: None,
        )
        runtime.provider = "openai"
        with patch.dict(os.environ, env, clear=False):
            overrides = runtime._config_overrides()
        self.assertIn('mcp_servers.BI_doris.command="npx"', overrides)
        self.assertIn(
            'mcp_servers.BI_doris.args=["-y", "@benborla29/mcp-server-mysql"]',
            overrides,
        )

    def test_codex_bin_is_read_from_env(self) -> None:
        import os
        import tempfile
        from unittest.mock import patch

        from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime

        with tempfile.NamedTemporaryFile() as fh:
            with patch.dict(
                os.environ,
                {"GENBI_CODEX_BIN": fh.name, "GENBI_ENV_FILE": "missing-for-test.env"},
                clear=True,
            ):
                runtime = CodexSdkAnalysisRuntime(
                    codex_factory=lambda: None,
                    async_codex_factory=lambda: None,
                )
            self.assertEqual(runtime.codex_bin, fh.name)

    def test_codex_bin_defaults_to_none_when_env_missing(self) -> None:
        import os
        from unittest.mock import patch

        from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime

        with patch.dict(os.environ, {"GENBI_ENV_FILE": "missing-for-test.env"}, clear=True):
            runtime = CodexSdkAnalysisRuntime(
                codex_factory=lambda: None,
                async_codex_factory=lambda: None,
            )
        self.assertIsNone(runtime.codex_bin)

    def test_codex_bin_constructor_arg_overrides_env(self) -> None:
        from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime

        runtime = CodexSdkAnalysisRuntime(
            codex_bin="/opt/codex-cli/bin/codex",
            codex_factory=lambda: None,
            async_codex_factory=lambda: None,
        )
        self.assertEqual(runtime.codex_bin, "/opt/codex-cli/bin/codex")

    def test_codex_home_renders_provider_and_native_mcp_config(self) -> None:
        import os
        import tempfile
        from unittest.mock import patch

        from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {
                    "GENBI_CODEX_HOME": tmp,
                    "GENBI_CODEX_BIN": "/usr/local/bin/codex",
                    "GENBI_CODEX_PROVIDER": "minimax",
                    "GENBI_CODEX_BASE_URL": "https://api.minimaxi.com/v1",
                    "GENBI_CODEX_API_KEY": "minimax-test-key",
                    "GENBI_CODEX_MCP_COUNT": "1",
                    "GENBI_CODEX_MCP_1_NAME": "BI_doris",
                    "GENBI_CODEX_MCP_1_COMMAND": "npx",
                    "GENBI_CODEX_MCP_1_ARGS": "-y @benborla29/mcp-server-mysql",
                    "GENBI_CODEX_MCP_1_ENV_KEYS": "MYSQL_HOST",
                    "GENBI_CODEX_MCP_1_ENV_VALUES": "8.134.63.30",
                    "GENBI_ENV_FILE": "missing-for-test.env",
                },
                clear=True,
            ):
                runtime = CodexSdkAnalysisRuntime(
                    codex_factory=lambda: None,
                    async_codex_factory=lambda: None,
                )
            config_path = os.path.join(tmp, "config.toml")
            with open(config_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertEqual(runtime.codex_home, tmp)
            self.assertIn('model_providers.minimax.name="minimax"', content)
            self.assertIn('mcp_servers.BI_doris.command="npx"', content)
            self.assertIn(
                'mcp_servers.BI_doris.args=["-y", "@benborla29/mcp-server-mysql"]',
                content,
            )
            self.assertIn(
                'mcp_servers.BI_doris.env.MYSQL_HOST="8.134.63.30"',
                content,
            )

    def test_codex_home_is_isolated_when_mcp_is_configured(self) -> None:
        import os
        from unittest.mock import patch

        from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime

        with patch.dict(
            os.environ,
            {
                "GENBI_CODEX_PROVIDER": "minimax",
                "GENBI_CODEX_BASE_URL": "https://api.minimaxi.com/v1",
                "GENBI_CODEX_API_KEY": "minimax-test-key",
                "GENBI_CODEX_MCP_COUNT": "1",
                "GENBI_CODEX_MCP_1_NAME": "BI_doris",
                "GENBI_CODEX_MCP_1_COMMAND": "npx",
                "GENBI_CODEX_MCP_1_ARGS": "-y @benborla29/mcp-server-mysql",
                "GENBI_ENV_FILE": "missing-for-test.env",
            },
            clear=True,
        ):
            runtime = CodexSdkAnalysisRuntime(
                codex_factory=lambda: None,
                async_codex_factory=lambda: None,
            )

        self.assertIsNotNone(runtime.codex_home)
        config_path = os.path.join(runtime.codex_home, "config.toml")
        with open(config_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("mcp_servers.BI_doris", content)

if __name__ == "__main__":
    unittest.main()
