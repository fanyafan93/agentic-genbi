# Progressive Report Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Agent's one-shot full Report creation path with nine persisted ReportBuild tools that render incrementally, recover after refresh/session switching, terminate no-progress loops, and atomically publish one formal Report.

**Architecture:** Add a ReportBuild domain service with JSON development storage and PostgreSQL row-level storage. The built-in stdio MCP server calls a protected loopback HTTP dispatch endpoint using a short-lived, server-signed execution token; it never receives database credentials or accepts owner/session/turn from model arguments. Codex native Tool Items remain the execution timeline, while one GenBI projection event tells the frontend which persisted build revision to reload and render through the existing Report renderer.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3, openai-codex Python SDK, PostgreSQL/JSONB, Next.js, React, TypeScript, Puck, ECharts, VTable, pytest, Vitest.

## Global Constraints

- Implement only persisted progressive Report creation; do not add Report versions, collaborative editing, RLS redesign, sharing changes, or unrelated UI work.
- Preserve current formal Report fields and existing Report CRUD/query behavior.
- Normal Agent runtime exposes exactly nine ReportBuild tools; legacy full `create_report` and `update_report` remain callable only as hidden compatibility handlers.
- Model arguments never carry trusted owner, session, turn, tenant, workspace, role, database URL, token, or secret values.
- ReportBuild query results remain runtime-only and are never written to PostgreSQL.
- Use Codex native `item/started`, `item/completed`, and `turn/completed`; never add `turn/failed` or `item/failed`.
- Every production behavior is implemented test-first and each failing test must be observed before production code is changed.
- Preserve all pre-existing dirty-worktree changes; stage only files or hunks created by this plan.
- Do not add a third-party dependency.

---

### Task 1: ReportBuild Models and Aggregate Validation

**Files:**
- Create: `backend/reports/build_models.py`
- Modify: `backend/reports/schema.py`
- Modify: `backend/reports/__init__.py`
- Create: `backend/tests/test_report_build_models.py`
- Modify: `backend/tests/test_report_store.py`

**Interfaces:**
- Produces: `ReportValidationIssue(path: str, code: str, message: str)`.
- Produces: `collect_report_validation_errors(report: Mapping[str, Any]) -> list[ReportValidationIssue]`.
- Produces: `ReportBuildRecord` with camel-case payload fields matching the design.
- Produces: `report_build_to_payload(record, *, renderable: bool = False) -> dict[str, Any]`.
- Produces: `renderable_report_from_build(record) -> dict[str, Any]`.
- Consumes: existing `validate_report_config`, `ReportValidationError`, and formal Report schema helpers.

- [ ] **Step 1: Write failing model and validation tests**

```python
def test_collect_report_validation_errors_returns_independent_paths() -> None:
    invalid = report_config()
    invalid["queries"]["sales-query"]["parameters"] = []
    invalid["charts"]["sales-chart"]["queryId"] = "missing-query"
    invalid["tables"]["sales-table"]["options"] = {}

    issues = collect_report_validation_errors(invalid)

    assert {issue.path for issue in issues} >= {
        "queries.sales-query.parameters",
        "charts.sales-chart.queryId",
        "tables.sales-table.options.columns",
    }


def test_renderable_build_derives_layout_without_mutating_content() -> None:
    record = build_record(
        content={
            **empty_report_config(),
            "charts": {
                "sales-chart": {
                    "queryId": "sales-query",
                    "option": {"series": []},
                }
            },
            "queries": {"sales-query": valid_query()},
        }
    )

    rendered = renderable_report_from_build(record)

    assert record.content["layout"]["content"] == []
    assert rendered["layout"]["content"][0]["type"] == "ChartBlock"
    assert rendered["layout"]["content"][0]["props"]["chartId"] == "sales-chart"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_report_build_models.py backend/tests/test_report_store.py -q -p no:cacheprovider
```

Expected: collection fails because `build_models` and aggregate validation do not exist.

- [ ] **Step 3: Implement immutable records and aggregate validation**

Create these exact public shapes:

```python
@dataclass(frozen=True)
class ReportValidationIssue:
    path: str
    code: str
    message: str


@dataclass(frozen=True)
class ReportBuildRecord:
    id: str
    ownerId: str
    sessionId: str
    turnId: str
    targetReportId: str | None
    status: str
    content: dict[str, Any]
    validationErrors: list[dict[str, str]]
    revision: int
    publishedReportId: str | None
    lastSuccessfulStep: str | None
    stepAttempts: dict[str, int]
    createdAt: str
    updatedAt: str
    expiresAt: str
```

`collect_report_validation_errors` must:

- validate top-level title/subtitle and object sections;
- validate every filter independently;
- validate every query against the complete filter map;
- validate every chart/table against the complete query map;
- validate every layout block independently;
- return deterministic path order with duplicate paths removed;
- leave `validate_report_config` behavior unchanged for existing callers.

`renderable_report_from_build` must:

- return formal Report-shaped data with `id = build.id`;
- preserve explicit non-empty `layout.content`;
- derive one `FilterBlock`, then stable-order `ChartBlock` and `TableBlock` entries when explicit content is empty;
- never mutate `record.content`;
- include `buildId`, `buildRevision`, and `buildStatus` only in the render projection.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_report_build_models.py backend/tests/test_report_store.py -q -p no:cacheprovider
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit clean/new files only**

