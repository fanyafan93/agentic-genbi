/**
 * @vitest-environment jsdom
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { AgentEvent, AgentInput } from "../src/modules/analysis/agentClients/types";
import type { SavedInteractiveReport } from "../src/modules/analysis/api/interactive-report-service";
import { interactiveReportFixture } from "./fixtures/interactive-report";

const {
  mockAgentSend,
  mockCreateAnalysisThreadFromReport,
  mockGetBackendAnalysisSession,
} = vi.hoisted(() => ({
  mockAgentSend: vi.fn(),
  mockCreateAnalysisThreadFromReport: vi.fn(),
  mockGetBackendAnalysisSession: vi.fn(),
}));

vi.hoisted(() => {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

const savedReport: SavedInteractiveReport = {
  report: {
    ...interactiveReportFixture,
    id: "report_draft_context",
    title: "抖音销售日报",
    source: undefined,
    originType: "seed",
  },
  savedAt: "2026-08-05T10:00:00.000Z",
};

vi.mock("next-auth/react", () => ({
  useSession: () => ({ data: { user: { id: "owner_1" } } }),
}));

vi.mock("../src/modules/analysis/agentClients", () => ({
  getAgentClient: () => ({
    send: mockAgentSend,
    cancel: vi.fn(),
  }),
}));

vi.mock("../src/modules/analysis/agentClients/backendClient", () => ({
  shouldUseBackendAnalysisClient: () => true,
  listBackendAnalysisSessions: () => Promise.resolve([]),
  getBackendAnalysisSession: mockGetBackendAnalysisSession,
  flowNodesFromBackendSession: () => [],
  deleteBackendAnalysisSession: () => Promise.resolve(),
}));

vi.mock("../src/modules/analysis/api/interactive-report-service", () => ({
  shouldUseBackendInteractiveReports: () => true,
  listReportCenterFromBackend: () => Promise.resolve({ mine: [savedReport], sharedWithMe: [] }),
  listInteractiveReportsByThreadFromBackend: () => Promise.resolve([]),
  saveInteractiveReportToBackend: vi.fn(),
  createAnalysisThreadFromReportBackend: mockCreateAnalysisThreadFromReport,
}));

import { AnalysisWorkspace } from "../src/modules/analysis/components/AnalysisWorkspace";

afterEach(() => {
  mockAgentSend.mockReset();
  mockCreateAnalysisThreadFromReport.mockReset();
  mockGetBackendAnalysisSession.mockReset();
  window.history.replaceState({}, "", "/");
});

test("opens a report-backed draft and creates the Codex session with the first question", async () => {
  mockCreateAnalysisThreadFromReport.mockResolvedValue({
    thread: {
      id: "premature_empty_thread",
      title: "抖音销售日报 新会话",
      status: "active",
      createdAt: "2026-08-05T10:00:00.000Z",
      updatedAt: "2026-08-05T10:00:00.000Z",
    },
    saved: savedReport,
  });
  mockGetBackendAnalysisSession.mockResolvedValue({
    session: {
      id: "codex_report_session",
      title: "抖音销售日报 新会话",
      status: "active",
      createdAt: "2026-08-05T10:01:00.000Z",
      updatedAt: "2026-08-05T10:01:00.000Z",
      metadata: { initial_report_artifact: savedReport.report },
    },
    turns: [],
    codexItemProjections: [],
  });
  mockAgentSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
    yield {
      type: "session/created",
      sessionId: "codex_report_session",
      codexThreadId: "codex_report_session",
    };
    yield {
      type: "user",
      nodeId: "user-report-question",
      content: input.kind === "start" ? String(input.question) : "",
    };
    yield { type: "done" };
  });

  render(<AnalysisWorkspace />);

  fireEvent.click(screen.getByRole("button", { name: "报表中心" }));
  await screen.findByRole("heading", { name: "抖音销售日报" });
  fireEvent.click(screen.getByRole("button", { name: "新建会话" }));

  await waitFor(() => {
    expect(screen.getByLabelText("分析结果")).toBeTruthy();
    expect(window.location.pathname).toBe("/analysis/new");
  });
  expect(mockCreateAnalysisThreadFromReport).not.toHaveBeenCalled();

  const question = "哪一天的 GMV 最高？";
  fireEvent.change(
    screen.getByPlaceholderText("输入待解决的业务问题，按回车发送"),
    { target: { value: question } },
  );
  fireEvent.click(screen.getByRole("button", { name: "发送" }));

  await waitFor(() => expect(mockAgentSend).toHaveBeenCalled());
  expect(mockAgentSend.mock.calls[0][0]).toEqual({
    kind: "start",
    question,
    sessionId: null,
    context: { sourceReportId: "report_draft_context" },
  });
  await waitFor(() => expect(window.location.pathname).toBe("/analysis/codex_report_session"));
});
