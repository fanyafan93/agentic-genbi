from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.harness.codex_mcp_config import (
    GENBI_ALIAS_MODULE,
    CodexMcpServer,
    apply_genbi_alias_wrapping,
    load_codex_mcp_servers_from_env,
    to_codex_config_overrides,
    wrap_server_with_genbi_alias,
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


class GenbiAliasWrappingTest(unittest.TestCase):
    def test_wrap_server_preserves_name_and_replaces_command(self) -> None:
        server = CodexMcpServer(
            name="BI_doris",
            command="npx",
            args=["-y", "@benborla29/mcp-server-mysql"],
        )
        wrapped = wrap_server_with_genbi_alias(server, python_bin="/usr/bin/python3")
        self.assertEqual(wrapped.name, "BI_doris")
        self.assertEqual(wrapped.command, "/usr/bin/python3")
        self.assertEqual(wrapped.args, ["-m", GENBI_ALIAS_MODULE])

    def test_wrap_server_forwards_original_command_and_args_via_env(self) -> None:
        import json as _json

        server = CodexMcpServer(
            name="BI_doris",
            command="npx",
            args=["--no-install", "@benborla29/mcp-server-mysql"],
            env={
                "MYSQL_HOST": "8.134.63.30",
                "MYSQL_PORT": "9030",
                "MYSQL_USER": "readonly_user",
            },
        )
        wrapped = wrap_server_with_genbi_alias(server)
        self.assertEqual(wrapped.env["GENBI_MCP_SERVER_NAME"], "BI_doris")
        self.assertEqual(wrapped.env["GENBI_MCP_DOWNSTREAM_COMMAND"], "npx")
        decoded_args = _json.loads(wrapped.env["GENBI_MCP_DOWNSTREAM_ARGS"])
        self.assertEqual(decoded_args, ["--no-install", "@benborla29/mcp-server-mysql"])
        self.assertEqual(
            wrapped.env["GENBI_MCP_DOWNSTREAM_ENV_MYSQL_HOST"],
            "8.134.63.30",
        )
        self.assertEqual(
            wrapped.env["GENBI_MCP_DOWNSTREAM_ENV_MYSQL_USER"],
            "readonly_user",
        )

    def test_apply_wrapping_routes_mysql_servers_but_preserves_others(self) -> None:
        servers = [
            CodexMcpServer(
                name="BI_doris",
                command="npx",
                args=["-y", "@benborla29/mcp-server-mysql"],
            ),
            CodexMcpServer(name="openmetadata", command="node", args=["/opt/om-mcp.js"]),
            CodexMcpServer(name="filesystem", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/data"]),
        ]
        wrapped = apply_genbi_alias_wrapping(servers, python_bin="python3")
        self.assertEqual(len(wrapped), 3)
        # BI_doris was rewired to the alias module.
        self.assertEqual(wrapped[0].name, "BI_doris")
        self.assertEqual(wrapped[0].args, ["-m", GENBI_ALIAS_MODULE])
        # Non-mysql servers pass through untouched.
        self.assertEqual(wrapped[1], servers[1])
        self.assertEqual(wrapped[2], servers[2])

    def test_apply_wrapping_defaults_python_bin_to_sys_executable(self) -> None:
        import sys as _sys

        server = CodexMcpServer(
            name="BI_doris",
            command="npx",
            args=["-y", "@benborla29/mcp-server-mysql"],
        )
        wrapped = apply_genbi_alias_wrapping([server])
        self.assertEqual(wrapped[0].command, _sys.executable)


class CodexSdkAnalysisRuntimeMcpIntegrationTest(unittest.TestCase):
    def test_openai_provider_emits_wrapped_alias_overrides_from_env(self) -> None:
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
        # After alias wrapping, BI_doris launches via python -m backend.harness.genbi_mcp_server
        # rather than directly invoking npx. We key off the command= prefix + args line because
        # the exact Python path varies by OS and has TOML escape differences on Windows.
        command_line = next(
            (line for line in overrides if line.startswith("mcp_servers.BI_doris.command=")),
            None,
        )
        self.assertIsNotNone(command_line)
        # A raw npx command was never emitted; the wrapping rewrote it to Python.
        self.assertNotIn('mcp_servers.BI_doris.command="npx"', overrides)
        self.assertIn("python", command_line.lower())
        self.assertIn(
            f'mcp_servers.BI_doris.args={_toml_array_for_test(["-m", GENBI_ALIAS_MODULE])}',
            overrides,
        )
        # The original downstream launch info is forwarded via GENBI_MCP_* env vars.
        self.assertIn(
            'mcp_servers.BI_doris.env.GENBI_MCP_SERVER_NAME="BI_doris"',
            overrides,
        )
        self.assertIn(
            'mcp_servers.BI_doris.env.GENBI_MCP_DOWNSTREAM_COMMAND="npx"',
            overrides,
        )

    def test_codex_bin_is_read_from_env(self) -> None:
        import os
        from unittest.mock import patch

        from backend.harness.codex_sdk_runner import CodexSdkAnalysisRuntime

        with patch.dict(
            os.environ,
            {"GENBI_CODEX_BIN": "/usr/local/bin/codex", "GENBI_ENV_FILE": "missing-for-test.env"},
            clear=True,
        ):
            runtime = CodexSdkAnalysisRuntime(
                codex_factory=lambda: None,
                async_codex_factory=lambda: None,
            )
        self.assertEqual(runtime.codex_bin, "/usr/local/bin/codex")

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

    def test_codex_home_renders_provider_and_wrapped_mcp_config(self) -> None:
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
            # Rendered config should be the alias-wrapped version: Python module
            # plus GENBI_MCP_* env forwards instead of raw npx.
            command_line = next(
                (
                    line
                    for line in content.splitlines()
                    if line.startswith("mcp_servers.BI_doris.command=")
                ),
                None,
            )
            self.assertIsNotNone(command_line)
            self.assertNotIn('mcp_servers.BI_doris.command="npx"', content)
            self.assertIn("python", command_line.lower())
            self.assertIn(
                'mcp_servers.BI_doris.env.GENBI_MCP_SERVER_NAME="BI_doris"',
                content,
            )
            self.assertIn(
                'mcp_servers.BI_doris.env.GENBI_MCP_DOWNSTREAM_ENV_MYSQL_HOST="8.134.63.30"',
                content,
            )


def _toml_array_for_test(values: list[str]) -> str:
    escaped = ', '.join('"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"' for v in values)
    return f"[{escaped}]"


if __name__ == "__main__":
    unittest.main()