```powershell
git add backend/reports/build_models.py backend/reports/schema.py backend/reports/__init__.py backend/tests/test_report_build_models.py backend/tests/test_report_store.py
git commit -m "feat: add report build model validation"
```

If one listed file contained pre-existing unstaged changes, stage only this task's hunks and verify with `git diff --cached --name-status`.

---

### Task 2: JSON ReportBuild Store and Domain Service

**Files:**
- Create: `backend/reports/build_store.py`
- Create: `backend/reports/build_service.py`
- Create: `backend/tests/test_report_build_store.py`
- Create: `backend/tests/test_report_build_service.py`

**Interfaces:**
- Consumes: `ReportBuildRecord`, `ReportValidationIssue`, `collect_report_validation_errors`, `ReportStore`.
- Produces: `ReportBuildContext(owner_id, session_id, turn_id, tenant_id=None, workspace_id=None, roles=())`.
- Produces: `ReportBuildStore.create/get/get_active_for_session/mutate/publish/cleanup_expired`.
- Produces: `ReportBuildService.invoke(tool_name, arguments, context) -> dict[str, Any]`.
- Produces: `ReportBuildNotFound`, `ReportBuildAccessDenied`, `ReportBuildValidationFailed`, `ReportBuildRetryExhausted`.

- [ ] **Step 1: Write failing store/service tests**

```python
def test_start_and_upsert_chart_persist_incremental_revisions(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    context = ReportBuildContext("user-1", "session-1", "turn-1")

    started = service.invoke(
        "start_report_build",
        {"title": "渠道分析", "subtitle": "本月"},
        context,
    )
    query = service.invoke(
        "upsert_report_query",
        {
            "build_id": started["buildId"],
            "query_id": "q-sales",
            "query": valid_query(),
        },
        context,
    )
    chart = service.invoke(
        "upsert_report_chart",
        {
            "build_id": started["buildId"],
            "chart_id": "c-sales",
            "chart": {
                "queryId": "q-sales",
                "option": {"series": []},
            },
        },
        context,
    )

    assert [started["revision"], query["revision"], chart["revision"]] == [0, 1, 2]
    restored = service.invoke(
        "get_report_build",
        {"build_id": started["buildId"]},
        context,
    )
    assert restored["build"]["content"]["charts"]["c-sales"]["queryId"] == "q-sales"


def test_failed_step_keeps_content_and_persists_error_revision(tmp_path: Path) -> None:
    service = build_service(tmp_path)
    context = ReportBuildContext("user-1", "session-1", "turn-1")
    started = start_build(service, context)

    failed = service.invoke(
        "upsert_report_chart",
        {
            "build_id": started["buildId"],
            "chart_id": "bad",
            "chart": {"queryId": "missing", "option": {"series": []}},
        },
        context,
    )

    assert failed["ok"] is False
    assert failed["status"] == "failed"
    assert failed["revision"] == 1
    assert failed["build"]["content"]["charts"] == {}
    assert failed["errors"][0]["path"] == "charts.bad.queryId"


def test_publish_is_idempotent_and_creates_one_report(tmp_path: Path) -> None:
    service, report_store = build_publishable_service(tmp_path)
    context = ReportBuildContext("user-1", "session-1", "turn-1")
    build_id = complete_build(service, context)

    first = service.invoke("publish_report_build", {"build_id": build_id}, context)
    second = service.invoke("publish_report_build", {"build_id": build_id}, context)

    assert first["report"]["id"] == second["report"]["id"]
    assert len(report_store.list_reports(owner_id="user-1")) == 1
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_report_build_store.py backend/tests/test_report_build_service.py -q -p no:cacheprovider
```

Expected: imports fail because store and service do not exist.

- [ ] **Step 3: Implement JSON storage with one mutation boundary**

Implement:

```python
class ReportBuildStore:
    def create_build(self, record: ReportBuildRecord) -> ReportBuildRecord: ...
    def get_build(self, build_id: str) -> ReportBuildRecord | None: ...
    def get_active_for_session(
        self, session_id: str, *, owner_id: str | None = None
    ) -> ReportBuildRecord | None: ...
    def mutate_build(
        self,
        build_id: str,
        *,
        owner_id: str,
        mutation: Callable[[ReportBuildRecord], ReportBuildRecord],
    ) -> ReportBuildRecord | None: ...
    def publish_build(
        self,
        build_id: str,
        *,
        owner_id: str,
        turn_id: str,
    ) -> tuple[ReportBuildRecord, ReportRecord] | None: ...
    def cleanup_expired(self, *, now: datetime | None = None) -> int: ...
```

Use an `RLock` so read-modify-write is atomic inside the JSON fallback. Keep builds in a dedicated `.resource-index/report-builds.json`; do not merge them into `reports.json`.

- [ ] **Step 4: Implement the nine service operations**

`ReportBuildService.invoke` must dispatch exactly:

```python
REPORT_BUILD_TOOL_NAMES = (
    "start_report_build",
    "get_report_build",
    "set_report_filters",
    "upsert_report_query",
    "upsert_report_chart",
    "upsert_report_table",
    "set_report_layout",
    "validate_report_build",
    "publish_report_build",
)
```

Mutation rules:

