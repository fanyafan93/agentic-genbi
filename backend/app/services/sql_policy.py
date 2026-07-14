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
        normalized = statement.limit(self._max_rows).sql(dialect="mysql")
        return NormalizedSql(sql=normalized, limit=self._max_rows)

    def _reject_unsafe_nodes(self, statement: exp.Expression) -> None:
        forbidden_nodes = (
            exp.Into,
            exp.Lock,
        )
        if any(statement.find(node_type) is not None for node_type in forbidden_nodes):
            raise SqlPolicyViolation("The query uses a forbidden read-only escape hatch.")

    def _validate_tables(self, statement: exp.Expression) -> None:
        cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}
        for table in statement.find_all(exp.Table):
            if table.name in cte_names:
                continue
            if table.db or table.catalog or table.name not in self._allowed_tables:
                raise SqlPolicyViolation("The query references a table outside the allowlist.")
