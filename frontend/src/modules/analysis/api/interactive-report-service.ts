import type { InteractiveReport } from "../types/interactive-report";

export type SavedInteractiveReport = {
  report: InteractiveReport;
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

type BackendReport = {
  id: string;
  title: string;
  subtitle: string;
  artifactType: "interactive_report";
  renderer: "puck";
  ownerId: string;
  originType: "codex" | "seed" | "import" | "manual";
  sourceThreadId?: string;
  sourceTurnId?: string;
  document: InteractiveReport["document"];
  filters: InteractiveReport["filters"];
  queries: InteractiveReport["queries"];
  chartSpecs: InteractiveReport["chartSpecs"];
  gridSpecs: InteractiveReport["gridSpecs"];
  datasets?: InteractiveReport["datasets"];
  createdAt: string;
  updatedAt: string;
};

type BackendReportDetailResponse = {
  report: BackendReport;
};

type BackendReportCenterResponse = {
  mine: Array<{ report: BackendReport }>;
  sharedWithMe: Array<{
    reportId: string;
    recipientUserId: string;
    permission: "view" | "view_and_reuse";
    createdAt: string;
    report: BackendReport;
  }>;
};

const DEFAULT_REPORT_OWNER_ID = "local-user";

export function shouldUseBackendInteractiveReports(): boolean {
  return process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME === "backend" && Boolean(getInteractiveReportApiBaseUrl());
}

export function getInteractiveReportApiBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ?? null;
}

export async function saveInteractiveReportToBackend(
  report: InteractiveReport,
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<SavedInteractiveReport> {
  const response = await fetchInteractiveReport("/api/analysis/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...report, ownerId }),
  });
  return toSavedInteractiveReport(await readJson<BackendReportDetailResponse>(response));
}

export async function getInteractiveReportFromBackend(reportId: string): Promise<SavedInteractiveReport> {
  const response = await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}`);
  return toSavedInteractiveReport(await readJson<BackendReportDetailResponse>(response));
}

export async function listInteractiveReportsFromBackend(ownerId = DEFAULT_REPORT_OWNER_ID): Promise<SavedInteractiveReport[]> {
  const response = await fetchInteractiveReport(`/api/analysis/reports?owner_id=${encodeURIComponent(ownerId)}`);
  const payload = await readJson<{ reports: BackendReport[] }>(response);
  return payload.reports.map((report) => toSavedInteractiveReport({ report }));
}

export async function listReportCenterFromBackend(userId = DEFAULT_REPORT_OWNER_ID): Promise<ReportCenter> {
  const response = await fetchInteractiveReport(`/api/analysis/report-center?user_id=${encodeURIComponent(userId)}`);
  const payload = await readJson<BackendReportCenterResponse>(response);
  const mine = payload.mine.map((item) => toSavedInteractiveReport({ report: item.report }));
  const sharedWithMe = payload.sharedWithMe.map((item) => ({
    ...toSavedInteractiveReport({ report: item.report }),
    permission: item.permission,
    sharedAt: item.createdAt,
    sharedByReportOwnerId: item.report.ownerId,
  }));
  return { mine, sharedWithMe };
}

export async function renameInteractiveReportInBackend(
  reportId: string,
  title: string,
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<void> {
  await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ownerId, title }),
  });
}

export async function shareInteractiveReportToBackend(
  reportId: string,
  recipientUserId: string,
  permission: "view" | "view_and_reuse",
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<void> {
  await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}/shares`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ownerId, recipientUserId, permission }),
  });
}

export async function deleteInteractiveReportFromBackend(
  reportId: string,
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<void> {
  await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}?owner_id=${encodeURIComponent(ownerId)}`, {
    method: "DELETE",
  });
}

export async function createAnalysisThreadFromReportBackend(
  reportId: string,
  title?: string,
  userId = DEFAULT_REPORT_OWNER_ID,
): Promise<ReportAnalysisThread> {
  // The new contract provisions a session anchored to a saved
  // report. The session id comes from the Codex runtime; the
  // body never carries it.
  const response = await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userId, title }),
  });
  const payload = await readJson<{ session: ReportAnalysisThread["thread"]; report: BackendReportDetailResponse }>(response);
  return {
    thread: payload.session,
    saved: toSavedInteractiveReport(payload.report),
  };
}

export async function listInteractiveReportsByThreadFromBackend(threadId: string): Promise<SavedInteractiveReport[]> {
  const response = await fetchInteractiveReport(`/api/analysis/reports?source_thread_id=${encodeURIComponent(threadId)}`);
  const payload = await readJson<{ reports: BackendReport[] }>(response);
  return payload.reports.map((report) => toSavedInteractiveReport({ report }));
}

async function fetchInteractiveReport(path: string, init?: RequestInit): Promise<Response> {
  const apiBaseUrl = getInteractiveReportApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Interactive report API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}${path}`, init);
  if (!response.ok) {
    throw new Error(`Interactive report API returned ${response.status}`);
  }
  return response;
}

async function readJson<T>(response: Response): Promise<T> {
  return await response.json() as T;
}

function toSavedInteractiveReport(payload: BackendReportDetailResponse): SavedInteractiveReport {
  const { report } = payload;
  const source = report.sourceThreadId && report.sourceTurnId
    ? { threadId: report.sourceThreadId, turnId: report.sourceTurnId }
    : undefined;
  return {
    report: {
      id: report.id,
      title: report.title,
      subtitle: report.subtitle,
      artifactType: report.artifactType,
      schemaVersion: "1.0",
      renderer: report.renderer,
      document: report.document,
      filters: report.filters,
      queries: report.queries,
      chartSpecs: report.chartSpecs,
      gridSpecs: report.gridSpecs,
      datasets: report.datasets,
      originType: report.originType,
      source,
    },
    savedAt: report.updatedAt,
  };
}
