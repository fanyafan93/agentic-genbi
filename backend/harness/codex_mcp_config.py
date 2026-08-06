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

from backend.mcp_servers.genbi_report_build_tools import (
    report_build_tool_schemas,
)


@dataclass(frozen=True)
class CodexMcpServer:
    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    env_vars: list[str] = field(default_factory=list)
    transport: str = "stdio"
    url: str = ""
    bearer_token_env_var: str = ""
    oauth_client_id: str = ""
    oauth_resource: str = ""
    runtime_env: dict[str, str] = field(default_factory=dict)


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


def load_runtime_codex_mcp_servers_from_env(
    environ: dict[str, str] | None = None,
    *,
    enabled_overrides: dict[str, bool] | None = None,
) -> list[CodexMcpServer]:
    """Return only MCP servers allowed for the analysis Codex runtime.

    The system UI may list all configured servers so operators can inspect and
    toggle them. The analysis runtime should expose only enabled servers that
    are explicitly allowed by GenBI configuration.
    """
    env = environ if environ is not None else dict(os.environ)
    if environ is None:
        from backend.system_management.mcp_registry import try_build_mcp_registry

        registry = try_build_mcp_registry()
        if registry is not None:
            allowed_names = _allowed_runtime_server_names(env)
            return [
                server
                for server in registry.runtime_servers()
                if allowed_names is None or server.name in allowed_names
            ]
    if enabled_overrides is None and environ is None:
        from backend.system_management import mcp_enabled_overrides

        enabled_overrides = mcp_enabled_overrides()
    effective_overrides = enabled_overrides or {}
    allowed_names = _allowed_runtime_server_names(env)
    servers: list[CodexMcpServer] = []
    for server in load_codex_mcp_servers_from_env(env):
        if not effective_overrides.get(
            server.name,
            _enabled_server(server, env=env),
        ):
            continue
        if allowed_names is not None and server.name not in allowed_names:
            continue
        servers.append(server)
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
        if server.transport == "streamable_http":
            overrides.append(
                f"mcp_servers.{server.name}.url={_toml_string(server.url)}"
            )
            if server.bearer_token_env_var:
                overrides.append(
                    f"mcp_servers.{server.name}.bearer_token_env_var="
                    f"{_toml_string(server.bearer_token_env_var)}"
                )
            if server.oauth_client_id:
                overrides.append(
                    f"mcp_servers.{server.name}.oauth_client_id="
                    f"{_toml_string(server.oauth_client_id)}"
                )
            if server.oauth_resource:
                overrides.append(
                    f"mcp_servers.{server.name}.oauth_resource="
                    f"{_toml_string(server.oauth_resource)}"
                )
        else:
            overrides.append(
                f"mcp_servers.{server.name}.command={_toml_string(server.command)}"
            )
            if server.args:
                overrides.append(
                    f"mcp_servers.{server.name}.args={_toml_array(server.args)}"
                )
            for env_key, env_value in server.env.items():
                overrides.append(
                    f"mcp_servers.{server.name}.env.{env_key}={_toml_string(env_value)}"
                )
            env_vars = list(server.env_vars)
            if server.name == "GenBI_report":
                for env_var in (
                    "GENBI_REPORT_TOOL_ENDPOINT",
                    "GENBI_REPORT_TOOL_TOKEN",
                ):
                    if env_var not in env_vars:
                        env_vars.append(env_var)
            if env_vars:
                overrides.append(
                    f"mcp_servers.{server.name}.env_vars={_toml_array(env_vars)}"
                )
    return overrides


def codex_mcp_runtime_environment(
    servers: Iterable[CodexMcpServer],
) -> dict[str, str]:
    environment: dict[str, str] = {}
    for server in servers:
        environment.update(server.runtime_env)
    return environment


def codex_mcp_server_statuses(
    environ: dict[str, str] | None = None,
    *,
    enabled_overrides: dict[str, bool] | None = None,
) -> list[CodexMcpServerStatus]:
    env = environ if environ is not None else dict(os.environ)
    if enabled_overrides is None and environ is None:
        from backend.system_management import mcp_enabled_overrides

        enabled_overrides = mcp_enabled_overrides()
    effective_overrides = enabled_overrides or {}
    return [
        _server_status(
            server,
            env=env,
            enabled=effective_overrides.get(server.name),
        )
        for server in load_codex_mcp_servers_from_env(env)
    ]


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


def _server_status(
    server: CodexMcpServer,
    *,
    env: dict[str, str],
    enabled: bool | None = None,
) -> CodexMcpServerStatus:
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
        enabled=_enabled_server(server, env=env) if enabled is None else enabled,
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


def _allowed_runtime_server_names(env: dict[str, str]) -> set[str] | None:
    raw_value = env.get("GENBI_CODEX_ALLOWED_MCP_SERVERS", "").strip()
    if not raw_value:
        return None
    return {
        item.strip()
        for item in raw_value.replace(",", " ").split()
        if item.strip()
    }


def _trusted_server(server: CodexMcpServer, *, env: dict[str, str]) -> bool:
    trusted_names = {
        item.strip()
        for item in env.get("GENBI_CODEX_TRUSTED_MCP_SERVERS", "GenBI_report").replace(",", " ").split()
        if item.strip()
    }
    return server.name in trusted_names


def _server_permission(server: CodexMcpServer) -> str:
    if server.name == "GenBI_report":
        return "report.write"
    if "mysql" in " ".join([server.command, *server.args]).lower() or "doris" in server.name.lower():
        return "database.readonly"
    return "tool.external"


def _known_tools(server: CodexMcpServer, *, trusted: bool) -> list[CodexMcpTool]:
    if server.name == "GenBI_report":
        return [
            CodexMcpTool(
                name=str(tool["name"]),
                description=str(tool["description"]),
                permission="report.write",
                trusted=trusted,
            )
            for tool in report_build_tool_schemas()
        ]
    if "mysql" in " ".join([server.command, *server.args]).lower() or "doris" in server.name.lower():
        return [
            CodexMcpTool("mysql_query", "Run a readonly SQL query through the configured Doris/MySQL MCP server.", "database.readonly"),
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
