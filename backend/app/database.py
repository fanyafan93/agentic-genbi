from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine

from app.config import Settings


def create_engine_for_settings(settings: Settings) -> Engine:
    """Create the server-side MySQL engine from the validated secret URL."""

    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_recycle=1800,
    )


@contextmanager
def connection_for_settings(settings: Settings) -> Iterator[Connection]:
    """Yield one connection and always return it to the pool afterwards."""

    with create_engine_for_settings(settings).connect() as connection:
        yield connection
