from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Protocol
from urllib.parse import unquote, urlsplit

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from backend.reports.models import ReportRecord


PARAMETER_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class UnsafeReportQuery(ValueError):
    pass


class ReportFilterError(ValueError):
    pass


class ReportQueryNotFound(LookupError):
    pass


class ReportQueryExecutionError(RuntimeError):
    pass


class QueryRunner(Protocol):
    def run(
        self,
        data_source: str,
        sql: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        ...


def validate_readonly_sql(sql: str) -> None:
    text = str(sql or "").strip()
    if not text:
        raise UnsafeReportQuery("report query SQL is required")
    try:
        statements = sqlglot.parse(text, read="mysql")
    except ParseError as exc:
        raise UnsafeReportQuery("report query SQL is invalid") from exc
    statements = [statement for statement in statements if statement]
    if len(statements) != 1:
        raise UnsafeReportQuery("report query must contain one statement")
    expression = statements[0]
    if expression.find(exp.Select) is None:
        raise UnsafeReportQuery("report query must be a SELECT")
    forbidden_names = (
        "Insert",
        "Update",
        "Delete",
        "Create",
        "Drop",
        "Alter",
        "Command",
        "Merge",
        "Grant",
        "Revoke",
        "Transaction",
        "Commit",
        "Rollback",
        "Copy",
        "Into",
        "Use",
    )
    forbidden_types = tuple(
        expression_type
        for name in forbidden_names
        if (expression_type := getattr(exp, name, None)) is not None
    )
    if forbidden_types and any(
        isinstance(node, forbidden_types) for node in expression.walk()
    ):
        raise UnsafeReportQuery("report query contains a non-readonly operation")


def query_parameter_names(sql: str) -> set[str]:
    validate_readonly_sql(sql)
    try:
        expression = sqlglot.parse_one(sql, read="mysql")
    except ParseError as exc:
        raise UnsafeReportQuery("report query SQL is invalid") from exc
    return {
        placeholder.name
        for placeholder in expression.find_all(exp.Placeholder)
    }


def bind_query_parameters(
    query: Mapping[str, Any],
    filters: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    sql = str(query.get("sql") or "")
    validate_readonly_sql(sql)
    try:
        expression = sqlglot.parse_one(sql, read="mysql")
    except ParseError as exc:
        raise UnsafeReportQuery("report query SQL is invalid") from exc
    parameters = query.get("parameters", {})
    if not isinstance(parameters, Mapping):
        raise ReportFilterError("query parameters must be an object")
    placeholders = list(expression.find_all(exp.Placeholder))
    placeholder_names = {placeholder.name for placeholder in placeholders}
    parameter_names = {str(name) for name in parameters}
    if placeholder_names != parameter_names:
        missing = sorted(placeholder_names - parameter_names)
        unused = sorted(parameter_names - placeholder_names)
        detail = []
        if missing:
            detail.append("missing bindings: " + ", ".join(missing))
        if unused:
            detail.append("unused bindings: " + ", ".join(unused))
        raise ReportFilterError("; ".join(detail))

    bound: dict[str, Any] = {}
    replacements: dict[str, str] = {}
    for parameter_name, binding in parameters.items():
        name = str(parameter_name)
        if not PARAMETER_NAME.fullmatch(name):
            raise ReportFilterError(f"invalid query parameter name: {name}")
        if not isinstance(binding, Mapping):
            raise ReportFilterError(
                f"parameter binding {name} must be an object"
            )
        filter_id = binding.get("filterId")
        if not isinstance(filter_id, str) or filter_id not in filters:
            raise ReportFilterError(f"filter value is missing: {filter_id}")
        value = filters[filter_id]
        if "valueIndex" in binding:
            index = binding["valueIndex"]
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
                or not isinstance(value, list)
                or index >= len(value)
            ):
                raise ReportFilterError(
                    f"filter value index is invalid: {filter_id}"
                )
            value = value[index]
        value_type = str(binding.get("type") or "")
        if value_type.endswith("[]"):
            if not isinstance(value, list):
                raise ReportFilterError(
                    f"filter value must be an array: {filter_id}"
                )
            scalar_type = value_type[:-2]
            names = []
            for index, item in enumerate(value):
                expanded_name = f"{name}_{index}"
                names.append(expanded_name)
                bound[expanded_name] = _coerce_value(
                    item,
                    scalar_type,
                    filter_id,
                )
            replacements[name] = (
                ", ".join(f"%({item})s" for item in names)
                if names
                else "NULL"
            )
        else:
            bound[name] = _coerce_value(value, value_type, filter_id)
            replacements[name] = f"%({name})s"

    for placeholder in placeholders:
        placeholder.replace(exp.Var(this=replacements[placeholder.name]))
    return expression.sql(dialect="mysql"), bound


class ReportQueryService:
    def __init__(
        self,
        runner: QueryRunner,
        *,
        max_rows: int | None = None,
    ) -> None:
        self._runner = runner
        configured_max = int(
            os.getenv("GENBI_DB_MAX_ROWS", "1000")
        )
        self._max_rows = max_rows if max_rows is not None else configured_max

    def execute(
        self,
        report: ReportRecord,
        query_id: str,
        *,
        filters: Mapping[str, Any],
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        query = report.queries.get(query_id)
        if not isinstance(query, dict):
            raise ReportQueryNotFound(query_id)
        data_source = str(query.get("dataSource") or "").strip()
        sql, params = bind_query_parameters(query, filters)
        try:
            if bool(query.get("pagination", False)):
                count_rows = self._runner.run(
                    data_source,
                    f"SELECT COUNT(*) AS total FROM ({sql}) AS genbi_count",
                    dict(params),
                )
                total = int(count_rows[0].get("total") or 0) if count_rows else 0
                page_params = {
                    **params,
                    "genbi_limit": page_size,
                    "genbi_offset": (page - 1) * page_size,
                }
                rows = self._runner.run(
                    data_source,
                    (
                        f"SELECT * FROM ({sql}) AS genbi_page "
                        "LIMIT %(genbi_limit)s OFFSET %(genbi_offset)s"
                    ),
                    page_params,
                )
                result_page = page
                result_page_size = page_size
            else:
                rows = self._runner.run(
                    data_source,
                    (
                        f"SELECT * FROM ({sql}) AS genbi_query "
                        "LIMIT %(genbi_limit)s"
                    ),
                    {**params, "genbi_limit": self._max_rows},
                )
                total = len(rows)
                result_page = 1
                result_page_size = self._max_rows
        except (
            UnsafeReportQuery,
            ReportFilterError,
            ReportQueryNotFound,
        ):
            raise
        except Exception as exc:
            raise ReportQueryExecutionError("report query failed") from exc
        return {
            "columns": _columns_from_rows(rows),
            "rows": rows,
            "page": result_page,
            "pageSize": result_page_size,
            "total": total,
        }


class MySqlQueryRunner:
    def run(
        self,
        data_source: str,
        sql: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if data_source.strip().lower() not in {"doris", "mysql"}:
            raise ReportQueryExecutionError("unsupported report data source")
        try:
            import pymysql
            import pymysql.cursors
        except ImportError as exc:  # pragma: no cover
            raise ReportQueryExecutionError(
                "PyMySQL is required for Report queries"
            ) from exc
        config = _mysql_config()
        timeout = int(os.getenv("GENBI_DB_TIMEOUT_SECONDS", "30"))
        connection = pymysql.connect(
            **config,
            connect_timeout=timeout,
            read_timeout=timeout,
            write_timeout=timeout,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        finally:
            connection.close()


def _coerce_value(value: Any, value_type: str, filter_id: str) -> Any:
    if value_type in {"string", "text"}:
        if not isinstance(value, str):
            raise ReportFilterError(
                f"filter value must be a string: {filter_id}"
            )
        return value
    if value_type in {"number", "integer"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ReportFilterError(
                f"filter value must be numeric: {filter_id}"
            )
        return int(value) if value_type == "integer" else value
    if value_type == "boolean":
        if not isinstance(value, bool):
            raise ReportFilterError(
                f"filter value must be boolean: {filter_id}"
            )
        return value
    if value_type == "date":
        if not isinstance(value, str):
            raise ReportFilterError(
                f"filter value must be an ISO date: {filter_id}"
            )
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ReportFilterError(
                f"filter value must be an ISO date: {filter_id}"
            ) from exc
        return value
    raise ReportFilterError(
        f"unsupported filter parameter type: {value_type or '<empty>'}"
    )


def _columns_from_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if not rows:
        return []
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    columns = []
    for field in fields:
        sample = next(
            (row.get(field) for row in rows if row.get(field) is not None),
            None,
        )
        columns.append(
            {
                "field": field,
                "label": field,
                "type": _column_type(sample),
            }
        )
    return columns


def _column_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, datetime):
        return "datetime"
    if isinstance(value, date):
        return "date"
    return "string"


def _mysql_config() -> dict[str, Any]:
    parsed = _parse_mysql_url(os.getenv("DATABASE_URL", ""))
    host = os.getenv("GENBI_DB_HOST") or parsed.get("host")
    user = os.getenv("GENBI_DB_USER") or parsed.get("user")
    password = os.getenv("GENBI_DB_PASSWORD")
    if password is None:
        password = parsed.get("password")
    database = os.getenv("GENBI_DB_DATABASE") or parsed.get("database")
    port = os.getenv("GENBI_DB_PORT") or parsed.get("port") or "3306"
    if not host or not user or password is None:
        raise ReportQueryExecutionError(
            "Report data source is not configured"
        )
    return {
        "host": host,
        "port": int(port),
        "user": user,
        "password": password,
        "database": database or None,
        "charset": "utf8mb4",
    }


def _parse_mysql_url(value: str) -> dict[str, str]:
    if not value:
        return {}
    parsed = urlsplit(value)
    if parsed.scheme not in {
        "mysql",
        "mysql+pymysql",
        "mysql+mysqlconnector",
    }:
        return {}
    return {
        "host": parsed.hostname or "",
        "port": str(parsed.port or ""),
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/"),
    }
