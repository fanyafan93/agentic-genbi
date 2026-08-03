"""Parse Codex MCP server entries from the GenBI environment.

MCP server entries are read from `GENBI_CODEX_MCP_COUNT` plus
`GENBI_CODEX_MCP_<N>_NAME`, `GENBI_CODEX_MCP_<N>_COMMAND`,
`GENBI_CODEX_MCP_<N>_ARGS`, `GENBI_CODEX_MCP_<N>_ENV_KEYS`,
`GENBI_CODEX_MCP_<N>_ENV_VALUES` style environment variables.

The parsed entries are later converted into CodexConfig.config_overrides
strings by `to_codex_config_overrides`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class CodexMcpServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def load_codex_mcp_servers_from_env(
    environ: dict[str, str] | None = None,
) -> list[CodexMcpServer]:
    """Parse MCP server entries from the environment.

    Returns an empty list when `GENBI_CODEX_MCP_COUNT` is unset or zero.
    Entries with missing required fields are skipped (callers may log).
    """
    env = environ if environ is not None else dict(os.environ)
    raw_count = env.get("GENBI_CODEX_MCP_COUNT", "").strip()
    if not raw_count:
        return []
    try:
        count = int(raw_count)
    except ValueError:
        return []
    if count <= 0:
        return []
    servers: list[CodexMcpServer] = []
    for index in range(1, count + 1):
        prefix = f"GENBI_CODEX_MCP_{index}_"
        name = env.get(prefix + "NAME", "").strip()
        command = env.get(prefix + "COMMAND", "").strip()
        if not name or not command:
            continue
        args = _split_tokens(env.get(prefix + "ARGS", ""))
        env_keys = _split_tokens(env.get(prefix + "ENV_KEYS", ""))
        env_values = _split_tokens(env.get(prefix + "ENV_VALUES", ""))
        env_pairs: dict[str, str] = {}
        for key, value in zip(env_keys, env_values):
            env_pairs[key] = value
        servers.append(
            CodexMcpServer(
                name=name,
                command=command,
                args=args,
                env=env_pairs,
            )
        )
    return servers


def _split_tokens(value: str) -> list[str]:
    if not value:
        return []
    tokens = value.replace(",", " ").split()
    return [token for token in tokens if token]


def to_codex_config_overrides(servers: Iterable[CodexMcpServer]) -> list[str]:
    """Convert MCP server entries into CodexConfig.config_overrides TOML strings."""
    overrides: list[str] = []
    for server in servers:
        overrides.append(f"mcp_servers.{server.name}.command={_toml_string(server.command)}")
        if server.args:
            overrides.append(
                f"mcp_servers.{server.name}.args={_toml_array(server.args)}"
            )
        for env_key, env_value in server.env.items():
            overrides.append(
                f"mcp_servers.{server.name}.env.{env_key}={_toml_string(env_value)}"
            )
    return overrides


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(item) for item in values) + "]"