- start returns an existing unpublished build for the same owner/session/turn and title, otherwise creates revision `0`;
- a successful mutation updates only its section, clears errors, sets `building`, and increments revision once;
- a validation failure leaves content unchanged, writes all errors, sets `failed`, increments revision once, and increments `(tool_name, object_id)` attempts;
- after the original failure, at most two correction failures are retryable; the third returns `retryable: false` and `report_build_retry_exhausted`;
- validate re-runs aggregate validation and persists either `building` or `failed`;
- publish validates again and delegates atomic/idempotent creation to the store.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_report_build_store.py backend/tests/test_report_build_service.py -q -p no:cacheprovider
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/reports/build_store.py backend/reports/build_service.py backend/tests/test_report_build_store.py backend/tests/test_report_build_service.py
git commit -m "feat: add persisted report build service"
```

---

### Task 3: PostgreSQL Row-Level Store and Migration

**Files:**
- Modify: `backend/persistence/postgres_stores.py`
- Modify: `backend/reports/build_service.py`
- Modify: `frontend/prisma/schema.prisma`
- Create: `frontend/prisma/migrations/20260806200000_report_builds/migration.sql`
- Create: `backend/tests/test_postgres_report_build_store.py`
- Create: `scripts/smoke_report_build_postgres.py`

**Interfaces:**
- Produces: `build_postgres_report_build_store() -> PostgresReportBuildStore`.
- Produces: `PostgresReportBuildStore` with the same public methods as JSON `ReportBuildStore`.
- Consumes: existing `reports`, `analysis_threads`, and `analysis_turns` tables.
- Produces: atomic `publish_build` transaction that inserts one row into `reports` and updates one `report_builds` row.

- [ ] **Step 1: Write failing PostgreSQL store tests**

```python
def test_postgres_mutation_locks_and_updates_one_build() -> None:
    store, connection = configured_store()
    record = build_record(revision=4)

    updated = store.mutate_build(
        record.id,
        owner_id=record.ownerId,
        mutation=lambda current: replace(
            current,
            revision=current.revision + 1,
            content={**current.content, "charts": {"c": valid_chart()}},
        ),
    )

    assert updated is not None
    assert updated.revision == 5
    assert "FOR UPDATE" in connection.executed_sql
    assert not any("SELECT * FROM report_builds" == sql.strip() for sql in connection.executed_sql)


def test_postgres_publish_uses_one_transaction_and_is_idempotent() -> None:
    store, connection = publishable_store()

    first = store.publish_build("build-1", owner_id="user-1", turn_id="turn-1")
    second = store.publish_build("build-1", owner_id="user-1", turn_id="turn-1")

    assert first is not None and second is not None
    assert first[1].id == second[1].id
    assert connection.inserted_report_ids == [first[1].id]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_postgres_report_build_store.py -q -p no:cacheprovider
