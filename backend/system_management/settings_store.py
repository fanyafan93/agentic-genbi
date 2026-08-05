from __future__ import annotations

import logging
from typing import Any

from backend.persistence.postgres_stores import get_postgres_database_url


LOGGER = logging.getLogger(__name__)
MCP_ENABLED_PREFIX = "mcp.enabled."
RUNTIME_POLICY_KEY = "runtime.policy"


def mcp_enabled_overrides() -> dict[str, bool]:
    database_url = get_postgres_database_url()
    if not database_url:
        return {}
    try:
        from psycopg import connect
        from psycopg.rows import dict_row

        with connect(database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT key, value
                FROM "SystemSetting"
                WHERE key LIKE %s
                """,
                (f"{MCP_ENABLED_PREFIX}%",),
            ).fetchall()
    except Exception as error:
        LOGGER.warning("system_setting_fallback error=%s", error)
        return {}
    overrides: dict[str, bool] = {}
    for row in rows:
        name = str(row["key"])[len(MCP_ENABLED_PREFIX) :]
        value: Any = row["value"]
        if isinstance(value, dict) and isinstance(value.get("enabled"), bool):
            overrides[name] = value["enabled"]
    return overrides


def runtime_policy_overrides() -> dict[str, Any]:
    database_url = get_postgres_database_url()
    if not database_url:
        return {}
    try:
        from psycopg import connect
        from psycopg.rows import dict_row

        with connect(database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT value
                FROM "SystemSetting"
                WHERE key = %s
                """,
                (RUNTIME_POLICY_KEY,),
            ).fetchone()
    except Exception as error:
        LOGGER.warning("runtime_policy_fallback error=%s", error)
        return {}
    value: Any = row["value"] if row else None
    if not isinstance(value, dict):
        return {}
    return dict(value)
