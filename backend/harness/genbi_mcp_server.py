"""GenBI MCP alias server.

Forwards Codex MCP tool calls to a downstream MCP server. The default
downstream is ``@benborla29/mcp-server-mysql`` which registers its tool
as ``mysql_query``; Codex's LLM emits calls as
``mcp__BI_doris__mysql_query``. We register a single tool under that
exact name and forward the request, stripping the prefix so the
downstream server can resolve it.

Run as a stdio MCP server: ``python -m backend.harness.genbi_mcp_server``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Iterable, Iterator


# Configuration via environment so the launch path stays simple.
# GENBI_MCP_DOWNSTREAM_COMMAND / GENBI_MCP_DOWNSTREAM_ARGS / GENBI_MCP_DOWNSTREAM_ENV
# default to the @benborla29 mysql mcp server using the BI_doris env vars.
DEFAULT_DOWNSTREAM_COMMAND = "npx"
DEFAULT_DOWNSTREAM_ARGS = ["--no-install", "@benborla29/mcp-server-mysql"]

DOWNSTREAM_ENV_PREFIX = "GENBI_MCP_DOWNSTREAM_ENV_"
SERVER_NAME = os.getenv("GENBI_MCP_SERVER_NAME", "BI_doris")
# Codex 0.146.0's LLM may emit the bare downstream tool name
# (`mysql_query`) or the prefixed form (`mcp__BI_doris__mysql_query`)
# when calling this server. We advertise the bare name in tools/list so
# the dispatcher can find it; the prefix-stripping helper inside the
# alias accepts both shapes on tools/call.
TOOL_NAME = "mysql_query"


def _resolve_downstream_env() -> dict[str, str]:
    """Forward every GENBI_MCP_DOWNSTREAM_ENV_* key to the downstream server.

    A key ``GENBI_MCP_DOWNSTREAM_ENV_MYSQL_HOST`` becomes ``MYSQL_HOST``.
    """
    out: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith(DOWNSTREAM_ENV_PREFIX):
            out[key.removeprefix(DOWNSTREAM_ENV_PREFIX)] = value
    return out


def _resolve_downstream_command() -> tuple[str, list[str]]:
    command = os.getenv("GENBI_MCP_DOWNSTREAM_COMMAND") or DEFAULT_DOWNSTREAM_COMMAND
    # Accept both space-separated and JSON-array forms so config generators
    # don't have to guess the escaping strategy.
    raw_args = os.getenv("GENBI_MCP_DOWNSTREAM_ARGS", "")
    if raw_args:
        stripped = raw_args.strip()
        if stripped.startswith("["):
            import json as _json

            try:
                parsed = _json.loads(stripped)
                if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                    return command, list(parsed)
            except _json.JSONDecodeError:
                pass
        args = raw_args.split()
    else:
        args = list(DEFAULT_DOWNSTREAM_ARGS)
    return command, args


class DownstreamClient:
    """Manage a single downstream MCP server subprocess.

    The downstream uses JSON-RPC over stdio (the same protocol Codex
    speaks to its MCP servers). We speak the same protocol on the other
    side so the alias server is a transparent proxy.
    """

    def __init__(self, command: str, args: list[str], env: dict[str, str]) -> None:
        merged_env = {**os.environ, **env}
        self._proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            text=True,
            bufsize=1,
        )
        self._next_id = 1

    @property
    def running(self) -> bool:
        return self._proc.poll() is None

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()
        assert self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            stderr = ""
            if self._proc.stderr is not None:
                stderr = self._proc.stderr.read() or ""
            raise RuntimeError(f"downstream closed pipe; stderr={stderr!r}")
        return json.loads(line)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(payload) + "\n")
        self._proc.stdin.flush()

    def close(self) -> None:
        if self.running:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()


def _strip_server_prefix(tool_name: str) -> str:
    """Strip the ``mcp__<server>__`` prefix that Codex prepends.

    Codex may emit one or more such prefixes depending on whether it
    prepends the server name to the bare tool name or to a name that
    already includes the prefix (some older Codex versions double-up on
    the prefix). We strip repeatedly until the result no longer starts
    with the alias server's prefix.
    """
    prefix = f"mcp__{SERVER_NAME}__"
    while tool_name.startswith(prefix):
        tool_name = tool_name[len(prefix):]
    return tool_name


class GenbiMcpServer:
    """Single-file stdio MCP server exposing one aliased tool."""

    def __init__(self, downstream: DownstreamClient) -> None:
        self._downstream = downstream

    def run(self, stdin: Iterable[str], stdout: Any) -> None:
        # Optional verbose logging to /tmp/genbi_alias.log. Off by default;
        # enabled by setting GENBI_MCP_DIAG_LOG so operators can capture what
        # Codex actually dispatched when the alias layer misbehaves.
        diag_path = os.environ.get("GENBI_MCP_DIAG_LOG")
        diag = open(diag_path, "a", buffering=1) if diag_path else None
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                continue
            method = request.get("method", "")
            request_id = request.get("id")
            params = request.get("params") or {}
            if diag:
                diag.write(f"<- {method} {line[:500]}\n")

            if method == "initialize":
                # Negotiate capabilities against the downstream server.
                downstream_init = self._downstream.request("initialize", params)
                self._downstream.notify("notifications/initialized")
                # Merge downstream capabilities with whatever the client asked
                # for so Codex sees every key it advertised as accepted. Echo
                # the server name verbatim (the configured Codex MCP name) so
                # the dispatcher's routing table recognises this connection.
                client_caps = (
                    params.get("capabilities", {})
                    if isinstance(params, dict)
                    else {}
                )
                downstream_result = downstream_init.get("result", {})
                server_caps = downstream_result.get("capabilities", {})
                merged_caps = dict(client_caps)
                for key, value in server_caps.items():
                    merged_caps.setdefault(key, value)
                result = dict(downstream_result)
                result["capabilities"] = merged_caps
                result["serverInfo"] = {
                    "name": SERVER_NAME,
                    "version": "0.1.0",
                }
                if diag:
                    diag.write(
                        f"  init result: {json.dumps(result, ensure_ascii=False)[:400]}\n"
                    )
                self._write(
                    stdout,
                    {"jsonrpc": "2.0", "id": request_id, "result": result},
                )
                continue

            if method == "notifications/initialized":
                # Downstream already notified above.
                continue

            if method == "tools/list":
                # Advertise the tool under its bare downstream name `mysql_query`.
                # Codex 0.146.0's tool dispatcher expects the tool name to match
                # what its LLM emitted exactly. We tell the LLM (via the
                # developer prompt) to call `mysql_query`, which lines up with
                # what Codex will dispatch to us. Codex's LLM sometimes prepends
                # the server prefix and the alias stripper handles that case.
                advertised_name = TOOL_NAME
                tools = [
                    {
                        "name": advertised_name,
                        "description": (
                            "Run a read-only SQL query against the GenBI business database. "
                            "Forwarded to the @benborla29/mcp-server-mysql MCP server."
                        ),
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "sql": {
                                    "type": "string",
                                    "description": "The SQL query to execute (read-only).",
                                }
                            },
                            "required": ["sql"],
                        },
                        "annotations": {
                            "readOnlyHint": True,
                            "idempotentHint": True,
                            "destructiveHint": False,
                            "openWorldHint": False,
                        },
                    }
                ]
                self._write(
                    stdout,
                    {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}},
                )
                continue

            if method == "tools/call":
                tool_name = params.get("name", "")
                arguments = params.get("arguments", {})
                if diag:
                    diag.write(
                        f"  tools/call tool_name={tool_name!r} TOOL_NAME={TOOL_NAME!r}\n"
                    )
                # Codex 0.146.0's LLM sometimes emits the bare downstream
                # name (`mysql_query`) and sometimes prepends the server
                # prefix (`mcp__BI_doris__mysql_query`). The stripper peels
                # any number of such prefixes so both forms route correctly.
                downstream_tool = _strip_server_prefix(tool_name)
                if downstream_tool != TOOL_NAME:
                    self._write(
                        stdout,
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"unsupported call: {tool_name}",
                            },
                        },
                    )
                    continue
                try:
                    response = self._downstream.request(
                        "tools/call",
                        {"name": downstream_tool, "arguments": arguments},
                    )
                except Exception as exc:
                    self._write(
                        stdout,
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32603,
                                "message": f"downstream error: {exc}",
                            },
                        },
                    )
                    continue
                # Use the upstream request id; drop downstream's id.
                forwarded = {"jsonrpc": response.get("jsonrpc", "2.0"), "id": request_id}
                if "result" in response:
                    forwarded["result"] = response["result"]
                elif "error" in response:
                    forwarded["error"] = response["error"]
                self._write(stdout, forwarded)
                continue

            # Unknown notification: ack silently.
            if request_id is None:
                continue
            self._write(
                stdout,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                },
            )

    @staticmethod
    def _write(stdout: Any, payload: dict[str, Any]) -> None:
        stdout.write(json.dumps(payload) + "\n")
        stdout.flush()


def main(argv: list[str] | None = None) -> int:
    command, args = _resolve_downstream_command()
    env = _resolve_downstream_env()
    downstream = DownstreamClient(command, args, env)
    try:
        server = GenbiMcpServer(downstream)
        server.run(sys.stdin, sys.stdout)
    finally:
        downstream.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())