```

Expected: `PostgresReportBuildStore` and builder are missing.

- [ ] **Step 3: Add Prisma model and idempotent SQL migration**

Add:

```prisma
model ReportBuild {
  id                   String   @id
  ownerId              String   @map("owner_id")
  sessionId            String   @map("session_id")
  turnId               String   @map("turn_id")
  targetReportId       String?  @map("target_report_id")
  status               String
  content              Json
  validationErrors     Json     @default("[]") @map("validation_errors")
  revision             BigInt   @default(0)
  publishedReportId    String?  @map("published_report_id")
  lastSuccessfulStep   String?  @map("last_successful_step")
  stepAttempts         Json     @default("{}") @map("step_attempts")
  createdAt            DateTime @default(now()) @map("created_at")
  updatedAt            DateTime @updatedAt @map("updated_at")
  expiresAt            DateTime @map("expires_at")

  @@index([sessionId, updatedAt(sort: Desc)])
  @@index([turnId])
  @@index([ownerId, status, updatedAt(sort: Desc)])
  @@index([expiresAt])
  @@map("report_builds")
}
```

Migration SQL must create the same columns, foreign keys, and four indexes with `IF NOT EXISTS`; it must not alter or delete existing Report rows.

- [ ] **Step 4: Implement row-level PostgreSQL methods**

Requirements:

- `get_build` selects only `WHERE id = %(id)s`;
- `get_active_for_session` selects only one session and statuses `building`, `validating`, `failed`;
- `mutate_build` uses `SELECT ... FOR UPDATE`, calls the domain mutation, and updates one row;
- JSON values use psycopg `Jsonb`;
- `cleanup_expired` deletes only expired/published rows selected by the documented retention rules;
- no method scans all builds or rewrites unrelated rows.

- [ ] **Step 5: Implement atomic publish**

Inside one connection transaction:

```text
SELECT report_builds row FOR UPDATE
if published_report_id exists: SELECT and return existing Report
collect + reject validation errors
INSERT one reports row
UPDATE one report_builds row to published
return both records
```

The JSON fallback keeps its existing lock-based best effort; PostgreSQL is the production atomicity contract.

- [ ] **Step 6: Run unit tests and schema checks**

Run:

```powershell
python -m pytest backend/tests/test_postgres_report_build_store.py backend/tests/test_postgres_report_store.py -q -p no:cacheprovider
Set-Location frontend
npx.cmd prisma validate
Set-Location ..
```

Expected: selected tests and Prisma validation pass.

- [ ] **Step 7: Add a real PostgreSQL smoke script**

`scripts/smoke_report_build_postgres.py` must:

- use explicit IDs beginning `smoke_report_build_`;
- insert its own session/turn fixtures only if absent;
- create two builds;
- mutate them concurrently from two threads;
- verify both revisions/content survive;
- publish one build twice and verify one formal Report;
- delete only exact `smoke_report_build_*` rows in a `finally` block.

Run:

```powershell
$env:GENBI_DATABASE_URL=((docker compose exec -T backend printenv GENBI_DATABASE_URL) -replace '@postgres:', '@127.0.0.1:').Trim()
python scripts/smoke_report_build_postgres.py
```

Expected: prints `report build postgres smoke: PASS`.

- [ ] **Step 8: Commit only this task's changes**

```powershell
git add backend/persistence/postgres_stores.py backend/reports/build_service.py frontend/prisma/schema.prisma frontend/prisma/migrations/20260806200000_report_builds/migration.sql backend/tests/test_postgres_report_build_store.py scripts/smoke_report_build_postgres.py
git commit -m "feat: persist report builds in postgres"
```

Use hunk staging for `postgres_stores.py` and `schema.prisma` because both already contain unrelated worktree changes.

---

### Task 4: Signed Turn Context and Nine Stateful MCP Tools

**Files:**
- Create: `backend/reports/build_context.py`
- Create: `backend/mcp_servers/genbi_report_build_tools.py`
- Modify: `backend/mcp_servers/genbi_report_server.py`
- Modify: `backend/harness/codex_sdk_runner.py`
- Modify: `backend/services/codex_turn_runner.py`
- Modify: `backend/api/analysis_api.py`
- Create: `backend/tests/test_report_build_context.py`
- Modify: `backend/tests/test_genbi_report_mcp_server.py`
- Modify: `backend/tests/test_codex_sdk_runner.py`
- Modify: `backend/tests/test_analysis_api.py`

**Interfaces:**
- Produces: `ReportToolExecutionRegistry.reserve/bind/resolve/release`.
- Produces: signed opaque execution token with expiry and unguessable execution ID.
- Produces: `POST /api/internal/report-build-tools/{tool_name}`.
- Produces: `invoke_report_build_tool(endpoint, token, tool_name, arguments)`.
- Consumes: `ReportBuildService.invoke`.

- [ ] **Step 1: Write failing execution-context tests**

```python
def test_execution_token_binds_server_ids_after_codex_provisions_turn() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test-secret")
    token = registry.reserve(
        owner_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    )

    registry.bind(token, session_id="session-1", turn_id="turn-1")
    context = registry.resolve(token)

    assert context.owner_id == "user-1"
    assert context.session_id == "session-1"
    assert context.turn_id == "turn-1"


def test_model_cannot_override_signed_context(client) -> None:
    token = bound_token(owner_id="user-1", session_id="session-1", turn_id="turn-1")

    response = client.post(
        "/api/internal/report-build-tools/start_report_build",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "渠道分析",
            "subtitle": "本月",
            "owner_id": "attacker",
            "session_id": "other",
        },
    )

    assert response.status_code == 422
```

- [ ] **Step 2: Write failing MCP discovery/dispatch tests**

```python
def test_lists_exactly_nine_progressive_report_tools() -> None:
    response = _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert [tool["name"] for tool in response["result"]["tools"]] == [
        "start_report_build",
        "get_report_build",
        "set_report_filters",
        "upsert_report_query",
        "upsert_report_chart",
        "upsert_report_table",
        "set_report_layout",
        "validate_report_build",
        "publish_report_build",
    ]


def test_progressive_tool_forwards_small_arguments_without_context_fields() -> None:
    calls: list[tuple[str, dict]] = []

    payload = _call_tool(
        "upsert_report_chart",
        {
            "build_id": "build-1",
            "chart_id": "chart-1",
            "chart": {"queryId": "query-1", "option": {"series": []}},
        },
        invoke=lambda name, args: calls.append((name, args)) or {"ok": True},
    )

    assert payload["ok"] is True
    assert calls[0][0] == "upsert_report_chart"
    assert set(calls[0][1]) == {"build_id", "chart_id", "chart"}
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_report_build_context.py backend/tests/test_genbi_report_mcp_server.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py -q -p no:cacheprovider
```

Expected: new context and tools are missing; old two-tool discovery assertion fails.

- [ ] **Step 4: Implement short-lived execution registry**

Token requirements:

- HMAC-SHA256 signed;
- payload contains only execution ID and expiry;
- context values remain in the single-worker in-process registry;
- `bind` is called immediately after Codex returns the real thread and turn IDs, before `turn.stream()`;
- `resolve` rejects invalid, expired, released, or unbound tokens;
- `release` runs in the runtime stream `finally`.

Extend `CodexSdkRunnerContext` with trusted principal fields and generate:

```text
GENBI_REPORT_TOOL_ENDPOINT=http://127.0.0.1:8000/api/internal/report-build-tools
GENBI_REPORT_TOOL_TOKEN=<opaque signed token>
```

in the per-turn Codex process environment. Do not place either value in model input, Tool Item payloads, logs, or generated `config.toml`.

- [ ] **Step 5: Implement the protected internal endpoint**

The endpoint must:

- require `Authorization: Bearer <token>`;
- resolve a bound context;
- reject extra context/security arguments using per-tool Pydantic bodies with `extra="forbid"`;
- call `ReportBuildService.invoke`;
- return tool validation failures as HTTP 200 structured payloads so the model can repair;
- return 401 for token failures and 404 for unknown tools.

- [ ] **Step 6: Implement nine small MCP schemas and loopback client**

`genbi_report_build_tools.py` owns:

- exact JSON schemas for the nine tools;
- stdlib `urllib.request` POST client;
- token and endpoint environment loading;
- sanitised network error result `{"ok": false, "status": "tool_unavailable", ...}`.

`genbi_report_server.py` must:

- advertise only the nine new tools;
- delegate them to the injected/default loopback invoker;
- keep old `create_report` and `update_report` handlers callable by direct name for compatibility, but omit them from `tools/list`;
- never add owner/session/turn properties to a tool schema.

- [ ] **Step 7: Pass trusted context from CodexTurnRunner**

`runtime_context` must derive:

```python
{
    "report_tool_owner_id": request.user_id or session.userId or "local-user",
    "report_tool_tenant_id": request.metadata.get("tenant_id"),
    "report_tool_workspace_id": request.metadata.get("workspace_id"),
    "report_tool_roles": request.metadata.get("roles", []),
}
```

No value comes from MCP arguments.

- [ ] **Step 8: Run tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_report_build_context.py backend/tests/test_genbi_report_mcp_server.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py -q -p no:cacheprovider
```

