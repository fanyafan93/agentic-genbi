# Direct Report Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the legacy interactive Report Artifact pipeline with a directly persisted, query-backed Report model rendered by Puck, Ant Design, ECharts, and VTable.

**Architecture:** The backend owns one current `Report` record, validates its five JSON configuration sections, executes saved read-only SQL with bound filter parameters, and projects the two Codex MCP Report tools into persisted Report events. The frontend keeps only transient filter/query state in `ReportContext`; Puck references chart/table/filter IDs, while ECharts and VTable consume query results.

**Tech Stack:** FastAPI, PostgreSQL JSONB, SQLGlot 30.15.0, PyMySQL 1.2.0, Next.js 16, React 19, Puck 0.22, ECharts 5.6, Ant Design 6.5.3, VTable/React-VTable 1.26.6, Vitest, pytest.

## Global Constraints

- Product naming is `Report`; remove Report-domain `Analysis Report`, `Interactive Report`, and `Report Artifact`.
- Persist `layout`, `filters`, `charts`, `tables`, and `queries`; never persist query result rows.
- Store only nullable `turn_id`; derive the source Session from `analysis_turns.session_id`.
- Directly drop legacy Report tables and do not migrate or render legacy Reports.
- Preserve `view` and `view_and_reuse` Report sharing behavior.
- Support multiple charts and tables by ID; components may share a query.
- Puck owns layout, ECharts owns charts, VTable owns tables, and the backend owns data.
- Do not retain AG Grid compatibility.
- Do not implement Excel export, versions, JSON Patch, cache, cancellation, RLS, tenant isolation, complex audit, or user-level query authorization.
- `update_report` and `PUT /api/reports/{id}` replace the complete five-section configuration.
- Preserve non-Report Analysis Session, Turn, Codex Item, and generic analysis-asset behavior.
- Every production behavior change follows RED → GREEN TDD.

---

### Task 1: Establish the direct Report domain contract

**Files:**
- Create: `backend/reports/__init__.py`
- Create: `backend/reports/models.py`
- Create: `backend/reports/schema.py`
- Create: `backend/reports/store.py`
- Create: `backend/tests/test_report_store.py`
- Delete after replacement: `backend/analysis/interactive_report_store.py`
- Delete after replacement: `backend/analysis/report_artifact.py`
- Delete after replacement: `backend/analysis/report_compiler.py`

**Interfaces:**
- Produces: `ReportRecord`, `ReportShareRecord`, `ReportStore`, `validate_report_config(report)`, `report_to_payload(record, source_session_id=None)`.
- `ReportStore.create_report(config, *, owner_id, turn_id=None)` generates `report_<uuid>`.
- `ReportStore.update_report(report_id, config, *, owner_id, turn_id=None)` performs full replacement and preserves `id`, `ownerId`, and `createdAt`.
- `ReportStore.update_report(..., turn_id=None)` preserves the existing Turn; an Agent update supplies a non-null current Turn.

- [ ] **Step 1: Write failing direct Report store tests**

```python
def report_config(title: str = "渠道销售") -> dict[str, Any]:
    return {
        "title": title,
        "subtitle": "2026-08",
        "layout": {
            "root": {"props": {}},
            "content": [
                {"type": "ChartBlock", "props": {"id": "chart-block", "chartId": "sales-chart"}},
                {"type": "TableBlock", "props": {"id": "table-block", "tableId": "sales-table"}},
            ],
            "zones": {},
        },
        "filters": {
            "region": {
                "type": "select",
                "label": "区域",
                "defaultValue": "华东",
                "options": [{"label": "华东", "value": "华东"}],
            }
        },
        "queries": {
            "sales-query": {
                "dataSource": "doris",
                "sql": "SELECT region, SUM(amount) AS amount FROM sales WHERE region = :region GROUP BY region",
                "parameters": {"region": {"filterId": "region", "type": "string"}},
                "pagination": False,
            }
        },
        "charts": {"sales-chart": {"queryId": "sales-query", "option": {"series": [{"type": "bar"}]}}},
        "tables": {"sales-table": {"queryId": "sales-query", "options": {"columns": [{"field": "region", "title": "区域"}]}}},
    }


def test_create_and_full_update_keep_one_current_report(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports.json")
    created = store.create_report(report_config(), owner_id="user-1", turn_id="turn-1")
    updated = store.update_report(created.id, report_config("渠道销售修订"), owner_id="user-1", turn_id="turn-2")

    assert updated is not None
    assert updated.id == created.id
    assert updated.createdAt == created.createdAt
    assert updated.turnId == "turn-2"
    assert updated.title == "渠道销售修订"
    assert len(store.list_reports(owner_id="user-1")) == 1


def test_code_created_report_has_no_turn_and_query_rows_are_not_persisted(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports.json")
    created = store.create_report(report_config(), owner_id="seed")

    payload = report_to_payload(created)
    assert payload["turnId"] is None
    assert "datasets" not in payload
    assert "artifactType" not in payload
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_report_store.py -q -p no:cacheprovider
```

