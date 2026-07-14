from sqlalchemy import inspect

from app.config import Settings
from app.database import connection_for_settings
from app.database.metadata import get_allowlisted_table_schema
from app.schemas.tools import TableSchema


def get_table_schema(table_name: str, settings: Settings) -> TableSchema:
    """Return one configured table schema without probing unavailable table names."""

    with connection_for_settings(settings) as connection:
        return get_allowlisted_table_schema(table_name, inspect(connection), settings)
