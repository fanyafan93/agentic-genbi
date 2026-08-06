import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import {
  buildEChartsOption,
  ReportPanel,
} from "../src/modules/analysis/components/ReportPanel";
import { buildVTableOption } from "../src/modules/analysis/components/ReportTable";
import {
  executeReportQuery,
  exportReportTable,
} from "../src/modules/analysis/api/report-service";
import type { Report } from "../src/modules/analysis/types/report";
import { reportFixture } from "./fixtures/report";
import "../src/app/globals.css";

const {
  emitVTableScrollMock,
  setScrollLeftMock,
  setScrollTopMock,
  vtableInstanceMock,
} = vi.hoisted(() => {
  const setScrollLeft = vi.fn();
  const setScrollTop = vi.fn();
  let scrollListener:
    | ((event: {
      scrollHeight: number;
      scrollLeft: number;
      scrollTop: number;
      scrollWidth: number;
    }) => void)
    | null = null;
  return {
    emitVTableScrollMock: (event: {
      scrollHeight: number;
      scrollLeft: number;
      scrollTop: number;
      scrollWidth: number;
    }) => scrollListener?.(event),
    setScrollLeftMock: setScrollLeft,
    setScrollTopMock: setScrollTop,
    vtableInstanceMock: {
      getAllColsWidth: () => 2400,
      getAllRowsHeight: () => 1600,
      on: vi.fn((
        _eventName: string,
        listener: typeof scrollListener,
      ) => {
        scrollListener = listener;
        return 1;
      }),
      off: vi.fn(),
      get scrollLeft() {
        return 0;
      },
      set scrollLeft(value: number) {
        setScrollLeft(value);
      },
      get scrollTop() {
        return 0;
      },
      set scrollTop(value: number) {
        setScrollTop(value);
      },
    },
  };
});

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
  ListTable: ({
    height,
    onReady,
    onDropdownMenuClick,
    option,
  }: {
    height?: number;
    onReady?: (instance: unknown, isInitial: boolean) => void;
    option?: { records?: Array<Record<string, unknown>> };
    onDropdownMenuClick?: (event: {
      field: string;
      menuKey: string;
    }) => void;
  }) => {
    onReady?.(vtableInstanceMock, true);
    return (
      <>
      <div
        data-testid="vtable-native"
        data-height={height}
        data-record-count={option?.records?.length ?? 0}
      />
      {onDropdownMenuClick ? (
        <button
          type="button"
          onClick={() => onDropdownMenuClick({
            field: "amount",
            menuKey: "sort:desc",
          })}
        >
          sort amount descending
        </button>
      ) : null}
      </>
    );
  },
  PivotTable: ({
    height,
    onReady,
    option,
  }: {
    height?: number;
    onReady?: (instance: unknown, isInitial: boolean) => void;
    option?: { records?: Array<Record<string, unknown>> };
  }) => {
    onReady?.(vtableInstanceMock, true);
    return (
      <div
        data-testid="vtable-pivot"
        data-height={height}
        data-record-count={option?.records?.length ?? 0}
      />
    );
  },
}));

vi.mock("../src/modules/analysis/api/report-service", () => ({
  executeReportBuildQuery: vi.fn(),
  executeReportQuery: vi.fn(),
  exportReportTable: vi.fn(),
}));

const executeQueryMock = vi.mocked(executeReportQuery);
const exportTableMock = vi.mocked(exportReportTable);

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
  setScrollLeftMock.mockClear();
  setScrollTopMock.mockClear();
  executeQueryMock.mockReset();
  exportTableMock.mockReset();
  exportTableMock.mockResolvedValue({
    blob: new Blob(["xlsx"]),
    filename: "渠道销售-sales-table.xlsx",
  });
  executeQueryMock.mockResolvedValue({
    columns: [],
    rows: [{ region: "华东", amount: 1 }],
    page: 1,
    pageSize: 50,
    total: 1,
  });
});

