from __future__ import annotations

from typing import Any

__all__ = ["check_runtime_env", "load_project_env"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import env

        return getattr(env, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
