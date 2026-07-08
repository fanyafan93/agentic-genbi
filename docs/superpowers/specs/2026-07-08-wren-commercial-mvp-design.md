# Wren Commercial Web MVP Design

Date: 2026-07-08
Status: Draft for user review

## Purpose

Build a commercial-style GenBI web product inspired by Wren AI Commercial Platform, using the current empty `GenBI` workspace as a fresh implementation. The first milestone should be a locally runnable product MVP that demonstrates the commercial user experience and preserves a path to integrate the open-source Wren context layer, CLI, or engine later.

The MVP is not a pixel-for-pixel clone. It should reproduce the commercial product shape: multi-tenant workspace management, Agentic analytics projects, natural-language BI workflows, business context management, generated apps, API access, and governance surfaces.

## Reference Inputs

- Product site: `https://www.getwren.ai/`
- Commercial Platform docs: `https://docs.getwren.ai/cp/overview`
- Current open-source repo: `https://github.com/Canner/WrenAI`
- Legacy v1 repo branch: `https://github.com/Canner/WrenAI/tree/legacy/v1`

## First Milestone Scope

The first implementation milestone is a single local web app with a mock-capable backend. It must be usable without external data warehouses or paid LLM credentials, while leaving integration seams for real services.

Included:

- Organization and project console.
- Agentic and Classic project types.
- Data source connection inventory and status workflows.
- Agentic Ask workspace with thread history, generated SQL, result table, chart, insight summary, and execution steps.
- Knowledge management for markdown documents.
- Skills catalog and skill detail/testing surface.
- Memories viewer and reset workflow.
- GenBI Apps gallery and generated dashboard preview.
- API Access area with keys, usage history, SQL generation endpoint concept, and chart generation endpoint concept.
- Governance surfaces for roles, audit logs, and policy previews.
- Seed data that makes every surface feel inhabited.

Deferred:

- Real authentication provider.
- Real data warehouse connections.
- Real LLM calls.
- Real Wren Engine query transpilation.
- Production billing, SSO, SCIM, and secrets storage.
- Multi-user collaboration beyond seeded roles and UI flows.

## Product Principles

- The first screen is the product console, not a marketing landing page.
- The interface should feel like a serious analytics SaaS tool: dense, calm, readable, and efficient.
- Commercial features should be visible through real workflows, not isolated empty static cards.
- Agentic behavior should be explainable: show plan, SQL, assumptions, result, chart, and suggested next actions.
- Mocked systems must be clearly implemented as adapter interfaces so real integrations can replace them.

## Architecture

Use a full-stack TypeScript application with this baseline:

- Frontend: React + Vite + TypeScript.
- Styling: CSS modules or plain CSS with design tokens; use lucide icons.
- Backend: Node + Fastify + TypeScript.
- Data store: SQLite for local persistence.
- Tests: Vitest for unit tests and Playwright for key UI workflows.

The repository should be organized around clear product boundaries:

```text
apps/
  web/                 # React app
  api/                 # API server
packages/
  domain/              # shared types, domain models, fixtures
  adapters/            # mock and future real connectors
docs/
  superpowers/specs/   # design specs
```

Use the monorepo structure from the start so domain types and service adapters stay separated.

## Core Domain Model

Organization:

- `id`
- `name`
- `slug`
- `plan`
- `createdAt`

Member:

- `id`
- `organizationId`
- `name`
- `email`
- `role`: owner, admin, analyst, viewer
- `status`: active, invited

Project:

- `id`
- `organizationId`
- `name`
- `type`: agentic, classic
- `language`
- `description`
- `status`
- `createdAt`
- `updatedAt`

DataSource:

- `id`
- `projectId`
- `type`: postgres, mysql, bigquery, snowflake, csv, duckdb
- `name`
- `status`: connected, syncing, error, draft
- `lastSyncedAt`
- `schemaSummary`

AskThread:

- `id`
- `projectId`
- `title`
- `mode`: agentic, interactive
- `messages`
- `runs`

