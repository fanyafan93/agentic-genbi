export type FineReportCounts = {
  sheets: number;
  datasets: number;
  sqlDatasets: number;
  parameters: number;
  parameterWidgets: number;
  conditionalRules: number;
  cells: number;
  formulas: number;
  bindings: number;
};

export type FineReportReportSummary = {
  id: string;
  name: string;
  sourceCptPath?: string | null;
  sheetNames: string[];
  status: "complete" | "incomplete";
  availableParts: string[];
  missingParts: string[];
  errors: string[];
  counts: FineReportCounts;
};

export type FineReportDataset = {
  name: string;
  type?: string;
  fine_report_class?: string;
  connection_name?: string;
  raw_sql?: string;
  parameters?: Array<Record<string, unknown>>;
  embedded_row_count?: number;
};

export type FineReportCell = {
  cell: string;
  row: number;
  column: string;
  columnIndex: number;
  rowspan: number;
  colspan: number;
  value?: unknown;
  formula?: string;
  binding?: { dataset?: string; field?: string } | null;
  dependencies?: unknown;
};

export type FineReportSheet = {
  name: string;
  rowCount: number;
  columnCount: number;
  cells: FineReportCell[];
};

export type FineReportReportDetail = {
  report: FineReportReportSummary;
  datasets: FineReportDataset[];
  parameters: Array<Record<string, unknown>>;
  parameterWidgets: Array<Record<string, unknown>>;
  conditionalRules: Array<Record<string, unknown>>;
  sheets: FineReportSheet[];
};

function apiBaseUrl(): string {
  const baseUrl = process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl) throw new Error("FineReport API base URL is not configured.");
  return baseUrl.replace(/\/$/, "");
}

export async function listFineReportReports(): Promise<FineReportReportSummary[]> {
  const response = await fetch(`${apiBaseUrl()}/api/business-semantics/finereport/reports`);
  if (!response.ok) throw new Error(`FineReport API returned ${response.status}`);
  const payload = (await response.json()) as { reports: FineReportReportSummary[] };
  return payload.reports;
}

export async function getFineReportReport(reportId: string): Promise<FineReportReportDetail> {
  const response = await fetch(
    `${apiBaseUrl()}/api/business-semantics/finereport/reports/${encodeURIComponent(reportId)}`,
  );
  if (!response.ok) throw new Error(`FineReport API returned ${response.status}`);
  return (await response.json()) as FineReportReportDetail;
}