Expected: collection fails because `backend.reports.store` does not exist.

- [ ] **Step 3: Implement immutable records, structural validation, and the JSON fallback store**

```python
@dataclass(frozen=True)
class ReportRecord:
    id: str
    title: str
    subtitle: str
    ownerId: str
    turnId: str | None
    layout: dict[str, Any]
    filters: dict[str, Any]
    charts: dict[str, Any]
    tables: dict[str, Any]
    queries: dict[str, Any]
    createdAt: str
    updatedAt: str


def validate_report_config(report: Mapping[str, Any]) -> None:
    require_non_empty_text(report, "title")
    require_non_empty_text(report, "subtitle")
    for key in ("layout", "filters", "charts", "tables", "queries"):
        if not isinstance(report.get(key), dict):
            raise ReportValidationError(key, f"{key} must be an object")
    validate_filter_types(report["filters"], {"select", "multiSelect", "date", "dateRange"})
    validate_query_references(report)
    validate_layout_references(report)
```

The validator must reject missing Chart/Table/Filter/Query references and invalid SQL/parameter definitions; it must not add legacy fields or default datasets.

- [ ] **Step 4: Run store tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_report_store.py -q -p no:cacheprovider
```

Expected: all tests pass.

- [ ] **Step 5: Commit the direct Report domain**

```powershell
git add backend/reports backend/tests/test_report_store.py
git commit -m "feat: add direct report domain"
```

---

### Task 2: Replace PostgreSQL legacy Report tables

**Files:**
- Modify: `backend/persistence/postgres_stores.py`
- Modify: `backend/tests/test_postgres_p0_compat.py`
- Create: `backend/tests/test_postgres_report_store.py`

**Interfaces:**
- Produces: `build_postgres_report_store() -> PostgresReportStore`.
- `reports.turn_id` references `analysis_turns(id) ON DELETE SET NULL`.
- `report_shares.report_id` references `reports(id) ON DELETE CASCADE`.
- The store returns only `turnId`; the API layer derives `sourceSessionId` through the existing Codex projection store.

- [ ] **Step 1: Write failing PostgreSQL schema and persistence tests**

```python
def test_report_schema_drops_legacy_tables_and_creates_direct_tables(fake_connect) -> None:
    PostgresReportStore("postgresql://test")
    sql = "\n".join(fake_connect.statements)

    assert "DROP TABLE IF EXISTS analysis_report_shares" in sql
    assert "DROP TABLE IF EXISTS analysis_report_versions" in sql
    assert "DROP TABLE IF EXISTS analysis_reports" in sql
    assert "CREATE TABLE IF NOT EXISTS reports" in sql
    assert "turn_id TEXT REFERENCES analysis_turns(id) ON DELETE SET NULL" in sql
    assert "CREATE TABLE IF NOT EXISTS report_shares" in sql
    assert "artifact_type" not in direct_report_create_statement(sql)
    assert "datasets" not in direct_report_create_statement(sql)


def test_postgres_update_replaces_config_without_changing_owner_or_created_at(fake_connect) -> None:
    store = PostgresReportStore("postgresql://test")
    store.update_report("report-1", report_config("修订"), owner_id="owner-1", turn_id="turn-2")

    update_sql, params = fake_connect.last_statement
    assert "owner_id =" not in update_sql.partition("SET")[2].partition("WHERE")[0]
    assert params["turn_id"] == "turn-2"
    assert set(params) >= {"layout", "filters", "charts", "tables", "queries"}
```

- [ ] **Step 2: Run the PostgreSQL tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_postgres_report_store.py backend/tests/test_postgres_p0_compat.py -q -p no:cacheprovider
```

Expected: failures reference missing `PostgresReportStore`, old table constants, and the old schema.

- [ ] **Step 3: Implement the direct schema and PostgreSQL store**

```sql
DROP TABLE IF EXISTS analysis_report_shares;
DROP TABLE IF EXISTS analysis_report_versions;
DROP TABLE IF EXISTS analysis_reports;

CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  subtitle TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  turn_id TEXT REFERENCES analysis_turns(id) ON DELETE SET NULL,
  layout JSONB NOT NULL DEFAULT '{}'::jsonb,
  filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  charts JSONB NOT NULL DEFAULT '{}'::jsonb,
  tables JSONB NOT NULL DEFAULT '{}'::jsonb,
  queries JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS report_shares (
  report_id TEXT NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  recipient_user_id TEXT NOT NULL,
  permission TEXT NOT NULL CHECK (permission IN ('view', 'view_and_reuse')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (report_id, recipient_user_id)
);
```

