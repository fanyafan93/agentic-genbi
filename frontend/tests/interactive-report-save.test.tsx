/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("InteractiveReportPanel save report", () => {
  test("asks for confirmation before saving a report to the report center", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const onSaveReport = vi.fn(async (saved) => ({
      ...saved,
      version: 2,
      savedAt: "2026-08-04T10:00:00+08:00",
    }));

    render(
      <InteractiveReportPanel
        taskTitle="分析任务"
        running={false}
        initialReport={interactiveReportFixture}
        initialVersion={1}
        onSaveReport={onSaveReport}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("报表中心"));
    await waitFor(() => expect(onSaveReport).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("已保存到报表中心。")).toBeTruthy();
    expect(await screen.findByText("已保存到报表中心")).toBeTruthy();
  });

  test("does not save the report when confirmation is cancelled", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const onSaveReport = vi.fn();

    render(
      <InteractiveReportPanel
        taskTitle="分析任务"
        running={false}
        initialReport={interactiveReportFixture}
        initialVersion={1}
        onSaveReport={onSaveReport}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    expect(onSaveReport).not.toHaveBeenCalled();
  });
});
