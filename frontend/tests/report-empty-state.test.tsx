/**
 * @vitest-environment jsdom
 */
import { cleanup, render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

  test("keeps the default report blueprint while analysis runs without a Report", () => {
    const view = render(<ReportPanel taskTitle="渠道销售占比分析" running />);

    expect(view.container.textContent).toContain("你的下一次分析，在这里。");
    expect(view.container.textContent).toContain("指标、图表和明细会随着分析结果在这里展开");
    expect(view.container.textContent).not.toContain("分析进行中");
    expect(view.container.textContent).not.toContain("指标、图表和明细将在分析完成后呈现");
    expect(view.container.querySelector(".result-panel-header")).toBeNull();
    expect(view.container.querySelector(".report-awaiting-spinner")).toBeNull();
    expect(view.container.querySelector(".report-empty-preview")).not.toBeNull();
  });

  test("keeps the idle report area visually continuous with the result pane", () => {
    const styles = readFileSync(
      resolve(process.cwd(), "src/app/globals.css"),
      "utf8",
    );

    expect(styles).toMatch(
      /\.report-awaiting-body\.is-idle\s*\{[^}]*background:\s*transparent/,
    );
    expect(styles).toMatch(
      /\.report-awaiting-body\.is-idle::after\s*\{[^}]*display:\s*none/,
    );
    expect(styles).toMatch(
      /\.report-panel\.report-awaiting\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)/,
    );
  });
});