AskRun:

- `id`
- `threadId`
- `question`
- `planSteps`
- `generatedSql`
- `assumptions`
- `resultRows`
- `chartSpec`
- `insight`
- `status`

KnowledgeDocument:

- `id`
- `projectId`
- `title`
- `path`
- `body`
- `status`: draft, published
- `updatedAt`

Skill:

- `id`
- `projectId`
- `name`
- `description`
- `enabled`
- `inputSchema`
- `examplePrompt`
- `lastRunAt`

Memory:

- `id`
- `projectId`
- `ownerType`: user, project
- `ownerName`
- `markdownBody`
- `updatedAt`

GenBIApp:

- `id`
- `projectId`
- `name`
- `description`
- `sourceThreadId`
- `widgets`
- `status`: draft, published
- `updatedAt`

ApiKey:

- `id`
- `organizationId`
- `name`
- `prefix`
- `scopes`
- `lastUsedAt`
- `createdAt`

AuditEvent:

- `id`
- `organizationId`
- `actor`
- `action`
- `target`
- `createdAt`
- `metadata`

## Main User Flows

### 1. Organization Console

The user lands on a workspace console with organization switcher, project list, usage summary, recent questions, data source health, and audit highlights. This establishes the commercial multi-tenant product shell.

### 2. Create or Open Project

The user can view Agentic and Classic projects. Agentic projects expose Knowledge, Skills, Memories, Ask, and GenBI Apps. Classic projects expose Ask, modeling, and dashboards with fewer agentic controls.

### 3. Connect Data Source

The data source screen shows supported connectors, connection form states, sync status, schema preview, and errors. The first milestone may simulate connection tests and schema syncs with seeded fixtures.

### 4. Ask Data

The Ask workspace supports a thread list and a central conversation/result area. A seeded prompt such as "What drove revenue changes last month?" should produce:

- Agent plan steps.
- Generated SQL.
- Assumptions and context references.
- Result table.
- Chart.
- Insight narrative.
- Suggested follow-up questions.

### 5. Manage Knowledge

The Knowledge area shows a file tree of markdown documents, editor/preview modes, draft/published state, and references used by Ask runs. This represents business context management.

### 6. Manage Skills

The Skills area shows enabled skills, built-in templates, custom skill details, input schema preview, and a try-it surface. The MVP can simulate runs.

### 7. Review Memories

The Memories area shows user/project memory markdown and a reset action. The UI should communicate that memories personalize future agent behavior.

### 8. Generate GenBI App

From an Ask run, the user can open a generated app preview. The GenBI Apps area lists generated apps and renders a dashboard-like preview with charts, KPI tiles, filters, and source thread references.

### 9. API Access

The API Access area shows API keys, scopes, usage logs, and examples for SQL generation and chart generation. The backend should expose stub endpoints that return deterministic generated SQL/chart payloads.

### 10. Governance

Governance screens show members, roles, project access, audit logs, and policy previews. This anchors the commercial product expectation without implementing full enterprise controls in milestone one.

## Backend Services

Use service interfaces so mock implementations can be replaced later:

- `OrganizationService`
- `ProjectService`
- `DataSourceService`
- `AskService`
- `KnowledgeService`
- `SkillService`
- `MemoryService`
- `GenBIAppService`
- `ApiAccessService`
- `AuditService`

`AskService` should depend on an `AnalyticsAgentAdapter`. The first adapter returns deterministic runs from fixtures. A future adapter can call Wren CLI, Wren Engine, an LLM, or a commercial-compatible workflow.

`DataSourceService` should depend on a `ConnectorAdapter`. The first adapter simulates connection tests and schema sync. Future adapters can connect to Postgres, MySQL, BigQuery, Snowflake, CSV, DuckDB, and Wren Engine-backed context.

## API Surface

Minimum local API routes:

