import { afterEach, describe, expect, test, vi } from "vitest";
import { getInteractiveReportFromBackend, listInteractiveReportVersionsFromBackend, saveInteractiveReportToBackend } from "../src/modules/analysis/api/interactive-report-service";
import { mockInteractiveReport } from "../src/modules/analysis/mocks/interactive-report";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

function backendReportPayload(version = 1) {
  return {
    report: {
      id: mockInteractiveReport.id,
      title: mockInteractiveReport.title,
      subtitle: mockInteractiveReport.subtitle,
      artifactType: "interactive_report",
      renderer: "puck",
      ownerId: "local-user",
      sourceThreadId: mockInteractiveReport.source.threadId,
      sourceTurnId: mockInteractiveReport.source.turnId,
      latestVersion: version,
      createdAt: "2026-08-01T08:00:00.000Z",
      updatedAt: "2026-08-01T08:00:00.000Z",
    },
    version: {
      reportId: mockInteractiveReport.id,
      version,
      sourceThreadId: mockInteractiveReport.source.threadId,
      sourceTurnId: mockInteractiveReport.source.turnId,
      document: mockInteractiveReport.document,
      filters: mockInteractiveReport.filters,
      queries: mockInteractiveReport.queries,
      chartSpecs: mockInteractiveReport.chartSpecs,
      gridSpecs: mockInteractiveReport.gridSpecs,
      createdAt: "2026-08-01T08:00:00.000Z",
    },
  };
}

describe("interactive report backend API client", () => {
  test("saves Puck report JSON and returns the server-assigned version", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(backendReportPayload(1)), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const saved = await saveInteractiveReportToBackend(mockInteractiveReport);

    expect(fetchMock.mock.calls[0][0]).toBe("http://192.168.101.12:8000/api/analysis/reports");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.document).toEqual(mockInteractiveReport.document);
    expect(body.expectedVersion).toBeUndefined();
    expect(saved.version).toBe(1);
    expect(saved.report.source).toEqual({
      threadId: mockInteractiveReport.source.threadId,
      turnId: mockInteractiveReport.source.turnId,
    });
  });

  test("opens a requested server report version", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(backendReportPayload(1)), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const opened = await getInteractiveReportFromBackend(mockInteractiveReport.id, 1);

    expect(fetchMock.mock.calls[0][0]).toBe(`http://192.168.101.12:8000/api/analysis/reports/${mockInteractiveReport.id}/versions/1`);
    expect(opened.version).toBe(1);
    expect(opened.report.document).toEqual(mockInteractiveReport.document);
    expect(opened.report.source.turnId).toBe(mockInteractiveReport.source.turnId);
  });

  test("lists server report version history", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      versions: [
        { reportId: mockInteractiveReport.id, version: 2, sourceThreadId: mockInteractiveReport.source.threadId, sourceTurnId: "turn_report_v2", createdAt: "2026-08-01T09:00:00.000Z" },
        { reportId: mockInteractiveReport.id, version: 1, sourceThreadId: mockInteractiveReport.source.threadId, sourceTurnId: mockInteractiveReport.source.turnId, createdAt: "2026-08-01T08:00:00.000Z" },
      ],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const versions = await listInteractiveReportVersionsFromBackend(mockInteractiveReport.id);

    expect(fetchMock.mock.calls[0][0]).toBe(`http://192.168.101.12:8000/api/analysis/reports/${mockInteractiveReport.id}/versions`);
    expect(versions.map((item) => item.version)).toEqual([2, 1]);
    expect(versions[0].sourceTurnId).toBe("turn_report_v2");
  });
});
