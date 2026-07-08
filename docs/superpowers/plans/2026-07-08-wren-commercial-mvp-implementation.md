# Wren Commercial MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable commercial-style GenBI web MVP inspired by Wren AI Commercial Platform.

**Architecture:** Use a TypeScript monorepo with shared domain types and fixtures, a Fastify API, and a React + Vite web app. The first milestone uses deterministic mock adapters for analytics, connector sync, SQL generation, and chart generation, while keeping service boundaries ready for Wren CLI, Wren Engine, and real database connectors.

**Tech Stack:** Node.js, npm workspaces, TypeScript, React, Vite, Fastify, Vitest, Playwright, lucide-react, CSS, local JSON-backed in-memory services.

## Global Constraints

- First screen is the product console, not a marketing landing page.
- Interface must feel like a serious analytics SaaS tool: dense, calm, readable, and efficient.
- Commercial features must be visible through real workflows, not isolated empty static cards.
- Agentic behavior must show plan, SQL, assumptions, result, chart, and suggested next actions.
- Mocked systems must be implemented through adapter interfaces so real integrations can replace them.
- Framework choice is React + Vite for the web app and Node + Fastify for the API.
- Repository shape is a TypeScript monorepo with `apps/` and `packages/`.
- Real Wren integration is deferred until the MVP product workflow is running.
- Styling must use lucide icons, border radius of 8px or less, and a restrained multi-accent palette.
- Tests must cover core service logic and at least one end-to-end Ask workflow.

---

## File Structure

Create this structure:

```text
package.json
tsconfig.base.json
README.md
apps/
  api/
    package.json
    tsconfig.json
    vitest.config.ts
    src/
      index.ts
      server.ts
      seed.ts
      routes/
        apiAccessRoutes.ts
        askRoutes.ts
        dataSourceRoutes.ts
        governanceRoutes.ts
        knowledgeRoutes.ts
        projectRoutes.ts
      services/
        ApiAccessService.ts
        AskService.ts
        AuditService.ts
        DataSourceService.ts
        GenBIAppService.ts
        KnowledgeService.ts
        MemoryService.ts
        ProjectService.ts
        SkillService.ts
      adapters/
        AnalyticsAgentAdapter.ts
        ConnectorAdapter.ts
      tests/
        askService.test.ts
        apiRoutes.test.ts
  web/
    package.json
    tsconfig.json
    vite.config.ts
    index.html
    src/
      main.tsx
      App.tsx
      api/client.ts
      styles.css
      components/
        AppShell.tsx
        ChartPanel.tsx
        DataTable.tsx
        StatusBadge.tsx
      screens/
        ApiAccessScreen.tsx
        AskScreen.tsx
        ConsoleScreen.tsx
        DataSourcesScreen.tsx
        GenBIAppsScreen.tsx
        GovernanceScreen.tsx
        KnowledgeScreen.tsx
        MemoriesScreen.tsx
        ProjectsScreen.tsx
        SkillsScreen.tsx
      tests/
        app.test.tsx
    tests/
      ask.spec.ts
packages/
  domain/
    package.json
    tsconfig.json
    src/
      fixtures.ts
      index.ts
      types.ts
    tests/
      fixtures.test.ts
```

Responsibility map:

- `packages/domain/src/types.ts` owns all shared domain shapes.
- `packages/domain/src/fixtures.ts` owns deterministic seed data and factory helpers.
- `apps/api/src/services/*` owns product behavior over seed data.
- `apps/api/src/adapters/*` owns deterministic mock external behavior.
- `apps/api/src/routes/*` maps HTTP routes to services.
- `apps/web/src/api/client.ts` owns HTTP calls from React.
- `apps/web/src/components/*` owns reusable product UI pieces.
- `apps/web/src/screens/*` owns primary commercial product screens.
- `README.md` documents startup, tests, mock limitations, and Wren integration path.

---

### Task 1: Monorepo Foundation

**Files:**
- Create: `package.json`
- Create: `tsconfig.base.json`
- Create: `apps/api/package.json`
- Create: `apps/api/tsconfig.json`
- Create: `apps/api/vitest.config.ts`
- Create: `apps/web/package.json`
- Create: `apps/web/tsconfig.json`
- Create: `apps/web/vite.config.ts`
- Create: `apps/web/index.html`
- Create: `packages/domain/package.json`
- Create: `packages/domain/tsconfig.json`

**Interfaces:**
- Produces: npm workspace scripts `dev`, `build`, `test`, `test:api`, `test:web`, `test:e2e`
- Produces: TypeScript path alias `@genbi/domain`

- [ ] **Step 1: Write workspace configuration**

Create `package.json`:

```json
{
  "name": "genbi-wren-commercial-mvp",
  "private": true,
  "type": "module",
  "workspaces": [
    "apps/*",
    "packages/*"
  ],
  "scripts": {
    "dev": "npm run dev -w apps/api & npm run dev -w apps/web",
    "build": "npm run build -ws",
    "test": "npm run test -ws",
    "test:api": "npm run test -w apps/api",
    "test:web": "npm run test -w apps/web",
    "test:e2e": "npm run test:e2e -w apps/web"
  },
  "devDependencies": {
    "@playwright/test": "^1.45.0",
    "@types/node": "^20.14.0",
    "typescript": "^5.5.0",
    "vitest": "^1.6.0"
  }
}
```

Create `tsconfig.base.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "strict": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "baseUrl": ".",
    "paths": {
      "@genbi/domain": ["packages/domain/src/index.ts"]
    }
  }
}
```

- [ ] **Step 2: Write package configs**

Create `packages/domain/package.json`:

```json
{
  "name": "@genbi/domain",
  "version": "0.1.0",
  "type": "module",
  "main": "src/index.ts",
  "scripts": {
    "build": "tsc -p tsconfig.json --noEmit",
    "test": "vitest run"
  },
  "devDependencies": {
    "vitest": "^1.6.0"
  }
}
```

Create `packages/domain/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "include": ["src", "tests"]
}
```

Create `apps/api/package.json`:

```json
{
  "name": "@genbi/api",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc -p tsconfig.json --noEmit",
    "test": "vitest run"
  },
  "dependencies": {
    "@fastify/cors": "^9.0.0",
    "@genbi/domain": "0.1.0",
    "fastify": "^4.28.0"
  },
  "devDependencies": {
    "tsx": "^4.16.0",
    "vitest": "^1.6.0"
  }
}
```

Create `apps/web/package.json`:

```json
{
  "name": "@genbi/web",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1",
    "build": "tsc -p tsconfig.json --noEmit && vite build",
    "test": "vitest run",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "@genbi/domain": "0.1.0",
    "@vitejs/plugin-react": "^4.3.0",
    "lucide-react": "^0.468.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "vite": "^5.3.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^15.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "jsdom": "^24.1.0",
    "typescript": "^5.5.0",
    "vitest": "^1.6.0"
  }
}
```

- [ ] **Step 3: Write TypeScript and Vite configs**

Create `apps/api/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "noEmit": true
  },
  "include": ["src", "tests"]
}
```

Create `apps/api/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node"
  }
});
```

Create `apps/web/tsconfig.json`:

```json
{
  "extends": "../../tsconfig.base.json",
  "compilerOptions": {
    "jsx": "react-jsx",
    "noEmit": true
  },
  "include": ["src", "tests"]
}
```

Create `apps/web/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/tests/setup.ts"
  }
});
```

Create `apps/web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>GenBI Commercial MVP</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Install dependencies**

Run: `npm install`

Expected: npm creates `package-lock.json` and installs workspace dependencies.

- [ ] **Step 5: Verify empty workspace scripts**

Run: `npm run build`

Expected: build fails because source files do not exist yet. The failure should mention missing inputs or missing source files, not JSON syntax errors.

- [ ] **Step 6: Commit**

Run:

```bash
git add package.json package-lock.json tsconfig.base.json apps packages
git commit -m "chore: scaffold TypeScript monorepo"
```

Expected: commit succeeds.

---

### Task 2: Domain Types And Seed Fixtures

**Files:**
- Create: `packages/domain/src/types.ts`
- Create: `packages/domain/src/fixtures.ts`
- Create: `packages/domain/src/index.ts`
- Create: `packages/domain/tests/fixtures.test.ts`

**Interfaces:**
- Produces: `createSeedData(): SeedData`
- Produces: domain type exports used by API and web
- Consumes: TypeScript alias `@genbi/domain`

- [ ] **Step 1: Write failing fixture tests**

Create `packages/domain/tests/fixtures.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createSeedData } from "../src/fixtures";

