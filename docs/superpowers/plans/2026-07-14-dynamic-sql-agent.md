# Dynamic SQL Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement task-by-task with TDD.

**Goal:** Replace the fixed SQL path with a safe, metadata-guided Agent query flow with bounded SQL repair.

**Architecture:** SQLGlot validates MySQL ASTs before a constrained executor runs them. A single Agent receives only three approved tools; a coordinator owns budgets, retries, SQL results, and report assembly.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, SQLGlot, Pydantic, OpenAI Agents SDK, MySQL 8.4, pytest.

## Global Constraints

- Only the configured MySQL database and read-only account may execute queries.
- Only allowlisted tables and read-only single-statement MySQL SELECT queries are valid.
- SQL result rows, timeout, limit, and retry limits are server-owned.
- At most three total SQL executions occur per task.
- No tool can run arbitrary code or receive connection, timeout, or row-limit parameters.

---

### Task 1: SQL Policy And Constrained Executor

**Files:**
- Create: `backend/app/services/sql_policy.py`
- Create: `backend/app/services/sql_executor.py`
- Create: `backend/tests/security/test_sql_policy.py`
- Create: `backend/tests/services/test_sql_executor.py`
- Modify: `backend/app/config.py`, `backend/app/query.py`, `backend/pyproject.toml`

- [ ] Write failing policy tests for SELECT/CTE acceptance, DML/DDL/multiple-statement rejection, allowlist enforcement, and enforced limits.
- [ ] Add `sqlglot` and implement AST validation plus server-owned `LIMIT` normalization.
- [ ] Write executor tests for normalized rows and safe result limits.
- [ ] Implement SQLAlchemy execution with MySQL timeout and `SqlExecutionResult` conversion.
- [ ] Run Task 1 tests and commit `feat: enforce read-only SQL execution policy`.

### Task 2: Structured SQL Errors And Repair Budget

**Files:**
- Create: `backend/app/database/errors.py`
- Create: `backend/app/services/retry_policy.py`
- Create: `backend/tests/database/test_errors.py`
- Create: `backend/tests/services/test_retry_policy.py`
- Modify: `backend/app/services/sql_executor.py`

- [ ] Write failing mapping tests for syntax, missing table/column, type, permission, timeout, connection, and generic errors.
- [ ] Add sanitized `SqlError` values and classify retryability.
- [ ] Write failing retry tests for exactly three maximum attempts and immediate stop errors.
- [ ] Implement retry policy and run Task 2 tests.
- [ ] Commit `feat: add structured SQL errors and retry budget`.

### Task 3: Approved Tools And Agent Coordinator

**Files:**
- Create: `backend/app/tools/execute_sql.py`
- Create: `backend/app/agents/coordinator.py`
- Create: `backend/tests/tools/test_execute_sql.py`
- Create: `backend/tests/agents/test_coordinator.py`
- Modify: `backend/app/agents/analysis_agent.py`, `backend/app/agents/prompts.py`, `backend/app/services/analysis_service.py`, `backend/app/main.py`

- [ ] Write scripted coordinator tests proving metadata before query, report assembly from server-owned results, and repair after a retryable failure.
- [ ] Wrap the three tools with Agents SDK function tools and reject unsupported arguments.
- [ ] Implement the coordinator's tool budget, final result capture, and repair loop.
- [ ] Replace the fixed analysis service dependency with the coordinator.
- [ ] Run Task 3 tests and commit `feat: orchestrate safe dynamic SQL agent`.

### Task 4: Integration, Documentation, And Runtime Verification

**Files:**
- Modify: `README.md`, `docs/plans/current.md`, `docs/handoffs/latest.md`, `.env.example`, `docker-compose.yml`
- Create: `backend/tests/agents/test_dynamic_live_smoke.py`

- [ ] Add Docker MySQL integration coverage for dynamic SELECT and rejected writes.
- [ ] Update the documented settings and task status.
- [ ] Run all backend tests, Docker Compose validation, integration tests, and opt-in live Agent test.
- [ ] Commit documentation and verification evidence.
