from __future__ import annotations

import logging

from backend.persistence.postgres_stores import get_postgres_database_url


LOGGER = logging.getLogger(__name__)
ANALYSIS_SYSTEM_PROMPT_KEY = "analysis_system"


def published_system_prompt(fallback: str) -> str:
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
