import { afterEach, describe, expect, test, vi } from "vitest";
import { fetchInteractiveReportQuery } from "../src/modules/analysis/api/interactive-report-query-service";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("interactive report query client", () => {
  test("posts only a registered query reference and runtime filters", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      queryRef: "finereport-operation-management-channel-sales",
      filters: { month: "2026-05" },
      columns: ["channel", "salesAmount", "salesShare"],
      rows: [{ channel: "线上自营", salesAmount: 100, salesShare: 1 }],
      rowCount: 1,
      elapsedMs: 10,
      truncated: false,
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchInteractiveReportQuery("finereport-operation-management-channel-sales", { month: "2026-05", brand: "all", region: "all" });

    expect(fetchMock.mock.calls[0][0]).toBe("http://192.168.101.12:8000/api/analysis/report-queries/finereport-operation-management-channel-sales");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({ filters: { month: "2026-05", brand: "all", region: "all" } });
    expect(result.rows[0].salesAmount).toBe(100);
  });
});
