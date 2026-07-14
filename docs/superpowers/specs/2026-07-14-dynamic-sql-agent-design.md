# Dynamic SQL Agent Design

## Scope

This increment implements Tasks 7, 9, 10, and 11: safe dynamic MySQL queries,
three approved Agent tools, sanitized SQL errors, and at most two repair retries.
The existing in-process task API and report JSON remain the public contract.

## Boundaries

- SQLGlot parses every candidate as MySQL before it reaches SQLAlchemy.
- Only one `SELECT` statement or a `WITH ... SELECT` statement is allowed.
- Referenced tables must be in `Settings.allowed_tables`; qualification cannot bypass
  the allowlist.
- The server applies the result limit and query timeout. Tool arguments never accept
  either value.
- MySQL's read-only account is a separate, defense-in-depth boundary.
- Agent tools are exactly `list_tables`, `get_table_schema`, and `execute_sql`.
- The agent never authors rows, SQL metadata, duration, or the final attempt count.

## SQL Policy And Execution

`SqlPolicy.validate(sql)` returns normalized SQL or a `SqlPolicyViolation`. The
policy rejects parse errors, multiple statements, non-query AST roots, non-allowlisted
tables, SELECT INTO, locking clauses, file access, administrative statements, and
explicit or hidden attempts to increase `LIMIT` beyond `max_query_rows`.

`SqlExecutor.execute(sql)` invokes the policy, applies a server-owned outer limit,
sets a MySQL session execution timeout, and converts rows to the existing
`SqlExecutionResult`. Expected database exceptions become `SqlToolResult` failures;
the original driver text remains internal.

## Agent Coordination

The coordinator builds one MiniMax-backed Agent with the three function tools. Its
instruction requires table discovery and schema inspection before a query. The SQL
tool returns either a structured query result or a sanitized `SqlError`; it has no
connection, timeout, retry, or row-count parameters.

The coordinator records the latest successful SQL result. Once the Agent finishes,
it validates the narrative and constructs `AnalysisReport` from that server-owned
result. A missing successful query is an invalid Agent result.

## Error And Repair Loop

`SqlErrorCode` distinguishes syntax, unknown table, unknown column, type, permission,
timeout, connection, resource, safety, and generic execution failures. Only syntax,
unknown-table, unknown-column, and type errors are repairable.

The coordinator permits three total SQL executions: one initial attempt and two
repairs. On a repairable failure it refreshes the relevant metadata and tells the
Agent to produce a replacement query. Safety, permission, timeout, connection, and
resource failures stop immediately. Repeated repairable failures finish with
`SQL_RETRY_EXHAUSTED`; genuinely ambiguous requests use `requires_input`.

## Verification

- Unit tests cover parser acceptance, dangerous SQL rejection, comments and strings,
  table allowlisting, and unbypassable limits.
- Executor tests cover normalized rows, timeout setup, and sanitized error mapping.
- Coordinator tests use scripted fake tools/runners to prove discovery, query,
  repair, limits, and terminal behavior without network access.
- Integration tests use the Docker MySQL read-only user to prove safe SELECT and
  rejected write/DDL operations.
- A live MiniMax smoke test is opt-in and uses only the seeded test database.
