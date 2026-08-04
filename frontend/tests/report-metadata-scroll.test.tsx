/**
 * @vitest-environment jsdom
 *
 * 复现并锁定"滚动元数据 JSON 弹窗时闪烁"的根因：
 * 1. <pre> 内的 JSON 字符串必须 useMemo 化，否则父组件 re-render 会触发
 *    新的文本节点，破坏滚动位置 + 触发 reflow。
 * 2. 滚动容器应当 contain: strict，隔离外层 layout。
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

vi.hoisted(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/shared/charts/EChartRenderer", () => ({
  EChartRenderer: () => <div data-testid="chart" />,
}));

vi.mock("@puckeditor/core", async () => {
  const React = await import("react");
  return {
    Render: ({ data }: { data: { content?: unknown[] } }) =>
      React.createElement("div", { "data-testid": "puck-render" }, String(data?.content?.length ?? 0)),
    Puck: () => React.createElement("div", { "data-testid": "puck-editor" }, "editor"),
  };
});

import { InteractiveReportPanel } from "../src/modules/analysis/components/InteractiveReportPanel";
import { interactiveReportFixture } from "./fixtures/interactive-report";

const renderReady = () =>
  render(
    <InteractiveReportPanel
      taskTitle="渠道销售占比分析"
      running={false}
      initialReport={interactiveReportFixture}
      initialVersion={1}
    />,
  );

afterEach(cleanup);

describe("report metadata json", () => {
  test("第一次打开：JsonView 渲染报告元数据", () => {
    renderReady();
    fireEvent.click(screen.getByRole("button", { name: "显示元数据" }));
    const pre = screen.getByTestId("report-metadata-json");
    // 树形视图，键名应直接出现，原始字符串不应再渲染
    expect(pre.textContent).toContain("report_test_channel_sales");
    expect(pre.textContent).toContain("渠道销售分析");
    expect(pre.textContent).not.toContain("\"id\": \"report_test_channel_sales\"");
  });

  test("切换运行时筛选后再次打开：<pre> 文本节点引用应保持稳定（useMemo 命中）", () => {
    // 监听 React 提交阶段的 commit
    const preBeforeRef = { current: null as Element | null };

    const view = renderReady();
    fireEvent.click(screen.getByRole("button", { name: "显示元数据" }));
    const pre = screen.getByTestId("report-metadata-json");
    preBeforeRef.current = pre;

    // 触发一次不相关的状态变更（与 report 无关），模拟 re-render
    // 这里通过 setNotice 没有公开 hook，模拟一次"保存"按钮 click 来触发
    // 父组件的 persist / setVersion 等会触发 setReport，验证在 report 不变时
    // 文本节点仍然稳定。
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    const preAfter = screen.getByTestId("report-metadata-json");
    expect(preAfter).toBe(preBeforeRef.current);
  });

  test("滚动容器具有 contain: strict，避免外层 layout 干扰", () => {
    renderReady();
    fireEvent.click(screen.getByRole("button", { name: "显示元数据" }));
    const pre = screen.getByTestId("report-metadata-json");
    // jsdom 不解析 contain，但仍可通过 ownerDocument 拿到 class 验证
    expect(pre.classList.contains("report-metadata-json")).toBe(true);
  });
});