test("exports only explicitly configured saved list tables", async () => {
  const exportableReport: Report = {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "TableBlock",
          props: { id: "table", tableId: "sales-table" },
        },
      ],
      zones: {},
    },
    charts: {},
    tables: {
      "sales-table": {
        type: "list",
        queryId: "sales-query",
        exportColumns: [
          { field: "region", title: "区域", type: "text" },
          { field: "amount", title: "销售额", type: "number" },
        ],
        options: {
          columns: [
            { field: "region", title: "区域" },
            { field: "amount", title: "销售额", sortable: true },
          ],
        },
      },
    },
    queries: {
      "sales-query": {
        ...reportFixture.queries["sales-query"],
        controls: {
          sortableFields: ["amount"],
          filterableFields: [],
        },
      },
    },
  };
  const createObjectUrl = vi.fn(() => "blob:report-export");
  const revokeObjectUrl = vi.fn();
  const clickDownload = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: createObjectUrl,
    revokeObjectURL: revokeObjectUrl,
  });

  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={exportableReport}
    />,
  );

  await screen.findByTestId("vtable-native");
  fireEvent.click(screen.getByRole("button", {
    name: "sort amount descending",
  }));
  await waitFor(() => expect(
    executeQueryMock.mock.calls.at(-1)?.[2],
  ).toMatchObject({ sort: { field: "amount", direction: "desc" } }));
  fireEvent.click(screen.getByRole("button", { name: "导出 Excel" }));

  await waitFor(() => expect(exportTableMock).toHaveBeenCalledWith(
    reportFixture.id,
    "sales-table",
    {
      filters: { region: "华东" },
      sort: { field: "amount", direction: "desc" },
      columnFilters: {},
    },
  ));
  expect(createObjectUrl).toHaveBeenCalledTimes(1);
  expect(clickDownload).toHaveBeenCalledTimes(1);
  expect(revokeObjectUrl).toHaveBeenCalledWith("blob:report-export");

  clickDownload.mockRestore();
});

test("does not offer Excel export without exportColumns", async () => {
  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={reportFixture}
    />,
  );

  await screen.findByTestId("vtable-native");
  expect(screen.queryByRole("button", { name: "导出 Excel" })).toBeNull();
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
  expect(
    screen.getAllByTestId("vtable-native").map(
      (element) => element.getAttribute("data-height"),
    ),
  ).toEqual(["360", "360"]);
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

test("keeps configured column widths and delegates scrolling to native bars", () => {
  const option = buildVTableOption(
    {
      columns: [
        {
          field: "region",
          title: "区域",
          width: 240,
          sortable: true,
          filterOptions: [
            { label: "华东", value: "华东" },
            { label: "华南", value: "华南" },
          ],
        },
      ],
      widthMode: "adaptive",
    },
    [{ region: "华东" }],
  );

  expect(option.widthMode).toBe("standard");
  expect(option.theme).toMatchObject({
    scrollStyle: {
      horizontalVisible: "none",
      verticalVisible: "none",
      barToSide: true,
    },
  });
  expect(option.columns).toEqual([
    expect.objectContaining({
      field: "region",
      width: 240,
      dropDownMenu: expect.arrayContaining([
        expect.objectContaining({ menuKey: "sort:asc" }),
        expect.objectContaining({ menuKey: "filter:%E5%8D%8E%E4%B8%9C" }),
      ]),
    }),
  ]);
});

test("renders draggable native scrollbars that control VTable", async () => {
  render(
    <ReportPanel
      taskTitle="Sales"
      running={false}
      initialReport={multiComponentReport()}
    />,
  );

  const horizontalBars = await screen.findAllByLabelText(
    "table horizontal scrollbar",
  );
  const verticalBars = screen.getAllByLabelText(
    "table vertical scrollbar",
  );
  fireEvent.scroll(horizontalBars[0], {
    target: { scrollLeft: 320 },
  });
  fireEvent.scroll(verticalBars[0], {
    target: { scrollTop: 480 },
  });

  expect(setScrollLeftMock).toHaveBeenCalledWith(320);
  expect(setScrollTopMock).toHaveBeenCalledWith(480);
});

test("does not collapse native scroll ranges on viewport-sized VTable events", async () => {
  const singleTableReport: Report = {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "TableBlock",
          props: { id: "table", tableId: "sales-table" },
        },
      ],
      zones: {},
    },
  };
  render(
    <ReportPanel
      taskTitle="Sales"
      running={false}
      initialReport={singleTableReport}
    />,
  );

  const horizontalBar = await screen.findByLabelText(
    "table horizontal scrollbar",
  );
  const verticalBar = screen.getByLabelText(
    "table vertical scrollbar",
  );
  await waitFor(() => {
    expect(horizontalBar.firstElementChild?.getAttribute("style"))
      .toContain("width: 2400px");
    expect(verticalBar.firstElementChild?.getAttribute("style"))
      .toContain("height: 1600px");
  });

  act(() => emitVTableScrollMock({
    scrollHeight: 400,
    scrollLeft: 300,
    scrollTop: 0,
    scrollWidth: 600,
  }));

  expect(horizontalBar.firstElementChild?.getAttribute("style"))
    .toContain("width: 2400px");
  expect(verticalBar.firstElementChild?.getAttribute("style"))
    .toContain("height: 1600px");
});

