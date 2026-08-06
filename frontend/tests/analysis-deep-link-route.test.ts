/**
 * @vitest-environment jsdom
 */
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { AnalysisWorkspace } from "../src/modules/analysis/components/AnalysisWorkspace";

const { mockGetBackendAnalysisSession } = vi.hoisted(() => ({
  mockGetBackendAnalysisSession: vi.fn(),
}));

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { id: "owner_1" } } }),
}));
vi.mock("../src/modules/analysis/components/ReportPanel", () => ({
  ReportPanel: () => null,
}));
vi.mock("../src/modules/analysis/hooks/use-flow", () => ({
  useFlow: () => ({
    nodes: [],
    // Reproduce the real hook's transition frame: after selecting session B,
    // the component can still observe session A's running snapshot until the
    // hook displays B's cached snapshot in its effect.
    running: true,
    report: undefined,
    start: vi.fn(),
    send: vi.fn(),
    reply: vi.fn(),
    stop: vi.fn(),
  }),
}));
vi.mock("../src/modules/analysis/agentClients/backendClient", () => ({
  shouldUseBackendAnalysisClient: () => true,
  listBackendAnalysisSessions: () => Promise.resolve([
    {
      id: "session-a",
      title: "Task A",
      status: "active",
      createdAt: "2026-08-05T00:00:00Z",
      updatedAt: "2026-08-05T00:01:00Z",
      latestTurnStatus: "running",
    },
    {
      id: "session-b",
      title: "Task B",
      status: "active",
      createdAt: "2026-08-05T00:00:00Z",
      updatedAt: "2026-08-05T00:00:30Z",
      latestTurnStatus: "cancelled",
    },
  ]),
  getBackendAnalysisSession: mockGetBackendAnalysisSession,
  flowNodesFromBackendSession: () => [],
  deleteBackendAnalysisSession: () => Promise.resolve(),
}));
vi.mock("../src/modules/analysis/api/report-service", () => ({
  shouldUseBackendReports: () => false,
  listReportCenter: () => Promise.resolve({ mine: [], sharedWithMe: [] }),
  listReportsBySession: () => Promise.resolve([]),
  getActiveReportBuild: () => Promise.resolve({
    build: null,
    report: null,
  }),
}));

const routePath = resolve(process.cwd(), "src/app/analysis/[sessionId]/page.tsx");
const workspacePath = resolve(
  process.cwd(),
  "src/modules/analysis/components/AnalysisWorkspace.tsx",
);

afterEach(() => {
  vi.restoreAllMocks();
  mockGetBackendAnalysisSession.mockReset();
  window.history.replaceState({}, "", "/");
});

