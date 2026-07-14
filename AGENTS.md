# Agentic GenBI MVP collaboration guide

## Project goal

Build the smallest useful web-based data analysis agent. A user submits a natural-language question, the backend inspects one allowed MySQL database, generates and safely executes read-only SQL, retries repairable SQL failures at most twice, and returns a structured report for table, chart, SQL, status, and narrative display.

The current phase is architecture and project documentation. Do not represent planned capabilities as implemented.

## MVP scope

The only required vertical flow is:

`Next.js UI -> FastAPI -> OpenAI Agents SDK -> metadata/query tools -> SQL safety layer -> read-only MySQL -> validated report JSON -> UI`

The MVP uses one test or desensitized MySQL database, one agent, in-process task state, and frontend polling. It does not provide production durability, multi-user isolation, or background job infrastructure.

## Technology stack

- Frontend: Next.js, React, TypeScript, Ant Design, ECharts, Vitest.
- Backend: Python, FastAPI, OpenAI Agents SDK, SQLAlchemy, Pydantic, pytest.
- Database: one MySQL test/desensitized database accessed through a read-only account.
- Local deployment: Docker Compose.

Versions remain **待验证假设** until the project skeleton task pins and verifies them. Do not invent version claims in documentation or code.

## Read first

Before changing code or architecture, read in order:

1. `docs/product/mvp-scope.md`
2. `docs/architecture/overview.md`
3. `docs/architecture/interfaces.md`
4. `docs/architecture/decisions/ADR-001-agent-runtime.md`
5. `docs/architecture/decisions/ADR-002-mvp-boundaries.md`
6. `docs/plans/current.md`
7. `docs/handoffs/latest.md`

## Architecture boundaries

- The browser calls FastAPI only. It never receives database credentials or connects to MySQL.
- FastAPI owns API validation, task lifecycle, orchestration budgets, report validation, and error mapping.
- OpenAI Agents SDK owns model interaction and tool selection. It does not own security policy, retry limits, or database authorization.
- Agent tools expose narrow typed operations: `list_tables`, `get_table_schema`, and `execute_sql`.
- `build_report` is not an Agent tool in the MVP. The Agent returns an `AnalysisReport` as structured output, which Pydantic validates.
- The SQL safety layer is a deterministic Python boundary called by `execute_sql` before SQLAlchemy. It must not rely on prompting.
- SQLAlchemy owns connection pooling and execution, not business analysis or Agent control flow.
- MySQL is the final authorization boundary and must use a read-only account restricted to allowed schemas/tables.
- Frontend chart rendering consumes the backend `ChartSpec`; it must not execute arbitrary JavaScript received from the model.

## SQL safety rules

Enforce all rules in Python and database permissions:

- Accept exactly one statement whose root is `SELECT` or a read-only `WITH ... SELECT`.
- Reject comments or syntax tricks that make statement count or intent ambiguous.
- Reject data-changing, DDL, administrative, file, locking, stored-program, and multi-statement operations, including `INSERT`, `UPDATE`, `DELETE`, `REPLACE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `GRANT`, `CALL`, `LOAD`, `INTO OUTFILE`, and `FOR UPDATE`.
- Parse SQL with a MySQL-aware parser; keyword matching alone is insufficient.
- Permit only configured schemas and tables. Metadata tools apply the same allowlist.
- Apply a server-controlled maximum row count even when the model supplies `LIMIT`.
- Apply a database/query timeout.
- Use a database account with no write or DDL privileges.
- Return normal SQL failures as `SqlError`; do not leak credentials, connection strings, or internal stack traces.
- Allow at most two repair retries after the first SQL attempt.
- Bound total Agent tool calls and record each attempt, SQL text, sanitized database error, timing, and final outcome.

Exact row, timeout, and tool-call limits are configuration values to be confirmed in the skeleton task. Tests must cover their enforcement.

## Testing requirements

- Follow red-green-refactor for behavior changes.
- Backend: pytest unit tests for models, SQL policy, tools, retry budget, and API contracts; integration tests use a disposable test database.
- Frontend: Vitest component/contract tests; browser-level coverage for the fixed report and final end-to-end flow.
- Maintain at least five deterministic analysis questions with expected structural outcomes.
- Never run automated tests against production data. Use test or desensitized fixtures only.
- A task is not complete until its targeted tests pass and relevant broader tests have been run.

## Git workflow

- Inspect `git status` before editing and preserve unrelated user changes.
- Keep each task independently reviewable and commit only files in scope.
- Use concise Conventional Commit messages where practical; recommended messages are listed in `docs/plans/current.md`.
- Do not rewrite history, force-push, amend, or reset user work unless explicitly requested.
- Update `docs/handoffs/latest.md` before ending every development session, including test evidence and remaining work.

## Technologies prohibited without a new decision record

Do not add WrenAI, LangGraph, multiple agents, Redis, Celery, Kubernetes, MinIO, a vector database, multi-database support, multi-tenancy, a full auth system, arbitrary code execution, PDF export, dashboard editing, or scheduled jobs. Do not add a generic repository/framework abstraction for hypothetical future databases.

## Definition of done

A task is complete only when:

- Its acceptance criteria and interface contract are satisfied.
- Security controls are implemented outside prompts and have tests.
- Targeted tests and relevant regression tests pass with recorded commands.
- User-facing and architecture documents match actual behavior.
- No secrets, production data, generated artifacts, or unrelated changes are committed.
- `docs/plans/current.md` status and `docs/handoffs/latest.md` are updated.
