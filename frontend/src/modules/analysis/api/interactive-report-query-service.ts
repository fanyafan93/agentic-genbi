import type { ReportDatasetRow, ReportRuntimeFilters } from "../types/interactive-report";

type ReportQueryResponse = {
  queryRef: string;
  rows: ReportDatasetRow[];
};

export function shouldUseBackendReportQueries(): boolean {
  return process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME === "backend" && Boolean(getReportQueryApiBaseUrl());
}

export async function fetchInteractiveReportQuery(queryRef: string, filters: ReportRuntimeFilters): Promise<ReportQueryResponse> {
  const apiBaseUrl = getReportQueryApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Interactive report query API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/report-queries/${encodeURIComponent(queryRef)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filters }),
  });
  if (!response.ok) throw new Error(`Interactive report query API returned ${response.status}`);
  return await response.json() as ReportQueryResponse;
}

function getReportQueryApiBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ?? null;
}
