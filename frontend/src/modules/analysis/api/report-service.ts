import type {
  Report,
  ReportCenter,
  ReportQueryRequest,
  ReportQueryResult,
  ReportTableExportFile,
  ReportTableExportRequest,
  SavedReport,
} from "../types/report";

const DEFAULT_REPORT_OWNER_ID = "local-user";

type ReportConfigBody = Pick<
  Report,
  | "title"
  | "subtitle"
  | "layout"
  | "filters"
  | "charts"
  | "tables"
  | "queries"
> & { ownerId: string };

export type ReportBuildResponse = {
  build: Record<string, unknown>;
  report: Report;
};

export type ActiveReportBuildResponse = {
  build: Record<string, unknown> | null;
  report: Report | null;
};

export function shouldUseBackendReports(): boolean {
  return (
    process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME === "backend"
    && Boolean(getReportApiBaseUrl())
  );
}

export function getReportApiBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ?? null;
}

export async function createReport(
  report: Report,
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<SavedReport> {
  return requestJson<SavedReport>("/api/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(toReportConfig(report, ownerId)),
  });
}

export async function updateReport(
  reportId: string,
  report: Report,
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<SavedReport> {
  return requestJson<SavedReport>(
    `/api/reports/${encodeURIComponent(reportId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toReportConfig(report, ownerId)),
    },
  );
}

export async function getReport(
  reportId: string,
): Promise<SavedReport> {
  return requestJson<SavedReport>(
    `/api/reports/${encodeURIComponent(reportId)}`,
  );
}

export async function getReportBuild(
  buildId: string,
  apiBaseUrl?: string,
): Promise<ReportBuildResponse> {
  return requestJson<ReportBuildResponse>(
    `/api/report-builds/${encodeURIComponent(buildId)}`,
    undefined,
    apiBaseUrl,
  );
}

export async function getActiveReportBuild(
  sessionId: string,
): Promise<ActiveReportBuildResponse> {
  return requestJson<ActiveReportBuildResponse>(
    `/api/analysis/sessions/${encodeURIComponent(sessionId)}/report-builds/active`,
  );
}

export async function listReportsBySession(
  sessionId: string,
): Promise<SavedReport[]> {
  const payload = await requestJson<{ reports: Report[] }>(
    `/api/reports?session_id=${encodeURIComponent(sessionId)}`,
  );
  return payload.reports.map((report) => ({ report }));
}

export async function listReportCenter(
  userId = DEFAULT_REPORT_OWNER_ID,
): Promise<ReportCenter> {
  return requestJson<ReportCenter>(
    `/api/report-center?user_id=${encodeURIComponent(userId)}`,
  );
}

export async function deleteReport(
  reportId: string,
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<void> {
  await requestJson(
    `/api/reports/${encodeURIComponent(reportId)}?owner_id=${encodeURIComponent(ownerId)}`,
    { method: "DELETE" },
  );
}

export async function shareReport(
  reportId: string,
  recipientUserId: string,
  permission: "view" | "view_and_reuse",
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<void> {
  await requestJson(
    `/api/reports/${encodeURIComponent(reportId)}/shares`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ownerId,
        recipientUserId,
        permission,
      }),
    },
  );
}

export async function executeReportQuery(
  reportId: string,
  queryId: string,
  request: ReportQueryRequest,
): Promise<ReportQueryResult> {
  return requestJson<ReportQueryResult>(
    `/api/reports/${encodeURIComponent(reportId)}/queries/${encodeURIComponent(queryId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}

export async function executeReportBuildQuery(
  buildId: string,
  queryId: string,
  request: ReportQueryRequest,
): Promise<ReportQueryResult> {
  return requestJson<ReportQueryResult>(
    `/api/report-builds/${encodeURIComponent(buildId)}/queries/${encodeURIComponent(queryId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}

export async function exportReportTable(
  reportId: string,
  tableId: string,
  request: ReportTableExportRequest,
): Promise<ReportTableExportFile> {
  const apiBaseUrl = getReportApiBaseUrl();
  if (!apiBaseUrl) {
    throw new Error("Report API base URL is not configured.");
  }
  const response = await fetch(
    `${apiBaseUrl}/api/reports/${encodeURIComponent(reportId)}`
      + `/tables/${encodeURIComponent(tableId)}/export`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    throw new Error(`Report API returned ${response.status}`);
  }
  return {
    blob: await response.blob(),
    filename: responseFilename(
      response.headers.get("Content-Disposition"),
      `${tableId}.xlsx`,
    ),
  };
}

function toReportConfig(
  report: Report,
  ownerId: string,
): ReportConfigBody {
  return {
    ownerId,
    title: report.title,
    subtitle: report.subtitle,
    layout: report.layout,
    filters: report.filters,
    charts: report.charts,
    tables: report.tables,
    queries: report.queries,
  };
}

async function requestJson<T = unknown>(
  path: string,
  init?: RequestInit,
  apiBaseUrlOverride?: string,
): Promise<T> {
  const apiBaseUrl = apiBaseUrlOverride ?? getReportApiBaseUrl();
  if (!apiBaseUrl) {
    throw new Error("Report API base URL is not configured.");
  }
  const response = await fetch(`${apiBaseUrl}${path}`, init);
  if (!response.ok) {
    throw new Error(`Report API returned ${response.status}`);
  }
  return await response.json() as T;
}

function responseFilename(
  contentDisposition: string | null,
  fallback: string,
): string {
  if (!contentDisposition) return fallback;
  const encoded = contentDisposition.match(
    /filename\*=UTF-8''([^;]+)/i,
  )?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      return fallback;
    }
  }
  return contentDisposition.match(/filename="?([^";]+)"?/i)?.[1]
    ?? fallback;
}
