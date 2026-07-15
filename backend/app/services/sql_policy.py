from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError


class SqlPolicyViolation(Exception):
    """Raised when candidate SQL violates the server-owned read-only policy."""


@dataclass(frozen=True)
class NormalizedSql:
    sql: str
    limit: int


class SqlPolicy:
    """Parse and constrain one MySQL read-only query before database execution."""

    def __init__(self, allowed_tables: tuple[str, ...], max_rows: int) -> None:
        self._allowed_tables = frozenset(allowed_tables)
        self._max_rows = max_rows

    def validate(self, candidate_sql: str) -> NormalizedSql:
        if not candidate_sql.strip():
            raise SqlPolicyViolation("SQL must not be blank.")

        try:
            statements = parse(candidate_sql, read="mysql")
        except ParseError as error:
            raise SqlPolicyViolation("SQL could not be parsed as MySQL.") from error

        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            raise SqlPolicyViolation("Only one read-only SELECT query is allowed.")

        statement = statements[0]
        self._reject_unsafe_nodes(statement)
        self._validate_tables(statement)
        # Fetch one extra row so the executor can report truncation accurately.
        normalized = statement.limit(self._max_rows + 1).sql(dialect="mysql")
        return NormalizedSql(sql=normalized, limit=self._max_rows)

    def referenced_tables(self, candidate_sql: str) -> frozenset[str]:
        """Return physical tables from one parseable query, excluding CTE aliases."""

        try:
            statements = parse(candidate_sql, read="mysql")
        except ParseError:
            return frozenset()
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            return frozenset()
        statement = statements[0]
        cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
        return frozenset(
            self._table_identifier(table)
            for table in statement.find_all(exp.Table)
            if table.name not in cte_names
        )

    def _reject_unsafe_nodes(self, statement: exp.Expression) -> None:
        forbidden_nodes = (
            exp.Into,
            exp.Lock,
            exp.SessionParameter,
        )
        if any(statement.find(node_type) is not None for node_type in forbidden_nodes):
            raise SqlPolicyViolation("The query uses a forbidden read-only escape hatch.")
        forbidden_functions = {"BENCHMARK", "LOAD_FILE", "SLEEP"}
        if any(
            function.name.upper() in forbidden_functions
            for function in statement.find_all(exp.Anonymous)
        ):
            raise SqlPolicyViolation("The query uses a forbidden file-access function.")

    def _validate_tables(self, statement: exp.Expression) -> None:
        cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
        for table in statement.find_all(exp.Table):
            if table.name in cte_names:
                continue
            if table.catalog or not self._is_allowed(table):
                raise SqlPolicyViolation("The query references a table outside the allowlist.")

    def _is_allowed(self, table: exp.Table) -> bool:
        identifier = self._table_identifier(table)
        if identifier in self._allowed_tables:
            return True
        return bool(table.db and f"{table.db}.*" in self._allowed_tables)

    @staticmethod
    def _table_identifier(table: exp.Table) -> str:
        return f"{table.db}.{table.name}" if table.db else table.name
