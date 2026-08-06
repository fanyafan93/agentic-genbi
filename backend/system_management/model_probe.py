from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from backend.system_management.model_connections import ModelRuntimeConnection


def probe_model_connection(
    connection: ModelRuntimeConnection,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    timeout_seconds: float = 15,
) -> dict[str, Any]:
    started = time.monotonic()
    request = urllib.request.Request(
        connection.base_url.rstrip("/") + "/responses",
        data=json.dumps(
            {
                "model": connection.model,
                "input": "Reply with OK.",
                "max_output_tokens": 8,
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {connection.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        response = opener(request, timeout=timeout_seconds)
        try:
            raw = response.read(262_145)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        if len(raw) > 262_144:
            return _result(
                False,
                "failed",
                "上游响应过大",
                started,
            )
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _result(
                False,
                "failed",
                "上游未返回有效 JSON",
                started,
            )
        if not isinstance(payload, dict):
            return _result(
                False,
                "failed",
                "上游响应格式不受支持",
                started,
            )
        return _result(
            True,
            "ready",
            "连接成功，Responses API 可用",
            started,
        )
    except urllib.error.HTTPError as error:
        return _result(
            False,
            "failed",
            f"连接失败（HTTP {int(error.code)}）",
            started,
        )
    except TimeoutError:
        return _result(False, "failed", "连接超时", started)
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            return _result(False, "failed", "连接超时", started)
        return _result(False, "failed", "无法连接模型服务", started)
    except Exception:
        return _result(False, "failed", "无法连接模型服务", started)


def _result(
    ok: bool,
    status: str,
    message: str,
    started: float,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "status": status,
        "message": message,
        "latencyMs": max(0, round((time.monotonic() - started) * 1000)),
    }
