/**
 * @vitest-environment jsdom
 */
import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

vi.hoisted(() => {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echarts-native" />,
}));

vi.mock("@visactor/react-vtable", () => ({
  ListTable: () => <div data-testid="vtable-native" />,
}));

import { MyAnalysisPage } from "../src/modules/analysis/components/MyAnalysisPage";
import type { SavedReport, SharedReport } from "../src/modules/analysis/types/report";
import { reportFixture } from "./fixtures/report";

const savedReport: SavedReport = {
  report: {
    ...reportFixture,
    title: "渠道销售概览",
    subtitle: "按渠道聚合",
    sourceSessionId: "session-source",
    layout: {
      root: { props: { title: "渠道销售概览" } },
      content: [
        {
          type: "MarkdownBlock",
          props: {
            id: "summary",
            content: "这是保存后的真实报表内容。",
          },
        },
      ],
      zones: {},
    },
  },
};

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderPage(
  options: {
    reports?: SavedReport[];
    sharedReports?: SharedReport[];
    exampleReports?: SavedReport[];
    onOpenReport?: (saved: SavedReport) => boolean | Promise<boolean>;
    onCreateAnalysis?: (saved: SavedReport) => void | Promise<void>;
    onDeleteReport?: (saved: SavedReport) => Promise<void>;
  } = {},
) {
  return render(
    <MyAnalysisPage
      reports={options.reports ?? [savedReport]}
      sharedReports={options.sharedReports ?? []}
      exampleReports={options.exampleReports ?? []}
      onOpenReport={options.onOpenReport ?? vi.fn().mockResolvedValue(true)}
      onCreateAnalysis={options.onCreateAnalysis ?? vi.fn()}
      onDeleteReport={options.onDeleteReport ?? vi.fn().mockResolvedValue(undefined)}
    />,
  );
}

describe("report center cards", () => {
  test("opens the real report from the card body without a preview action", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "渠道销售概览" })).toBeTruthy();
    expect(screen.getByText(`ID: ${savedReport.report.id}`)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "预览" })).toBeNull();
    expect(screen.queryByText("交互式报告")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "打开渠道销售概览" }));

    expect(screen.getByRole("dialog", { name: "报表预览" })).toBeTruthy();
    expect(screen.getByLabelText("分析结果")).toBeTruthy();
    expect(screen.getByText("这是保存后的真实报表内容。")).toBeTruthy();
  });

  test("runs card actions without also opening the report", async () => {
    const onOpenReport = vi.fn().mockResolvedValue(true);
    const onCreateAnalysis = vi.fn();
    renderPage({ onOpenReport, onCreateAnalysis });

    fireEvent.click(screen.getByRole("button", { name: "回到会话" }));
    await waitFor(() => expect(onOpenReport).toHaveBeenCalledWith(savedReport));
    expect(screen.queryByRole("dialog", { name: "报表预览" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(onCreateAnalysis).toHaveBeenCalledWith(savedReport);
    expect(screen.queryByRole("dialog", { name: "报表预览" })).toBeNull();
  });

  test("always shows return-to-session and explains a missing source", async () => {
    const onOpenReport = vi.fn().mockResolvedValue(true);
    const seedReport: SavedReport = {
      ...savedReport,
      report: { ...savedReport.report, sourceSessionId: null },
    };
    renderPage({ reports: [seedReport], onOpenReport });

    fireEvent.click(screen.getByRole("button", { name: "回到会话" }));

    expect((await screen.findByRole("status")).textContent).toContain("无关联会话或会话已经删除");
    expect(onOpenReport).not.toHaveBeenCalled();
  });

  test("explains when an associated session can no longer be opened", async () => {
    renderPage({ onOpenReport: vi.fn().mockResolvedValue(false) });

    fireEvent.click(screen.getByRole("button", { name: "回到会话" }));

    expect((await screen.findByRole("status")).textContent).toContain("无关联会话或会话已经删除");
  });

  test("removes an owned card after confirmed deletion", async () => {
    const onDeleteReport = vi.fn().mockResolvedValue(undefined);

    function Harness() {
      const [reports, setReports] = useState([savedReport]);
      return (
        <MyAnalysisPage
          reports={reports}
          sharedReports={[]}
          exampleReports={[]}
          onOpenReport={vi.fn().mockResolvedValue(true)}
          onCreateAnalysis={vi.fn()}
          onDeleteReport={async (saved) => {
            await onDeleteReport(saved);
            setReports((items) => items.filter((item) => item.report.id !== saved.report.id));
          }}
        />
      );
    }

    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "删除" }));

    const dialog = screen.getByRole("dialog", { name: "确认删除 Report" });
    expect(dialog.textContent).toContain("删除“渠道销售概览”？");
    expect(onDeleteReport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => expect(onDeleteReport).toHaveBeenCalledWith(savedReport));
    expect(screen.queryByRole("heading", { name: "渠道销售概览" })).toBeNull();
  });

  test("cancels deletion from the in-page confirmation dialog", () => {
    const onDeleteReport = vi.fn().mockResolvedValue(undefined);
    renderPage({ onDeleteReport });

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(screen.getByRole("dialog", { name: "确认删除 Report" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "取消" }));

    expect(screen.queryByRole("dialog", { name: "确认删除 Report" })).toBeNull();
    expect(onDeleteReport).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "渠道销售概览" })).toBeTruthy();
  });

  test("keeps the owned card and shows an error when deletion fails", async () => {
    renderPage({ onDeleteReport: vi.fn().mockRejectedValue(new Error("network")) });

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect((await screen.findByRole("alert")).textContent).toContain("删除失败，请稍后重试");
    expect(screen.getByRole("heading", { name: "渠道销售概览" })).toBeTruthy();
  });

  test("does not expose deletion for a shared report", () => {
    const shared: SharedReport = {
      ...savedReport,
      reportId: savedReport.report.id,
      recipientUserId: "user-2",
      permission: "view_and_reuse",
      createdAt: "2026-08-06T00:00:00Z",
    };

    renderPage({ reports: [], sharedReports: [shared] });

    expect(screen.queryByRole("button", { name: "删除" })).toBeNull();
    expect(screen.getByText(`ID: ${shared.report.id}`)).toBeTruthy();
    expect(screen.getByRole("button", { name: "回到会话" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "新建会话" })).toBeTruthy();
  });

  test("renders public examples with only new-session action", () => {
    const example: SavedReport = {
      report: {
        ...savedReport.report,
        id: "report_example_0123456789",
        title: "公开示例",
        isExample: true,
        sourceSessionId: null,
      },
    };

    renderPage({
      reports: [],
      exampleReports: [example],
    });

    const section = screen.getByRole("region", {
      name: "示例报表",
    });
    expect(section.textContent).toContain(
      "report_example_0123456789",
    );
    expect(section.querySelector("code")?.textContent).toBe(
      "ID: report_example_0123456789",
    );
    expect(
      screen.getByRole("button", { name: "新建会话" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "删除" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "回到会话" }),
    ).toBeNull();
  });
});
