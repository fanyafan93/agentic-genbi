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
import shutil
from dataclasses import asdict, dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class CodexMcpServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CodexMcpTool:
    name: str
    description: str
    permission: str = "read"
    trusted: bool = False


@dataclass(frozen=True)
class CodexMcpServerStatus:
    name: str
    command: str
    args: list[str]
    enabled: bool
    status: str
    permission: str
    trusted: bool
    approval: str
    tools: list[CodexMcpTool]
    envKeys: list[str]
    message: str


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


def codex_mcp_server_statuses(
    environ: dict[str, str] | None = None,
) -> list[CodexMcpServerStatus]:
    env = environ if environ is not None else dict(os.environ)
    return [_server_status(server, env=env) for server in load_codex_mcp_servers_from_env(env)]


def codex_mcp_server_status_payload(environ: dict[str, str] | None = None) -> dict[str, object]:
    servers = codex_mcp_server_statuses(environ)
    return {"servers": [asdict(server) for server in servers]}


def test_codex_mcp_server(name: str, environ: dict[str, str] | None = None) -> dict[str, object]:
    env = environ if environ is not None else dict(os.environ)
    server = next((item for item in load_codex_mcp_servers_from_env(env) if item.name == name), None)
    if not server:
        return {"name": name, "ok": False, "status": "missing", "message": "MCP server is not configured."}
    status = _server_status(server, env=env)
    return {
        "name": server.name,
        "ok": status.status in {"ready", "trusted"},
        "status": status.status,
        "message": status.message,
    }


def _server_status(server: CodexMcpServer, *, env: dict[str, str]) -> CodexMcpServerStatus:
    trusted = _trusted_server(server, env=env)
    command_available = _command_available(server.command)
    status = "trusted" if trusted else "ready" if command_available else "unavailable"
    message = (
        "Internal trusted GenBI report tool. Approval can be bypassed by GenBI policy."
        if trusted
        else "Command is available."
        if command_available
        else f"Command `{server.command}` was not found in PATH."
    )
    return CodexMcpServerStatus(
        name=server.name,
        command=server.command,
        args=server.args,
        enabled=_enabled_server(server, env=env),
        status=status,
        permission=_server_permission(server),
        trusted=trusted,
        approval="trusted" if trusted else "required",
        tools=_known_tools(server, trusted=trusted),
        envKeys=sorted(server.env.keys()),
        message=message,
    )


def _enabled_server(server: CodexMcpServer, *, env: dict[str, str]) -> bool:
    value = env.get(f"GENBI_CODEX_MCP_{server.name}_ENABLED", "").strip().lower()
    return value not in {"0", "false", "off", "no", "disabled"}


def _trusted_server(server: CodexMcpServer, *, env: dict[str, str]) -> bool:
    trusted_names = {
        item.strip()
        for item in env.get("GENBI_CODEX_TRUSTED_MCP_SERVERS", "GenBI_report").replace(",", " ").split()
        if item.strip()
    }
    return server.name in trusted_names


def _server_permission(server: CodexMcpServer) -> str:
    if server.name == "GenBI_report":
        return "artifact.write"
    if "mysql" in " ".join([server.command, *server.args]).lower() or "doris" in server.name.lower():
        return "database.readonly"
    return "tool.external"


def _known_tools(server: CodexMcpServer, *, trusted: bool) -> list[CodexMcpTool]:
    if server.name == "GenBI_report":
        return [
            CodexMcpTool(
                name="create_interactive_report",
                description="Create a GenBI interactive_report artifact from verified rows for the right-side Puck panel.",
                permission="artifact.write",
                trusted=trusted,
            ),
            CodexMcpTool(
                name="update_interactive_report",
                description="Planned: update an existing interactive_report artifact.",
                permission="artifact.write",
                trusted=trusted,
            ),
            CodexMcpTool(
                name="get_interactive_report",
                description="Planned: read an existing interactive_report artifact.",
                permission="artifact.read",
                trusted=trusted,
            ),
        ]
    if "mysql" in " ".join([server.command, *server.args]).lower() or "doris" in server.name.lower():
        return [
            CodexMcpTool("mysql_query", "Run a readonly SQL query through the configured Doris/MySQL MCP server.", "database.readonly"),
            CodexMcpTool("list_mcp_resources", "List MCP resources exposed by the server.", "metadata.read"),
            CodexMcpTool("read_mcp_resource", "Read a specific MCP resource exposed by the server.", "metadata.read"),
        ]
    return []


def _command_available(command: str) -> bool:
    if command in {"python", "python3"}:
        return True
    return shutil.which(command) is not None


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(item) for item in values) + "]"