Implement create/update/list/get/delete/share/revoke/report-center using the Task 1 records. Physical deletion is used for direct Reports; share rows are removed by the FK cascade.

- [ ] **Step 4: Run PostgreSQL tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_postgres_report_store.py backend/tests/test_postgres_p0_compat.py -q -p no:cacheprovider
```

Expected: all tests pass.

- [ ] **Step 5: Commit the database cutover**

```powershell
git add backend/persistence/postgres_stores.py backend/tests/test_postgres_report_store.py backend/tests/test_postgres_p0_compat.py
git commit -m "feat: replace legacy report tables"
```

---

### Task 3: Add read-only Report query execution

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/reports/query_service.py`
- Create: `backend/tests/test_report_query_service.py`

**Interfaces:**
- Produces: `validate_readonly_sql(sql)`, `bind_query_parameters(query, filters)`, `ReportQueryService.execute(report, query_id, filters, page, page_size)`.
- `ReportQueryService` receives a `QueryRunner` protocol so tests use a real deterministic fake instead of a live external database.
- The production runner resolves only `doris` and `mysql` to the existing `GENBI_DB_*`/`DATABASE_URL` configuration and returns dict rows.

- [ ] **Step 1: Write failing SQL safety, binding, and pagination tests**

```python
@pytest.mark.parametrize("sql", [
    "DELETE FROM sales",
    "SELECT * FROM sales; DROP TABLE sales",
    "WITH changed AS (UPDATE sales SET amount = 0 RETURNING *) SELECT * FROM changed",
])
def test_readonly_validator_rejects_write_or_multiple_statements(sql: str) -> None:
    with pytest.raises(UnsafeReportQuery):
        validate_readonly_sql(sql)


def test_parameter_binding_expands_multi_select_without_string_interpolation() -> None:
    query = {
        "sql": "SELECT region FROM sales WHERE region IN (:regions) AND sale_date >= :startDate",
        "parameters": {
            "regions": {"filterId": "regions", "type": "string[]"},
            "startDate": {"filterId": "dateRange", "valueIndex": 0, "type": "date"},
        },
    }
    sql, params = bind_query_parameters(
        query,
        {"regions": ["华东", "华南"], "dateRange": ["2026-08-01", "2026-08-31"]},
    )

    assert "IN (%(regions_0)s, %(regions_1)s)" in sql
    assert params == {"regions_0": "华东", "regions_1": "华南", "startDate": "2026-08-01"}


def test_paginated_query_returns_rows_columns_and_total() -> None:
    result = ReportQueryService(FakeQueryRunner(total=12)).execute(
        report_record,
        "detail",
        filters={"region": "华东"},
        page=2,
        page_size=5,
    )
    assert result == {
        "columns": [{"field": "region", "label": "region", "type": "string"}],
        "rows": [{"region": "华东"}],
        "page": 2,
        "pageSize": 5,
        "total": 12,
    }
```

- [ ] **Step 2: Run query-service tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_report_query_service.py -q -p no:cacheprovider
```

Expected: collection fails because `backend.reports.query_service` does not exist.

- [ ] **Step 3: Add pinned dependencies and implement the query service**

```text
PyMySQL==1.2.0
sqlglot==30.15.0
```

Use `sqlglot.parse(sql, read="mysql")`; require exactly one root query and reject every `Insert`, `Update`, `Delete`, `Create`, `Drop`, `Alter`, `Command`, `Merge`, `Grant`, and `Transaction` node. Replace named placeholders with PyMySQL mapping placeholders and pass a separate params dict to `cursor.execute`.

For a paginated query execute:

```sql
SELECT COUNT(*) AS total FROM (<validated bound query>) AS genbi_count
SELECT * FROM (<validated bound query>) AS genbi_page LIMIT %(genbi_limit)s OFFSET %(genbi_offset)s
```

For a non-paginated query cap rows at `GENBI_DB_MAX_ROWS` (default `1000`) without modifying persisted SQL.

- [ ] **Step 4: Run query-service tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_report_query_service.py -q -p no:cacheprovider
```

Expected: all tests pass, including write/multi-statement rejection.

- [ ] **Step 5: Commit the data execution slice**

```powershell
git add backend/requirements.txt backend/reports/query_service.py backend/tests/test_report_query_service.py
git commit -m "feat: execute bound report queries"
```

---

### Task 4: Expose direct Report HTTP APIs

**Files:**
- Modify: `backend/api/analysis_api.py`
- Create: `backend/tests/test_report_api.py`
- Delete after replacement: `backend/tests/test_interactive_report_api.py`

**Interfaces:**
- Produces:
  - `POST /api/reports`
  - `GET /api/reports`
  - `GET /api/reports/{report_id}`
  - `PUT /api/reports/{report_id}`
  - `DELETE /api/reports/{report_id}`
  - `POST /api/reports/{report_id}/shares`
  - `DELETE /api/reports/{report_id}/shares/{recipient_user_id}`
  - `GET /api/report-center`
  - `POST /api/reports/{report_id}/queries/{query_id}`
