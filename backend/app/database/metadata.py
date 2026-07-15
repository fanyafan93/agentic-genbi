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
    tables: dict[str, TableInfo] = {}
    for allowed_table in settings.allowed_tables:
        schema, table_name = _split_table_identifier(allowed_table)
        available_tables = set(inspector.get_table_names(schema=schema))
        if table_name == "*" and schema is not None:
            for discovered_table in available_tables:
                qualified_name = f"{schema}.{discovered_table}"
                tables[qualified_name] = TableInfo(
                    name=qualified_name,
                    comment=_table_comment(inspector, discovered_table, schema),
                )
        elif table_name in available_tables:
            public_name = f"{schema}.{table_name}" if schema else table_name
            tables[public_name] = TableInfo(
                name=public_name,
                comment=_table_comment(inspector, table_name, schema),
            )
    return ListTablesResult(tables=[tables[name] for name in sorted(tables)])


def get_allowlisted_table_schema(
    table_name: str, inspector: InspectorLike, settings: Settings
) -> TableSchema:
    schema, physical_table_name = _split_table_identifier(table_name)
    if not _is_allowlisted(table_name, schema, settings.allowed_tables):
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
            for column in inspector.get_columns(physical_table_name, schema=schema)
        ],
    )


def _is_allowlisted(
    table_name: str, schema: str | None, allowed_tables: tuple[str, ...]
) -> bool:
    return table_name in allowed_tables or bool(schema and f"{schema}.*" in allowed_tables)


def _split_table_identifier(table_name: str) -> tuple[str | None, str]:
    if "." not in table_name:
        return None, table_name
    schema, physical_table_name = table_name.split(".", maxsplit=1)
    return schema, physical_table_name


def _table_comment(inspector: InspectorLike, table_name: str, schema: str | None) -> str | None:
    return _optional_comment(inspector.get_table_comment(table_name, schema=schema).get("text"))


def _optional_comment(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
