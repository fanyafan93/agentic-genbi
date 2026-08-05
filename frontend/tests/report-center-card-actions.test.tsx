/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
import type { SavedReport } from "../src/modules/analysis/types/report";
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

afterEach(cleanup);

describe("report center cards", () => {
  test("renders compact report cards and opens the real report preview", () => {
    render(<MyAnalysisPage reports={[savedReport]} sharedReports={[]} onOpenReport={vi.fn()} onCreateAnalysis={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "渠道销售概览" })).toBeTruthy();
    expect(screen.queryByText("交互式报告")).toBeNull();
    expect(screen.queryByText(/行数据/)).toBeNull();
    expect(screen.queryByText(/个图表/)).toBeNull();
    expect(screen.queryByText(/个表格/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "预览" }));

    expect(screen.getByRole("dialog", { name: "报表预览" })).toBeTruthy();
    expect(screen.getByLabelText("分析结果")).toBeTruthy();
    expect(screen.getByText("这是保存后的真实报表内容。")).toBeTruthy();
  });

  test("shows return and new-session actions for a report with a source session", () => {
    const onOpenReport = vi.fn();
    const onCreateAnalysis = vi.fn();
    const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
    render(<MyAnalysisPage reports={[savedReport]} sharedReports={[]} onOpenReport={onOpenReport} onCreateAnalysis={onCreateAnalysis} />);

    fireEvent.click(screen.getByRole("button", { name: "回到会话" }));
    expect(onOpenReport).toHaveBeenCalledWith(savedReport);

    fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(onCreateAnalysis).toHaveBeenCalledWith(savedReport);

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(alert).toHaveBeenCalledWith("删除功能待接入后端。");
  });

  test("shows only new-session action for a report without a source session", () => {
    const onOpenReport = vi.fn();
    const onCreateAnalysis = vi.fn();
    const seedReport: SavedReport = {
      ...savedReport,
      report: {
        ...savedReport.report,
        sourceSessionId: null,
      },
    };

    render(<MyAnalysisPage reports={[seedReport]} sharedReports={[]} onOpenReport={onOpenReport} onCreateAnalysis={onCreateAnalysis} />);

    expect(screen.queryByRole("button", { name: "回到会话" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "新建会话" }));
    expect(onCreateAnalysis).toHaveBeenCalledWith(seedReport);
    expect(onOpenReport).not.toHaveBeenCalled();
  });
});