Expected: all selected tests pass.

- [ ] **Step 9: Commit task changes**

```powershell
git add backend/reports/build_context.py backend/mcp_servers/genbi_report_build_tools.py backend/mcp_servers/genbi_report_server.py backend/harness/codex_sdk_runner.py backend/services/codex_turn_runner.py backend/api/analysis_api.py backend/tests/test_report_build_context.py backend/tests/test_genbi_report_mcp_server.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py
git commit -m "feat: expose progressive report build tools"
```

Stage only task hunks in pre-dirty files.

---

### Task 5: Build Projection Events, Recovery API, and Build Queries

**Files:**
- Modify: `backend/services/report_projector.py`
- Modify: `backend/services/codex_turn_runner.py`
- Modify: `backend/api/analysis_api.py`
- Modify: `backend/reports/query_service.py`
- Modify: `backend/tests/test_report_projector.py`
- Modify: `backend/tests/test_report_turn_runner.py`
- Modify: `backend/tests/test_analysis_api.py`
- Modify: `backend/tests/test_report_query_service.py`

**Interfaces:**
- Consumes: MCP result actions `build_started`, `build_updated`, `build_failed`, `build_validated`, `build_published`.
- Produces: `genbi/report/build_updated` with metadata only.
- Produces: existing `genbi/report/created` after publish.
- Produces: `GET /api/report-builds/{build_id}`.
- Produces: `GET /api/analysis/sessions/{session_id}/report-builds/active`.
- Produces: `POST /api/report-builds/{build_id}/queries/{query_id}`.

- [ ] **Step 1: Write failing projector tests**

```python
def test_projector_emits_metadata_only_build_revision_event() -> None:
    projected = projector.project_report(
        completed_build_tool_event(
            action="build_updated",
            build_id="build-1",
            revision=4,
            status="building",
            changed_section="charts",
        ),
        session_id="session-1",
        turn_id="turn-1",
        owner_id="user-1",
    )

    assert projected.type == "genbi/report/build_updated"
    assert projected.payload == {
        "eventSource": "genbi_projection",
        "buildId": "build-1",
        "sessionId": "session-1",
        "turnId": "turn-1",
        "status": "building",
        "revision": 4,
        "changedSection": "charts",
        "codex_item_id": "item-1",
    }
    assert "content" not in projected.payload
    assert "sql" not in json.dumps(projected.payload)


def test_publish_projects_existing_report_created_without_second_save() -> None:
    projected = projector.project_report(
        completed_publish_event(report_payload()),
        session_id="session-1",
        turn_id="turn-1",
        owner_id="user-1",
    )

    assert projected.type == "genbi/report/created"
    assert report_store.create_calls == 0
```

- [ ] **Step 2: Write failing API/query tests**

```python
def test_active_build_route_recovers_renderable_content(client) -> None:
    response = client.get(
        "/api/analysis/sessions/session-1/report-builds/active",
        headers=principal_headers("user-1"),
    )

    assert response.status_code == 200
    assert response.json()["build"]["revision"] == 3
    assert response.json()["report"]["buildId"] == "build-1"


def test_build_query_uses_same_readonly_query_service(client) -> None:
    response = client.post(
        "/api/report-builds/build-1/queries/q-sales",
        headers=principal_headers("user-1"),
        json={"filters": {}, "page": 1, "pageSize": 50},
    )

    assert response.status_code == 200
    assert response.json()["rows"] == [{"channel": "抖音", "sales": 10}]
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_report_projector.py backend/tests/test_report_turn_runner.py backend/tests/test_analysis_api.py backend/tests/test_report_query_service.py -q -p no:cacheprovider
```

Expected: build projection and routes do not exist.

- [ ] **Step 4: Change projector to projection-only behavior**

For new tools:

- never write ReportBuild or Report data;
- emit one build event for persisted state changes;
- emit existing `genbi/report/created` using the report payload returned by atomic publish;
- ignore `get_report_build` results;
- keep legacy hidden create/update projection behavior for compatibility tests.