test("changes page size and sends column sorting to the backend", async () => {
  const controlledReport: Report = {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "TableBlock",
          props: { id: "table", tableId: "sales-table" },
        },
      ],
      zones: {},
    },
    tables: {
      "sales-table": {
        queryId: "sales-query",
        options: {
          columns: [
            {
              field: "amount",
              title: "销售额",
              width: 220,
              sortable: true,
            },
          ],
        },
      },
    },
    queries: {
      "sales-query": {
        ...reportFixture.queries["sales-query"],
        pagination: true,
        controls: {
          sortableFields: ["amount"],
          filterableFields: [],
        },
      },
    },
  };
  executeQueryMock.mockImplementation(async (
    _reportId,
    _queryId,
    request,
  ) => ({
    columns: [],
    rows: [{ amount: 1200 }],
    page: request.page ?? 1,
    pageSize: request.pageSize ?? 50,
    total: 100,
  }));

  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={controlledReport}
    />,
  );

  await screen.findByTestId("vtable-native");
  fireEvent.mouseDown(screen.getByLabelText("每页条数"));
  fireEvent.click(await screen.findByText("20 条/页"));
  await waitFor(() => expect(
    executeQueryMock.mock.calls.at(-1)?.[2],
  ).toMatchObject({ page: 1, pageSize: 20 }));

  fireEvent.click(screen.getByRole("button", {
    name: "sort amount descending",
  }));
  await waitFor(() => expect(
    executeQueryMock.mock.calls.at(-1)?.[2],
  ).toMatchObject({
    page: 1,
    pageSize: 20,
    sort: { field: "amount", direction: "desc" },
  }));
});

test("keeps the current table visible while the next page loads", async () => {
  const pagedReport: Report = {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "TableBlock",
          props: { id: "table", tableId: "sales-table" },
        },
      ],
      zones: {},
    },
    charts: {},
    queries: {
      "sales-query": {
        ...reportFixture.queries["sales-query"],
        pagination: true,
      },
    },
  };
  let resolveSecondPage: (
    value: Awaited<ReturnType<typeof executeReportQuery>>,
  ) => void = () => {};
  executeQueryMock.mockImplementation(async (
    _reportId,
    _queryId,
    request,
  ) => {
    if ((request.page ?? 1) === 1) {
      return {
        columns: [],
        rows: [{ region: "华东", amount: 1 }],
        page: 1,
        pageSize: 50,
        total: 100,
      };
    }
    return new Promise((resolve) => {
      resolveSecondPage = resolve;
    });
  });

  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={pagedReport}
    />,
  );

  const table = await screen.findByTestId("vtable-native");
  const nextPage = screen.getByRole("button", { name: "下一页" });
  fireEvent.click(nextPage);
  await waitFor(() => expect(
    executeQueryMock.mock.calls.at(-1)?.[2],
  ).toMatchObject({ page: 2, pageSize: 50 }));

  expect(screen.getByTestId("vtable-native")).toBe(table);
  expect(
    screen.getByTestId("vtable-native").getAttribute("data-record-count"),
  ).toBe("1");
  expect(screen.getByRole("status").textContent).toContain("正在加载第 2 页");
  expect((nextPage as HTMLButtonElement).disabled).toBe(true);

  resolveSecondPage({
    columns: [],
    rows: [{ region: "华南", amount: 2 }],
    page: 2,
    pageSize: 50,
    total: 100,
  });
  await screen.findByText("2 / 2");
  expect(screen.queryByText("正在加载第 2 页")).toBeNull();
});

