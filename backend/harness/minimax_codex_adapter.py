from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable


DEFAULT_PROXY_BASE_URL = "http://127.0.0.1:8000/api/codex-minimax/v1"


@dataclass(frozen=True)
class NamespaceToolMap:
    namespace: str
    tool_names: frozenset[str]


def adapter_enabled(environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    value = env.get("GENBI_CODEX_MINIMAX_ADAPTER_ENABLED", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def adapter_base_url(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    return env.get("GENBI_CODEX_MINIMAX_ADAPTER_BASE_URL", DEFAULT_PROXY_BASE_URL).strip() or DEFAULT_PROXY_BASE_URL


def minimax_upstream_base_url(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    return (
        env.get("GENBI_MINIMAX_UPSTREAM_BASE_URL", "").strip()
        or env.get("MINIMAX_BASE_URL", "").strip()
        or env.get("GENBI_LLM_BASE_URL", "").strip()
        or "https://api.minimaxi.com/v1"
    ).rstrip("/")


def minimax_api_key(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    return (
        env.get("GENBI_MINIMAX_UPSTREAM_API_KEY", "").strip()
        or env.get("MINIMAX_API_KEY", "").strip()
        or env.get("GENBI_LLM_API_KEY", "").strip()
    )


def rewrite_request_body(body: dict[str, Any]) -> tuple[dict[str, Any], list[NamespaceToolMap]]:
    rewritten = dict(body)
    rewritten["model"] = _rewrite_model_name(rewritten.get("model"))
    tools = body.get("tools")
    if not isinstance(tools, list):
        return rewritten, []
    out_tools: list[Any] = []
    namespace_maps: list[NamespaceToolMap] = []
    for tool in tools:
        if not _is_namespace_tool(tool):
            out_tools.append(tool)
            continue
        namespace = str(tool.get("name") or "")
        inner_tools = tool.get("tools")
        if not namespace or not isinstance(inner_tools, list):
            out_tools.append(tool)
            continue
        tool_names: set[str] = set()
        for inner in inner_tools:
            if not isinstance(inner, dict):
                continue
            inner_name = str(inner.get("name") or "")
            if not inner_name:
                continue
            tool_names.add(inner_name)
            flattened = dict(inner)
            flattened["type"] = "function"
            flattened["name"] = _join_namespace_tool_name(namespace, inner_name)
            if "description" not in flattened and tool.get("description"):
                flattened["description"] = str(tool["description"])
            out_tools.append(flattened)
        if tool_names:
            namespace_maps.append(NamespaceToolMap(namespace=namespace, tool_names=frozenset(tool_names)))
    rewritten["tools"] = out_tools
    return rewritten, namespace_maps


def _rewrite_model_name(model: Any, environ: dict[str, str] | None = None) -> Any:
    if model != "codex-auto-review":
        return model
    env = environ if environ is not None else os.environ
    return (
        env.get("GENBI_CODEX_AUTO_REVIEW_MODEL", "").strip()
        or env.get("GENBI_ANALYSIS_MODEL", "").strip()
        or env.get("MINIMAX_MODEL", "").strip()
        or "MiniMax-M3"
    )


def rewrite_response_event(event: dict[str, Any], namespace_maps: Iterable[NamespaceToolMap]) -> dict[str, Any]:
    maps = list(namespace_maps)
    if not maps:
        return event
    rewritten = json.loads(json.dumps(event, ensure_ascii=False))
    _rewrite_function_calls_in_place(rewritten, maps)
    return rewritten


def rewrite_sse_chunk_text(text: str, namespace_maps: Iterable[NamespaceToolMap]) -> str:
    blocks = text.split("\n\n")
    if len(blocks) == 1:
        return text
    rewritten_blocks: list[str] = []
    for block in blocks:
        if not block:
            rewritten_blocks.append(block)
            continue
        rewritten_blocks.append(_rewrite_sse_block(block, namespace_maps))
    return "\n\n".join(rewritten_blocks)


def proxy_minimax_response(raw_body: bytes, *, stream: bool) -> tuple[int, dict[str, str], bytes | Iterable[bytes]]:
    body = json.loads(raw_body.decode("utf-8") or "{}")
    rewritten_body, namespace_maps = rewrite_request_body(body)
    upstream_url = minimax_upstream_base_url() + "/responses"
    api_key = minimax_api_key()
    if not api_key:
        return 401, {"content-type": "application/json"}, json.dumps({"error": "minimax_api_key_missing"}).encode("utf-8")
    payload = json.dumps(rewritten_body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        upstream_url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
        },
    )
    try:
        response = urllib.request.urlopen(req, timeout=float(os.getenv("GENBI_MINIMAX_ADAPTER_TIMEOUT_SECONDS", "180")))
    except urllib.error.HTTPError as exc:
        return exc.code, {"content-type": exc.headers.get("content-type", "application/json")}, exc.read()
    headers = {"content-type": response.headers.get("content-type", "text/event-stream" if stream else "application/json")}
    if stream:
        return response.status, headers, _iter_rewritten_sse(response, namespace_maps)
    data = response.read()
    try:
        event = json.loads(data.decode("utf-8"))
        data = json.dumps(rewrite_response_event(event, namespace_maps), ensure_ascii=False).encode("utf-8")
    except Exception:
        pass
    return response.status, headers, data


def _is_namespace_tool(tool: Any) -> bool:
    return isinstance(tool, dict) and tool.get("type") == "namespace"


def _join_namespace_tool_name(namespace: str, tool_name: str) -> str:
    return namespace + tool_name if namespace.endswith("__") else namespace + "__" + tool_name


def _rewrite_function_calls_in_place(value: Any, namespace_maps: list[NamespaceToolMap]) -> None:
    if isinstance(value, dict):
        if value.get("type") == "function_call":
            name = str(value.get("name") or "")
            match = _match_flattened_name(name, namespace_maps)
            if match:
                namespace, tool_name = match
                value["namespace"] = namespace
                value["name"] = tool_name
        for child in value.values():
            _rewrite_function_calls_in_place(child, namespace_maps)
    elif isinstance(value, list):
        for child in value:
            _rewrite_function_calls_in_place(child, namespace_maps)


def _match_flattened_name(name: str, namespace_maps: list[NamespaceToolMap]) -> tuple[str, str] | None:
    normalized = _normalize_tool_name(name)
    for item in namespace_maps:
        prefix = item.namespace if item.namespace.endswith("__") else item.namespace + "__"
        if not normalized.startswith(prefix):
            continue
        tool_name = normalized[len(prefix) :]
        if tool_name in item.tool_names:
            return item.namespace, tool_name
    bare_matches = [
        (item.namespace, tool_name)
        for item in namespace_maps
        for tool_name in item.tool_names
        if normalized == _normalize_tool_name(tool_name)
    ]
    if len(bare_matches) == 1:
        return bare_matches[0]
    return None


def _normalize_tool_name(name: str) -> str:
    normalized = name.strip()
    for sep in (":", ".", "/", "-"):
        normalized = normalized.replace(sep, "__")
    return normalized


def _rewrite_sse_block(block: str, namespace_maps: Iterable[NamespaceToolMap]) -> str:
    lines = block.splitlines()
    out: list[str] = []
    for line in lines:
        if not line.startswith("data:"):
            out.append(line)
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            out.append(line)
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            out.append(line)
            continue
        payload = rewrite_response_event(payload, namespace_maps)
        out.append("data: " + json.dumps(payload, ensure_ascii=False))
    return "\n".join(out)


def _iter_rewritten_sse(response: Any, namespace_maps: list[NamespaceToolMap]) -> Iterable[bytes]:
    buffer = ""
    try:
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                yield (_rewrite_sse_block(block, namespace_maps) + "\n\n").encode("utf-8")
        if buffer:
            yield _rewrite_sse_block(buffer, namespace_maps).encode("utf-8")
    except TimeoutError:
        yield _sse_error_event("minimax_stream_timeout", "MiniMax response stream timed out.")
    except OSError as exc:
        yield _sse_error_event("minimax_stream_error", str(exc) or "MiniMax response stream failed.")
    finally:
        try:
            response.close()
        except Exception:
            pass


def _sse_error_event(code: str, message: str) -> bytes:
    payload = {
        "type": "response.failed",
        "error": {
            "code": code,
            "message": message,
        },
    }
    return ("event: response.failed\n" + "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")
