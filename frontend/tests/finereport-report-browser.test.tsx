import { afterEach, describe, expect, test, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BusinessSemanticLibrary } from "../src/modules/business-semantics/components/BusinessSemanticLibrary";

const reportSummary = {
  id: "finereport_budget",
  name: "预算管控",
  sourceCptPath: "reports/预算管控.cpt",
  sheetNames: ["额度报表"],
  status: "complete",
  availableParts: ["01", "02", "03"],
  missingParts: [],
  errors: [],
  counts: {
    sheets: 1,
    datasets: 1,
    sqlDatasets: 1,
    parameters: 0,
    parameterWidgets: 1,
    conditionalRules: 1,
    cells: 2,
    formulas: 1,
    bindings: 1,
    usageUsers: 1,
    totalUsageCount: 3,
  },
};

const reportDetail = {
  report: reportSummary,
  datasets: [
    {
      name: "ds",
      type: "database_query",
      connection_name: "fat_dm",
      raw_sql: "select amount from dm.budget",
      parameters: [{ name: "month" }],
    },
  ],
  parameters: [],
  parameterWidgets: [{ parameter: "month", widget_class: "ComboBox", label: "月份" }],
  conditionalRules: [{ cell: "A2", condition: "amount > 0", action_class: "Style", action: "highlight" }],
  reportUsage: {
    totalUsageCount: 3,
    users: [{ userName: "朱子越", position: "财务BP", department: "财务管理部", usageCount: 3 }],
  },
  sheets: [
    {
      name: "额度报表",
      rowCount: 2,
      columnCount: 2,
      cells: [
        { cell: "A1", row: 1, column: "A", columnIndex: 1, rowspan: 1, colspan: 2, value: "预算" },
        {
          cell: "A2",
          row: 2,
          column: "A",
          columnIndex: 1,
          rowspan: 1,
          colspan: 1,
          formula: "=sum(A3)",
          binding: { dataset: "ds", field: "amount" },
        },
      ],
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("FineReport report browser", () => {
  test("loads parsed reports and renders the report grid", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ reports: [reportSummary] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(reportDetail), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<BusinessSemanticLibrary />);

    expect((await screen.findAllByText("预算管控")).length).toBeGreaterThan(0);
    const mergedCell = await screen.findByRole("button", { name: "A1 预算" });
    expect(mergedCell.style.gridColumn).toBe("1 / span 2");
    expect(mergedCell.style.gridRow).toBe("1 / span 1");
    expect(screen.getByRole("button", { name: "额度报表" })).toBeTruthy();
    expect(fetchMock.mock.calls[0][0]).toBe("http://192.168.101.12:8000/api/business-semantics/finereport/reports");
    expect(fetchMock.mock.calls[1][0]).toBe(
      "http://192.168.101.12:8000/api/business-semantics/finereport/reports/finereport_budget",
    );

    fireEvent.click(screen.getByRole("button", { name: "数据集与 SQL" }));
    await waitFor(() => expect(screen.getByText("select amount from dm.budget")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "使用情况" }));
    await waitFor(() => expect(screen.getByText("朱子越")).toBeTruthy());
    expect(screen.getByText("财务BP / 财务管理部")).toBeTruthy();
  });

  test("keeps the main area empty for other structured knowledge sources", () => {
    render(<BusinessSemanticLibrary section="structured" structuredKnowledgeSource="hop" />);

    expect(screen.getByRole("region", { name: "业务语义库" }).children.length).toBe(0);
  });
});
