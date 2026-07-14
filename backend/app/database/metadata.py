from typing import Any, Protocol

from app.config import Settings
from app.schemas.tools import ListTablesResult, TableColumn, TableInfo, TableSchema


class InspectorLike(Protocol):
    def get_table_names(self, schema: str | None = None) -> list[str]: ...

    def get_table_comment(self, table_name: str, schema: str | None = None) -> dict[str, Any]: ...

    def get_columns(self, table_name: str, schema: str | None = None) -> list[dict[str, Any]]: ...


class MetadataToolError(Exception):
    """A public, stable metadata-tool error that does not reveal hidden objects."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def list_allowlisted_tables(inspector: InspectorLike, settings: Settings) -> ListTablesResult:
    available_tables = set(inspector.get_table_names())
    tables = [
        TableInfo(name=table_name, comment=_table_comment(inspector, table_name))
        for table_name in sorted(settings.allowed_tables)
        if table_name in available_tables
    ]
    return ListTablesResult(tables=tables)


def get_allowlisted_table_schema(
    table_name: str, inspector: InspectorLike, settings: Settings
) -> TableSchema:
    if table_name not in settings.allowed_tables:
        raise MetadataToolError("TABLE_NOT_AVAILABLE", "Requested table is not available.")

    return TableSchema(
        table_name=table_name,
        columns=[
            TableColumn(
                name=str(column["name"]),
                data_type=str(column["type"]),
                nullable=bool(column["nullable"]),
                comment=_optional_comment(column.get("comment")),
            )
            for column in inspector.get_columns(table_name)
        ],
    )


def _table_comment(inspector: InspectorLike, table_name: str) -> str | None:
    return _optional_comment(inspector.get_table_comment(table_name).get("text"))


def _optional_comment(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
