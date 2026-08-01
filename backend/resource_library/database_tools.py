from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import unquote, urlparse

import sqlglot
from sqlglot import exp

from backend.config import load_project_env


DEFAULT_MAX_ROWS = 1000
DEFAULT_TIMEOUT_SECONDS = 30
_NAMED_PARAMETER_RE = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")
FORBIDDEN_EXPRESSIONS = (
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Merge,
    exp.TruncateTable,
    exp.Update,
)


class CursorLike(Protocol):
    description: Any

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> Any: ...

    def fetchall(self) -> list[Any]: ...

    def close(self) -> Any: ...


class ConnectionLike(Protocol):
    def cursor(self) -> CursorLike: ...

    def close(self) -> Any: ...


@dataclass(frozen=True)
class DatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    database: str | None = None
    enabled: bool = True
    max_rows: int = DEFAULT_MAX_ROWS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    allow_select_star: bool = False

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        load_project_env()
        database_url = _parse_mysql_database_url(os.getenv("DATABASE_URL", ""))
        return cls(
            host=os.getenv("GENBI_DB_HOST") or database_url.get("host") or "127.0.0.1",
            port=int(os.getenv("GENBI_DB_PORT") or database_url.get("port") or "3306"),
            user=os.getenv("GENBI_DB_USER") or database_url.get("user", ""),
            password=os.getenv("GENBI_DB_PASSWORD") or database_url.get("password", ""),
            database=os.getenv("GENBI_DB_DATABASE") or database_url.get("database") or None,
            enabled=os.getenv("GENBI_BUSINESS_QUERY_ENABLED", "true").lower() == "true",
            max_rows=int(os.getenv("GENBI_DB_MAX_ROWS", str(DEFAULT_MAX_ROWS))),
            timeout_seconds=int(os.getenv("GENBI_DB_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
            allow_select_star=os.getenv("GENBI_DB_ALLOW_SELECT_STAR", "false").lower() == "true",
        )


@dataclass(frozen=True)
class QueryValidation:
    ok: bool
    normalized_sql: str | None
    reasons: list[str]


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    elapsed_ms: int
    truncated: bool


@dataclass(frozen=True)
class TableProfile:
    table_schema: str
    table_name: str
    table_type: str | None
    table_comment: str | None
    approximate_rows: int | None
    data_length_bytes: int | None
    index_length_bytes: int | None
    total_length_bytes: int | None
    create_time: str | None
    update_time: str | None
    partition_count: int
    time_column_candidates: list[str]


class ReadonlyDatabaseTools:
    def __init__(self, config: DatabaseConfig, *, connection: ConnectionLike | None = None) -> None:
        self.config = config
        self._connection = connection

    def search_db_tables(self, keyword: str, *, schema: str | None = None, limit: int = 50) -> QueryResult:
        sql = """
            select table_schema, table_name, table_type, table_comment
            from information_schema.tables
            where (%s is null or table_schema = %s)
              and (table_name like %s or table_comment like %s)
            order by table_schema, table_name
            limit %s
        """
        like = f"%{keyword}%"
        return self._fetch(sql, (schema, schema, like, like, limit), max_rows=limit)

    def get_table_schema(self, schema: str, table: str) -> QueryResult:
        sql = """
            select ordinal_position, column_name, data_type, is_nullable, column_key, column_comment
            from information_schema.columns
            where table_schema = %s and table_name = %s
            order by ordinal_position
        """
        return self._fetch(sql, (schema, table), max_rows=500)

    def inspect_table_profile(self, schema: str, table: str) -> TableProfile:
        table_sql = """
            select table_schema, table_name, table_type, table_comment, table_rows,
                   data_length, index_length, create_time, update_time
            from information_schema.tables
            where table_schema = %s and table_name = %s
            limit 1
        """
        table_result = self._fetch(table_sql, (schema, table), max_rows=1)
        if not table_result.rows:
            raise ValueError(f"table_not_found: {schema}.{table}")
        row = table_result.rows[0]

        partition_sql = """
            select count(*) as partition_count
            from information_schema.partitions
            where table_schema = %s and table_name = %s and partition_name is not null
        """
        partition_result = self._fetch(partition_sql, (schema, table), max_rows=1)
        partition_count = int(partition_result.rows[0].get("partition_count") or 0) if partition_result.rows else 0

        columns = self.get_table_schema(schema, table)
        time_candidates = [
            str(item.get("COLUMN_NAME") or item.get("column_name"))
            for item in columns.rows
            if _looks_like_time_column(
                str(item.get("COLUMN_NAME") or item.get("column_name") or ""),
                str(item.get("DATA_TYPE") or item.get("data_type") or ""),
                str(item.get("COLUMN_COMMENT") or item.get("column_comment") or ""),
            )
        ][:20]

        data_length = _optional_int(row.get("DATA_LENGTH") or row.get("data_length"))
        index_length = _optional_int(row.get("INDEX_LENGTH") or row.get("index_length"))
        return TableProfile(
            table_schema=str(row.get("TABLE_SCHEMA") or row.get("table_schema") or schema),
            table_name=str(row.get("TABLE_NAME") or row.get("table_name") or table),
            table_type=_optional_str(row.get("TABLE_TYPE") or row.get("table_type")),
            table_comment=_optional_str(row.get("TABLE_COMMENT") or row.get("table_comment")),
            approximate_rows=_optional_int(row.get("TABLE_ROWS") or row.get("table_rows")),
            data_length_bytes=data_length,
            index_length_bytes=index_length,
            total_length_bytes=(data_length or 0) + (index_length or 0) if data_length is not None or index_length is not None else None,
            create_time=_optional_str(row.get("CREATE_TIME") or row.get("create_time")),
            update_time=_optional_str(row.get("UPDATE_TIME") or row.get("update_time")),
            partition_count=partition_count,
            time_column_candidates=time_candidates,
        )

    def run_readonly_query(self, sql: str, *, reason: str, max_rows: int | None = None) -> QueryResult:
        if not reason.strip():
            raise ValueError("run_readonly_query requires a reason.")
        validation = validate_readonly_sql(
            sql,
            max_rows=max_rows or self.config.max_rows,
            allow_select_star=self.config.allow_select_star,
        )
        if not validation.ok or not validation.normalized_sql:
            raise ValueError("; ".join(validation.reasons))
        return self._fetch(validation.normalized_sql, None, max_rows=max_rows or self.config.max_rows)

    def run_readonly_template(
        self,
        sql_template: str,
        parameters: Mapping[str, Any],
        *,
        reason: str,
        max_rows: int | None = None,
    ) -> QueryResult:
        """Execute a server-owned SELECT template with driver-bound named values.

        Callers must never receive this as a free-form browser SQL surface. The
        template is AST-validated before `:name` placeholders become DB-API
        `%s` bindings.
        """

        if not reason.strip():
            raise ValueError("run_readonly_template requires a reason.")
        effective_max_rows = max_rows or self.config.max_rows
        validation = validate_readonly_sql(
            sql_template,
            max_rows=effective_max_rows,
            allow_select_star=self.config.allow_select_star,
        )
        if not validation.ok or not validation.normalized_sql:
            raise ValueError("; ".join(validation.reasons))
        bound_sql, values = bind_readonly_sql_template(validation.normalized_sql, parameters)
        return self._fetch(bound_sql, values, max_rows=effective_max_rows)

    def _fetch(self, sql: str, params: tuple[Any, ...] | None, *, max_rows: int) -> QueryResult:
        if not self.config.enabled:
            raise RuntimeError("Business data query is disabled by configuration.")
        start = time.perf_counter()
        connection = self._connection or _connect(self.config)
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            rows_raw = cursor.fetchall()
            columns = _columns_from_cursor(cursor, rows_raw)
            rows = _rows_to_dicts(rows_raw, columns)
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
            return QueryResult(
                columns=columns,
                rows=rows,
                row_count=len(rows),
                elapsed_ms=int((time.perf_counter() - start) * 1000),
                truncated=truncated,
            )
        finally:
            cursor.close()
            if self._connection is None:
                connection.close()


def validate_readonly_sql(sql: str, *, max_rows: int = DEFAULT_MAX_ROWS, allow_select_star: bool = False) -> QueryValidation:
    text = sql.strip().rstrip(";")
    reasons: list[str] = []
    if not text:
        return QueryValidation(False, None, ["sql_empty"])
    if ";" in text:
        return QueryValidation(False, None, ["multiple_statements_forbidden"])

    try:
        expression = sqlglot.parse_one(text, read="mysql")
    except sqlglot.errors.ParseError as exc:
        return QueryValidation(False, None, [f"parse_error: {exc}"])

    if isinstance(expression, FORBIDDEN_EXPRESSIONS) or any(isinstance(node, FORBIDDEN_EXPRESSIONS) for node in expression.walk()):
        reasons.append("write_or_ddl_statement_forbidden")

    if not isinstance(expression, (exp.Select, exp.Union)) and not _is_with_select(expression):
        reasons.append("only_select_or_with_queries_allowed")

    if not allow_select_star and any(isinstance(node, exp.Star) for node in expression.walk()):
        reasons.append("select_star_forbidden")

    if reasons:
        return QueryValidation(False, None, reasons)

    normalized_sql = expression.sql(dialect="mysql")
    if not expression.args.get("limit"):
        normalized_sql = f"{normalized_sql} LIMIT {max_rows}"
    return QueryValidation(True, normalized_sql, [])


def bind_readonly_sql_template(sql: str, parameters: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
    """Convert validated `:name` placeholders to DB-API bindings without interpolation."""

    names = _NAMED_PARAMETER_RE.findall(sql)
    supplied = set(parameters)
    required = set(names)
    missing = sorted(required - supplied)
    unexpected = sorted(supplied - required)
    if missing:
        raise ValueError(f"sql_template_parameters_missing: {', '.join(missing)}")
    if unexpected:
        raise ValueError(f"sql_template_parameters_unexpected: {', '.join(unexpected)}")
    values = tuple(parameters[name] for name in names)
    return _NAMED_PARAMETER_RE.sub("%s", sql), values


def _is_with_select(expression: exp.Expression) -> bool:
    return bool(expression.args.get("with")) and isinstance(expression, exp.Select)


def _connect(config: DatabaseConfig) -> ConnectionLike:
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("pymysql is required for database tools.") from exc

    if not config.user or not config.password:
        raise RuntimeError("Database credentials are not configured.")

    return pymysql.connect(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        database=config.database,
        charset="utf8mb4",
        read_timeout=config.timeout_seconds,
        write_timeout=config.timeout_seconds,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _columns_from_cursor(cursor: CursorLike, rows_raw: list[Any]) -> list[str]:
    if cursor.description:
        return [column[0] for column in cursor.description]
    if rows_raw and isinstance(rows_raw[0], dict):
        return list(rows_raw[0].keys())
    return []


def _rows_to_dicts(rows_raw: list[Any], columns: list[str]) -> list[dict[str, Any]]:
    if not rows_raw:
        return []
    if isinstance(rows_raw[0], dict):
        return [dict(row) for row in rows_raw]
    return [dict(zip(columns, row)) for row in rows_raw]


def _looks_like_time_column(name: str, data_type: str, comment: str) -> bool:
    text = f"{name} {data_type} {comment}".lower()
    return any(token in text for token in ("date", "time", "day", "month", "year", "日期", "时间", "月份", "年份"))


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_mysql_database_url(value: str) -> dict[str, str]:
    if not value.strip():
        return {}
    parsed = urlparse(value)
    if parsed.scheme not in {"mysql", "mysql+pymysql", "mysql+mysqlconnector"}:
        return {}
    return {
        key: current
        for key, current in {
            "host": parsed.hostname or "",
            "port": str(parsed.port) if parsed.port else "",
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": parsed.path.lstrip("/"),
        }.items()
        if current
    }


def _to_json(value: Any) -> str:
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Readonly database exploration tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate and normalize readonly SQL.")
    validate.add_argument("sql")

    search = subparsers.add_parser("search-tables", help="Search information_schema tables.")
    search.add_argument("keyword")
    search.add_argument("--schema", default=None)
    search.add_argument("--limit", type=int, default=50)

    schema = subparsers.add_parser("table-schema", help="Get one table schema.")
    schema.add_argument("schema")
    schema.add_argument("table")

    profile = subparsers.add_parser("table-profile", help="Inspect approximate row count and size for one table.")
    profile.add_argument("schema")
    profile.add_argument("table")

    query = subparsers.add_parser("query", help="Run a bounded readonly query.")
    query.add_argument("sql")
    query.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_project_env()
    args = build_arg_parser().parse_args(argv)
    config = DatabaseConfig.from_env()
    tools = ReadonlyDatabaseTools(config)
    if args.command == "validate":
        print(_to_json(validate_readonly_sql(args.sql, max_rows=config.max_rows, allow_select_star=config.allow_select_star)))
    elif args.command == "search-tables":
        print(_to_json(tools.search_db_tables(args.keyword, schema=args.schema, limit=args.limit)))
    elif args.command == "table-schema":
        print(_to_json(tools.get_table_schema(args.schema, args.table)))
    elif args.command == "table-profile":
        print(_to_json(tools.inspect_table_profile(args.schema, args.table)))
    elif args.command == "query":
        print(_to_json(tools.run_readonly_query(args.sql, reason=args.reason)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
