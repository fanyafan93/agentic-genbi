from __future__ import annotations

import logging
import json
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


def set_mcp_enabled_override(
    name: str,
    enabled: bool,
    *,
    actor_id: str,
) -> None:
    database_url = get_postgres_database_url()
    if not database_url:
        return
    from psycopg import connect

    with connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO "SystemSetting" (key, value, "updatedById", "updatedAt")
            VALUES (%s, %s::jsonb, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (key)
            DO UPDATE SET
                value = EXCLUDED.value,
                "updatedById" = EXCLUDED."updatedById",
                "updatedAt" = CURRENT_TIMESTAMP
            """,
            (
                f"{MCP_ENABLED_PREFIX}{name}",
                json.dumps({"enabled": enabled}),
                actor_id,
            ),
        )
