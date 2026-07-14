# Agentic GenBI MVP

A minimal web data analysis Agent that turns a natural-language question into a safely executed read-only MySQL query and a validated report containing status, SQL, table data, chart metadata, and narrative conclusions.

## Current stage

**Architecture and planning only.** This branch currently contains project documentation; the frontend, backend, Docker Compose services, and executable tests have not yet been implemented. Commands below describe the intended local developer contract and become valid as the corresponding tasks in `docs/plans/current.md` are completed.

## Planned MVP capability

1. Submit one analysis question from a Next.js page.
2. Create an in-process analysis task through FastAPI and poll its status.
3. Let one OpenAI Agents SDK Agent inspect allowed MySQL tables and schemas.
4. Validate and execute one read-only SQL statement through a deterministic safety layer.
5. Return SQL failures as structured data and allow at most two automatic repairs.
6. Return a Pydantic-validated report JSON rendered as status, SQL, Ant Design table, ECharts chart, and summary.

See [MVP scope](docs/product/mvp-scope.md), [architecture](docs/architecture/overview.md), and [interfaces](docs/architecture/interfaces.md).

## Planned repository layout

```text
.
|-- AGENTS.md                         # Shared rules for coding agents
|-- CLAUDE.md                         # Imports AGENTS.md
|-- README.md                         # Project entry point and actual status
|-- docker-compose.yml                # Planned local frontend/backend/MySQL stack
|-- docs/
|   |-- product/                      # Product scope and acceptance criteria
|   |-- architecture/                 # Architecture, contracts, and ADRs
|   |-- plans/                        # Ordered, independently testable work
|   |-- handoffs/                     # Latest development-session handoff
|   `-- runbooks/                     # Operational notes added only when needed
|-- backend/
|   |-- app/
|   |   |-- api/                      # FastAPI routes and dependencies
|   |   |-- agents/                   # Agent definition and run coordinator
|   |   |-- tools/                    # Typed Agent tool adapters
|   |   |-- database/                 # SQLAlchemy and metadata/query access
|   |   |-- schemas/                  # Pydantic API/domain contracts
|   |   `-- services/                 # Task, SQL policy, retry, and report services
|   `-- tests/                        # Unit and integration tests
`-- frontend/
    |-- src/
    |   |-- app/                      # Next.js routes and layouts
    |   |-- components/               # Reusable presentation components
    |   |-- features/analysis/        # Analysis form, polling, status, report view
    |   |-- services/                 # Typed FastAPI client
    |   `-- types/                    # Frontend copies/generated API contract types
    `-- tests/                        # Vitest tests and fixed fixtures
```

Directories are created by the first task that needs them; empty scaffolding is intentionally avoided.

## Intended local startup

After the project skeleton and Docker Compose task is complete:

```bash
cp .env.example .env
docker compose up --build
```

Planned endpoints:

- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/health`
- Backend API docs: `http://localhost:8000/docs`

These endpoints are not available in the current documentation-only stage.

## Planned environment variables

| Variable | Owner | Purpose | Secret |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | Backend | OpenAI model authentication | Yes |
| `OPENAI_MODEL` | Backend | Explicit model selection | No |
| `DATABASE_URL` | Backend | SQLAlchemy MySQL read-only connection URL | Yes |
| `DB_ALLOWED_SCHEMAS` | Backend | Comma-separated schema allowlist | No |
| `DB_ALLOWED_TABLES` | Backend | Optional comma-separated table allowlist | No |
| `SQL_MAX_ROWS` | Backend | Server-enforced result cap | No |
| `SQL_TIMEOUT_SECONDS` | Backend | Query timeout budget | No |
| `AGENT_MAX_TOOL_CALLS` | Backend | Per-task tool-call budget | No |
| `SQL_MAX_RETRIES` | Backend | Repair retries; must equal `2` for MVP | No |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend | FastAPI base URL; contains no credentials | No |

Exact non-secret defaults and dependency versions remain **待验证假设** until Task 1 verifies them. `.env.example` must contain placeholder values only.

## Intended test commands

After the relevant skeleton tasks exist:

```bash
docker compose run --rm backend pytest
docker compose run --rm frontend npm run test
```

The end-to-end command will be documented when Task 13 selects and installs the smallest browser test setup. No test command is currently runnable because no application code exists.

## Not implemented in this MVP

WrenAI, LangGraph, multi-Agent workflows, Redis, Celery, Kubernetes, MinIO, multiple databases, multi-tenancy, production authentication/authorization, vector search, arbitrary code execution, PDF export, dashboard editing, scheduling, and database writes are explicitly outside scope.
