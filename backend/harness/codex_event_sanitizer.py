from __future__ import annotations

import re
from enum import Enum
from typing import Any


REDACTED = "[REDACTED]"
TRUNCATED_SUFFIX = "\n...[truncated]"
MAX_STRING_CHARS = 20_000
MAX_COLLECTION_ITEMS = 200
MAX_DEPTH = 8

_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|token|password|passwd|secret|authorization|cookie|credential)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+")
_HEADER_SECRET = re.compile(r"(?im)^(\s*(?:authorization|cookie)\s*:\s*).+$")
_INLINE_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|token|password|passwd|secret|credential)\s*[:=]\s*[^\s,;]+"
)
_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<credentials>[^/@\s]+)@",
    re.IGNORECASE,
)


def sanitize_codex_value(value: Any, *, _depth: int = 0) -> Any:
    """Return a bounded, JSON-safe Codex payload with credentials removed."""

    if _depth >= MAX_DEPTH:
        return "[max depth reached]"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_COLLECTION_ITEMS:
                output["..."] = "[truncated]"
                break
            output[str(key)] = (
                REDACTED
                if _SENSITIVE_KEY.search(str(key))
                else sanitize_codex_value(item, _depth=_depth + 1)
            )
        return output
    if isinstance(value, (list, tuple)):
        items = list(value[:MAX_COLLECTION_ITEMS])
        output = [sanitize_codex_value(item, _depth=_depth + 1) for item in items]
        if len(value) > MAX_COLLECTION_ITEMS:
            output.append("[truncated]")
        return output
    if isinstance(value, str):
        text = _BEARER.sub(r"\1[REDACTED]", value)
        text = _HEADER_SECRET.sub(r"\1[REDACTED]", text)
        text = _INLINE_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
        text = _URL_CREDENTIALS.sub(r"\g<scheme>[REDACTED]@", text)
        if len(text) > MAX_STRING_CHARS:
            return text[:MAX_STRING_CHARS] + TRUNCATED_SUFFIX
        return text
    if hasattr(value, "model_dump"):
        return sanitize_codex_value(value.model_dump(), _depth=_depth + 1)
    if isinstance(value, Enum):
        return sanitize_codex_value(value.value, _depth=_depth + 1)
    if hasattr(value, "__dict__"):
        return sanitize_codex_value(vars(value), _depth=_depth + 1)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)
