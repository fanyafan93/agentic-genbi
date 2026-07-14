# Web Data Analysis Agent MVP Scope

Status: Approved design baseline
Date: 2026-07-14

## User scenario

An analyst enters a question such as “查询最近三个月各品牌销售额趋势，并分析下降最大的品牌。” The system inspects the allowed database metadata, generates and safely executes read-only SQL, repairs ordinary SQL mistakes within a fixed budget, and returns a report suitable for immediate review in a browser.

The MVP validates one thing: whether a single Agent can complete this narrow analysis loop safely and transparently enough to justify further product work.

## MVP goals

- Demonstrate one complete request from browser input to table, chart, SQL, and conclusions.
- Make metadata discovery and SQL execution observable through execution steps.
- Prove deterministic safety enforcement outside the model prompt.
- Prove bounded recovery from common table, column, alias, grouping, function, and syntax errors.
- Keep the implementation small enough for one developer or coding Agent to understand and test end to end.

## In scope

- One Next.js analysis page using React, TypeScript, Ant Design, and ECharts.
- One FastAPI service with in-process task creation and polling.
- One OpenAI Agents SDK analysis Agent.
- Tools: `list_tables`, `get_table_schema`, and `execute_sql`.
- One MySQL test or desensitized database through SQLAlchemy and a read-only account.
- Deterministic SQL parsing, statement/type validation, schema/table allowlisting, row limit, query timeout, and tool-call budget.
- Initial SQL attempt plus at most two repair retries.
- Structured `SqlError`, execution steps, task status, and report JSON.
- Pydantic-validated Agent structured output for report generation.
- Backend pytest, frontend Vitest, core security tests, and at least five deterministic end-to-end questions.
- Docker Compose for local development.

## Out of scope

- WrenAI or a semantic layer.
- LangGraph or multiple Agents.
- Redis, Celery, durable queues, resumable jobs, or cross-process task state.
- Multi-database support, dynamic connectors, or database federation.
- Multi-tenancy, production identity, fine-grained application authorization, SSO, or billing.
- Kubernetes, MinIO, cloud deployment automation, or production observability platforms.
- Vector databases, long-term memory, autonomous schema modification, or arbitrary code execution.
- Database writes of any kind.
- PDF/HTML report export, dashboard editing, scheduling, sharing, or collaboration.

## Acceptance criteria

1. A user can submit a non-empty analysis question in the web page.
2. FastAPI creates a task and returns an `AnalysisTaskStatus`; the frontend can poll until a terminal state.
3. The Agent can call `list_tables` and `get_table_schema` within an allowlist.
4. The Agent can generate and execute one safe read-only SQL statement.
5. A wrong column can be repaired using a structured error and refreshed table schema.
6. A wrong table can be repaired by listing allowed tables again.
7. The first execution plus no more than two repair retries is enforced in Python.
8. Unsafe SQL, database authorization failures, timeouts, ambiguous requirements, missing business definitions, and exhausted budgets stop safely.
9. A successful task returns one validated `AnalysisReport` contract.
10. The UI displays task status/steps, final SQL, result table, ECharts visualization, and conclusions.
11. Five fixed questions cover trend, comparison, ranking, composition, and one repair scenario.
12. Backend unit tests, core SQL security tests, frontend component tests, and the fixed end-to-end flow run successfully.

## Known limitations

- Task state is process memory only. Restarting FastAPI loses tasks, and multiple backend workers are unsupported.
- Polling is used instead of streaming; progress visibility is step-level and may lag by the polling interval.
- There is no semantic layer. Business terms are limited to database names/comments and prompt context.
- Chart support is intentionally narrow: table-only fallback plus line, bar, and pie specifications.
- The Agent may produce analytically weak conclusions even when SQL is valid; report claims must be grounded in returned rows.
- Result truncation can make some analyses incomplete; the report must expose truncation.

## 待验证假设

- The selected MySQL test dataset has useful table/column comments and five stable questions with known expected structure.
- The chosen OpenAI model supports the required structured output and tool calling through the selected Agents SDK version.
- A MySQL-compatible SQL parser can reliably enforce the required read-only subset; the skeleton/security task must evaluate candidates before pinning one.
- Database-driver timeout behavior is enforceable consistently in the selected local MySQL image.
- The team accepts process-local task loss and a single FastAPI worker for this MVP.
