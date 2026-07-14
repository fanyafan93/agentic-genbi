import pytest

from app.config import Settings


class FakeInspector:
    def __init__(self) -> None:
        self.inspected_names: list[str] = []

    def get_columns(self, table_name: str, schema: str | None = None) -> list[dict[str, object]]:
        assert schema is None
        self.inspected_names.append(table_name)
        return [
            {"name": "month_start", "type": "DATE", "nullable": False, "comment": "Month start"},
            {"name": "sales_amount", "type": "DECIMAL(12, 2)", "nullable": False, "comment": None},
        ]


def test_get_table_schema_returns_json_serializable_column_metadata() -> None:
    from app.database.metadata import get_allowlisted_table_schema

    settings = Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
        allowed_tables=("sales_channel_monthly",),
    )

    result = get_allowlisted_table_schema("sales_channel_monthly", FakeInspector(), settings)

    assert result.model_dump(mode="json") == {
        "table_name": "sales_channel_monthly",
        "columns": [
            {"name": "month_start", "data_type": "DATE", "nullable": False, "comment": "Month start"},
            {"name": "sales_amount", "data_type": "DECIMAL(12, 2)", "nullable": False, "comment": None},
        ],
    }


def test_get_table_schema_does_not_probe_a_table_outside_the_allowlist() -> None:
    from app.database.metadata import MetadataToolError, get_allowlisted_table_schema

    inspector = FakeInspector()
    settings = Settings(
        app_env="test",
        database_url="mysql+pymysql://readonly_user:readonly-password@localhost:3306/analytics",
        allowed_tables=("sales_channel_monthly",),
    )

    with pytest.raises(MetadataToolError) as error:
        get_allowlisted_table_schema("hidden_table", inspector, settings)

    assert error.value.code == "TABLE_NOT_AVAILABLE"
    assert str(error.value) == "Requested table is not available."
    assert inspector.inspected_names == []
