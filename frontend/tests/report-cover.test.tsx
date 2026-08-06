/**
 * @vitest-environment jsdom
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { ReportCover } from "../src/modules/analysis/components/ReportCover";
import { reportFixture } from "./fixtures/report";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("renders a multi-column report blueprint without runtime queries", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const report = {
    ...reportFixture,
    title: "多栏经营看板",
    filters: {
      date: { type: "date" as const, label: "日期" },
    },
    charts: {
      bars: {
        queryId: "query-1",
        option: { series: [{ type: "bar" }] },
      },
      line: {
        queryId: "query-2",
        option: { series: [{ type: "line" }] },
      },
    },
    tables: {
      detail: { queryId: "query-3", options: {} },
    },
    layout: {
      root: { props: {} },
      content: [
        { type: "FilterBlock", props: { id: "filters", filterIds: ["date"], columnSpan: 12 } },
        { type: "ChartBlock", props: { id: "bars", chartId: "bars", columnSpan: 4 } },
        { type: "ChartBlock", props: { id: "line", chartId: "line", columnSpan: 8 } },
        { type: "TableBlock", props: { id: "table", tableId: "detail", columnSpan: 12 } },
      ],
      zones: {},
    },
  };

  render(<ReportCover report={report} />);

  expect(screen.getByLabelText("多栏经营看板 报表封面")).toBeTruthy();
  expect(screen.getByTestId("report-cover-filter").style.gridColumn).toBe("span 12");
  expect(screen.getByTestId("report-cover-chart-bars").style.gridColumn).toBe("span 4");
  expect(screen.getByTestId("report-cover-chart-line").style.gridColumn).toBe("span 8");
  expect(screen.getByTestId("report-cover-table").style.gridColumn).toBe("span 12");
  expect(screen.getByTestId("report-cover-chart-bars").getAttribute("data-chart-kind")).toBe("bar");
  expect(screen.getByTestId("report-cover-chart-line").getAttribute("data-chart-kind")).toBe("line");
  expect(fetch).not.toHaveBeenCalled();
});
