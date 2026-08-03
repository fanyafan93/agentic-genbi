/**
 * @vitest-environment jsdom
 */
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { InteractiveReportPanel } from "../src/modules/analysis/components/InteractiveReportPanel";
import type { InteractiveReport } from "../src/modules/analysis/types/interactive-report";

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

afterEach(cleanup);

describe("interactive report Puck ids", () => {
  test("adds stable ids to legacy report blocks before rendering", () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    const report: InteractiveReport = {
      artifactType: "interactive_report",
      schemaVersion: "1.0",
      id: "report_legacy_no_ids",
      title: "遗留报告",
      subtitle: "缺少 Puck block id",
      renderer: "puck",
      document: {
        root: { props: { title: "遗留报告" } },
        content: [
          { type: "SectionBlock", props: { title: "本期结论", tone: "coral" } },
          { type: "MarkdownBlock", props: { content: "结论正文" } },
        ],
        zones: {},
      },
      filters: [],
      queries: {},
      chartSpecs: {},
      gridSpecs: {},
      datasets: {},
      source: { threadId: "thread_legacy", turnId: "turn_legacy" },
    };

    render(<InteractiveReportPanel taskTitle="遗留任务" running={false} initialReport={report} />);

    const keyWarnings = consoleError.mock.calls.filter((call) => call.join(" ").includes("unique \"key\" prop"));
    expect(keyWarnings).toHaveLength(0);
    consoleError.mockRestore();
  });
});
