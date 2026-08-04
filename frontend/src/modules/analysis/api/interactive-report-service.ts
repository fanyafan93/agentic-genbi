import type { InteractiveReport } from "../types/interactive-report";

export type SavedInteractiveReport = {
  report: InteractiveReport;
  version: number;
  savedAt: string;
};

export type SharedInteractiveReport = SavedInteractiveReport & {
  permission: "view" | "view_and_reuse";
  sharedAt: string;
  sharedByReportOwnerId: string;
};

export type ReportCenter = {
  mine: SavedInteractiveReport[];
  sharedWithMe: SharedInteractiveReport[];
};

export type ReportAnalysisThread = {
  thread: {
    id: string;
    title?: string | null;
    status?: string | null;
    createdAt?: string | null;
    updatedAt?: string | null;
    latestQuestion?: string | null;
  };
  saved: SavedInteractiveReport;
};

type BackendReportSummary = {
  id: string;
  title: string;
  subtitle: string;
  artifactType: "interactive_report";
  renderer: "puck";
  ownerId: string;
  sourceThreadId: string;
  sourceTurnId: string;
  latestVersion: number;
  createdAt: string;
  updatedAt: string;
};

type BackendReportVersion = {
  reportId: string;
  version: number;
  sourceThreadId: string;
  sourceTurnId: string;
  document: InteractiveReport["document"];
  filters: InteractiveReport["filters"];
  queries: InteractiveReport["queries"];
  chartSpecs: InteractiveReport["chartSpecs"];
  gridSpecs: InteractiveReport["gridSpecs"];
  datasets?: InteractiveReport["datasets"];
  createdAt: string;
};

export type InteractiveReportVersionSummary = {
  reportId: string;
  version: number;
  sourceThreadId: string;
  sourceTurnId: string;
  createdAt: string;
};

type BackendReportDetailResponse = {
  report: BackendReportSummary;
  version: BackendReportVersion;
};

type BackendReportCenterResponse = {
  mine: Array<{ report: BackendReportSummary }>;
  sharedWithMe: Array<{
    reportId: string;
    recipientUserId: string;
    permission: "view" | "view_and_reuse";
    createdAt: string;
    report: BackendReportSummary;
  }>;
};

export function shouldUseBackendInteractiveReports(): boolean {
  return process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME === "backend" && Boolean(getInteractiveReportApiBaseUrl());
}

export function getInteractiveReportApiBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ?? null;
}

export async function saveInteractiveReportToBackend(
  report: InteractiveReport,
  expectedVersion?: number,
): Promise<SavedInteractiveReport> {
  // The backend derives ``ownerId`` from the active Auth.js session cookie.
  // We never attach an identity field from the client.
  const response = await fetchInteractiveReport("/api/analysis/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...report, expectedVersion }),
    credentials: "include",
  });
  return toSavedInteractiveReport(await readJson<BackendReportDetailResponse>(response));
}

export async function getInteractiveReportFromBackend(reportId: string, version?: number): Promise<SavedInteractiveReport> {
  const suffix = version === undefined ? "" : `/versions/${version}`;
  const response = await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}${suffix}`, {
    credentials: "include",
  });
  return toSavedInteractiveReport(await readJson<BackendReportDetailResponse>(response));
}

export async function listInteractiveReportVersionsFromBackend(reportId: string): Promise<InteractiveReportVersionSummary[]> {
  const response = await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}/versions`, {
    credentials: "include",
  });
  const payload = await readJson<{ versions: InteractiveReportVersionSummary[] }>(response);
  return payload.versions;
}

export async function listInteractiveReportsFromBackend(): Promise<SavedInteractiveReport[]> {
  const response = await fetchInteractiveReport("/api/analysis/reports", {
    credentials: "include",
  });
  const payload = await readJson<{ reports: BackendReportSummary[] }>(response);
  return Promise.all(payload.reports.map((report) => getInteractiveReportFromBackend(report.id)));
}

export async function listReportCenterFromBackend(): Promise<ReportCenter> {
  const response = await fetchInteractiveReport("/api/analysis/report-center", {
    credentials: "include",
  });
  const payload = await readJson<BackendReportCenterResponse>(response);
  const mine = await Promise.all(payload.mine.map((item) => getInteractiveReportFromBackend(item.report.id)));
  const sharedWithMe = await Promise.all(payload.sharedWithMe.map(async (item) => ({
    ...await getInteractiveReportFromBackend(item.report.id),
    permission: item.permission,
    sharedAt: item.createdAt,
    sharedByReportOwnerId: item.report.ownerId,
  })));
  return { mine, sharedWithMe };
}

export async function renameInteractiveReportInBackend(reportId: string, title: string): Promise<void> {
  await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
    credentials: "include",
  });
}

export async function shareInteractiveReportToBackend(
  reportId: string,
  recipientUserId: string,
  permission: "view" | "view_and_reuse",
): Promise<void> {
  await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}/shares`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recipientUserId, permission }),
    credentials: "include",
  });
}

export async function deleteInteractiveReportFromBackend(reportId: string): Promise<void> {
  await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}`, {
    method: "DELETE",
    credentials: "include",
  });
}

export async function createAnalysisThreadFromReportBackend(
  reportId: string,
  title?: string,
): Promise<ReportAnalysisThread> {
  const response = await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}/analysis-thread`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
    credentials: "include",
  });
  const payload = await readJson<{ thread: ReportAnalysisThread["thread"]; report: BackendReportDetailResponse }>(response);
  return {
    thread: payload.thread,
    saved: toSavedInteractiveReport(payload.report),
  };
}

export async function listInteractiveReportsByThreadFromBackend(threadId: string): Promise<SavedInteractiveReport[]> {
  const response = await fetchInteractiveReport(`/api/analysis/reports?source_thread_id=${encodeURIComponent(threadId)}`, {
    credentials: "include",
  });
  const payload = await readJson<{ reports: BackendReportSummary[] }>(response);
  return Promise.all(payload.reports.map((report) => getInteractiveReportFromBackend(report.id)));
}

async function fetchInteractiveReport(path: string, init?: RequestInit): Promise<Response> {
  const apiBaseUrl = getInteractiveReportApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Interactive report API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}${path}`, init);
  if (!response.ok) {
    const message = response.status === 401
      ? "登录会话已过期，请重新登录后再试。"
      : response.status === 409
      ? "分析结果已被其他更新覆盖，请重新打开后再保存。"
      : `Interactive report API returned ${response.status}`;
    throw new Error(message);
  }
  return response;
}

async function readJson<T>(response: Response): Promise<T> {
  return await response.json() as T;
}

function toSavedInteractiveReport(payload: BackendReportDetailResponse): SavedInteractiveReport {
  const { report, version } = payload;
  return {
    report: {
      id: report.id,
      title: report.title,
      subtitle: report.subtitle,
      artifactType: report.artifactType,
      schemaVersion: "1.0",
      renderer: report.renderer,
      document: version.document,
      filters: version.filters,
      queries: version.queries,
      chartSpecs: version.chartSpecs,
      gridSpecs: version.gridSpecs,
      datasets: version.datasets,
      source: {
        threadId: version.sourceThreadId,
        turnId: version.sourceTurnId,
      },
    },
    version: version.version,
    savedAt: version.createdAt,
  };
}
