import type { Data } from "@puckeditor/core";

export type ReportFilterId = "month" | "brand" | "region";

export type ReportFilterDefinition = {
  id: ReportFilterId;
  label: string;
  options: Array<{ label: string; value: string }>;
  defaultValue: string;
};

export type ReportChartSpec = {
  id: string;
  datasetId: string;
  type: "bar" | "line";
  xField: string;
  title: string;
  series: Array<{ field: string; label: string; format?: "currency" | "percent" | "number" }>;
};

export type ReportGridSpec = {
  id: string;
  datasetId: string;
  columns: Array<{ field: string; label: string; format?: "currency" | "percent" | "number" }>;
  pageSize: number;
};

export type InteractiveReport = {
  artifactType: "interactive_report";
  schemaVersion: "1.0";
  id: string;
  title: string;
  subtitle: string;
  renderer: "puck";
  document: Data;
  filters: ReportFilterDefinition[];
  queries: Record<string, { datasetId: string; filterBindings: ReportFilterId[] }>;
  chartSpecs: Record<string, ReportChartSpec>;
  gridSpecs: Record<string, ReportGridSpec>;
  datasets?: Record<string, { rows: ReportDatasetRow[] }>;
  originType?: "codex" | "seed" | "import" | "manual";
  source?: {
    threadId: string;
    turnId: string;
  };
};

export type ReportRuntimeFilters = Record<ReportFilterId, string>;

export type ReportDatasetRow = Record<string, string | number>;
