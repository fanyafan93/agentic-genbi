import { render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import {
  buildEChartsOption,
  ReportPanel,
} from "../src/modules/analysis/components/ReportPanel";
import { buildVTableOption } from "../src/modules/analysis/components/ReportTable";
import { executeReportQuery } from "../src/modules/analysis/api/report-service";
import type { Report } from "../src/modules/analysis/types/report";
import { reportFixture } from "./fixtures/report";

vi.hoisted(() => {
  globalThis.ResizeObserver = class {
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

vi.mock("../src/modules/analysis/api/report-service", () => ({
  executeReportQuery: vi.fn(),
}));

const executeQueryMock = vi.mocked(executeReportQuery);

function multiComponentReport(): Report {
  return {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "ChartBlock",
          props: { id: "chart-1", chartId: "sales-chart" },
        },
        {
          type: "ChartBlock",
          props: { id: "chart-2", chartId: "detail-chart" },
        },
        {
          type: "TableBlock",
          props: { id: "table-1", tableId: "sales-table" },
        },
        {
          type: "TableBlock",
          props: { id: "table-2", tableId: "detail-table" },
        },
      ],
      zones: {},
    },
    charts: {
      ...reportFixture.charts,
      "detail-chart": {
        queryId: "detail-query",
        option: { series: [{ type: "line" }] },
      },
    },
    tables: {
      ...reportFixture.tables,
      "detail-table": {
        queryId: "detail-query",
        options: {
          columns: [{ field: "region", title: "区域" }],
        },
      },
    },
    queries: {
      ...reportFixture.queries,
      "detail-query": {
        ...reportFixture.queries["sales-query"],
        pagination: true,
      },
    },
  };
}

beforeEach(() => {
  executeQueryMock.mockReset();
  executeQueryMock.mockResolvedValue({
    columns: [],
    rows: [{ region: "华东", amount: 1 }],
    page: 1,
    pageSize: 50,
    total: 1,
  });
});

test("renders multiple charts and tables from Puck ID references", async () => {
  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={multiComponentReport()}
    />,
  );

  expect(await screen.findAllByTestId("report-chart")).toHaveLength(2);
  expect(await screen.findAllByTestId("report-table")).toHaveLength(2);
  expect(screen.getAllByTestId("echarts-native")).toHaveLength(2);
  expect(screen.getAllByTestId("vtable-native")).toHaveLength(2);
});

test("injects rows into native ECharts dataset and VTable records", () => {
  expect(
    buildEChartsOption(
      { series: [] },
      [{ region: "华东", amount: 1 }],
    ),
  ).toEqual({
    dataset: { source: [{ region: "华东", amount: 1 }] },
    series: [],
  });
  expect(
    buildVTableOption(
      { columns: [{ field: "region", title: "区域" }] },
      [{ region: "华东" }],
    ).records,
  ).toEqual([{ region: "华东" }]);
});

test("renders only the empty Report state when no Report exists", () => {
  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
    />,
  );

  expect(screen.getByText("你的下一次分析，在这里。")).toBeTruthy();
  expect(screen.queryByTestId("report-chart")).toBeNull();
});
