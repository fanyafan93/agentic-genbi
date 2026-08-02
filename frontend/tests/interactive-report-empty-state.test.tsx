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

vi.mock("@/shared/charts/EChartRenderer", () => ({
  EChartRenderer: () => <div data-testid="chart" />,
}));

import { InteractiveReportPanel } from "../src/modules/analysis/components/InteractiveReportPanel";

afterEach(cleanup);

describe("interactive report empty state", () => {
  test("does not render a mock report before a real artifact exists", () => {
    const view = render(<InteractiveReportPanel taskTitle="渠道销售占比分析" running={false} />);

    expect(view.container.textContent).toContain("暂无分析结果");
    expect(view.container.textContent).not.toContain("渠道销售结构与增长分析");
    expect(view.container.querySelector(".report-canvas")).toBeNull();
  });
});