- `GET /api/organizations/current`
- `GET /api/projects`
- `GET /api/projects/:projectId`
- `GET /api/projects/:projectId/data-sources`
- `POST /api/projects/:projectId/data-sources/test`
- `POST /api/projects/:projectId/ask`
- `GET /api/projects/:projectId/threads`
- `GET /api/projects/:projectId/knowledge`
- `PUT /api/projects/:projectId/knowledge/:documentId`
- `GET /api/projects/:projectId/skills`
- `POST /api/projects/:projectId/skills/:skillId/run`
- `GET /api/projects/:projectId/memories`
- `POST /api/projects/:projectId/memories/:memoryId/reset`
- `GET /api/projects/:projectId/apps`
- `POST /api/projects/:projectId/apps`
- `GET /api/api-keys`
- `POST /api/api-keys`
- `POST /api/v1/generate-sql`
- `POST /api/v1/generate-chart`
- `GET /api/audit-events`

## Frontend Screens

Primary navigation:

- Home
- Projects
- Ask
- Data Sources
- Knowledge
- Skills
- Memories
- GenBI Apps
- API Access
- Governance

Key layout:

- Fixed left navigation with organization/project switcher.
- Top bar with project status, environment, and user menu.
- Main content optimized for repeated analytics work.
- Right-side contextual panel for lineage, assumptions, references, or activity where useful.

## Design System

Use a restrained palette with high contrast and multiple accent colors. Avoid a single-hue purple/blue or beige-heavy theme. Suggested direction:

- Neutral background: near-white and cool gray.
- Text: charcoal.
- Primary accent: teal or green-blue.
- Secondary accents: amber for warnings, rose for errors, indigo for API/developer surfaces.
- Cards: only for repeated entities and tool panels; avoid cards inside cards.
- Border radius: 8px or less.
- Icons: lucide icons for navigation and actions.

## Error Handling

- Data source connection tests show success, invalid credentials, network failure, and unsupported feature states.
- Ask runs show queued, running, completed, and failed states.
- API key creation validates name and scopes.
- Knowledge editing handles unsaved changes and publish errors.
- Empty states should provide real next actions, not marketing copy.

## Testing Strategy

Unit tests:

- Domain fixture factories.
- Service methods for projects, ask runs, API keys, and memory reset.
- Adapter responses for deterministic SQL/chart generation.

Integration tests:

- API routes return expected seeded data.
- Ask route creates a run and audit event.
- GenBI App route creates app from an ask thread.

End-to-end tests:

- User opens console and navigates project.
- User submits an Ask question and sees SQL, table, chart, insight.
- User edits and publishes a Knowledge document.
- User creates an API key and calls local SQL generation route.
- User opens a generated GenBI App preview.

Visual verification:

- Desktop and mobile screenshots for console, Ask, Knowledge, GenBI Apps, and API Access.
- Check text does not overlap and controls remain usable at common breakpoints.

## Future Integration Path

The MVP should not block real Wren integration. Future work should be able to replace mocks in this order:

1. Use Wren CLI or Wren context commands for semantic model validation.
2. Connect Wren Engine or Wren AI service for SQL generation/transpilation.
3. Add real database connectors and query execution.
4. Add persistent auth and organization membership.
5. Add production deployment, secrets management, SSO, and audit retention.

## Acceptance Criteria For Milestone One

- The app starts locally with one command documented in the README.
- The console renders seeded commercial product data.
- At least one Agentic project demonstrates Ask, Knowledge, Skills, Memories, GenBI Apps, API Access, and Governance.
- Ask returns deterministic SQL, result data, chart spec, insight, and follow-up prompts.
- Generated GenBI App preview is reachable from a seeded or newly created Ask run.
- API Access exposes deterministic SQL and chart generation endpoints.
- Tests cover core service logic and at least one end-to-end Ask workflow.
- README explains current mock limitations and future Wren integration path.

## Implementation Decisions

- Framework choice is React + Vite for the web app and Node + Fastify for the API.
- Repository shape is a TypeScript monorepo with `apps/` and `packages/`.
- Real Wren integration is explicitly deferred until the MVP product workflow is running.