- [ ] **Step 5: Generalize query execution input**

Define a structural protocol:

```python
class ReportQuerySource(Protocol):
    queries: Mapping[str, Any]
```

Allow `ReportQueryService.execute` to consume either `ReportRecord` or a ReportBuild query source without branching SQL safety logic.

- [ ] **Step 6: Add authorised read/recovery/query routes**

Rules:

- exact build lookup verifies owner or admin role;
- active-session lookup first verifies Principal can access the Session, then returns the newest non-expired `building`, `validating`, or `failed` build;
- build query verifies the same access and executes against canonical `content`, not the derived layout projection;
- absent active build returns `{"build": null, "report": null}`, not 404;
- build query uses the existing `ReportQueryBody`.

- [ ] **Step 7: Run tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_report_projector.py backend/tests/test_report_turn_runner.py backend/tests/test_analysis_api.py backend/tests/test_report_query_service.py -q -p no:cacheprovider
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit task changes**

```powershell
git add backend/services/report_projector.py backend/services/codex_turn_runner.py backend/api/analysis_api.py backend/reports/query_service.py backend/tests/test_report_projector.py backend/tests/test_report_turn_runner.py backend/tests/test_analysis_api.py backend/tests/test_report_query_service.py
git commit -m "feat: project and query active report builds"
```

Stage only task hunks in pre-dirty files.

---

### Task 6: Frontend Incremental Rendering and Refresh Recovery

**Files:**
- Modify: `frontend/src/modules/analysis/types/report.ts`
- Modify: `frontend/src/modules/analysis/api/report-service.ts`
- Modify: `frontend/src/modules/analysis/agentClients/types.ts`
- Modify: `frontend/src/modules/analysis/agentClients/backendClient.ts`
- Modify: `frontend/src/modules/analysis/hooks/use-flow.ts`
- Modify: `frontend/src/modules/analysis/components/AnalysisWorkspace.tsx`
- Modify: `frontend/src/modules/analysis/components/ReportContext.tsx`
- Modify: `frontend/src/modules/analysis/components/ReportPanel.tsx`
- Modify: `frontend/tests/report-api-client.test.ts`
- Modify: `frontend/tests/analysis-backend-client.test.ts`
- Modify: `frontend/tests/report-context.test.tsx`
- Modify: `frontend/tests/report-renderer.test.tsx`
- Modify: `frontend/tests/report-draft-session.test.tsx`

**Interfaces:**
- Produces: `ReportBuildStatus = "building" | "validating" | "failed" | "published"`.
- Extends `Report` with optional `buildId`, `buildRevision`, `buildStatus`, and `buildValidationErrors`.
- Produces: `getReportBuild`, `getActiveReportBuild`, `executeReportBuildQuery`.
- Consumes: `genbi/report/build_updated`.

- [ ] **Step 1: Write failing API/event mapping tests**

```typescript
it("reloads the authoritative build on build_updated", async () => {
  server.enqueueSse(buildUpdatedEvent({ buildId: "build-1", revision: 4 }));
  server.enqueueJson("/api/report-builds/build-1", buildPayload({ revision: 4 }));

  const events = await collect(client.send(messageInput("session-1")));

  expect(events).toContainEqual(expect.objectContaining({
    type: "report",
    report: expect.objectContaining({
      buildId: "build-1",
      buildRevision: 4,
    }),
  }));
});


it("ignores an older build revision", () => {
  const current = buildReport({ buildId: "build-1", buildRevision: 5 });
  const next = applyReportRevision(current, buildReport({
    buildId: "build-1",
    buildRevision: 4,
  }));

  expect(next).toBe(current);
});
```

- [ ] **Step 2: Write failing renderer/query tests**

```typescript
it("queries build endpoint for a build report", async () => {
  render(
    <ReportProvider report={buildReport({ buildId: "build-1" })}>
      <Probe />
    </ReportProvider>,
  );

  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    expect.stringContaining("/api/report-builds/build-1/queries/q-sales"),
    expect.anything(),
  ));
});


it("restores active build after opening an existing session", async () => {
  mockSession("session-1");
  mockReportsBySession("session-1", []);
  mockActiveBuild("session-1", buildPayload({ revision: 3 }));

  render(<AnalysisWorkspace initialSessionId="session-1" />);

  expect(await screen.findByText("渠道销售分析")).toBeTruthy();
});
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
Set-Location frontend
npm.cmd test -- tests/report-api-client.test.ts tests/analysis-backend-client.test.ts tests/report-context.test.tsx tests/report-renderer.test.tsx tests/report-draft-session.test.tsx
Set-Location ..
```

Expected: build types, API calls, revision guard, and recovery are missing.

- [ ] **Step 4: Add build API functions and render type**

`getReportBuild` and `getActiveReportBuild` return the backend's already-derived `report` projection. `executeReportBuildQuery` mirrors `executeReportQuery` but uses the build URL.

- [ ] **Step 5: Fetch build state when the SSE event arrives**

In `BackendAnalysisAgentClient.send`:

- intercept raw `genbi/report/build_updated`;
- fetch `/api/report-builds/{buildId}`;
- verify fetched revision is at least event revision;
- yield `AgentEvent { type: "report", report }`;
- on fetch failure yield a non-destructive `error` event while leaving prior report snapshot intact.

