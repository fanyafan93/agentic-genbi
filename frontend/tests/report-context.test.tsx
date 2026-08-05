import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import {
  ReportProvider,
  useReportContext,
} from "../src/modules/analysis/components/ReportContext";
import { executeReportQuery } from "../src/modules/analysis/api/report-service";
import type { Report } from "../src/modules/analysis/types/report";
import { reportFixture } from "./fixtures/report";

vi.mock("../src/modules/analysis/api/report-service", () => ({
  executeReportQuery: vi.fn(),
}));

const executeQueryMock = vi.mocked(executeReportQuery);

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
  const { queryStates, setFilterValue } = useReportContext();
  return (
    <div>
      {Object.entries(queryStates).map(([queryId, state]) => (
        <span key={queryId}>
          {queryId}:{state.error ? "error" : state.loading ? "loading" : "ready"}
          :{state.rows.length}
        </span>
      ))}
      <button
        type="button"
        onClick={() => setFilterValue("region", "华南")}
      >
        change region
      </button>
    </div>
  );
}

beforeEach(() => {
  executeQueryMock.mockReset();
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