test("renders VTable pivot configuration for complex cross tables", async () => {
  const pivotReport: Report = {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "TableBlock",
          props: { id: "pivot", tableId: "status-pivot" },
        },
      ],
      zones: {},
    },
    charts: {},
    tables: {
      "status-pivot": {
        type: "pivot",
        queryId: "sales-query",
        options: {
          rows: [{ dimensionKey: "region", title: "区域" }],
          columns: [{ dimensionKey: "channel", title: "渠道" }],
          indicators: [
            { indicatorKey: "amount", title: "销售额" },
          ],
        },
      },
    },
  };

  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={pivotReport}
    />,
  );

  expect(await screen.findByTestId("vtable-pivot")).toBeTruthy();
  expect(screen.queryByTestId("vtable-native")).toBeNull();
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

test("keeps Report filters visible inside report-center preview", async () => {
  render(
    <div className="report-preview-body">
      <ReportPanel
        taskTitle="销售"
        running={false}
        initialReport={reportFixture}
      />
    </div>,
  );

  const filterRow = await screen.findByLabelText("报告筛选条件");
  expect(getComputedStyle(filterRow).display).toBe("flex");
});

test("spans Report filters and tables across the Puck grid", async () => {
  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={reportFixture}
    />,
  );

  const filterRow = await screen.findByLabelText("报告筛选条件");
  const tableBlock = await screen.findByTestId("report-table");

  expect(filterRow.style.gridColumn).toBe("1 / -1");
  expect(tableBlock.style.gridColumn).toBe("1 / -1");
});

test("uses explicit twelve-column spans for multi-column reports", async () => {
  const multiColumnReport: Report = {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "ChartBlock",
          props: {
            id: "chart",
            chartId: "sales-chart",
            columnSpan: 6,
          },
        },
        {
          type: "TableBlock",
          props: {
            id: "table",
            tableId: "sales-table",
            columnSpan: 6,
          },
        },
      ],
      zones: {},
    },
  };

  render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={multiColumnReport}
    />,
  );

  const chartBlock = await screen.findByTestId("report-chart");
  const tableBlock = await screen.findByTestId("report-table");
  expect(chartBlock.style.gridColumn).toBe("span 6");
  expect(tableBlock.style.gridColumn).toBe("span 6");
});

test("gives date-range filters enough width to show both dates", async () => {
  const reportWithDateRange: Report = {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "FilterBlock",
          props: { id: "filters", filterIds: ["date_range"] },
        },
      ],
      zones: {},
    },
    filters: {
      date_range: {
        type: "dateRange",
        label: "日期范围",
        defaultValue: ["2026-07-05", "2026-08-03"],
      },
    },
  };
  const { container } = render(
    <ReportPanel
      taskTitle="销售"
      running={false}
      initialReport={reportWithDateRange}
    />,
  );

  await screen.findByLabelText("报告筛选条件");
  const rangePicker = container.querySelector<HTMLElement>(
    ".ant-picker-range",
  );

  expect(rangePicker?.style.width).toBe("280px");
  expect(rangePicker?.style.maxWidth).toBe("100%");
});
