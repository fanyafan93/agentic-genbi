/**
 * @vitest-environment jsdom
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

vi.hoisted(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="chart" />,
}));

vi.mock("@visactor/react-vtable", () => ({
  ListTable: () => <div data-testid="table" />,
}));

import { ReportPanel } from "../src/modules/analysis/components/ReportPanel";

afterEach(cleanup);

describe("Report empty state", () => {
  test("presents an intentional report preview without a result header before a Report exists", () => {
    const view = render(<ReportPanel taskTitle="渠道销售占比分析" running={false} />);

    expect(view.container.textContent).toContain("你的下一次分析，在这里。");
    expect(view.container.textContent).toContain("指标、图表和明细会随着分析结果在这里展开");
    expect(view.container.textContent).not.toContain("INTERACTIVE RESULT");
    expect(view.container.textContent).not.toContain("暂无分析结果");
    expect(view.container.textContent).not.toContain("当前分析任务");
    expect(view.container.textContent).not.toContain("当前任务尚无报告");
    expect(view.container.textContent).not.toContain("渠道销售结构与增长分析");
    expect(view.container.querySelector(".result-panel-header")).toBeNull();
    expect(view.container.querySelector(".report-empty-preview")).not.toBeNull();
    expect(view.container.querySelector(".report-canvas")).toBeNull();
  });

  test("keeps the live analysis status in the headerless report area", () => {
    const view = render(<ReportPanel taskTitle="渠道销售占比分析" running />);

    expect(view.container.textContent).toContain("分析进行中");
    expect(view.container.querySelector(".result-panel-header")).toBeNull();
    expect(view.container.querySelector(".report-awaiting-spinner")).not.toBeNull();
  });
});
