from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Any

from backend.harness.codex_mcp_config import CodexMcpServer


def probe_mcp_server(
    server: CodexMcpServer,
    *,
    timeout_seconds: float = 15,
) -> dict[str, Any]:
    try:
        if server.transport == "streamable_http":
            tools = _probe_http(server, timeout_seconds=timeout_seconds)
        else:
            tools = _probe_stdio(server, timeout_seconds=timeout_seconds)
    except Exception as error:
        return {
            "name": server.name,
            "ok": False,
            "status": "unavailable",
            "message": _safe_error_message(error),
            "tools": [],
        }
    trusted = server.name == "GenBI_report"
    permission = "report.write" if trusted else "tool.external"
    return {
        "name": server.name,
        "ok": True,
        "status": "trusted" if trusted else "ready",
        "message": f"Connected and discovered {len(tools)} tool(s).",
        "tools": [
            {
                "name": str(tool.get("name") or ""),
                "description": str(tool.get("description") or ""),
                "permission": permission,
                "trusted": trusted,
            }
            for tool in tools
            if str(tool.get("name") or "").strip()
        ],
    }


def _probe_stdio(
    server: CodexMcpServer,
    *,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    environment = os.environ.copy()
    environment.update(server.env)
    environment.update(server.runtime_env)
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    )
    process = subprocess.Popen(
        [server.command, *server.args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=environment,
        creationflags=creationflags,
    )
    messages: queue.Queue[dict[str, Any]] = queue.Queue()

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                messages.put(value)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    try:
        _write_stdio(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "genbi-admin", "version": "1"},
                },
            },
        )
        _wait_for_response(messages, request_id=1, timeout_seconds=timeout_seconds)
        _write_stdio(
            process,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        _write_stdio(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        response = _wait_for_response(
            messages,
            request_id=2,
            timeout_seconds=timeout_seconds,
        )
        result = response.get("result")
        return _tools_from_result(result)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def _write_stdio(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("MCP process stdin is unavailable.")
    process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    process.stdin.flush()


def _wait_for_response(
    messages: queue.Queue[dict[str, Any]],
    *,
    request_id: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    while True:
        try:
            message = messages.get(timeout=timeout_seconds)
        except queue.Empty as error:
            raise TimeoutError("MCP server did not respond before the timeout.") from error
        if message.get("id") != request_id:
            continue
        if "error" in message:
            raise RuntimeError("MCP server returned a protocol error.")
        return message


def _probe_http(
    server: CodexMcpServer,
    *,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    bearer = server.runtime_env.get(server.bearer_token_env_var, "")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    initialize, response_headers = _http_request(
        server.url,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "genbi-admin", "version": "1"},
            },
        },
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    if "error" in initialize:
        raise RuntimeError("MCP server returned an initialize error.")
    session_id = response_headers.get("Mcp-Session-Id")
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    tools_response, _ = _http_request(
        server.url,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
        headers=headers,
        timeout_seconds=timeout_seconds,
    )
    if "error" in tools_response:
        raise RuntimeError("MCP server returned a tools/list error.")
    return _tools_from_result(tools_response.get("result"))


def _http_request(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout_seconds: float,
) -> tuple[dict[str, Any], Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            parsed = _parse_http_body(body, response.headers.get_content_type())
            return parsed, response.headers
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"MCP HTTP server returned {error.code}.") from error


def _parse_http_body(body: str, content_type: str) -> dict[str, Any]:
    if content_type == "text/event-stream" or body.lstrip().startswith("event:"):
        for line in body.splitlines():
            if line.startswith("data:"):
                value = json.loads(line[5:].strip())
                if isinstance(value, dict):
                    return value
        raise RuntimeError("MCP HTTP server returned an empty event stream.")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise RuntimeError("MCP HTTP server returned an invalid payload.")
    return value


def _tools_from_result(result: Any) -> list[dict[str, Any]]:
    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
        return []
    return [item for item in result["tools"] if isinstance(item, dict)]


def _safe_error_message(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return str(error)
    if isinstance(error, FileNotFoundError):
        return "MCP command was not found."
    return str(error) or error.__class__.__name__
