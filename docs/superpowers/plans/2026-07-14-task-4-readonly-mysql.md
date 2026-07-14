# Task 4 Read-Only MySQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a reproducible local MySQL schema and a backend SQLAlchemy connection boundary that uses a database-enforced read-only account.

**Architecture:** Docker Compose runs MySQL 8.4 with bootstrap SQL for deterministic sample data and a `SELECT`-only account. `app.database` owns engine construction and connection cleanup; SQL execution policy remains out of scope.

**Tech Stack:** Python 3.12, FastAPI, Pydantic Settings, SQLAlchemy 2, PyMySQL, pytest, Docker Compose, MySQL 8.4.

## Global Constraints

- Only one local MySQL schema: `analytics`.
- Application access uses `readonly_user` and MySQL grants only `SELECT` on `analytics.*`.
- Do not implement SQL parsing, task report changes, Agent integration, or SQL retry behavior.
- `DATABASE_URL` cannot be exposed in an API response, browser artifact, or configuration-validation error.

---

### Task 1: Database configuration and lifecycle

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/app/config.py`
- Create: `backend/app/database.py`
- Create: `backend/tests/database/test_database.py`

**Interfaces:**
- Consumes: `Settings.database_url: SecretStr`.
- Produces: `create_engine_for_settings(settings: Settings) -> Engine` and `connection_for_settings(settings: Settings) -> Iterator[Connection]`.

- [x] Write a failing test proving `database_url` is required and its value is absent from validation errors.
- [x] Run the configuration and lifecycle failure tests before implementation.
- [x] Add SQLAlchemy and PyMySQL RSA support, then implement an engine factory with `pool_pre_ping=True`, `pool_recycle=1800`, and a context-managed connection.
- [x] Re-run focused and complete backend tests; all pass.

### Task 2: Real MySQL read-only integration

**Files:**
- Create: `mysql/init/001-schema-and-readonly-user.sql`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Create: `backend/tests/database/test_connection.py`

**Interfaces:**
- Consumes: Compose root bootstrap variables.
- Produces: `analytics.sales_channel_monthly` with six deterministic rows and `readonly_user` with `SELECT` only.

- [x] Write a failing `@pytest.mark.integration` test: count six rows, and assert `INSERT` and `DROP TABLE` raise `DBAPIError`.
- [x] Run the test against isolated port `3307`; it failed because the Task 4 test service did not yet exist.
- [x] Add bootstrap SQL and mount it at `/docker-entrypoint-initdb.d`; pass `DATABASE_URL` to backend and make backend wait for MySQL health.
- [x] Start the isolated MySQL container and re-run the integration test; all assertions pass.

### Task 3: Documentation, completion, and verification

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/current.md`
- Modify: `docs/handoffs/latest.md`

- [x] Document `docker compose up -d mysql` and `uv run --frozen pytest tests/database/test_connection.py -v -m integration`.
- [x] Run `docker compose config`, then from `backend` run the complete backend suite and focused real-MySQL integration suite: 11 backend tests and 1 focused integration test pass.
- [x] Review the diff, update Task 4 status and next handoff, then commit `feat: connect read-only MySQL test database`.