- Removes every `/api/analysis/reports*` and `/api/analysis/report-center` route.
- API responses may include derived `sourceSessionId` for “回到会话”; the field comes from the Turn relation and is never stored.

- [ ] **Step 1: Write failing HTTP contract tests**

```python
def test_report_crud_uses_direct_paths_and_full_put(client: TestClient) -> None:
    created = client.post("/api/reports", json={"ownerId": "user-1", **report_config()})
    report_id = created.json()["report"]["id"]
    updated = client.put(
        f"/api/reports/{report_id}",
        json={"ownerId": "user-1", **report_config("修订")},
    )

    assert created.status_code == 201
    assert updated.status_code == 200
    assert updated.json()["report"]["title"] == "修订"
    assert client.get("/api/analysis/reports").status_code == 404


def test_query_endpoint_loads_saved_sql_instead_of_accepting_client_sql(client: TestClient) -> None:
    response = client.post(
        "/api/reports/report-1/queries/sales-query",
        json={"filters": {"region": "华东"}, "page": 1, "pageSize": 50, "sql": "DELETE FROM sales"},
    )
    assert response.status_code == 422
```

The Pydantic request model uses `extra="forbid"`, so client-supplied SQL fails before execution.

- [ ] **Step 2: Run API tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_report_api.py -q -p no:cacheprovider
```

Expected: the direct routes return `404`.

- [ ] **Step 3: Implement direct request models, routes, status mapping, and Turn-derived navigation**

```python
class ReportConfigBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ownerId: str = Field(default="local-user", min_length=1)
    title: str = Field(min_length=1)
    subtitle: str = Field(min_length=1)
    layout: dict[str, Any]
    filters: dict[str, Any]
    charts: dict[str, Any]
    tables: dict[str, Any]
    queries: dict[str, Any]


class ReportQueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: dict[str, Any] = Field(default_factory=dict)
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=50, ge=1, le=500)
```

Map structural/SQL validation to `422`, filter binding errors to `400`, missing Report/Query to `404`, and execution failures to a generic `500 report_query_failed`.

Add `CodexProjectionStore.get_turn_by_id(turn_id)` and use it only to derive `sourceSessionId`.

- [ ] **Step 4: Run Report API plus Analysis API regressions and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_report_api.py backend/tests/test_analysis_api.py -q -p no:cacheprovider
```

Expected: all tests pass with no legacy Report route expectations.

- [ ] **Step 5: Commit the direct HTTP contract**

```powershell
git add backend/api/analysis_api.py backend/harness/codex_projection_store.py backend/tests/test_report_api.py backend/tests/test_analysis_api.py
git commit -m "feat: expose direct report APIs"
```

---

### Task 5: Replace Report Artifact MCP projection with Report tools

**Files:**
- Modify: `backend/mcp_servers/genbi_report_server.py`
- Modify: `backend/harness/codex_mcp_config.py`
- Modify: `backend/harness/codex_sdk_runner.py`
- Create: `backend/services/report_projector.py`
- Modify: `backend/services/codex_turn_runner.py`
- Modify: `backend/services/session_service.py`
- Modify: `backend/tests/test_genbi_report_mcp_server.py`
- Modify: `backend/tests/test_codex_mcp_config.py`
- Modify: `backend/tests/test_codex_sdk_runner.py`
- Modify: `backend/tests/test_analysis_api.py`
- Delete after replacement: `backend/services/artifact_projector.py`

**Interfaces:**
- MCP tools are exactly `create_report(report)` and `update_report(report_id, report)`.
- MCP output is `{"ok": true, "action": "create|update", "reportId": "...", "report": {...}}`.
- `ReportProjector.project_report(event, session_id, turn_id, owner_id)` persists via the shared Report store.
- Events are `genbi/report/created`, `genbi/report/updated`, and `genbi/report/failed`.
- Initial referenced context is named `initial_report`, not `initial_report_artifact`.

- [ ] **Step 1: Replace MCP and projection tests with failing direct-contract tests**

```python
def test_lists_only_create_and_update_report_tools() -> None:
    response = _handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [tool["name"] for tool in response["result"]["tools"]] == ["create_report", "update_report"]


def test_create_report_returns_validated_direct_report_without_owner_or_turn_input() -> None:
    response = call_tool("create_report", {"report": report_config()})
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["ok"] is True
    assert payload["action"] == "create"
    assert payload["reportId"].startswith("report_")
    assert "artifactType" not in payload["report"]
    assert "datasets" not in payload["report"]


def test_projector_derives_owner_and_turn_and_emits_report_created(tmp_path: Path) -> None:
    event = completed_mcp_event("create_report", valid_create_result)
    projected = ReportProjector(ReportStore(tmp_path / "reports.json")).project_report(
        event,
        session_id="session-1",
        turn_id="turn-1",
        owner_id="user-1",
    )
    assert projected.type == "genbi/report/created"
    assert projected.payload["turnId"] == "turn-1"
```