describe("analysis deep-link route", () => {
  test("starts with the task sidebar collapsed and gives the report most of the workspace", async () => {
    render(createElement(AnalysisWorkspace, { initialSessionId: "new" }));

    const shell = document.querySelector(".shell");
    const workspace = document.querySelector<HTMLElement>(".workspace");
    expect(shell?.classList.contains("collapsed")).toBe(true);
    expect(workspace?.style.gridTemplateColumns).toBe("34% 7px minmax(0, 1fr)");

    const primaryNavigation = screen.getByRole("navigation", { name: "主导航" });
    fireEvent.click(within(primaryNavigation).getByRole("button", { name: "分析工作台" }));
    expect(shell?.classList.contains("collapsed")).toBe(false);
    expect(await screen.findByRole("button", { name: /Task A/ })).toBeTruthy();
  });

  test("keeps the undecided workbench completely empty", () => {
    render(createElement(AnalysisWorkspace));

    const primaryNavigation = screen.getByRole("navigation", { name: "主导航" });
    fireEvent.click(within(primaryNavigation).getByRole("button", { name: "工作台" }));

    const shell = document.querySelector(".shell");
    const sidebar = screen.getByRole("complementary", { name: "侧栏" });
    const workbench = screen.getByRole("region", { name: "工作台" });

    expect(shell?.classList.contains("collapsed")).toBe(true);
    expect(sidebar.textContent).toBe("");
    expect(workbench.textContent).toBe("");
    expect(screen.queryByText("这里聚合最近分析、待确认口径、常用资产和运行状态；真正开始分析时进入分析工作台。")).toBeNull();
  });

  test("represents the business semantic library with a knowledge graph glyph", () => {
    render(createElement(AnalysisWorkspace));

    const primaryNavigation = screen.getByRole("navigation", { name: "主导航" });
    const semanticButton = within(primaryNavigation).getByRole("button", { name: "业务语义库" });
    const semanticIcon = semanticButton.querySelector('svg[data-icon="businessSemantics"]');

    expect(semanticIcon).toBeTruthy();
    expect(semanticIcon?.querySelectorAll("circle")).toHaveLength(4);
    expect(semanticIcon?.querySelectorAll("path")).toHaveLength(3);
    expect(semanticIcon?.querySelector("ellipse")).toBeNull();
  });

  test("allows selecting another task while the current Codex turn keeps running", async () => {
    window.history.replaceState({ analysisSessionId: "session-a" }, "", "/analysis/session-a");
    mockGetBackendAnalysisSession.mockImplementation((sessionId: string) => Promise.resolve({
      session: {
        id: sessionId,
        title: sessionId === "session-a" ? "Task A" : "Task B",
        status: "active",
        createdAt: "2026-08-05T00:00:00Z",
        updatedAt: "2026-08-05T00:01:00Z",
        latestTurnStatus: sessionId === "session-a" ? "running" : "cancelled",
        metadata: {},
      },
      turns: [],
      codexItemProjections: [],
    }));

    render(createElement(AnalysisWorkspace, { initialSessionId: "session-a" }));

    const taskB = await screen.findByRole("button", { name: /Task B/ });
    const taskOrder = () => screen.getAllByRole("button")
      .filter((button) => /Task [AB]/.test(button.textContent ?? ""))
      .map((button) => button.textContent?.match(/Task [AB]/)?.[0]);
    expect(taskOrder()).toEqual(["Task A", "Task B"]);

    mockGetBackendAnalysisSession.mockClear();
    fireEvent.click(taskB);

    await waitFor(() => {
      expect(mockGetBackendAnalysisSession).toHaveBeenCalledWith("session-b");
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Task B.*本轮已取消/ })).toBeTruthy();
    });
    expect(taskOrder()).toEqual(["Task A", "Task B"]);
    expect(window.location.pathname).toBe("/analysis/session-b");
  });

  test("does not restore an archived session into the workspace after refresh", async () => {
    window.history.replaceState(
      { analysisSessionId: "session-archived" },
      "",
      "/analysis/session-archived",
    );
    mockGetBackendAnalysisSession.mockResolvedValue({
      session: {
        id: "session-archived",
        title: "Archived Task",
        status: "archived",
        createdAt: "2026-08-05T00:00:00Z",
        updatedAt: "2026-08-05T00:02:00Z",
        latestTurnStatus: "completed",
        metadata: {},
      },
      turns: [],
      codexItemProjections: [],
    });

    render(createElement(AnalysisWorkspace, { initialSessionId: "session-archived" }));

    await waitFor(() => {
      expect(window.location.pathname).toBe("/analysis/new");
    });
    expect(screen.queryByRole("button", { name: /Archived Task/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "新分析" })).toBeTruthy();
    expect(screen.queryByText("报告加载中")).toBeNull();
  });

  test("uses the workspace sidebar as the only system module navigation", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/system/access") {
        return Promise.resolve(
          new Response(JSON.stringify({ access: "administrator" }), { status: 200 }),
        );
      }
      if (url === "/api/system/mcp/servers") {
        return Promise.resolve(
          new Response(JSON.stringify({ servers: [] }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    });

    render(createElement(AnalysisWorkspace));

    fireEvent.click(screen.getByRole("button", { name: "系统" }));
    const sidebar = within(screen.getByRole("complementary", { name: "侧栏" }));
    const mcpNavigation = await sidebar.findByRole("button", { name: /MCP 服务/ });
    const main = document.querySelector("main.main");
    expect(main).toBeTruthy();
    if (!main) return;

    expect(
      within(main as HTMLElement).queryByRole("navigation", { name: "系统管理导航" }),
    ).toBeNull();

    fireEvent.click(mcpNavigation);

    expect(
      await within(main as HTMLElement).findByRole("heading", { name: "MCP 服务" }),
    ).toBeTruthy();
  });

  test("serves /analysis/:sessionId through a real Next.js route", () => {
    expect(existsSync(routePath)).toBe(true);
    if (!existsSync(routePath)) return;

    const routeSource = readFileSync(routePath, "utf8");
    expect(routeSource).toContain("params: Promise<{ sessionId: string }>");
    expect(routeSource).toContain("<AnalysisWorkspace initialSessionId={sessionId}");
    expect(routeSource).toContain("<SignInScreen />");
  });

  test("restores the routed session instead of treating it as a new analysis", () => {
    const workspaceSource = readFileSync(workspacePath, "utf8");
    expect(workspaceSource).toContain("initialSessionId?: string | null");
    expect(workspaceSource).toContain("getBackendAnalysisSession(initialSessionId)");
    expect(workspaceSource).toContain("setInitialFlowMessages(flowNodesFromBackendSession(detail))");
    expect(workspaceSource).toContain("setCurrentAnalysisTaskId(initialSessionId)");
  });

  test("allows the routed session summary to be absent during the first server render", () => {
    const workspaceSource = readFileSync(workspacePath, "utf8");
    expect(workspaceSource).toContain(
      "function analysisLatestTurnStatus(thread: BackendAnalysisSessionSummary | null | undefined)",
    );
    expect(workspaceSource).toContain(
      "const value = thread?.latestTurnStatus ?? thread?.latest_turn_status;",
    );
  });

  test("server-renders a routed session before its summary has loaded", () => {
    expect(() => renderToString(
      createElement(AnalysisWorkspace, { initialSessionId: "session_from_url" }),
    )).not.toThrow();
  });
});
