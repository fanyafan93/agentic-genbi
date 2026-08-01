import { describe, expect, test } from "vitest";
import { channelSalesReportQueryRef, createDefaultReportFilters, mockInteractiveReport, queryMockDataset } from "../src/modules/analysis/mocks/interactive-report";
import { loadSavedInteractiveReports, saveInteractiveReport } from "../src/modules/analysis/mocks/interactive-report-storage";

describe("interactive report mock contract", () => {
  test("keeps report layout, query references, and runtime filters separate", () => {
    const filters = createDefaultReportFilters();
    const before = JSON.stringify(mockInteractiveReport.document);
    const rows = queryMockDataset("channel_sales", { ...filters, month: "2026-04" });

    expect(mockInteractiveReport.artifactType).toBe("interactive_report");
    expect(mockInteractiveReport.renderer).toBe("puck");
    expect(mockInteractiveReport.queries[channelSalesReportQueryRef].filterBindings).toEqual(["month", "brand", "region"]);
    expect(rows).toHaveLength(5);
    expect(JSON.stringify(mockInteractiveReport.document)).toBe(before);
  });

  test("recalculates the shown share from the active runtime filter", () => {
    const filters = createDefaultReportFilters();
    const allRows = queryMockDataset("channel_sales", filters);
    const eastRows = queryMockDataset("channel_sales", { ...filters, region: "华东" });

    expect(allRows).toHaveLength(5);
    expect(eastRows).toHaveLength(3);
    expect(eastRows.reduce((sum, row) => sum + Number(row.salesShare), 0)).toBeCloseTo(1);
  });

  test("persists a saved result separately from transient runtime filters", () => {
    window.localStorage.clear();

    const saved = saveInteractiveReport({
      report: mockInteractiveReport,
      version: 2,
      savedAt: "2026-08-01T08:00:00.000Z",
    });

    expect(saved).toHaveLength(1);
    expect(loadSavedInteractiveReports()).toEqual(saved);
    expect(loadSavedInteractiveReports()[0].report.document).toEqual(mockInteractiveReport.document);
  });
});
