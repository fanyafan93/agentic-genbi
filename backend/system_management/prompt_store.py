from __future__ import annotations

import logging

from backend.persistence.postgres_stores import get_postgres_database_url


LOGGER = logging.getLogger(__name__)
ANALYSIS_SYSTEM_PROMPT_KEY = "analysis_system"
BASE_INSTRUCTIONS_SETTING_KEY = "context.base_instructions"
SYSTEM_PROMPT_SETTING_KEY = "context.system_prompt"


def managed_base_instructions() -> str | None:
    return _managed_instruction(BASE_INSTRUCTIONS_SETTING_KEY)


def published_system_prompt(fallback: str) -> str:
    managed = _managed_instruction(SYSTEM_PROMPT_SETTING_KEY)
    if managed:
        return managed
    database_url = get_postgres_database_url()
    if not database_url:
        return fallback
    try:
        from psycopg import connect
        from psycopg.rows import dict_row

        with connect(database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT content
                FROM "SystemPromptVersion"
                WHERE "promptKey" = %s AND status = 'published'
                ORDER BY version DESC
                LIMIT 1
                """,
                (ANALYSIS_SYSTEM_PROMPT_KEY,),
            ).fetchone()
    except Exception as error:
        LOGGER.warning("system_prompt_fallback error=%s", error)
        return fallback
    content = str(row["content"]).strip() if row else ""
    return content or fallback


def _managed_instruction(key: str) -> str | None:
    database_url = get_postgres_database_url()
    if not database_url:
        return None
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
                (key,),
            ).fetchone()
    except Exception as error:
        LOGGER.warning("managed_context_fallback key=%s error=%s", key, error)
        return None
    value = row["value"] if row else None
    if not isinstance(value, dict):
        return None
    content = value.get("content")
    return str(content).strip() if isinstance(content, str) and content.strip() else None