Do not put full Report content into the SSE mapping function.

- [ ] **Step 6: Add revision-aware flow snapshots**

`applyReportRevision(current, incoming)` must:

- accept formal Report over a build Report after publish;
- accept a greater revision for the same build;
- reject lower/equal duplicate revision;
- keep session-scoped snapshots so switching Sessions does not replace another Session's report.

- [ ] **Step 7: Restore the active build in AnalysisWorkspace**

For initial deep-link load and manual session selection:

```text
load Session detail
load latest formal Report
load active ReportBuild
prefer active build projection when present
otherwise keep latest formal Report / initial Report
```

Keep Report center arrays formal-only. Store restored build separately from `savedReports`.

- [ ] **Step 8: Query and display a build through existing components**

`ReportProvider` selects:

```typescript
report.buildId
  ? executeReportBuildQuery(report.buildId, queryId, request)
  : executeReportQuery(report.id, queryId, request)
```

`ReportPanel` reuses the same Puck/ECharts/VTable tree. It may show a small status label for `building`, `validating`, or `failed`, but must not introduce a second renderer or replace already rendered components with an empty loading screen.

- [ ] **Step 9: Run tests and verify GREEN**

Run:

```powershell
Set-Location frontend
npm.cmd test -- tests/report-api-client.test.ts tests/analysis-backend-client.test.ts tests/report-context.test.tsx tests/report-renderer.test.tsx tests/report-draft-session.test.tsx
npx.cmd tsc --noEmit --incremental false
Set-Location ..
```

Expected: selected tests and TypeScript pass.

- [ ] **Step 10: Commit task changes**

```powershell
git add frontend/src/modules/analysis/types/report.ts frontend/src/modules/analysis/api/report-service.ts frontend/src/modules/analysis/agentClients/types.ts frontend/src/modules/analysis/agentClients/backendClient.ts frontend/src/modules/analysis/hooks/use-flow.ts frontend/src/modules/analysis/components/AnalysisWorkspace.tsx frontend/src/modules/analysis/components/ReportContext.tsx frontend/src/modules/analysis/components/ReportPanel.tsx frontend/tests/report-api-client.test.ts frontend/tests/analysis-backend-client.test.ts frontend/tests/report-context.test.tsx frontend/tests/report-renderer.test.tsx frontend/tests/report-draft-session.test.tsx
git commit -m "feat: render report builds incrementally"
```

Stage only task hunks in pre-dirty frontend files.

---

### Task 7: MiniMax No-Progress Guard and Agent Instructions

**Files:**
- Modify: `backend/reports/build_context.py`
- Modify: `backend/harness/minimax_codex_adapter.py`
- Modify: `backend/harness/codex_sdk_runner.py`
- Modify: `backend/harness/codex_mcp_config.py`
- Modify: `backend/system_management/mcp_registry.py`
- Modify: `backend/tests/test_minimax_codex_adapter.py`
- Modify: `backend/tests/test_codex_sdk_runner.py`
- Modify: `backend/tests/test_codex_mcp_config.py`
- Modify: `backend/tests/test_mcp_registry.py`

**Interfaces:**
- Produces: execution-scoped `begin_model_round`, `record_successful_report_mutation`, and `no_progress_exhausted`.
- Produces: MiniMax adapter path `/api/codex-minimax/v1/executions/{execution_id}/responses`.
- Updates: Report MCP display metadata to the nine tools.

- [ ] **Step 1: Write failing no-progress tests**

```python
def test_three_model_rounds_without_report_progress_block_the_fourth() -> None:
    registry = ReportToolExecutionRegistry(secret=b"test")
    token = bound_execution(registry)
    registry.record_successful_report_mutation(token, "start_report_build")

    assert registry.begin_model_round(execution_id(token)) is True
    assert registry.begin_model_round(execution_id(token)) is True
    assert registry.begin_model_round(execution_id(token)) is True
    assert registry.begin_model_round(execution_id(token)) is False


def test_successful_mutation_resets_no_progress_rounds() -> None:
    registry = started_execution_registry()
    assert registry.begin_model_round(EXECUTION_ID) is True
    assert registry.begin_model_round(EXECUTION_ID) is True

    registry.record_successful_report_mutation(TOKEN, "upsert_report_chart")

    assert registry.begin_model_round(EXECUTION_ID) is True
```

- [ ] **Step 2: Write failing tool metadata/instruction tests**

```python
def test_system_report_mcp_lists_progressive_tools_only() -> None:
    payload = registry.get("GenBI_report")
    assert [tool["name"] for tool in payload["tools"]] == list(REPORT_BUILD_TOOL_NAMES)


def test_analysis_instructions_require_progressive_publish() -> None:
    assert "start_report_build" in CODEX_ANALYSIS_INSTRUCTIONS
    assert "publish_report_build" in CODEX_ANALYSIS_INSTRUCTIONS
    assert "create_report(report_json)" not in CODEX_ANALYSIS_INSTRUCTIONS
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_minimax_codex_adapter.py backend/tests/test_codex_sdk_runner.py backend/tests/test_codex_mcp_config.py backend/tests/test_mcp_registry.py -q -p no:cacheprovider
```

Expected: execution round guard and new tool metadata are missing.

- [ ] **Step 4: Add execution-scoped adapter URL and round guard**

