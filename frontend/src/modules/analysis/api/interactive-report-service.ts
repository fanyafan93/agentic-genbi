import type { SavedInteractiveReport } from "../mocks/interactive-report-storage";
import type { InteractiveReport } from "../types/interactive-report";

type BackendReportSummary = {
  id: string;
  title: string;
  subtitle: string;
  artifactType: "interactive_report";
  renderer: "puck";
  ownerId: string;
  sourceThreadId: string;
  sourceTurnId: string;
  sourceExecutionAttemptId?: string;
  sourceRunId?: string;
  latestVersion: number;
  createdAt: string;
  updatedAt: string;
};

type BackendReportVersion = {
  reportId: string;
  version: number;
  sourceThreadId: string;
  sourceTurnId: string;
  sourceExecutionAttemptId?: string;
  sourceRunId?: string;
  document: InteractiveReport["document"];
  filters: InteractiveReport["filters"];
  queries: InteractiveReport["queries"];
  chartSpecs: InteractiveReport["chartSpecs"];
  gridSpecs: InteractiveReport["gridSpecs"];
  createdAt: string;
};

export type InteractiveReportVersionSummary = {
  reportId: string;
  version: number;
  sourceThreadId: string;
  sourceTurnId: string;
  sourceExecutionAttemptId?: string;
  sourceRunId?: string;
  createdAt: string;
};

type BackendReportDetailResponse = {
  report: BackendReportSummary;
  version: BackendReportVersion;
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
  expectedVersion?: number,
  ownerId = DEFAULT_REPORT_OWNER_ID,
): Promise<SavedInteractiveReport> {
  const response = await fetchInteractiveReport("/api/analysis/reports", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...report, ownerId, expectedVersion }),
  });
  return toSavedInteractiveReport(await readJson<BackendReportDetailResponse>(response));
}

export async function getInteractiveReportFromBackend(reportId: string, version?: number): Promise<SavedInteractiveReport> {
  const suffix = version === undefined ? "" : `/versions/${version}`;
  const response = await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}${suffix}`);
  return toSavedInteractiveReport(await readJson<BackendReportDetailResponse>(response));
}

export async function listInteractiveReportVersionsFromBackend(reportId: string): Promise<InteractiveReportVersionSummary[]> {
  const response = await fetchInteractiveReport(`/api/analysis/reports/${encodeURIComponent(reportId)}/versions`);
  const payload = await readJson<{ versions: InteractiveReportVersionSummary[] }>(response);
  return payload.versions;
}

export async function listInteractiveReportsFromBackend(ownerId = DEFAULT_REPORT_OWNER_ID): Promise<SavedInteractiveReport[]> {
  const response = await fetchInteractiveReport(`/api/analysis/reports?owner_id=${encodeURIComponent(ownerId)}`);
  const payload = await readJson<{ reports: BackendReportSummary[] }>(response);
  return Promise.all(payload.reports.map((report) => getInteractiveReportFromBackend(report.id)));
}

async function fetchInteractiveReport(path: string, init?: RequestInit): Promise<Response> {
  const apiBaseUrl = getInteractiveReportApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Interactive report API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}${path}`, init);
  if (!response.ok) {
    const message = response.status === 409 ? "分析结果已被其他更新覆盖，请重新打开后再保存。" : `Interactive report API returned ${response.status}`;
    throw new Error(message);
  }
  return response;
}

async function readJson<T>(response: Response): Promise<T> {
  return await response.json() as T;
}

function toSavedInteractiveReport(payload: BackendReportDetailResponse): SavedInteractiveReport {
  const { report, version } = payload;
  const executionAttemptId = version.sourceExecutionAttemptId ?? version.sourceRunId ?? "";
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
      source: {
        threadId: version.sourceThreadId,
        turnId: version.sourceTurnId,
        executionAttemptId,
        runId: version.sourceRunId ?? executionAttemptId,
      },
    },
    version: version.version,
    savedAt: version.createdAt,
  };
}
