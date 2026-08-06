import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import {
  ReportProvider,
  useReportContext,
} from "../src/modules/analysis/components/ReportContext";
import {
  executeReportBuildQuery,
  executeReportQuery,
} from "../src/modules/analysis/api/report-service";
import type { Report } from "../src/modules/analysis/types/report";
import { reportFixture } from "./fixtures/report";

vi.mock("../src/modules/analysis/api/report-service", () => ({
  executeReportBuildQuery: vi.fn(),
  executeReportQuery: vi.fn(),
}));

const executeQueryMock = vi.mocked(executeReportQuery);
const executeBuildQueryMock = vi.mocked(executeReportBuildQuery);

function runtimeReport(): Report {
  return {
    ...reportFixture,
    layout: {
      root: { props: {} },
      content: [
        {
          type: "ChartBlock",
          props: { id: "chart", chartId: "sales-chart" },
        },
        {
          type: "TableBlock",
          props: { id: "detail", tableId: "detail-table" },
        },
      ],
      zones: {},
    },
    tables: {
      ...reportFixture.tables,
      "detail-table": {
        queryId: "detail-query",
        options: { columns: [] },
      },
    },
    queries: {
      ...reportFixture.queries,
      "detail-query": {
        dataSource: "doris",
        sql: "SELECT region FROM sales WHERE region = :region",
        parameters: {
          region: { filterId: "region", type: "string" },
        },
        pagination: true,
      },
      "unrelated-query": {
        dataSource: "doris",
        sql: "SELECT 1",
        parameters: {},
        pagination: false,
      },
    },
  };
}

function ContextProbe() {
  const {
    queryStates,
    setFilterValue,
    executeQuery,
  } = useReportContext();
  return (
    <div>
      {Object.entries(queryStates).map(([queryId, state]) => (
        <div key={queryId}>
          <span>
            {queryId}:{state.error ? "error" : state.loading ? "loading" : "ready"}
            :{state.rows.length}
          </span>
          <output aria-label={`${queryId} controls`}>
            {state.pageSize}:{state.sort?.direction ?? "none"}:
            {Object.keys(state.columnFilters).join(",") || "none"}
          </output>
        </div>
      ))}
      <button
        type="button"
        onClick={() => setFilterValue("region", "华南")}
      >
        change region
      </button>
      <button
        type="button"
        onClick={() => void executeQuery(
          "sales-query",
          1,
          20,
          {
            sort: { field: "amount", direction: "desc" },
            columnFilters: { channel: ["直播"] },
          },
        )}
      >
        control sales
      </button>
    </div>
  );
}

beforeEach(() => {
  executeQueryMock.mockReset();
  executeBuildQueryMock.mockReset();
});

test("queries the build endpoint for a Report build", async () => {
  executeBuildQueryMock.mockResolvedValue({
    columns: [],
    rows: [{ region: "华东" }],
    page: 1,
    pageSize: 50,
    total: 1,
  });
  const report = {
    ...runtimeReport(),
    id: "build-1",
    buildId: "build-1",
    buildRevision: 3,
    buildStatus: "building" as const,
  };

  render(
    <ReportProvider report={report}>
      <ContextProbe />
    </ReportProvider>,
  );

  await waitFor(() => expect(
    executeBuildQueryMock,
  ).toHaveBeenCalled());
  expect(executeBuildQueryMock.mock.calls[0][0]).toBe("build-1");
  expect(executeQueryMock).not.toHaveBeenCalled();
});

test("loads layout-referenced queries and refetches only bound queries", async () => {
  executeQueryMock.mockResolvedValue({
    columns: [],
    rows: [{ region: "华东" }],
    page: 1,
    pageSize: 50,
    total: 1,
  });

  render(
    <ReportProvider report={runtimeReport()}>
      <ContextProbe />
    </ReportProvider>,
  );

  await screen.findByText("sales-query:ready:1");
  await screen.findByText("detail-query:ready:1");
  expect(screen.queryByText(/unrelated-query/)).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "change region" }));
  await waitFor(() => expect(executeQueryMock).toHaveBeenCalledTimes(4));
  expect(
    executeQueryMock.mock.calls.slice(2).map((call) => call[1]),
  ).toEqual(expect.arrayContaining(["sales-query", "detail-query"]));
  expect(
    executeQueryMock.mock.calls[2][2].filters.region,
  ).toBe("华南");
});

test("one failed query does not remove another query result", async () => {
  executeQueryMock.mockImplementation(async (_reportId, queryId) => {
    if (queryId === "detail-query") {
      throw new Error("query failed");
    }
    return {
      columns: [],
      rows: [{ region: "华东" }],
      page: 1,
      pageSize: 50,
      total: 1,
    };
  });

  render(
    <ReportProvider report={runtimeReport()}>
      <ContextProbe />
    </ReportProvider>,
  );

  await screen.findByText("sales-query:ready:1");
  await screen.findByText("detail-query:error:0");
  expect(screen.getByText("sales-query:ready:1")).toBeTruthy();
});

test("independent filters only refresh their bound query", async () => {
  const report = runtimeReport();
  report.filters.channel = {
    type: "select",
    label: "渠道",
    defaultValue: "直播",
    options: [{ label: "直播", value: "直播" }],
  };
  report.queries["detail-query"] = {
    ...report.queries["detail-query"],
    sql: "SELECT region FROM sales WHERE channel = :channel",
    parameters: {
      channel: { filterId: "channel", type: "string" },
    },
  };
  executeQueryMock.mockResolvedValue({
    columns: [],
    rows: [{ region: "华东" }],
    page: 1,
    pageSize: 50,
    total: 1,
  });

  function IndependentProbe() {
    const { setFilterValue } = useReportContext();
    return (
      <button
        type="button"
        onClick={() => setFilterValue("region", "华南")}
      >
        change only region
      </button>
    );
  }

  render(
    <ReportProvider report={report}>
      <IndependentProbe />
    </ReportProvider>,
  );

  await waitFor(() => expect(executeQueryMock).toHaveBeenCalledTimes(2));
  executeQueryMock.mockClear();
  fireEvent.click(screen.getByRole("button", {
    name: "change only region",
  }));
  await waitFor(() => expect(executeQueryMock).toHaveBeenCalledTimes(1));
  expect(executeQueryMock.mock.calls[0][1]).toBe("sales-query");
});

test("report filters preserve table page size and column controls", async () => {
  executeQueryMock.mockImplementation(async (
    _reportId,
    _queryId,
    request,
  ) => ({
    columns: [],
    rows: [{ region: "华东" }],
    page: request.page ?? 1,
    pageSize: request.pageSize ?? 50,
    total: 1,
  }));

  render(
    <ReportProvider report={runtimeReport()}>
      <ContextProbe />
    </ReportProvider>,
  );

  await screen.findByText("sales-query:ready:1");
  fireEvent.click(screen.getByRole("button", { name: "control sales" }));
  await waitFor(() => expect(
    executeQueryMock.mock.calls.at(-1)?.[2],
  ).toMatchObject({ pageSize: 20 }));
  await screen.findByText("20:desc:channel");
  const beforeFilterChange = executeQueryMock.mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "change region" }));
  await waitFor(() => {
    const salesRequest = executeQueryMock.mock.calls
      .slice(beforeFilterChange)
      .find((call) => call[1] === "sales-query")?.[2];
    expect(salesRequest).toMatchObject({
      page: 1,
      pageSize: 20,
      sort: { field: "amount", direction: "desc" },
      columnFilters: { channel: ["直播"] },
    });
  });
});
