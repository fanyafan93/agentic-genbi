from app.config import Settings


class FakeInspector:
    def get_table_names(self, schema: str | None = None) -> list[str]:
        assert schema is None
        return ["hidden_table", "sales_channel_monthly", "another_allowed"]

    def get_table_comment(self, table_name: str, schema: str | None = None) -> dict[str, str]:
        assert schema is None
        return {
            "sales_channel_monthly": {"text": "Monthly channel sales"},
            "another_allowed": {"text": "Another allowed table"},
        }[table_name]


def test_list_tables_returns_only_allowlisted_tables_in_stable_order() -> None:
    from app.database.metadata import list_allowlisted_tables

    settings = Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
        allowed_tables=("sales_channel_monthly", "another_allowed"),
    )

    result = list_allowlisted_tables(FakeInspector(), settings)

    assert result.model_dump(mode="json") == {
        "tables": [
            {"name": "another_allowed", "comment": "Another allowed table"},
            {"name": "sales_channel_monthly", "comment": "Monthly channel sales"},
        ]
    }
