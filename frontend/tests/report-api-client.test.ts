import { afterEach, describe, expect, test, vi } from "vitest";
import {
  createReport,
  deleteReport,
  executeReportBuildQuery,
  executeReportQuery,
  exportReportTable,
  getActiveReportBuild,
  getReport,
  getReportBuild,
  listReportCenter,
  listReportsBySession,
  shareReport,
  updateReport,
} from "../src/modules/analysis/api/report-service";
import { reportFixture } from "./fixtures/report";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function reportResponse() {
  return { report: reportFixture };
}

describe("direct Report API client", () => {
  test("creates a Report without server-managed fields", async () => {
    vi.stubEnv(
      "NEXT_PUBLIC_GENBI_API_BASE_URL",
      "http://192.168.101.12:8000",
    );
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(reportResponse()));
    vi.stubGlobal("fetch", fetchMock);

    await createReport(reportFixture, "owner-1");

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://192.168.101.12:8000/api/reports",
    );
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(Object.keys(body).sort()).toEqual(
      [
        "charts",
        "filters",
        "layout",
        "ownerId",
        "queries",
        "subtitle",
        "tables",
        "title",
      ].sort(),
    );
  });

  test("updates the complete direct Report through PUT", async () => {
    vi.stubEnv(
      "NEXT_PUBLIC_GENBI_API_BASE_URL",
      "http://192.168.101.12:8000",
    );
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse(reportResponse()));
    vi.stubGlobal("fetch", fetchMock);

    const saved = await updateReport(
      reportFixture.id,
      reportFixture,
      "owner-1",
    );

    expect(fetchMock.mock.calls[0][0]).toBe(
      `http://192.168.101.12:8000/api/reports/${reportFixture.id}`,
    );
    expect(fetchMock.mock.calls[0][1].method).toBe("PUT");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(Object.keys(body).sort()).toEqual(
      [
        "charts",
        "filters",
        "layout",
        "ownerId",
        "queries",
        "subtitle",
        "tables",
        "title",
      ].sort(),
    );
    expect(saved.report.turnId).toBe("turn-1");
  });

  test("executes a saved query without sending SQL", async () => {
    vi.stubEnv(
      "NEXT_PUBLIC_GENBI_API_BASE_URL",
      "http://192.168.101.12:8000",
    );
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        columns: [],
        rows: [],
        page: 1,
        pageSize: 50,
        total: 0,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await executeReportQuery("report-1", "sales-query", {
      filters: { region: "华东" },
      page: 1,
      pageSize: 50,
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.sql).toBeUndefined();
    expect(body).toEqual({
      filters: { region: "华东" },
      page: 1,
      pageSize: 50,
    });
  });

  test("downloads a configured table export without sending SQL", async () => {
    vi.stubEnv(
      "NEXT_PUBLIC_GENBI_API_BASE_URL",
      "http://192.168.101.12:8000",
    );
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("xlsx", {
        status: 200,
        headers: {
          "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          "Content-Disposition": "attachment; filename*=UTF-8''orders.xlsx",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const exported = await exportReportTable(
      "report-1",
      "orders",
      {
        filters: { region: "华东" },
        sort: { field: "amount", direction: "desc" },
        columnFilters: { region: ["华东"] },
      },
    );

    expect(fetchMock.mock.calls[0][0]).toBe(
      "http://192.168.101.12:8000/api/reports/report-1/tables/orders/export",
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      filters: { region: "华东" },
      sort: { field: "amount", direction: "desc" },
      columnFilters: { region: ["华东"] },
    });
    expect(exported.filename).toBe("orders.xlsx");
    expect(await exported.blob.text()).toBe("xlsx");
  });

  test("reads and queries persisted Report builds", async () => {
    vi.stubEnv(
      "NEXT_PUBLIC_GENBI_API_BASE_URL",
      "http://192.168.101.12:8000",
    );
    const buildReport = {
      ...reportFixture,
      id: "build-1",
      buildId: "build-1",
      buildRevision: 3,
      buildStatus: "building" as const,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({
        build: { id: "build-1", revision: 3 },
        report: buildReport,
      }))
      .mockResolvedValueOnce(jsonResponse({
        build: { id: "build-1", revision: 3 },
        report: buildReport,
      }))
      .mockResolvedValueOnce(jsonResponse({
        columns: [],
        rows: [{ channel: "抖音", sales: 10 }],
        page: 1,
        pageSize: 50,
        total: 1,
      }));
    vi.stubGlobal("fetch", fetchMock);

    const exact = await getReportBuild("build-1");
    const active = await getActiveReportBuild("session-1");
    const query = await executeReportBuildQuery(
      "build-1",
      "q-sales",
      { filters: {}, page: 1, pageSize: 50 },
    );

    expect(exact.report.buildRevision).toBe(3);
    expect(active.report?.buildId).toBe("build-1");
    expect(query.rows).toEqual([{ channel: "抖音", sales: 10 }]);
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      "http://192.168.101.12:8000/api/report-builds/build-1",
      "http://192.168.101.12:8000/api/analysis/sessions/session-1/report-builds/active",
      "http://192.168.101.12:8000/api/report-builds/build-1/queries/q-sales",
    ]);
  });

  test("uses only direct Report and Report Center paths", async () => {
    vi.stubEnv(
      "NEXT_PUBLIC_GENBI_API_BASE_URL",
      "http://192.168.101.12:8000",
    );
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(reportResponse()))
      .mockResolvedValueOnce(jsonResponse({ reports: [reportFixture] }))
      .mockResolvedValueOnce(
        jsonResponse({ mine: [], sharedWithMe: [] }),
      )
      .mockResolvedValueOnce(jsonResponse({ share: {} }))
      .mockResolvedValueOnce(jsonResponse({ deleted: true }));
    vi.stubGlobal("fetch", fetchMock);

    await getReport(reportFixture.id);
    await listReportsBySession("session-1");
    await listReportCenter("owner-1");
    await shareReport(
      reportFixture.id,
      "user-2",
      "view_and_reuse",
      "owner-1",
    );
    await deleteReport(reportFixture.id, "owner-1");

    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls).toEqual([
      `http://192.168.101.12:8000/api/reports/${reportFixture.id}`,
      "http://192.168.101.12:8000/api/reports?session_id=session-1",
      "http://192.168.101.12:8000/api/report-center?user_id=owner-1",
      `http://192.168.101.12:8000/api/reports/${reportFixture.id}/shares`,
      `http://192.168.101.12:8000/api/reports/${reportFixture.id}?owner_id=owner-1`,
    ]);
  });
});
