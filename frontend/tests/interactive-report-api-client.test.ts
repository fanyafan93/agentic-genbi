import { afterEach, describe, expect, test, vi } from "vitest";
import {
  createAnalysisThreadFromReportBackend,
  deleteInteractiveReportFromBackend,
  getInteractiveReportFromBackend,
  listReportCenterFromBackend,
  renameInteractiveReportInBackend,
  saveInteractiveReportToBackend,
  shareInteractiveReportToBackend,
} from "../src/modules/analysis/api/interactive-report-service";
import { interactiveReportFixture } from "./fixtures/interactive-report";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function backendReportPayload(version = 1) {
  return {
    report: {
      id: interactiveReportFixture.id,
      title: interactiveReportFixture.title,
      subtitle: interactiveReportFixture.subtitle,
      artifactType: "interactive_report",
      renderer: "puck",
      ownerId: "local-user",
      sourceThreadId: interactiveReportFixture.source.threadId,
      sourceTurnId: interactiveReportFixture.source.turnId,
      latestVersion: version,
      createdAt: "2026-08-01T08:00:00.000Z",
      updatedAt: "2026-08-01T08:00:00.000Z",
    },
    version: {
      reportId: interactiveReportFixture.id,
      version,
      sourceThreadId: interactiveReportFixture.source.threadId,
      sourceTurnId: interactiveReportFixture.source.turnId,
      document: interactiveReportFixture.document,
      filters: interactiveReportFixture.filters,
      queries: interactiveReportFixture.queries,
      chartSpecs: interactiveReportFixture.chartSpecs,
      gridSpecs: interactiveReportFixture.gridSpecs,
      datasets: { channel_sales: { rows: [{ channel: "direct", salesAmount: 1000 }] } },
      createdAt: "2026-08-01T08:00:00.000Z",
    },
  };
}

describe("interactive report backend API client", () => {
  test("saves Puck report JSON and returns the server-assigned version", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(backendReportPayload(1)), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const saved = await saveInteractiveReportToBackend(interactiveReportFixture);

    expect(fetchMock.mock.calls[0][0]).toBe("http://192.168.101.12:8000/api/analysis/reports");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.document).toEqual(interactiveReportFixture.document);
    expect(body.expectedVersion).toBeUndefined();
    expect(saved.version).toBe(1);
    expect(saved.report.source).toEqual({
      threadId: interactiveReportFixture.source.threadId,
      turnId: interactiveReportFixture.source.turnId,
    });
    expect(saved.report.datasets?.channel_sales.rows[0].salesAmount).toBe(1000);
  });

  test("opens a requested server report version", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(backendReportPayload(1)), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const opened = await getInteractiveReportFromBackend(interactiveReportFixture.id, 1);

    expect(fetchMock.mock.calls[0][0]).toBe(`http://192.168.101.12:8000/api/analysis/reports/${interactiveReportFixture.id}/versions/1`);
    expect(opened.version).toBe(1);
    expect(opened.report.document).toEqual(interactiveReportFixture.document);
    expect(opened.report.source.turnId).toBe(interactiveReportFixture.source.turnId);
  });

  test("lists report center as mine and shared reports", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        mine: [
          { report: backendReportPayload(2).report },
        ],
        sharedWithMe: [
          { reportId: "report_shared", recipientUserId: "local-user", permission: "view_and_reuse", createdAt: "2026-08-01T10:00:00.000Z", report: { ...backendReportPayload(1).report, id: "report_shared", title: "共享日报" } },
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(backendReportPayload(2)), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        ...backendReportPayload(1),
        report: { ...backendReportPayload(1).report, id: "report_shared", title: "共享日报" },
        version: { ...backendReportPayload(1).version, reportId: "report_shared" },
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const center = await listReportCenterFromBackend("local-user");

    expect(fetchMock.mock.calls[0][0]).toBe("http://192.168.101.12:8000/api/analysis/report-center?user_id=local-user");
    expect(center.mine[0].report.title).toBe(interactiveReportFixture.title);
    expect(center.sharedWithMe[0].permission).toBe("view_and_reuse");
    expect(center.sharedWithMe[0].report.title).toBe("共享日报");
  });

  test("renames deletes and shares current report assets", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ report: { ...backendReportPayload(1).report, title: "新标题" } }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ share: { reportId: interactiveReportFixture.id, recipientUserId: "user_2", permission: "view", createdAt: "2026-08-01T10:00:00.000Z" } }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ deleted: true, report_id: interactiveReportFixture.id }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await renameInteractiveReportInBackend(interactiveReportFixture.id, "新标题", "owner_1");
    await shareInteractiveReportToBackend(interactiveReportFixture.id, "user_2", "view", "owner_1");
    await deleteInteractiveReportFromBackend(interactiveReportFixture.id, "owner_1");

    expect(fetchMock.mock.calls[0][0]).toBe(`http://192.168.101.12:8000/api/analysis/reports/${interactiveReportFixture.id}`);
    expect(fetchMock.mock.calls[0][1].method).toBe("PATCH");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({ ownerId: "owner_1", title: "新标题" });
    expect(fetchMock.mock.calls[1][0]).toBe(`http://192.168.101.12:8000/api/analysis/reports/${interactiveReportFixture.id}/shares`);
    expect(fetchMock.mock.calls[1][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string)).toEqual({ ownerId: "owner_1", recipientUserId: "user_2", permission: "view" });
    expect(fetchMock.mock.calls[2][0]).toBe(`http://192.168.101.12:8000/api/analysis/reports/${interactiveReportFixture.id}?owner_id=owner_1`);
    expect(fetchMock.mock.calls[2][1].method).toBe("DELETE");
  });

  test("creates a backend analysis session from a saved report", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      session: {
        id: "analysis_session_report123",
        title: "渠道销售概览 新分析",
        status: "active",
        createdAt: "2026-08-04T10:00:00.000Z",
        updatedAt: "2026-08-04T10:00:00.000Z",
        latestQuestion: null,
      },
      report: backendReportPayload(3),
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const created = await createAnalysisThreadFromReportBackend(interactiveReportFixture.id, "渠道销售概览 新分析", "owner_1");

    expect(fetchMock.mock.calls[0][0]).toBe(`http://192.168.101.12:8000/api/analysis/reports/${interactiveReportFixture.id}/sessions`);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
      userId: "owner_1",
      title: "渠道销售概览 新分析",
    });
    expect(created.thread.id).toBe("analysis_session_report123");
    expect(created.thread.status).toBe("active");
    expect(created.saved.version).toBe(3);
    expect(created.saved.report.document).toEqual(interactiveReportFixture.document);
  });
});