- [ ] **Step 2: Run MCP/projector tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_genbi_report_mcp_server.py backend/tests/test_codex_mcp_config.py backend/tests/test_analysis_api.py -q -p no:cacheprovider
```

Expected: tool names and event types still expose the old interactive Artifact contract.

- [ ] **Step 3: Implement direct tools and Report projection**

```python
CREATE_TOOL_NAME = "create_report"
UPDATE_TOOL_NAME = "update_report"

def _create_report(message: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    report = require_valid_report(arguments.get("report"))
    report_id = f"report_{uuid4().hex}"
    return tool_result(message, {"ok": True, "action": "create", "reportId": report_id, "report": report})

def _update_report(message: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    report_id = require_text(arguments, "report_id")
    report = require_valid_report(arguments.get("report"))
    return tool_result(message, {"ok": True, "action": "update", "reportId": report_id, "report": report})
```

Pass `request.user_id` to `ReportProjector`; if it is empty, use the registered Session user and finally `local-user`. The model never supplies `ownerId` or `turnId`.

Update Codex instructions to tell the Agent to save SQL plus parameter bindings, never inline result rows, and to call `create_report` or `update_report`.

- [ ] **Step 4: Run MCP, runner, and API regressions and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_genbi_report_mcp_server.py backend/tests/test_codex_mcp_config.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py -q -p no:cacheprovider
```

Expected: all tests pass and Report events contain no old Artifact fields.

- [ ] **Step 5: Commit the Agent/MCP cutover**

```powershell
git add backend/mcp_servers/genbi_report_server.py backend/harness backend/services backend/tests
git commit -m "feat: add codex report tools"
```

---

### Task 6: Replace frontend Report types and API client

**Files:**
- Create: `frontend/src/modules/analysis/types/report.ts`
- Create: `frontend/src/modules/analysis/api/report-service.ts`
- Create: `frontend/tests/fixtures/report.ts`
- Create: `frontend/tests/report-api-client.test.ts`
- Delete after replacement: `frontend/src/modules/analysis/types/interactive-report.ts`
- Delete after replacement: `frontend/src/modules/analysis/api/interactive-report-service.ts`
- Delete after replacement: `frontend/tests/fixtures/interactive-report.ts`
- Delete after replacement: `frontend/tests/interactive-report-api-client.test.ts`

**Interfaces:**
- Produces: `Report`, `ReportFilterDefinition`, `ReportQuery`, `ReportChart`, `ReportTable`, `SavedReport`, `SharedReport`.
- Produces client functions `createReport`, `updateReport`, `getReport`, `listReportsBySession`, `listReportCenter`, `deleteReport`, `shareReport`, `executeReportQuery`.
- No type contains `artifactType`, `renderer`, `schemaVersion`, `document`, `chartSpecs`, `gridSpecs`, or `datasets`.

- [ ] **Step 1: Write failing frontend contract tests**

```typescript
test("updates the complete direct Report through PUT", async () => {
  const saved = await updateReport(reportFixture.id, reportFixture, "owner-1");
  expect(fetchMock.mock.calls[0][0]).toBe(
    `http://192.168.101.12:8000/api/reports/${reportFixture.id}`,
  );
  expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
  const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
  expect(Object.keys(body).sort()).toEqual(
    ["charts", "filters", "layout", "ownerId", "queries", "subtitle", "tables", "title"].sort(),
  );
  expect(saved.report.turnId).toBe("turn-1");
});


test("executes a saved query without sending SQL", async () => {
  await executeReportQuery("report-1", "sales-query", {
    filters: { region: "华东" },
    page: 1,
    pageSize: 50,
  });
  const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
  expect(body.sql).toBeUndefined();
});
```

- [ ] **Step 2: Run API-client tests and verify RED**

Run:

```powershell
npm.cmd test -- report-api-client.test.ts
```

Expected: the new module cannot be imported.

- [ ] **Step 3: Implement direct TypeScript types and client**

```typescript
export type Report = {
  id: string;
  title: string;
  subtitle: string;
  ownerId: string;
  turnId: string | null;
  sourceSessionId?: string | null;
  layout: Data;
  filters: Record<string, ReportFilterDefinition>;
  charts: Record<string, ReportChart>;
  tables: Record<string, ReportTable>;
  queries: Record<string, ReportQuery>;
  createdAt?: string;
  updatedAt?: string;
};

