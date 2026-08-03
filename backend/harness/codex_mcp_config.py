"""Parse Codex MCP server entries from the GenBI environment.

MCP server entries are read from `GENBI_CODEX_MCP_COUNT` plus
`GENBI_CODEX_MCP_<N>_NAME`, `GENBI_CODEX_MCP_<N>_COMMAND`,
`GENBI_CODEX_MCP_<N>_ARGS`, `GENBI_CODEX_MCP_<N>_ENV_KEYS`,
`GENBI_CODEX_MCP_<N>_ENV_VALUES` style environment variables.

The parsed entries are later converted into CodexConfig.config_overrides
strings by `to_codex_config_overrides`.

MySQL-style entries (those using ``@benborla29/mcp-server-mysql`` or named
like ``BI_doris``) are automatically wrapped with the GenBI alias server
so Codex's built-in ``mcp__<server>__<tool>`` naming convention lines up
with the tool name the downstream server actually accepts.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Iterable


GENBI_ALIAS_SERVER_NAME = "GENBI_alias"
GENBI_ALIAS_MODULE = "backend.harness.genbi_mcp_server"

# Server names that should always be routed through the GenBI alias layer
# even when the args don't explicitly mention @benborla29/mcp-server-mysql.
_GENBI_ALIAS_FORCED_SERVER_NAMES = frozenset({"BI_doris"})


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


def _is_mysql_mcp_server(server: CodexMcpServer) -> bool:
    """Return True when the server should be routed through the GenBI alias layer.

    Triggered either by the server name (BI_doris) or when the launch command
    clearly targets the @benborla29/mcp-server-mysql package that only accepts
    bare tool names like ``mysql_query``.
    """
    if server.name in _GENBI_ALIAS_FORCED_SERVER_NAMES:
        return True
    joined = " ".join(server.args)
    return "@benborla29/mcp-server-mysql" in joined or "mcp-server-mysql" in joined


def wrap_server_with_genbi_alias(
    server: CodexMcpServer,
    *,
    python_bin: str | None = None,
) -> CodexMcpServer:
    """Rewrite a raw MySQL MCP server entry into a GenBI alias launch.

    The returned server keeps the original ``name`` so Codex's LLM continues
    to emit the familiar ``mcp__<server>__mysql_query`` call; under the hood
    we actually start :mod:`backend.harness.genbi_mcp_server`, which exposes
    a tool under that prefixed name and strips the prefix before forwarding
    to the real downstream server.
    """
    command = python_bin or sys.executable
    alias_env: dict[str, str] = {
        # The alias server advertises its tool with the exact prefix Codex
        # LLM expects based on the original (pre-rewrite) server name.
        "GENBI_MCP_SERVER_NAME": server.name,
        # Tell the alias layer how to launch the real downstream package.
        "GENBI_MCP_DOWNSTREAM_COMMAND": server.command,
        # Serialize args as JSON so spaces inside a single token stay intact
        # and the parser on the other side can reconstruct the list precisely.
        "GENBI_MCP_DOWNSTREAM_ARGS": json.dumps(server.args, ensure_ascii=False),
    }
    # Lift every raw env var into the GENBI_MCP_DOWNSTREAM_ENV_ namespace so
    # the alias client can forward the exact MYSQL_* set into the child.
    for env_key, env_value in server.env.items():
        alias_env[f"GENBI_MCP_DOWNSTREAM_ENV_{env_key}"] = env_value
    return CodexMcpServer(
        name=server.name,
        command=command,
        args=["-m", GENBI_ALIAS_MODULE],
        env=alias_env,
    )


def apply_genbi_alias_wrapping(
    servers: Iterable[CodexMcpServer],
    *,
    python_bin: str | None = None,
) -> list[CodexMcpServer]:
    """Apply :func:`wrap_server_with_genbi_alias` to every MySQL-style server.

    Non-MySQL servers pass through unchanged so arbitrary other MCP providers
    keep working without going through the alias proxy.
    """
    out: list[CodexMcpServer] = []
    for server in servers:
        if _is_mysql_mcp_server(server):
            out.append(wrap_server_with_genbi_alias(server, python_bin=python_bin))
        else:
            out.append(server)
    return out