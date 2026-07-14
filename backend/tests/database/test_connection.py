import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.database import connection_for_settings


INTEGRATION_DATABASE_URL = os.getenv(
    "INTEGRATION_DATABASE_URL",
    "mysql+pymysql://readonly_user:readonly-password@127.0.0.1:3307/analytics",
)


def integration_settings() -> Settings:
    return Settings(app_env="test", database_url=INTEGRATION_DATABASE_URL)


@pytest.mark.integration
def test_readonly_user_can_read_but_cannot_insert_or_drop() -> None:
    with connection_for_settings(integration_settings()) as connection:
        row_count = connection.execute(
            text("SELECT COUNT(*) FROM sales_channel_monthly")
        ).scalar_one()

        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO sales_channel_monthly "
                    "(month_start, channel, sales_amount) "
                    "VALUES ('2026-04-01', 'test', 1.00)"
                )
            )
        connection.rollback()

        with pytest.raises(DBAPIError):
            connection.execute(text("DROP TABLE sales_channel_monthly"))

    assert row_count == 6
