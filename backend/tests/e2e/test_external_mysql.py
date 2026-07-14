"""Opt-in acceptance checks for a customer-provided read-only MySQL database."""

import os

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.database import connection_for_settings
from app.database.metadata import list_allowlisted_tables
from app.services.sql_executor import SqlExecutor


@pytest.mark.integration
def test_external_mysql_supports_allowlisted_cross_schema_reads_and_denies_writes() -> None:
    if os.getenv("RUN_EXTERNAL_MYSQL_CHECK") != "true":
        pytest.skip("Set RUN_EXTERNAL_MYSQL_CHECK=true with external MySQL settings to run this check.")

    settings = Settings(app_env="test", _env_file=None)
    with connection_for_settings(settings) as connection:
        tables = list_allowlisted_tables(inspect(connection), settings).tables
    assert tables, "No configured allowlisted tables were visible to the read-only account."

    selected_table = tables[0].name
    read_result = SqlExecutor(settings).execute(f"SELECT 1 AS readable FROM {selected_table}")
    assert read_result.success is True

    with connection_for_settings(settings) as connection:
        with pytest.raises(DBAPIError):
            # The predicate is always false, so a misconfigured write grant cannot modify a row.
            connection.execute(text(f"DELETE FROM {selected_table} WHERE 1 = 0"))
