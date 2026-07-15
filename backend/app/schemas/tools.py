from pydantic import Field

from app.schemas.analysis import StrictModel


class TableInfo(StrictModel):
    name: str
    comment: str | None = None


class ListTablesResult(StrictModel):
    tables: list[TableInfo] = Field(default_factory=list)


class TableSchemaRequest(StrictModel):
    table_name: str = Field(min_length=1, max_length=128)


class TableColumn(StrictModel):
    name: str
    data_type: str
    nullable: bool
    comment: str | None = None


class TableSchema(StrictModel):
    table_name: str
    columns: list[TableColumn]
