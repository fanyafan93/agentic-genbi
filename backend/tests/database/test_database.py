from importlib import import_module

from app.config import Settings


TEST_DATABASE_URL = "mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics"


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_: object) -> None:
        self.closed = True


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self._connection = connection

    def connect(self) -> FakeConnection:
        return self._connection


def test_connection_context_closes_connection(monkeypatch) -> None:
    database = import_module("app.database")
    connection = FakeConnection()
    monkeypatch.setattr(
        database,
        "create_engine_for_settings",
        lambda _: FakeEngine(connection),
    )

    settings = Settings(app_env="test", database_url=TEST_DATABASE_URL)
    with database.connection_for_settings(settings) as opened:
        assert opened is connection

    assert connection.closed is True
