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

import { MyAnalysisPage } from "../src/modules/analysis/components/MyAnalysisPage";
import type { SavedInteractiveReport } from "../src/modules/analysis/api/interactive-report-service";
import { interactiveReportFixture } from "./fixtures/interactive-report";

const savedReport: SavedInteractiveReport = {
  report: {
    ...interactiveReportFixture,
    title: "渠道销售概览",
    subtitle: "按渠道聚合",
    document: {
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
  version: 1,
  savedAt: "2026-08-04T10:00:00+08:00",
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

  test("routes report actions without calling delete backend", () => {
    const onOpenReport = vi.fn();
    const onCreateAnalysis = vi.fn();
    const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
    render(<MyAnalysisPage reports={[savedReport]} sharedReports={[]} onOpenReport={onOpenReport} onCreateAnalysis={onCreateAnalysis} />);

    fireEvent.click(screen.getByRole("button", { name: "回到原任务" }));
    expect(onOpenReport).toHaveBeenCalledWith(savedReport);

    fireEvent.click(screen.getByRole("button", { name: "新建分析" }));
    expect(onCreateAnalysis).toHaveBeenCalledWith(savedReport);

    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    expect(alert).toHaveBeenCalledWith("删除功能待接入后端。");
  });
});