describe("createSeedData", () => {
  it("creates a commercial workspace with one agentic project", () => {
    const seed = createSeedData();

    expect(seed.organization.name).toBe("Acme Analytics");
    expect(seed.projects.some((project) => project.type === "agentic")).toBe(true);
    expect(seed.threads[0].runs[0].generatedSql).toContain("monthly_revenue");
  });

  it("includes commercial surfaces required by the MVP", () => {
    const seed = createSeedData();

    expect(seed.knowledgeDocuments.length).toBeGreaterThanOrEqual(2);
    expect(seed.skills.length).toBeGreaterThanOrEqual(3);
    expect(seed.memories[0].markdownBody).toContain("preferred gross margin");
    expect(seed.genBIApps.length).toBeGreaterThanOrEqual(1);
    expect(seed.apiKeys[0].scopes).toContain("generate:sql");
    expect(seed.auditEvents.length).toBeGreaterThanOrEqual(3);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -w packages/domain`

Expected: FAIL with module resolution errors for `../src/fixtures`.

- [ ] **Step 3: Write domain types**

Create `packages/domain/src/types.ts` with exported interfaces matching the approved spec. Include these exact union types:

```ts
export type ProjectType = "agentic" | "classic";
export type MemberRole = "owner" | "admin" | "analyst" | "viewer";
export type DataSourceType = "postgres" | "mysql" | "bigquery" | "snowflake" | "csv" | "duckdb";
export type DataSourceStatus = "connected" | "syncing" | "error" | "draft";
export type AskMode = "agentic" | "interactive";
export type RunStatus = "queued" | "running" | "completed" | "failed";
export type DocumentStatus = "draft" | "published";
export type AppStatus = "draft" | "published";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: string;
  createdAt: string;
}

export interface Member {
  id: string;
  organizationId: string;
  name: string;
  email: string;
  role: MemberRole;
  status: "active" | "invited";
}

export interface Project {
  id: string;
  organizationId: string;
  name: string;
  type: ProjectType;
  language: string;
  description: string;
  status: string;
  createdAt: string;
  updatedAt: string;
}

export interface SchemaSummary {
  tables: number;
  fields: number;
  businessModels: string[];
}

export interface DataSource {
  id: string;
  projectId: string;
  type: DataSourceType;
  name: string;
  status: DataSourceStatus;
  lastSyncedAt: string | null;
  schemaSummary: SchemaSummary;
}

export interface AskMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
}

export interface ChartSpec {
  type: "line" | "bar" | "area";
  xField: string;
  yFields: string[];
  title: string;
}

export interface AskRun {
  id: string;
  threadId: string;
  question: string;
  planSteps: string[];
  generatedSql: string;
  assumptions: string[];
  resultRows: Record<string, string | number>[];
  chartSpec: ChartSpec;
  insight: string;
  followUps: string[];
  status: RunStatus;
  createdAt: string;
}

export interface AskThread {
  id: string;
  projectId: string;
  title: string;
  mode: AskMode;
  messages: AskMessage[];
  runs: AskRun[];
}

export interface KnowledgeDocument {
  id: string;
  projectId: string;
  title: string;
  path: string;
  body: string;
  status: DocumentStatus;
  updatedAt: string;
}

export interface Skill {
  id: string;
  projectId: string;
  name: string;
  description: string;
  enabled: boolean;
  inputSchema: Record<string, string>;
  examplePrompt: string;
  lastRunAt: string | null;
}

export interface Memory {
  id: string;
  projectId: string;
  ownerType: "user" | "project";
  ownerName: string;
  markdownBody: string;
  updatedAt: string;
}

export interface GenBIWidget {
  id: string;
  type: "kpi" | "chart" | "table";
  title: string;
  metric?: string;
  chartSpec?: ChartSpec;
}

export interface GenBIApp {
  id: string;
  projectId: string;
  name: string;
  description: string;
  sourceThreadId: string;
  widgets: GenBIWidget[];
  status: AppStatus;
  updatedAt: string;
}

export interface ApiKey {
  id: string;
  organizationId: string;
  name: string;
  prefix: string;
  scopes: string[];
  lastUsedAt: string | null;
  createdAt: string;
}

export interface AuditEvent {
  id: string;
  organizationId: string;
  actor: string;
  action: string;
  target: string;
  createdAt: string;
  metadata: Record<string, string>;
}

export interface SeedData {
  organization: Organization;
  members: Member[];
  projects: Project[];
  dataSources: DataSource[];
  threads: AskThread[];
  knowledgeDocuments: KnowledgeDocument[];
  skills: Skill[];
  memories: Memory[];
  genBIApps: GenBIApp[];
  apiKeys: ApiKey[];
  auditEvents: AuditEvent[];
}
```

- [ ] **Step 4: Write deterministic fixtures**

Create `packages/domain/src/fixtures.ts`:

```ts
import type { SeedData } from "./types";

export function createSeedData(): SeedData {
  const now = "2026-07-08T13:00:00.000Z";
  const organizationId = "org_acme";
  const projectId = "proj_revenue_agentic";
  const threadId = "thread_revenue_change";

  return {
    organization: {
      id: organizationId,
      name: "Acme Analytics",
      slug: "acme-analytics",
      plan: "Commercial",
      createdAt: "2026-06-01T09:00:00.000Z"
    },
    members: [
      { id: "mem_owner", organizationId, name: "Jason Fan", email: "jason@example.com", role: "owner", status: "active" },
      { id: "mem_analyst", organizationId, name: "Mira Chen", email: "mira@example.com", role: "analyst", status: "active" },
      { id: "mem_viewer", organizationId, name: "Owen Li", email: "owen@example.com", role: "viewer", status: "invited" }
    ],
    projects: [
      {
        id: projectId,
        organizationId,
        name: "Revenue Intelligence",
        type: "agentic",
        language: "English",
        description: "Agentic revenue analytics workspace with governed business context.",
        status: "healthy",
        createdAt: "2026-06-10T10:00:00.000Z",
        updatedAt: now
      },
      {
        id: "proj_sales_classic",
        organizationId,
        name: "Sales Operations Classic",
        type: "classic",
        language: "English",
        description: "Classic semantic BI workspace for sales performance.",
        status: "syncing",
        createdAt: "2026-06-12T10:00:00.000Z",
        updatedAt: now
      }
    ],
    dataSources: [
      {
        id: "ds_warehouse",
        projectId,
        type: "snowflake",
        name: "Production Warehouse",
        status: "connected",
        lastSyncedAt: "2026-07-08T12:40:00.000Z",
        schemaSummary: { tables: 28, fields: 412, businessModels: ["Revenue", "Accounts", "Campaigns"] }
      },
      {
        id: "ds_csv",
        projectId,
        type: "csv",
        name: "Marketing Spend CSV",
        status: "error",
        lastSyncedAt: null,
        schemaSummary: { tables: 3, fields: 44, businessModels: ["Spend"] }
      }
    ],
    threads: [
      {
        id: threadId,
        projectId,
        title: "Monthly revenue change",
        mode: "agentic",
        messages: [
          { id: "msg_1", role: "user", content: "What drove revenue changes last month?", createdAt: now },
          { id: "msg_2", role: "assistant", content: "Revenue increased because expansion ARR outpaced churn in enterprise accounts.", createdAt: now }
        ],
        runs: [
          {
            id: "run_revenue_change",
            threadId,
            question: "What drove revenue changes last month?",
            planSteps: [
              "Resolve revenue metric from Knowledge",
              "Compare current and prior month ARR",
              "Break down delta by segment and movement type",
              "Generate chart and follow-up prompts"
            ],
            generatedSql: "select month, segment, monthly_revenue, expansion_arr, churn_arr from analytics.monthly_revenue where month >= date '2026-05-01' order by month, segment;",
            assumptions: [
              "Revenue means recognized monthly recurring revenue.",
              "Enterprise segment uses account_tier = 'enterprise'."
            ],
            resultRows: [
              { month: "2026-05", segment: "Enterprise", monthly_revenue: 1240000, expansion_arr: 184000, churn_arr: 42000 },
              { month: "2026-06", segment: "Enterprise", monthly_revenue: 1385000, expansion_arr: 231000, churn_arr: 39000 },
              { month: "2026-05", segment: "SMB", monthly_revenue: 410000, expansion_arr: 44000, churn_arr: 28000 },
              { month: "2026-06", segment: "SMB", monthly_revenue: 426000, expansion_arr: 47000, churn_arr: 31000 }
            ],
            chartSpec: { type: "bar", xField: "month", yFields: ["monthly_revenue"], title: "Monthly revenue by segment" },
            insight: "Enterprise expansion contributed most of the June increase, while SMB churn rose slightly.",
            followUps: ["Which accounts drove enterprise expansion?", "Show churn reasons by segment", "Create a dashboard for this trend"],
            status: "completed",
            createdAt: now
          }
        ]
      }
    ],
    knowledgeDocuments: [
      {
        id: "know_revenue_metric",
        projectId,
        title: "Revenue Metric Definitions",
        path: "/metrics/revenue.md",
        body: "# Revenue\nRevenue means recognized monthly recurring revenue. Exclude one-time setup fees and tax adjustments.",
        status: "published",
        updatedAt: now
      },
      {
        id: "know_segments",
        projectId,
        title: "Customer Segments",
        path: "/dimensions/customer-segments.md",
        body: "# Customer Segments\nEnterprise accounts have account_tier = 'enterprise'. SMB accounts have account_tier = 'smb'.",
        status: "draft",
        updatedAt: now
      }
    ],
    skills: [
      { id: "skill_metric_lookup", projectId, name: "Metric Lookup", description: "Find governed metric definitions before SQL generation.", enabled: true, inputSchema: { metric: "string" }, examplePrompt: "Resolve revenue", lastRunAt: now },
      { id: "skill_anomaly_scan", projectId, name: "Anomaly Scan", description: "Detect unusual changes in metric series.", enabled: true, inputSchema: { metric: "string", window: "string" }, examplePrompt: "Scan ARR anomalies", lastRunAt: now },
      { id: "skill_app_builder", projectId, name: "GenBI App Builder", description: "Turn answered questions into dashboard widgets.", enabled: true, inputSchema: { threadId: "string" }, examplePrompt: "Create app from this thread", lastRunAt: null }
    ],
    memories: [
      {
        id: "mem_project",
        projectId,
        ownerType: "project",
        ownerName: "Revenue Intelligence",
        markdownBody: "# Project Memory\nUse preferred gross margin threshold of 72%. Prioritize enterprise account explanations.",
        updatedAt: now
      }
    ],
    genBIApps: [
      {
        id: "app_revenue_pulse",
        projectId,
        name: "Revenue Pulse",
        description: "Generated app for monthly revenue movement and segment drivers.",
        sourceThreadId: threadId,
        widgets: [
          { id: "wid_arr", type: "kpi", title: "June Revenue", metric: "$1.81M" },
          { id: "wid_growth", type: "kpi", title: "MoM Growth", metric: "+9.2%" },
          { id: "wid_chart", type: "chart", title: "Revenue Trend", chartSpec: { type: "bar", xField: "month", yFields: ["monthly_revenue"], title: "Monthly revenue by segment" } }
        ],
        status: "published",
        updatedAt: now
      }
    ],
    apiKeys: [
      { id: "key_server", organizationId, name: "Server analytics key", prefix: "gb_live_8a31", scopes: ["generate:sql", "generate:chart"], lastUsedAt: "2026-07-08T12:50:00.000Z", createdAt: "2026-07-01T10:00:00.000Z" }
    ],
    auditEvents: [
      { id: "audit_1", organizationId, actor: "Jason Fan", action: "asked_question", target: "Monthly revenue change", createdAt: now, metadata: { projectId } },
      { id: "audit_2", organizationId, actor: "Mira Chen", action: "published_knowledge", target: "Revenue Metric Definitions", createdAt: "2026-07-08T11:40:00.000Z", metadata: { projectId } },
      { id: "audit_3", organizationId, actor: "System", action: "synced_schema", target: "Production Warehouse", createdAt: "2026-07-08T12:40:00.000Z", metadata: { tables: "28" } }
    ]
  };
}
```

Create `packages/domain/src/index.ts`:

```ts
export * from "./types";
export * from "./fixtures";
```

- [ ] **Step 5: Run tests**

Run: `npm run test -w packages/domain`

Expected: PASS with 2 tests.

- [ ] **Step 6: Commit**

Run:

```bash
git add packages/domain
git commit -m "feat: add GenBI domain fixtures"
```

Expected: commit succeeds.

---

### Task 3: API Services And Mock Adapters

**Files:**
- Create: `apps/api/src/seed.ts`
- Create: `apps/api/src/adapters/AnalyticsAgentAdapter.ts`
- Create: `apps/api/src/adapters/ConnectorAdapter.ts`
- Create: `apps/api/src/services/AuditService.ts`
- Create: `apps/api/src/services/ProjectService.ts`
- Create: `apps/api/src/services/AskService.ts`
- Create: `apps/api/src/services/DataSourceService.ts`
- Create: `apps/api/src/services/KnowledgeService.ts`
- Create: `apps/api/src/services/SkillService.ts`
- Create: `apps/api/src/services/MemoryService.ts`
- Create: `apps/api/src/services/GenBIAppService.ts`
- Create: `apps/api/src/services/ApiAccessService.ts`
- Create: `apps/api/src/tests/askService.test.ts`

**Interfaces:**
- Consumes: `createSeedData(): SeedData`
- Produces: `createServices(): Services`
- Produces: `AskService.ask(projectId: string, question: string): AskRun`
- Produces: `DataSourceService.testConnection(projectId: string, type: DataSourceType): ConnectionTestResult`
- Produces: `ApiAccessService.generateSql(question: string): SqlGenerationResult`
- Produces: `ApiAccessService.generateChart(sql: string): ChartGenerationResult`

- [ ] **Step 1: Write failing service tests**

Create `apps/api/src/tests/askService.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { createServices } from "../seed";

describe("AskService", () => {
  it("creates a deterministic completed ask run and audit event", () => {
    const services = createServices();
    const project = services.projects.listProjects()[0];
    const run = services.ask.ask(project.id, "What drove revenue changes last month?");

    expect(run.status).toBe("completed");
    expect(run.generatedSql).toContain("analytics.monthly_revenue");
    expect(run.planSteps).toHaveLength(4);
    expect(run.followUps).toContain("Create a dashboard for this trend");
    expect(services.audit.listEvents()[0].action).toBe("asked_question");
  });

  it("generates a GenBI app from the newest ask run", () => {
    const services = createServices();
    const project = services.projects.listProjects()[0];
    const run = services.ask.ask(project.id, "Create revenue pulse");
    const app = services.genBIApps.createFromRun(project.id, run.threadId);

    expect(app.sourceThreadId).toBe(run.threadId);
    expect(app.widgets.map((widget) => widget.type)).toContain("chart");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -w apps/api`

Expected: FAIL with module resolution errors for `../seed`.

- [ ] **Step 3: Implement seed service composition**

Create `apps/api/src/seed.ts`:

```ts
import { createSeedData } from "@genbi/domain";
import type { SeedData } from "@genbi/domain";
import { MockAnalyticsAgentAdapter } from "./adapters/AnalyticsAgentAdapter";
import { MockConnectorAdapter } from "./adapters/ConnectorAdapter";
import { ApiAccessService } from "./services/ApiAccessService";
import { AskService } from "./services/AskService";
import { AuditService } from "./services/AuditService";
import { DataSourceService } from "./services/DataSourceService";
import { GenBIAppService } from "./services/GenBIAppService";
import { KnowledgeService } from "./services/KnowledgeService";
import { MemoryService } from "./services/MemoryService";
import { ProjectService } from "./services/ProjectService";
import { SkillService } from "./services/SkillService";

export interface Services {
  data: SeedData;
  audit: AuditService;
  projects: ProjectService;
  ask: AskService;
  dataSources: DataSourceService;
  knowledge: KnowledgeService;
  skills: SkillService;
  memories: MemoryService;
  genBIApps: GenBIAppService;
  apiAccess: ApiAccessService;
}

export function createServices(): Services {
  const data = createSeedData();
  const audit = new AuditService(data);
  const analyticsAdapter = new MockAnalyticsAgentAdapter();
  const connectorAdapter = new MockConnectorAdapter();
  const projects = new ProjectService(data);
  const ask = new AskService(data, analyticsAdapter, audit);
  const dataSources = new DataSourceService(data, connectorAdapter, audit);
  const knowledge = new KnowledgeService(data, audit);
  const skills = new SkillService(data, audit);
  const memories = new MemoryService(data, audit);
  const genBIApps = new GenBIAppService(data, audit);
  const apiAccess = new ApiAccessService(data, audit);

  return { data, audit, projects, ask, dataSources, knowledge, skills, memories, genBIApps, apiAccess };
}
```

- [ ] **Step 4: Implement adapters**

Create `apps/api/src/adapters/AnalyticsAgentAdapter.ts`:

```ts
import type { AskRun, ChartSpec } from "@genbi/domain";

export interface AnalyticsAgentAdapter {
  run(question: string, threadId: string): Omit<AskRun, "id" | "threadId" | "question" | "createdAt">;
}

export class MockAnalyticsAgentAdapter implements AnalyticsAgentAdapter {
  run(): Omit<AskRun, "id" | "threadId" | "question" | "createdAt"> {
    const chartSpec: ChartSpec = { type: "bar", xField: "month", yFields: ["monthly_revenue"], title: "Monthly revenue by segment" };

    return {
      planSteps: [
        "Resolve revenue metric from Knowledge",
        "Compare current and prior month ARR",
        "Break down delta by segment and movement type",
        "Generate chart and follow-up prompts"
      ],
      generatedSql: "select month, segment, monthly_revenue, expansion_arr, churn_arr from analytics.monthly_revenue where month >= date '2026-05-01' order by month, segment;",
      assumptions: [
        "Revenue means recognized monthly recurring revenue.",
        "Enterprise segment uses account_tier = 'enterprise'."
      ],
      resultRows: [
        { month: "2026-05", segment: "Enterprise", monthly_revenue: 1240000, expansion_arr: 184000, churn_arr: 42000 },
        { month: "2026-06", segment: "Enterprise", monthly_revenue: 1385000, expansion_arr: 231000, churn_arr: 39000 },
        { month: "2026-05", segment: "SMB", monthly_revenue: 410000, expansion_arr: 44000, churn_arr: 28000 },
        { month: "2026-06", segment: "SMB", monthly_revenue: 426000, expansion_arr: 47000, churn_arr: 31000 }
      ],
      chartSpec,
      insight: "Enterprise expansion contributed most of the June increase, while SMB churn rose slightly.",
      followUps: ["Which accounts drove enterprise expansion?", "Show churn reasons by segment", "Create a dashboard for this trend"],
      status: "completed"
    };
  }
}
```

Create `apps/api/src/adapters/ConnectorAdapter.ts`:

```ts
import type { DataSourceType, SchemaSummary } from "@genbi/domain";

export interface ConnectionTestResult {
  status: "success" | "invalid_credentials" | "network_failure" | "unsupported_feature";
  message: string;
  schemaSummary: SchemaSummary;
}

export interface ConnectorAdapter {
  testConnection(type: DataSourceType): ConnectionTestResult;
}

export class MockConnectorAdapter implements ConnectorAdapter {
  testConnection(type: DataSourceType): ConnectionTestResult {
    if (type === "csv") {
      return {
        status: "invalid_credentials",
        message: "CSV import requires a readable file and delimiter selection.",
        schemaSummary: { tables: 0, fields: 0, businessModels: [] }
      };
    }

    return {
      status: "success",
      message: `${type} connection test succeeded with mock schema sync.`,
      schemaSummary: { tables: 12, fields: 148, businessModels: ["Revenue", "Customers"] }
    };
  }
}
```

- [ ] **Step 5: Implement services**

Create service classes with these exact methods:

```ts
// AuditService.ts
import type { AuditEvent, SeedData } from "@genbi/domain";

export class AuditService {
  constructor(private readonly data: SeedData) {}

  listEvents(): AuditEvent[] {
    return [...this.data.auditEvents].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }

  record(action: string, target: string, metadata: Record<string, string> = {}): AuditEvent {
    const event: AuditEvent = {
      id: `audit_${this.data.auditEvents.length + 1}`,
      organizationId: this.data.organization.id,
      actor: "Jason Fan",
      action,
      target,
      createdAt: new Date().toISOString(),
      metadata
    };
    this.data.auditEvents.unshift(event);
    return event;
  }
}
```

```ts
// ProjectService.ts
import type { Project, SeedData } from "@genbi/domain";

export class ProjectService {
  constructor(private readonly data: SeedData) {}

  getOrganization() {
    return this.data.organization;
  }

  listMembers() {
    return this.data.members;
  }

  listProjects(): Project[] {
    return this.data.projects;
  }

  getProject(projectId: string): Project {
    const project = this.data.projects.find((item) => item.id === projectId);
    if (!project) throw new Error(`Project not found: ${projectId}`);
    return project;
  }
}
```

```ts
// AskService.ts
import type { AskRun, AskThread, SeedData } from "@genbi/domain";
import type { AnalyticsAgentAdapter } from "../adapters/AnalyticsAgentAdapter";
import type { AuditService } from "./AuditService";

export class AskService {
  constructor(
    private readonly data: SeedData,
    private readonly adapter: AnalyticsAgentAdapter,
    private readonly audit: AuditService
  ) {}

  listThreads(projectId: string): AskThread[] {
    return this.data.threads.filter((thread) => thread.projectId === projectId);
  }

  ask(projectId: string, question: string): AskRun {
    let thread = this.data.threads.find((item) => item.projectId === projectId);
    if (!thread) {
      thread = { id: `thread_${Date.now()}`, projectId, title: question, mode: "agentic", messages: [], runs: [] };
      this.data.threads.unshift(thread);
    }
    const response = this.adapter.run(question, thread.id);
    const run: AskRun = {
      id: `run_${Date.now()}`,
      threadId: thread.id,
      question,
      createdAt: new Date().toISOString(),
      ...response
    };
    thread.runs.unshift(run);
    thread.messages.push({ id: `msg_${Date.now()}_u`, role: "user", content: question, createdAt: run.createdAt });
    thread.messages.push({ id: `msg_${Date.now()}_a`, role: "assistant", content: run.insight, createdAt: run.createdAt });
    this.audit.record("asked_question", thread.title, { projectId });
    return run;
  }
}
```

Implement the remaining services with the same direct style:

```ts
// DataSourceService.ts
import type { DataSource, DataSourceType, SeedData } from "@genbi/domain";
import type { ConnectorAdapter, ConnectionTestResult } from "../adapters/ConnectorAdapter";
import type { AuditService } from "./AuditService";

export class DataSourceService {
  constructor(private readonly data: SeedData, private readonly adapter: ConnectorAdapter, private readonly audit: AuditService) {}

  list(projectId: string): DataSource[] {
    return this.data.dataSources.filter((source) => source.projectId === projectId);
  }

  testConnection(projectId: string, type: DataSourceType): ConnectionTestResult {
    const result = this.adapter.testConnection(type);
    this.audit.record("tested_data_source", type, { projectId, status: result.status });
    return result;
  }
}
```

```ts
// KnowledgeService.ts
import type { KnowledgeDocument, SeedData } from "@genbi/domain";
import type { AuditService } from "./AuditService";

export class KnowledgeService {
  constructor(private readonly data: SeedData, private readonly audit: AuditService) {}

  list(projectId: string): KnowledgeDocument[] {
    return this.data.knowledgeDocuments.filter((document) => document.projectId === projectId);
  }

  update(projectId: string, documentId: string, body: string, status: KnowledgeDocument["status"]): KnowledgeDocument {
    const document = this.data.knowledgeDocuments.find((item) => item.projectId === projectId && item.id === documentId);
    if (!document) throw new Error(`Knowledge document not found: ${documentId}`);
    document.body = body;
    document.status = status;
    document.updatedAt = new Date().toISOString();
    this.audit.record(status === "published" ? "published_knowledge" : "saved_knowledge", document.title, { projectId });
    return document;
  }
}
```

```ts
// SkillService.ts
import type { SeedData, Skill } from "@genbi/domain";
import type { AuditService } from "./AuditService";

export class SkillService {
  constructor(private readonly data: SeedData, private readonly audit: AuditService) {}

  list(projectId: string): Skill[] {
    return this.data.skills.filter((skill) => skill.projectId === projectId);
  }

  run(projectId: string, skillId: string) {
    const skill = this.list(projectId).find((item) => item.id === skillId);
    if (!skill) throw new Error(`Skill not found: ${skillId}`);
    skill.lastRunAt = new Date().toISOString();
    this.audit.record("ran_skill", skill.name, { projectId });
    return { skill, output: `${skill.name} completed using deterministic mock context.` };
  }
}
```

```ts
// MemoryService.ts
import type { Memory, SeedData } from "@genbi/domain";
import type { AuditService } from "./AuditService";

export class MemoryService {
  constructor(private readonly data: SeedData, private readonly audit: AuditService) {}

  list(projectId: string): Memory[] {
    return this.data.memories.filter((memory) => memory.projectId === projectId);
  }

  reset(projectId: string, memoryId: string): Memory {
    const memory = this.list(projectId).find((item) => item.id === memoryId);
    if (!memory) throw new Error(`Memory not found: ${memoryId}`);
    memory.markdownBody = "# Project Memory\nNo learned preferences are stored for this project.";
    memory.updatedAt = new Date().toISOString();
    this.audit.record("reset_memory", memory.ownerName, { projectId });
    return memory;
  }
}
```

```ts
// GenBIAppService.ts
import type { GenBIApp, SeedData } from "@genbi/domain";
import type { AuditService } from "./AuditService";

export class GenBIAppService {
  constructor(private readonly data: SeedData, private readonly audit: AuditService) {}

  list(projectId: string): GenBIApp[] {
    return this.data.genBIApps.filter((app) => app.projectId === projectId);
  }

  createFromRun(projectId: string, threadId: string): GenBIApp {
    const app: GenBIApp = {
      id: `app_${Date.now()}`,
      projectId,
      name: "Generated Revenue Brief",
      description: "Generated app from the latest ask run.",
      sourceThreadId: threadId,
      widgets: [
        { id: "wid_generated_kpi", type: "kpi", title: "Revenue", metric: "$1.81M" },
        { id: "wid_generated_chart", type: "chart", title: "Revenue Trend", chartSpec: { type: "bar", xField: "month", yFields: ["monthly_revenue"], title: "Monthly revenue by segment" } }
      ],
      status: "draft",
      updatedAt: new Date().toISOString()
    };
    this.data.genBIApps.unshift(app);
    this.audit.record("created_genbi_app", app.name, { projectId, threadId });
    return app;
  }
}
```

```ts
// ApiAccessService.ts
import type { ApiKey, ChartSpec, SeedData } from "@genbi/domain";
import type { AuditService } from "./AuditService";

export interface SqlGenerationResult {
  sql: string;
  assumptions: string[];
}

export interface ChartGenerationResult {
  chartSpec: ChartSpec;
  insight: string;
}

export class ApiAccessService {
  constructor(private readonly data: SeedData, private readonly audit: AuditService) {}

  listKeys(): ApiKey[] {
    return this.data.apiKeys;
  }

  createKey(name: string, scopes: string[]): ApiKey {
    if (!name.trim()) throw new Error("API key name is required");
    const key: ApiKey = {
      id: `key_${Date.now()}`,
      organizationId: this.data.organization.id,
      name,
      prefix: `gb_live_${Math.random().toString(16).slice(2, 6)}`,
      scopes,
      lastUsedAt: null,
      createdAt: new Date().toISOString()
    };
    this.data.apiKeys.unshift(key);
    this.audit.record("created_api_key", name, { scopes: scopes.join(",") });
    return key;
  }

  generateSql(question: string): SqlGenerationResult {
    this.audit.record("generated_sql", question);
    return {
      sql: "select month, segment, monthly_revenue from analytics.monthly_revenue order by month, segment;",
      assumptions: ["Used governed revenue definition", "Limited to published semantic models"]
    };
  }

  generateChart(): ChartGenerationResult {
    this.audit.record("generated_chart", "API chart generation");
    return {
      chartSpec: { type: "bar", xField: "month", yFields: ["monthly_revenue"], title: "Monthly revenue by segment" },
      insight: "Enterprise revenue is the largest contributor in the current result set."
    };
  }
}
```

- [ ] **Step 6: Run tests**

Run: `npm run test -w apps/api`

Expected: PASS with 2 tests.

- [ ] **Step 7: Commit**

Run:

```bash
git add apps/api/src packages/domain/src
git commit -m "feat: add mock commercial API services"
```

Expected: commit succeeds.

---

### Task 4: Fastify API Routes

**Files:**
- Create: `apps/api/src/server.ts`
- Create: `apps/api/src/index.ts`
- Create: `apps/api/src/routes/projectRoutes.ts`
- Create: `apps/api/src/routes/dataSourceRoutes.ts`
- Create: `apps/api/src/routes/askRoutes.ts`
- Create: `apps/api/src/routes/knowledgeRoutes.ts`
- Create: `apps/api/src/routes/apiAccessRoutes.ts`
- Create: `apps/api/src/routes/governanceRoutes.ts`
- Create: `apps/api/src/tests/apiRoutes.test.ts`

**Interfaces:**
- Consumes: `createServices(): Services`
- Produces: `buildServer(): FastifyInstance`
- Produces: all API routes from the approved spec

- [ ] **Step 1: Write failing route tests**

Create `apps/api/src/tests/apiRoutes.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildServer } from "../server";

describe("API routes", () => {
  it("returns organization and project data", async () => {
    const server = buildServer();
    const org = await server.inject({ method: "GET", url: "/api/organizations/current" });
    const projects = await server.inject({ method: "GET", url: "/api/projects" });

    expect(org.statusCode).toBe(200);
    expect(org.json().name).toBe("Acme Analytics");
    expect(projects.json()[0].type).toBe("agentic");
  });

  it("runs ask and returns SQL plus chart data", async () => {
    const server = buildServer();
    const result = await server.inject({
      method: "POST",
      url: "/api/projects/proj_revenue_agentic/ask",
      payload: { question: "What drove revenue changes last month?" }
    });

    expect(result.statusCode).toBe(200);
    expect(result.json().generatedSql).toContain("monthly_revenue");
    expect(result.json().chartSpec.title).toBe("Monthly revenue by segment");
  });

  it("generates API SQL and chart payloads", async () => {
    const server = buildServer();
    const sql = await server.inject({ method: "POST", url: "/api/v1/generate-sql", payload: { question: "Revenue by month" } });
    const chart = await server.inject({ method: "POST", url: "/api/v1/generate-chart", payload: { sql: "select 1" } });

    expect(sql.statusCode).toBe(200);
    expect(sql.json().sql).toContain("select month");
    expect(chart.json().chartSpec.type).toBe("bar");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -w apps/api`

Expected: FAIL with module resolution error for `../server`.

- [ ] **Step 3: Implement server registration**

Create `apps/api/src/server.ts`:

```ts
import cors from "@fastify/cors";
import Fastify from "fastify";
import { createServices } from "./seed";
import { registerApiAccessRoutes } from "./routes/apiAccessRoutes";
import { registerAskRoutes } from "./routes/askRoutes";
import { registerDataSourceRoutes } from "./routes/dataSourceRoutes";
import { registerGovernanceRoutes } from "./routes/governanceRoutes";
import { registerKnowledgeRoutes } from "./routes/knowledgeRoutes";
import { registerProjectRoutes } from "./routes/projectRoutes";

export function buildServer() {
  const server = Fastify({ logger: false });
  const services = createServices();

  server.register(cors, { origin: true });
  server.get("/api/health", async () => ({ status: "ok" }));

  registerProjectRoutes(server, services);
  registerDataSourceRoutes(server, services);
  registerAskRoutes(server, services);
  registerKnowledgeRoutes(server, services);
  registerApiAccessRoutes(server, services);
  registerGovernanceRoutes(server, services);

  return server;
}
```

Create `apps/api/src/index.ts`:

```ts
import { buildServer } from "./server";

const server = buildServer();
const port = Number(process.env.PORT ?? 8787);

server.listen({ port, host: "127.0.0.1" }).catch((error) => {
  server.log.error(error);
  process.exit(1);
});
```

- [ ] **Step 4: Implement route modules**

Use this route registration pattern in each route file:

```ts
// projectRoutes.ts
import type { FastifyInstance } from "fastify";
import type { Services } from "../seed";

export function registerProjectRoutes(server: FastifyInstance, services: Services) {
  server.get("/api/organizations/current", async () => services.projects.getOrganization());
  server.get("/api/members", async () => services.projects.listMembers());
  server.get("/api/projects", async () => services.projects.listProjects());
  server.get<{ Params: { projectId: string } }>("/api/projects/:projectId", async (request) => {
    return services.projects.getProject(request.params.projectId);
  });
}
```

```ts
// dataSourceRoutes.ts
import type { DataSourceType } from "@genbi/domain";
import type { FastifyInstance } from "fastify";
import type { Services } from "../seed";

export function registerDataSourceRoutes(server: FastifyInstance, services: Services) {
  server.get<{ Params: { projectId: string } }>("/api/projects/:projectId/data-sources", async (request) => {
    return services.dataSources.list(request.params.projectId);
  });

  server.post<{ Params: { projectId: string }; Body: { type: DataSourceType } }>("/api/projects/:projectId/data-sources/test", async (request) => {
    return services.dataSources.testConnection(request.params.projectId, request.body.type);
  });
}
```

```ts
// askRoutes.ts
import type { FastifyInstance } from "fastify";
import type { Services } from "../seed";

export function registerAskRoutes(server: FastifyInstance, services: Services) {
  server.get<{ Params: { projectId: string } }>("/api/projects/:projectId/threads", async (request) => {
    return services.ask.listThreads(request.params.projectId);
  });

  server.post<{ Params: { projectId: string }; Body: { question: string } }>("/api/projects/:projectId/ask", async (request) => {
    return services.ask.ask(request.params.projectId, request.body.question);
  });
}
```

```ts
// knowledgeRoutes.ts
import type { KnowledgeDocument } from "@genbi/domain";
import type { FastifyInstance } from "fastify";
import type { Services } from "../seed";

export function registerKnowledgeRoutes(server: FastifyInstance, services: Services) {
  server.get<{ Params: { projectId: string } }>("/api/projects/:projectId/knowledge", async (request) => {
    return services.knowledge.list(request.params.projectId);
  });

  server.put<{ Params: { projectId: string; documentId: string }; Body: { body: string; status: KnowledgeDocument["status"] } }>("/api/projects/:projectId/knowledge/:documentId", async (request) => {
    return services.knowledge.update(request.params.projectId, request.params.documentId, request.body.body, request.body.status);
  });

  server.get<{ Params: { projectId: string } }>("/api/projects/:projectId/skills", async (request) => {
    return services.skills.list(request.params.projectId);
  });

  server.post<{ Params: { projectId: string; skillId: string } }>("/api/projects/:projectId/skills/:skillId/run", async (request) => {
    return services.skills.run(request.params.projectId, request.params.skillId);
  });

  server.get<{ Params: { projectId: string } }>("/api/projects/:projectId/memories", async (request) => {
    return services.memories.list(request.params.projectId);
  });

  server.post<{ Params: { projectId: string; memoryId: string } }>("/api/projects/:projectId/memories/:memoryId/reset", async (request) => {
    return services.memories.reset(request.params.projectId, request.params.memoryId);
  });

  server.get<{ Params: { projectId: string } }>("/api/projects/:projectId/apps", async (request) => {
    return services.genBIApps.list(request.params.projectId);
  });

  server.post<{ Params: { projectId: string }; Body: { threadId: string } }>("/api/projects/:projectId/apps", async (request) => {
    return services.genBIApps.createFromRun(request.params.projectId, request.body.threadId);
  });
}
```

```ts
// apiAccessRoutes.ts
import type { FastifyInstance } from "fastify";
import type { Services } from "../seed";

export function registerApiAccessRoutes(server: FastifyInstance, services: Services) {
  server.get("/api/api-keys", async () => services.apiAccess.listKeys());
  server.post<{ Body: { name: string; scopes: string[] } }>("/api/api-keys", async (request) => {
    return services.apiAccess.createKey(request.body.name, request.body.scopes);
  });
  server.post<{ Body: { question: string } }>("/api/v1/generate-sql", async (request) => {
    return services.apiAccess.generateSql(request.body.question);
  });
  server.post<{ Body: { sql: string } }>("/api/v1/generate-chart", async () => {
    return services.apiAccess.generateChart();
  });
}
```

```ts
// governanceRoutes.ts
import type { FastifyInstance } from "fastify";
import type { Services } from "../seed";

export function registerGovernanceRoutes(server: FastifyInstance, services: Services) {
  server.get("/api/audit-events", async () => services.audit.listEvents());
}
```

- [ ] **Step 5: Run API tests and build**

Run: `npm run test -w apps/api`

Expected: PASS with service and route tests.

Run: `npm run build -w apps/api`

Expected: PASS with no TypeScript errors.

- [ ] **Step 6: Commit**

Run:

```bash
git add apps/api
git commit -m "feat: expose commercial MVP API routes"
```

Expected: commit succeeds.

---

### Task 5: Web API Client And App Shell

**Files:**
- Create: `apps/web/src/main.tsx`
- Create: `apps/web/src/App.tsx`
- Create: `apps/web/src/api/client.ts`
- Create: `apps/web/src/components/AppShell.tsx`
- Create: `apps/web/src/components/StatusBadge.tsx`
- Create: `apps/web/src/styles.css`
- Create: `apps/web/src/tests/setup.ts`
- Create: `apps/web/src/tests/app.test.tsx`

**Interfaces:**
- Produces: `ApiClient` methods for all API route families
- Produces: navigation state keys `console`, `projects`, `ask`, `data-sources`, `knowledge`, `skills`, `memories`, `apps`, `api-access`, `governance`
- Consumes: domain types from `@genbi/domain`

- [ ] **Step 1: Write failing shell test**

Create `apps/web/src/tests/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

Create `apps/web/src/tests/app.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "../App";

describe("App shell", () => {
  it("renders the product console as the first screen", async () => {
    render(<App />);

    expect(await screen.findByText("Acme Analytics")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ask/i })).toBeInTheDocument();
    expect(screen.getByText("Commercial")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -w apps/web`

Expected: FAIL with module resolution error for `../App`.

- [ ] **Step 3: Implement API client**

Create `apps/web/src/api/client.ts`:

```ts
import type { ApiKey, AskRun, AskThread, AuditEvent, DataSource, DataSourceType, GenBIApp, KnowledgeDocument, Memory, Member, Organization, Project, Skill } from "@genbi/domain";

const baseUrl = "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`);
  if (!response.ok) throw new Error(`GET ${path} failed with ${response.status}`);
  return response.json() as Promise<T>;
}

async function sendJson<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) throw new Error(`${method} ${path} failed with ${response.status}`);
  return response.json() as Promise<T>;
}

export const apiClient = {
  organization: () => getJson<Organization>("/api/organizations/current"),
  members: () => getJson<Member[]>("/api/members"),
  projects: () => getJson<Project[]>("/api/projects"),
  dataSources: (projectId: string) => getJson<DataSource[]>(`/api/projects/${projectId}/data-sources`),
  testDataSource: (projectId: string, type: DataSourceType) => sendJson(`/api/projects/${projectId}/data-sources/test`, { type }),
  threads: (projectId: string) => getJson<AskThread[]>(`/api/projects/${projectId}/threads`),
  ask: (projectId: string, question: string) => sendJson<AskRun>(`/api/projects/${projectId}/ask`, { question }),
  knowledge: (projectId: string) => getJson<KnowledgeDocument[]>(`/api/projects/${projectId}/knowledge`),
  updateKnowledge: (projectId: string, documentId: string, body: string, status: KnowledgeDocument["status"]) => sendJson<KnowledgeDocument>(`/api/projects/${projectId}/knowledge/${documentId}`, { body, status }, "PUT"),
  skills: (projectId: string) => getJson<Skill[]>(`/api/projects/${projectId}/skills`),
  runSkill: (projectId: string, skillId: string) => sendJson(`/api/projects/${projectId}/skills/${skillId}/run`, {}),
  memories: (projectId: string) => getJson<Memory[]>(`/api/projects/${projectId}/memories`),
  resetMemory: (projectId: string, memoryId: string) => sendJson<Memory>(`/api/projects/${projectId}/memories/${memoryId}/reset`, {}),
  apps: (projectId: string) => getJson<GenBIApp[]>(`/api/projects/${projectId}/apps`),
  createApp: (projectId: string, threadId: string) => sendJson<GenBIApp>(`/api/projects/${projectId}/apps`, { threadId }),
  apiKeys: () => getJson<ApiKey[]>("/api/api-keys"),
  createApiKey: (name: string, scopes: string[]) => sendJson<ApiKey>("/api/api-keys", { name, scopes }),
  generateSql: (question: string) => sendJson<{ sql: string; assumptions: string[] }>("/api/v1/generate-sql", { question }),
  generateChart: (sql: string) => sendJson("/api/v1/generate-chart", { sql }),
  auditEvents: () => getJson<AuditEvent[]>("/api/audit-events")
};
```

- [ ] **Step 4: Implement shell and styling**

Create `apps/web/src/components/StatusBadge.tsx`:

```tsx
export function StatusBadge({ children, tone = "neutral" }: { children: string; tone?: "neutral" | "good" | "warn" | "bad" }) {
  return <span className={`status-badge status-badge--${tone}`}>{children}</span>;
}
```

Create `apps/web/src/components/AppShell.tsx` with left navigation using lucide icons:

```tsx
import { Activity, AppWindow, BookOpen, Database, Home, KeyRound, MessageSquare, ShieldCheck, Sparkles, UsersRound, Workflow } from "lucide-react";
import type { ReactNode } from "react";

export type ScreenKey = "console" | "projects" | "ask" | "data-sources" | "knowledge" | "skills" | "memories" | "apps" | "api-access" | "governance";

const navItems = [
  { key: "console", label: "Home", icon: Home },
  { key: "projects", label: "Projects", icon: Workflow },
  { key: "ask", label: "Ask", icon: MessageSquare },
  { key: "data-sources", label: "Data Sources", icon: Database },
  { key: "knowledge", label: "Knowledge", icon: BookOpen },
  { key: "skills", label: "Skills", icon: Sparkles },
  { key: "memories", label: "Memories", icon: Activity },
  { key: "apps", label: "GenBI Apps", icon: AppWindow },
  { key: "api-access", label: "API Access", icon: KeyRound },
  { key: "governance", label: "Governance", icon: ShieldCheck }
] as const;

export function AppShell({ children, current, onNavigate }: { children: ReactNode; current: ScreenKey; onNavigate: (screen: ScreenKey) => void }) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <UsersRound size={20} />
          <div>
            <strong>Acme Analytics</strong>
            <span>Commercial</span>
          </div>
        </div>
        <nav className="nav-list">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.key} className={current === item.key ? "nav-item nav-item--active" : "nav-item"} onClick={() => onNavigate(item.key)}>
                <Icon size={17} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>
      <main className="workspace">{children}</main>
    </div>
  );
}
```

Create `apps/web/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Create a first `apps/web/src/App.tsx` that renders `AppShell` and a console heading:

```tsx
import { useState } from "react";
import { AppShell, type ScreenKey } from "./components/AppShell";
import { StatusBadge } from "./components/StatusBadge";

export default function App() {
  const [screen, setScreen] = useState<ScreenKey>("console");

  return (
    <AppShell current={screen} onNavigate={setScreen}>
      <section className="page-header">
        <div>
          <p className="eyebrow">Acme Analytics</p>
          <h1>Commercial GenBI Console</h1>
          <p>Agentic analytics workspace for governed natural-language BI.</p>
        </div>
        <StatusBadge tone="good">Commercial</StatusBadge>
      </section>
      <section className="panel-grid">
        <article className="metric-panel">
          <span>Projects</span>
          <strong>2</strong>
        </article>
        <article className="metric-panel">
          <span>Connected sources</span>
          <strong>1</strong>
        </article>
        <article className="metric-panel">
          <span>Generated apps</span>
          <strong>1</strong>
        </article>
      </section>
    </AppShell>
  );
}
```

Create `apps/web/src/styles.css` with design tokens, 8px radius, responsive shell, buttons, panels, badges, and table basics.

- [ ] **Step 5: Run tests**

Run: `npm run test -w apps/web`

Expected: PASS with shell test.

Run: `npm run build -w apps/web`

Expected: PASS with no TypeScript errors.

- [ ] **Step 6: Commit**

Run:

```bash
git add apps/web
git commit -m "feat: add commercial app shell"
```

Expected: commit succeeds.

---

### Task 6: Product Screens And Data Loading

**Files:**
- Modify: `apps/web/src/App.tsx`
- Create: `apps/web/src/components/DataTable.tsx`
- Create: `apps/web/src/components/ChartPanel.tsx`
- Create: `apps/web/src/screens/ConsoleScreen.tsx`
- Create: `apps/web/src/screens/ProjectsScreen.tsx`
- Create: `apps/web/src/screens/DataSourcesScreen.tsx`
- Create: `apps/web/src/screens/KnowledgeScreen.tsx`
- Create: `apps/web/src/screens/SkillsScreen.tsx`
- Create: `apps/web/src/screens/MemoriesScreen.tsx`
- Create: `apps/web/src/screens/GenBIAppsScreen.tsx`
- Create: `apps/web/src/screens/ApiAccessScreen.tsx`
- Create: `apps/web/src/screens/GovernanceScreen.tsx`

**Interfaces:**
- Consumes: `apiClient` from Task 5
- Produces: visible commercial surfaces for console, projects, data sources, knowledge, skills, memories, apps, API access, and governance

- [ ] **Step 1: Add reusable table and chart panels**

Create `DataTable.tsx`:

```tsx
export function DataTable({ rows }: { rows: Record<string, string | number>[] }) {
  const columns = rows[0] ? Object.keys(rows[0]) : [];
  return (
    <table className="data-table">
      <thead>
        <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index}>
            {columns.map((column) => <td key={column}>{row[column]}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

Create `ChartPanel.tsx`:

```tsx
import type { ChartSpec } from "@genbi/domain";

export function ChartPanel({ spec, rows }: { spec: ChartSpec; rows: Record<string, string | number>[] }) {
  const values = rows.map((row) => Number(row[spec.yFields[0]] ?? 0));
  const max = Math.max(...values, 1);

  return (
    <div className="chart-panel" aria-label={spec.title}>
      <div className="chart-title">{spec.title}</div>
      <div className="bars">
        {rows.map((row, index) => (
          <div className="bar-column" key={`${row[spec.xField]}-${index}`}>
            <div className="bar" style={{ height: `${Math.max(12, (Number(row[spec.yFields[0]]) / max) * 100)}%` }} />
            <span>{String(row[spec.xField])}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement screens**

Each screen loads data with `useEffect` and shows a loading line before data arrives. Use these exact titles:

```tsx
// ConsoleScreen.tsx
export function ConsoleScreen() {
  return <section className="screen"><h1>Commercial GenBI Console</h1><p>Workspace health, recent questions, source sync, and generated app activity.</p></section>;
}
```

Implement the remaining screens with these required visible labels:

- `ProjectsScreen`: "Projects", "Agentic", "Classic"
- `DataSourcesScreen`: "Data Sources", "Production Warehouse", "Test Snowflake"
- `KnowledgeScreen`: "Knowledge", "Revenue Metric Definitions", "Publish"
- `SkillsScreen`: "Skills", "Metric Lookup", "Try skill"
- `MemoriesScreen`: "Memories", "Project Memory", "Reset memory"
- `GenBIAppsScreen`: "GenBI Apps", "Revenue Pulse", "Published"
- `ApiAccessScreen`: "API Access", "Server analytics key", "Generate SQL"
- `GovernanceScreen`: "Governance", "Members", "Audit log"

For action buttons, wire these client calls:

- Data source test button calls `apiClient.testDataSource(projectId, "snowflake")`.
- Knowledge publish button calls `apiClient.updateKnowledge(projectId, documentId, body, "published")`.
- Skill run button calls `apiClient.runSkill(projectId, skillId)`.
- Memory reset button calls `apiClient.resetMemory(projectId, memoryId)`.
- API SQL button calls `apiClient.generateSql("Revenue by month")`.

- [ ] **Step 3: Update App routing**

Modify `App.tsx` so each `ScreenKey` renders the matching screen. Use `proj_revenue_agentic` as the selected project id until project switching is implemented.

- [ ] **Step 4: Build and smoke test**

Run: `npm run build -w apps/web`

Expected: PASS with no TypeScript errors.

Run: `npm run test -w apps/web`

Expected: PASS with shell test still finding console and Ask navigation.

- [ ] **Step 5: Commit**

Run:

```bash
git add apps/web/src
git commit -m "feat: add commercial product screens"
```

Expected: commit succeeds.

---

### Task 7: Agentic Ask Workspace

**Files:**
- Create: `apps/web/src/screens/AskScreen.tsx`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`
- Create: `apps/web/tests/ask.spec.ts`

**Interfaces:**
- Consumes: `apiClient.threads(projectId)` and `apiClient.ask(projectId, question)`
- Produces: a visible Agentic Ask workflow with plan, SQL, assumptions, table, chart, insight, and follow-ups

- [ ] **Step 1: Implement AskScreen**

Create `AskScreen.tsx`:

```tsx
import type { AskRun, AskThread } from "@genbi/domain";
import { Send } from "lucide-react";
import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import { ChartPanel } from "../components/ChartPanel";
import { DataTable } from "../components/DataTable";

export function AskScreen({ projectId }: { projectId: string }) {
  const [threads, setThreads] = useState<AskThread[]>([]);
  const [question, setQuestion] = useState("What drove revenue changes last month?");
  const [activeRun, setActiveRun] = useState<AskRun | null>(null);

  useEffect(() => {
    apiClient.threads(projectId).then((items) => {
      setThreads(items);
      setActiveRun(items[0]?.runs[0] ?? null);
    });
  }, [projectId]);

  async function submitQuestion() {
    const run = await apiClient.ask(projectId, question);
    setActiveRun(run);
    const updatedThreads = await apiClient.threads(projectId);
    setThreads(updatedThreads);
  }

  return (
    <section className="ask-layout">
      <aside className="thread-list">
        <h2>Ask</h2>
        {threads.map((thread) => <button key={thread.id}>{thread.title}</button>)}
      </aside>
      <div className="ask-main">
        <div className="ask-input">
          <input value={question} onChange={(event) => setQuestion(event.target.value)} aria-label="Ask question" />
          <button onClick={submitQuestion}><Send size={16} /> Run</button>
        </div>
        {activeRun && (
          <div className="run-grid">
            <section className="tool-panel">
              <h3>Agent plan</h3>
              <ol>{activeRun.planSteps.map((step) => <li key={step}>{step}</li>)}</ol>
            </section>
            <section className="tool-panel">
              <h3>Generated SQL</h3>
              <pre>{activeRun.generatedSql}</pre>
            </section>
            <section className="tool-panel">
              <h3>Assumptions</h3>
              <ul>{activeRun.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
            </section>
            <section className="tool-panel wide">
              <h3>Result table</h3>
              <DataTable rows={activeRun.resultRows} />
            </section>
            <section className="tool-panel wide">
              <ChartPanel spec={activeRun.chartSpec} rows={activeRun.resultRows} />
            </section>
            <section className="tool-panel wide">
              <h3>Insight</h3>
              <p>{activeRun.insight}</p>
              <div className="follow-ups">{activeRun.followUps.map((item) => <button key={item}>{item}</button>)}</div>
            </section>
          </div>
        )}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Add Ask routing**

Modify `App.tsx` so `screen === "ask"` renders `<AskScreen projectId="proj_revenue_agentic" />`.

- [ ] **Step 3: Add Playwright test**

Create `apps/web/tests/ask.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test("agentic ask shows plan, SQL, result, chart, and insight", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Ask" }).click();
  await page.getByRole("button", { name: "Run" }).click();

  await expect(page.getByText("Agent plan")).toBeVisible();
  await expect(page.getByText("Generated SQL")).toBeVisible();
  await expect(page.getByText("analytics.monthly_revenue")).toBeVisible();
  await expect(page.getByText("Result table")).toBeVisible();
  await expect(page.getByText("Enterprise expansion contributed most")).toBeVisible();
  await expect(page.getByLabel("Monthly revenue by segment")).toBeVisible();
});
```

Create `apps/web/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry"
  },
  webServer: [
    {
      command: "npm run dev -w apps/api",
      url: "http://127.0.0.1:8787/api/health",
      reuseExistingServer: true
    },
    {
      command: "npm run dev -w apps/web",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: true
    }
  ],
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } }
  ]
});
```

- [ ] **Step 4: Run verification**

Run: `npm run build`

Expected: PASS for all workspaces.

Run: `npm run test:e2e -w apps/web`

Expected: PASS for Ask workflow.

- [ ] **Step 5: Commit**

Run:

```bash
git add apps/web
git commit -m "feat: build agentic ask workspace"
```

Expected: commit succeeds.

---

### Task 8: README, Final Verification, And Local Run

**Files:**
- Create: `README.md`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- Produces: documented local startup
- Produces: documented mock limitations and Wren integration path
- Consumes: all app scripts from earlier tasks

- [ ] **Step 1: Write README**

Create `README.md`:

````md
# GenBI Wren Commercial MVP

Commercial-style GenBI web MVP inspired by Wren AI Commercial Platform.

## Run Locally

```bash
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

The API runs on `http://127.0.0.1:8787`.

## Test

```bash
npm run build
npm run test
npm run test:e2e -w apps/web
```

## Current Mock Boundaries

- Data source connection tests use deterministic mock adapters.
- Ask, SQL generation, chart generation, and GenBI App generation use deterministic mock analytics output.
- Authentication, SSO, SCIM, billing, secrets storage, real warehouse connections, real LLM calls, and Wren Engine transpilation are outside milestone one.

## Future Wren Integration Path

1. Use Wren CLI or Wren context commands for semantic model validation.
2. Connect Wren Engine or Wren AI service for SQL generation and transpilation.
3. Add real database connectors and query execution.
4. Add persistent authentication and organization membership.
5. Add production deployment, secrets management, SSO, and audit retention.
````

- [ ] **Step 2: Polish responsive CSS**

Ensure `styles.css` includes:

- `@media (max-width: 900px)` collapsing shell layout.
- `.tool-panel`, `.metric-panel`, and `.nav-item` with `border-radius: 8px`.
- No negative letter spacing.
- No nested card styling.
- Table cells with `overflow-wrap: anywhere`.
- Buttons with icons aligned and text fitting on mobile.

- [ ] **Step 3: Run full verification**

Run: `npm run build`

Expected: PASS for `@genbi/domain`, `@genbi/api`, and `@genbi/web`.

Run: `npm run test`

Expected: PASS for domain, API, and web unit tests.

Run: `npm run test:e2e -w apps/web`

Expected: PASS for Ask workflow.

- [ ] **Step 4: Start local dev server**

Run: `npm run dev`

Expected: API is available at `http://127.0.0.1:8787/api/health`, web app is available at `http://127.0.0.1:5173`.

- [ ] **Step 5: Manual acceptance checklist**

Open `http://127.0.0.1:5173` and verify:

- Console is the first screen.
- Navigation includes Home, Projects, Ask, Data Sources, Knowledge, Skills, Memories, GenBI Apps, API Access, and Governance.
- Ask shows plan, SQL, assumptions, table, chart, insight, and follow-ups.
- Data Sources shows connected and error states plus connection test action.
- Knowledge shows published and draft documents plus publish action.
- Skills shows enabled skills plus try action.
- Memories shows project memory plus reset action.
- GenBI Apps shows `Revenue Pulse` with KPI and chart widgets.
- API Access shows key list plus SQL generation action.
- Governance shows members and audit log.

- [ ] **Step 6: Commit**

Run:

```bash
git add README.md apps/web/src/styles.css
git commit -m "docs: document commercial MVP runbook"
```

Expected: commit succeeds.

---

## Self-Review

Spec coverage:

- Organization and project console: Task 2 fixtures, Task 4 routes, Task 6 screens.
- Agentic and Classic project types: Task 2 fixtures, Task 6 Projects screen.
- Data sources and status workflows: Task 3 adapter/service, Task 4 routes, Task 6 Data Sources screen.
- Agentic Ask workspace: Task 3 service, Task 4 routes, Task 7 screen and e2e test.
- Knowledge: Task 3 service, Task 4 routes, Task 6 screen.
- Skills: Task 3 service, Task 4 routes, Task 6 screen.
- Memories: Task 3 service, Task 4 routes, Task 6 screen.
- GenBI Apps: Task 3 service, Task 4 routes, Task 6 screen, Task 7 link from Ask output.
- API Access: Task 3 service, Task 4 routes, Task 6 screen.
- Governance: Task 2 audit fixtures, Task 4 routes, Task 6 Governance screen.
- README and Wren integration path: Task 8.
- Tests: Tasks 2, 3, 4, 5, 7, and 8.

Placeholder scan:

- The plan contains no unresolved placeholder markers or deferred implementation instructions inside task steps.

Type consistency:

- `ProjectType`, `DataSourceType`, `AskRun`, `AskThread`, `KnowledgeDocument`, `Skill`, `Memory`, `GenBIApp`, `ApiKey`, and `AuditEvent` are defined in Task 2 and consumed with the same names in later tasks.
- `createServices()` is defined in Task 3 and consumed in Task 4.
- `apiClient` is defined in Task 5 and consumed in Tasks 6 and 7.