When MiniMax adapter is enabled, per-turn config overrides the provider base URL with:

```text
http://127.0.0.1:8000/api/codex-minimax/v1/executions/{execution_id}
```

Before proxying `/responses`, the route calls `begin_model_round`. It only counts after `start_report_build` succeeds. The fourth request after three completed no-progress rounds returns a deterministic Responses API failure with code `report_build_no_progress`.

Any successful mutating ReportBuild tool resets the count. `get_report_build` does not.

- [ ] **Step 5: Update instructions and administrative metadata**

The instruction sequence must state:

```text
start_report_build
set_report_filters when needed
upsert_report_query one query at a time
upsert_report_chart / upsert_report_table one component at a time
set_report_layout
validate_report_build
publish_report_build
```

It must explicitly forbid full Report JSON in chat and legacy Agent calls. Update both environment-known tool metadata and built-in MCP registry payload to exactly nine tools.

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_minimax_codex_adapter.py backend/tests/test_codex_sdk_runner.py backend/tests/test_codex_mcp_config.py backend/tests/test_mcp_registry.py -q -p no:cacheprovider
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit task changes**

```powershell
git add backend/reports/build_context.py backend/harness/minimax_codex_adapter.py backend/harness/codex_sdk_runner.py backend/harness/codex_mcp_config.py backend/system_management/mcp_registry.py backend/tests/test_minimax_codex_adapter.py backend/tests/test_codex_sdk_runner.py backend/tests/test_codex_mcp_config.py backend/tests/test_mcp_registry.py
git commit -m "fix: stop stalled report build loops"
```

Stage only task hunks in pre-dirty files.

---

### Task 8: Full Verification, Runtime Rebuild, and Current-State Documentation

**Files:**
- Modify: `docs/architecture/overview.md`
- Modify: `docs/plans/current.md`
- Verify: all implementation and test files from Tasks 1–7

**Interfaces:**
- Consumes: all preceding task deliverables.
- Produces: verified running backend/frontend/postgres with progressive Report generation.

- [ ] **Step 1: Update stable architecture and current-state docs**

`docs/architecture/overview.md` must replace the one-shot Agent paragraph with the nine-tool ReportBuild flow while keeping formal Report single-record semantics.

`docs/plans/current.md` must record only verified facts:

- migration and table status;
- exact selected/full test results;
- service rebuild status;
- PostgreSQL smoke result;
- browser result;
- each real MiniMax Session ID and resulting Report ID or exact failure.

- [ ] **Step 2: Run full backend verification**

```powershell
python -m pytest backend/tests -q -p no:cacheprovider
```

Expected: all backend tests pass.

- [ ] **Step 3: Run full frontend verification**

```powershell
Set-Location frontend
npm.cmd test
npx.cmd tsc --noEmit --incremental false
npm.cmd run build
Set-Location ..
```

Expected: all frontend tests, TypeScript, and production build pass.

- [ ] **Step 4: Run repository/config checks**

```powershell
git diff --check
docker compose config --quiet
```

Expected: both pass; unrelated pre-existing Docker credential warnings may be reported separately.

- [ ] **Step 5: Rebuild without replacing PostgreSQL data**

Use the repository script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-services.ps1 -Build -ForceRecreate
```

Before execution, inspect the script and ensure it does not remove volumes. Rebuild frontend/backend only if the script would replace PostgreSQL. Never run `docker compose down -v`.

- [ ] **Step 6: Verify health and migration**

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:3000/ -UseBasicParsing
docker compose exec -T postgres psql -U agentic_genbi -d agentic_genbi -c "\d+ report_builds"
$env:GENBI_DATABASE_URL=((docker compose exec -T backend printenv GENBI_DATABASE_URL) -replace '@postgres:', '@127.0.0.1:').Trim()
python scripts/smoke_report_build_postgres.py
```

Expected: both HTTP endpoints return 200, table/indexes exist, smoke prints PASS.

- [ ] **Step 7: Browser verification**

Using the in-app browser:

1. open a fresh `/analysis/new`;
2. send a Report-generating question;
3. confirm title then at least one component appears before final publish;
4. refresh while building and confirm current content recovers;
5. switch to another Session and back without cancelling the Turn;
6. confirm final formal Report replaces the build without duplicate content;
7. confirm Report center contains only the formal Report;
8. confirm console has no new error or warning.

- [ ] **Step 8: Real MiniMax repeat verification**

Run three fresh Sessions against a known safe Doris table. For every run record:

```text
Session ID
Turn ID
ReportBuild ID
observed revision sequence
formal Report ID
terminal Turn status
```

Acceptance requires all three to produce persisted intermediate revisions and one formal Report. A validation failure must either recover within two correction retries or finish with `turn/completed status=failed`; it must not continue indefinitely.

- [ ] **Step 9: Final completion audit**

Verify every line of `docs/superpowers/specs/2026-08-06-progressive-report-build-design.md` against:

- source code;
- migration/schema;
- selected/full test output;
- running database;
- browser behavior;
- three real MiniMax runs.

Do not mark complete if any required evidence is missing.

- [ ] **Step 10: Stage and commit only this feature's remaining hunks**

```powershell
git diff --check
git diff --cached --name-status
git commit -m "feat: generate reports progressively"
```

Before committing, inspect the staged diff and remove any unrelated pre-existing worktree hunks.
