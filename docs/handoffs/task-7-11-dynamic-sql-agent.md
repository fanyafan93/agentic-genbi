# Task 7, 9, 10, and 11 Handoff

## Delivered

- `sqlglot==30.12.0` is the MySQL AST parser for every dynamic query.
- SQL policy allows only a single SELECT or CTE SELECT against `ALLOWED_TABLES`.
  It rejects writes, DDL, multiple statements, locks, file output, and qualified
  database objects, then applies a server-owned LIMIT.
- `SqlExecutor` sets MySQL `MAX_EXECUTION_TIME`, normalizes rows, and returns
  sanitized errors. Browser and Agent inputs cannot set connection, timeout, row,
  or retry parameters.
- `DynamicAnalysisCoordinator` exposes exactly `list_tables`, `get_table_schema`,
  and `execute_sql` to the MiniMax Agent. The final report always uses the last
  successful server-owned SQL result.
- Unknown table/column, syntax, and type errors can prompt a repair. Total SQL
  execution is capped at three attempts: one initial attempt and two repairs.

## Verification

- `uv run --frozen pytest -q`: `62 passed, 1 skipped`.
- `uv run --frozen pytest tests/security/test_read_only_database.py -q -m integration`:
  one real MySQL test passed; dynamic SELECT returned six rows and INSERT was
  rejected before execution.
- A live MiniMax smoke command selected `sales_channel_monthly`, generated a channel
  aggregation SQL query, returned two rows, and produced a valid report in one attempt.

## Remaining Work

- Task 12: expose execution steps and `requires_input` states in the frontend.
- Task 13: add browser-level multi-question end-to-end coverage and runbooks.
