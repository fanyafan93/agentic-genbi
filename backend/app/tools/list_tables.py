from sqlalchemy import inspect

from app.config import Settings
from app.database import connection_for_settings
from app.database.metadata import list_allowlisted_tables
from app.schemas.tools import ListTablesResult


def list_tables(settings: Settings) -> ListTablesResult:
    """Return only configured table metadata; callers cannot supply database objects."""

    with connection_for_settings(settings) as connection:
        return list_allowlisted_tables(inspect(connection), settings)