export type ReportQueryResult = {
  columns: Array<{ field: string; label: string; type: string }>;
  rows: Array<Record<string, unknown>>;
  page: number;
  pageSize: number;
  total: number;
};
```

Use only `/api/reports` and `/api/report-center`. Strip server-managed fields before POST/PUT.

- [ ] **Step 4: Run API-client tests and verify GREEN**

Run:

```powershell
npm.cmd test -- report-api-client.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit the frontend contract**

```powershell
git add frontend/src/modules/analysis/types frontend/src/modules/analysis/api frontend/tests/fixtures frontend/tests/report-api-client.test.ts
git commit -m "feat: adopt direct report client contract"
```

---

### Task 7: Implement ReportContext and the Puck/ECharts/VTable/Ant renderer

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/src/app/layout.tsx`
- Create: `frontend/src/modules/analysis/components/ReportContext.tsx`
- Create: `frontend/src/modules/analysis/components/ReportTable.tsx`
- Create: `frontend/src/modules/analysis/components/ReportPanel.tsx`
- Modify: `frontend/src/app/globals.css`
- Create: `frontend/tests/report-context.test.tsx`
- Create: `frontend/tests/report-renderer.test.tsx`
- Delete after replacement: `frontend/src/modules/analysis/components/InteractiveReportPanel.tsx`
- Delete/update after replacement: old `frontend/tests/interactive-report-*.test.tsx`

**Interfaces:**
- `ReportProvider` exposes `filterValues`, `queryStates`, `setFilterValue`, and `executeQuery`.
- `FilterBlock` references `filterIds`.
- `ChartBlock` references `chartId`, looks up `queryId`, and injects rows into `option.dataset.source`.
- `TableBlock` references `tableId`, looks up `queryId`, and injects rows into VTable `records`.

- [ ] **Step 1: Install only the approved renderer dependencies**

Run:

```powershell
npm.cmd install antd@6.5.3 dayjs@1.11.21 @visactor/vtable@1.26.6 @visactor/react-vtable@1.26.6
npm.cmd uninstall ag-grid-community ag-grid-react
```

Expected: `package.json` and lockfile contain Ant Design/VTable and no AG Grid packages.

- [ ] **Step 2: Write failing ReportContext behavior tests**

```typescript
test("loads every layout-referenced query and refetches only queries bound to a changed filter", async () => {
  render(
    <ReportProvider report={reportFixture}>
      <ContextProbe />
    </ReportProvider>,
  );
  await screen.findByText("sales-query:ready");
  await screen.findByText("detail-query:ready");

  fireEvent.click(screen.getByRole("button", { name: "change region" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));

  const refetched = fetchMock.mock.calls.slice(2).map(([url]) => String(url));
  expect(refetched).toContain(expect.stringContaining("/queries/sales-query"));
  expect(refetched).toContain(expect.stringContaining("/queries/detail-query"));
  expect(screen.queryByText("unrelated-query:ready")).toBeNull();
});


test("one failed query does not remove another query result", async () => {
  render(<ReportProvider report={reportFixture}><ContextProbe /></ReportProvider>);
  await screen.findByText("sales-query:1");
  await screen.findByText("detail-query:error");
  expect(screen.getByText("sales-query:1")).toBeTruthy();
});
```

- [ ] **Step 3: Run ReportContext tests and verify RED**

Run:

```powershell
npm.cmd test -- report-context.test.tsx
```

Expected: `ReportContext` cannot be imported.

- [ ] **Step 4: Implement the minimal ReportContext**

```typescript
type QueryState = {
  columns: ReportQueryResult["columns"];
  rows: ReportQueryResult["rows"];
  total: number;
  page: number;
  pageSize: number;
  loading: boolean;
  error: string | null;
};

type ReportRuntimeContext = {
  report: Report;
  filterValues: Record<string, ReportFilterValue>;
  queryStates: Record<string, QueryState>;
  setFilterValue(filterId: string, value: ReportFilterValue): void;
  executeQuery(queryId: string, page?: number, pageSize?: number): Promise<void>;
};
```

Initialize defaults, traverse Puck content/zones to collect referenced chart/table query IDs, fetch them once, and refetch only queries whose `parameters.*.filterId` matches the changed filter. Do not add caching, cancellation, debouncing, or linkage rules.

- [ ] **Step 5: Write failing renderer tests**

```typescript
test("renders multiple charts and tables from ID references", async () => {
  render(<ReportPanel taskTitle="销售" running={false} initialReport={multiComponentReport} />);
  expect(await screen.findAllByTestId("report-chart")).toHaveLength(2);
  expect(await screen.findAllByTestId("report-table")).toHaveLength(2);
});


test("injects rows into native ECharts dataset and VTable records", () => {
  expect(buildEChartsOption({ series: [] }, [{ region: "华东", amount: 1 }])).toEqual({
    dataset: { source: [{ region: "华东", amount: 1 }] },
    series: [],
  });
  expect(buildVTableOption(
    { columns: [{ field: "region", title: "区域" }] },
    [{ region: "华东" }],
  ).records).toEqual([{ region: "华东" }]);
});
```

- [ ] **Step 6: Run renderer tests and verify RED**

Run:

```powershell
npm.cmd test -- report-renderer.test.tsx
```

Expected: the new `ReportPanel`/helpers do not exist.

- [ ] **Step 7: Implement Ant filters, native ECharts options, VTable, and Puck references**

Use:

```typescript
import { DatePicker, Select } from "antd";
import ReactECharts from "echarts-for-react";
import { ListTable } from "@visactor/react-vtable";

const chartOption = {
  ...chart.option,
  dataset: { ...(asObject(chart.option.dataset)), source: queryState.rows },
};

const tableOption = {
  ...table.options,
  records: queryState.rows,
};
```

Render `select`, `multiSelect`, `date`, and `dateRange` only. Render loading/error/retry per query. Server pagination changes only the Table query page. Remove the mock Excel export action.

- [ ] **Step 8: Run Report runtime tests and verify GREEN**

Run:

```powershell
npm.cmd test -- report-context.test.tsx report-renderer.test.tsx
npx.cmd tsc --noEmit --incremental false
```

Expected: tests and typecheck pass.

- [ ] **Step 9: Commit the Report runtime**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/src/app frontend/src/modules/analysis/components frontend/tests
git commit -m "feat: render query-backed reports"
```

---

### Task 8: Rewire workspace events, report center, and new-session context

**Files:**
- Modify: `frontend/src/modules/analysis/agentClients/backendClient.ts`
- Modify: `frontend/src/modules/analysis/agentClients/types.ts`
- Modify: `frontend/src/modules/analysis/hooks/use-flow.ts`
- Modify: `frontend/src/modules/analysis/components/AnalysisWorkspace.tsx`
- Modify: `frontend/src/modules/analysis/components/MyAnalysisPage.tsx`
- Modify: `frontend/tests/analysis-backend-client.test.ts`
- Modify: `frontend/tests/analysis-deep-link-route.test.ts`
- Modify: `frontend/tests/analysis-task-copy.test.ts`
- Modify: `frontend/tests/report-center-card-actions.test.tsx`
- Modify: `frontend/tests/report-draft-session.test.tsx`

**Interfaces:**
- Agent frontend event is `{type: "report"; report: Report}`.
- Backend events accepted are `genbi/report/created` and `genbi/report/updated`.
- Session metadata/context key is `initial_report`.
- A Report with derived `sourceSessionId` shows “回到会话” and “新建会话”.
- A Report without it shows only “新建会话”.
- “新建会话” opens `/analysis/new` with the Report as draft context and does not provision a Session until the first message.

- [ ] **Step 1: Write failing event and action tests**

```typescript
test("maps direct Report events without Artifact fields", async () => {
  const events = await collect(mapBackendEvents([
    backendEvent("genbi/report/created", reportFixture),
  ]));
  expect(events[0]).toEqual(expect.objectContaining({ type: "report", report: reportFixture }));
});


test("source report exposes return and new-session actions", () => {
  renderReportCard({ ...savedReport, report: { ...savedReport.report, sourceSessionId: "session-1" } });
  expect(screen.getByRole("button", { name: "回到会话" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "新建会话" })).toBeTruthy();
});


test("draft Report creates no Session before the first question", async () => {
  fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
  expect(window.location.pathname).toBe("/analysis/new");
  expect(createSessionMock).not.toHaveBeenCalled();
  fireEvent.submit(screen.getByRole("textbox"), { target: { value: "分析异常区域" } });
  expect(startTurnBody.metadata.source_report_id).toBe(reportFixture.id);
});
```

- [ ] **Step 2: Run workspace/event tests and verify RED**

Run:

```powershell
npm.cmd test -- analysis-backend-client.test.ts report-center-card-actions.test.tsx report-draft-session.test.tsx
```

Expected: frontend still listens for `genbi/artifact/updated` and legacy source fields.

- [ ] **Step 3: Rewire event parsing and workspace navigation**

Replace `reportArtifact` state with `report`, remove Artifact validation, use `turnId` and derived `sourceSessionId`, and keep `source_report_id` as the first-turn reference pointer.

When the backend expands a referenced Report into Codex context, store and send:

```json
{
  "source_report_id": "report_123",
  "initial_report": {
    "id": "report_123",
    "title": "渠道销售",
    "layout": {},
    "filters": {},
    "charts": {},
    "tables": {},
    "queries": {}
  }
}
```

- [ ] **Step 4: Run workspace/event tests and verify GREEN**

Run:

```powershell
npm.cmd test -- analysis-backend-client.test.ts analysis-deep-link-route.test.ts analysis-task-copy.test.ts report-center-card-actions.test.tsx report-draft-session.test.tsx
```

Expected: all tests pass and session creation remains deferred until the first message.

- [ ] **Step 5: Commit workspace integration**

```powershell
git add frontend/src/modules/analysis frontend/tests
git commit -m "feat: integrate reports with codex sessions"
```

---

### Task 9: Remove legacy Report concepts and update durable documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/product/product-scope.md`
- Modify: `docs/architecture/overview.md`
- Modify: `docs/superpowers/specs/2026-08-05-report-architecture-design.md`
- Modify: `docs/plans/current.md`
- Remove/rename remaining Report-domain files and tests reported by the scans below.

**Interfaces:**
- Durable docs describe the direct Report model and current branch truth.
- Generic Artifact/analysis-asset concepts outside Report stay unchanged.

- [ ] **Step 1: Scan for forbidden Report-domain legacy names**

Run:

```powershell
rg -n "InteractiveReport|interactive_report|ReportArtifact|analysis_reports|analysis_report_shares|chartSpecs|gridSpecs|reportArtifact|report-artifact|genbi/artifact/(created|updated|failed)|AgGrid|ag-grid" backend frontend README.md docs/product/product-scope.md docs/architecture/overview.md
```

Expected before cleanup: matches identify remaining legacy Report code/tests/docs.

- [ ] **Step 2: Remove only Report-domain legacy references**

Update the durable docs to state:

```text
Report：当前报表配置，直接保存 layout / filters / charts / tables / queries。
Report 与 Codex Turn：reports.turn_id 指向最后一次由 Agent 生成或修改当前内容的 Turn。
Report 查询结果：只存在于浏览器 ReportContext，不写入 reports。
```

Clarify in the design that `sourceSessionId` is a derived API field for navigation, not a database column. Update `docs/plans/current.md` with this branch, verified commands, known risks, and 1–3 next steps.

- [ ] **Step 3: Re-run the legacy-name scan**

Run the Step 1 command again.

Expected: no Report-domain matches; matches for generic analysis assets or FineReport names are allowed only when they do not represent the removed Report implementation.

- [ ] **Step 4: Run focused backend and frontend suites**

Run:

```powershell
python -m pytest backend/tests/test_report_store.py backend/tests/test_postgres_report_store.py backend/tests/test_report_query_service.py backend/tests/test_report_api.py backend/tests/test_genbi_report_mcp_server.py backend/tests/test_analysis_api.py -q -p no:cacheprovider
npm.cmd test -- report-api-client.test.ts report-context.test.tsx report-renderer.test.tsx report-center-card-actions.test.tsx report-draft-session.test.tsx analysis-backend-client.test.ts
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit cleanup and docs**

```powershell
git add README.md docs backend frontend
git commit -m "docs: align product with direct reports"
```

---

### Task 10: Run completion gates and deploy the changed services locally

**Files:**
- Modify only if a verification failure proves a required fix.

**Interfaces:**
- Proves the entire approved Report design against tests, build, Compose, schema, and live HTTP/UI behavior.

- [ ] **Step 1: Run the complete backend suite**

Run:

```powershell
python -m pytest backend/tests -q -p no:cacheprovider
```

Expected: zero failures.

- [ ] **Step 2: Run the complete frontend suite and typecheck**

Run:

```powershell
npm.cmd test
npx.cmd tsc --noEmit --incremental false
npm.cmd run build
```

Expected: zero test failures, zero TypeScript errors, and a successful Next.js production build.

- [ ] **Step 3: Validate Compose**

Run:

```powershell
docker compose config --quiet
```

Expected: exit code `0`.

- [ ] **Step 4: Check the diff and requirement-by-requirement completion**

Run:

```powershell
git diff --check
git status --short --branch
git log --oneline --decorate -10
```

Expected: no whitespace errors; only intentional Report work remains.

- [ ] **Step 5: Rebuild and recreate backend/frontend containers**

Run:

```powershell
docker compose up -d --build backend frontend
```

Expected: PostgreSQL contains `reports` and `report_shares`, legacy Report tables are absent, and both services are healthy.

- [ ] **Step 6: Run live HTTP and browser smoke tests**

Verify:

```text
GET /health returns 200.
POST /api/reports creates a turn-less code Report.
GET /api/report-center returns it under “我的报表”.
The Report page renders at least two charts and two tables from one JSON.
Changing a filter issues backend query requests and updates only bound components.
A Report with a source Session shows “回到会话” and “新建会话”.
A Report without a source Session shows only “新建会话”.
“新建会话” stays on /analysis/new until the first question, then the new Codex Session contains initial_report context.
```

- [ ] **Step 7: Update the final current-branch snapshot and commit**

```powershell
git add docs/plans/current.md
git commit -m "docs: record report architecture verification"
```
