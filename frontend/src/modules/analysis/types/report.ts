import type { Data } from "@puckeditor/core";

export type ReportFilterValue =
  | string
  | string[]
  | null;

export type ReportFilterDefinition = {
  type: "select" | "multiSelect" | "date" | "dateRange";
  label: string;
  defaultValue?: ReportFilterValue;
  options?: Array<{ label: string; value: string }>;
};

export type ReportQueryParameter = {
  filterId: string;
  type: "string" | "string[]" | "date" | "number" | "boolean";
  valueIndex?: number;
};

export type ReportSort = {
  field: string;
  direction: "asc" | "desc";
};

export type ReportColumnFilters = Record<string, string[]>;

export type ReportQueryControls = {
  sortableFields: string[];
  filterableFields: string[];
};

export type ReportQuery = {
  dataSource: "doris" | "mysql";
  sql: string;
  parameters: Record<string, ReportQueryParameter>;
  pagination: boolean;
  controls?: ReportQueryControls;
};

export type ReportChart = {
  queryId: string;
  option: Record<string, unknown>;
};

export type ReportExportColumn = {
  field: string;
  title: string;
  type?: "text" | "number" | "date" | "datetime" | "boolean";
};

export type ReportTable = {
  type?: "list" | "pivot";
  queryId: string;
  exportColumns?: ReportExportColumn[];
  options: Record<string, unknown>;
};

export type ReportBuildStatus =
  | "building"
  | "validating"
  | "failed"
  | "published";

export type ReportBuildValidationError = {
  path: string;
  code: string;
  message: string;
};

export type Report = {
  id: string;
  title: string;
  subtitle: string;
  ownerId: string;
  turnId: string | null;
  sourceSessionId?: string | null;
  isExample: boolean;
  layout: Data;
  filters: Record<string, ReportFilterDefinition>;
  charts: Record<string, ReportChart>;
  tables: Record<string, ReportTable>;
  queries: Record<string, ReportQuery>;
  buildId?: string;
  buildRevision?: number;
  buildStatus?: ReportBuildStatus;
  buildValidationErrors?: ReportBuildValidationError[];
  createdAt?: string;
  updatedAt?: string;
};

export type SavedReport = {
  report: Report;
};

export type SharedReport = SavedReport & {
  reportId: string;
  recipientUserId: string;
  permission: "view" | "view_and_reuse";
  createdAt: string;
};

export type ReportCenter = {
  mine: SavedReport[];
  sharedWithMe: SharedReport[];
  examples: SavedReport[];
};

export type ReportQueryRequest = {
  filters: Record<string, ReportFilterValue>;
  page?: number;
  pageSize?: number;
  sort?: ReportSort | null;
  columnFilters?: ReportColumnFilters;
};

export type ReportQueryResult = {
  columns: Array<{
    field: string;
    label: string;
    type: string;
  }>;
  rows: Array<Record<string, unknown>>;
  page: number;
  pageSize: number;
  total: number;
};

export type ReportTableExportRequest = Pick<
  ReportQueryRequest,
  "filters" | "sort" | "columnFilters"
>;

export type ReportTableExportFile = {
  blob: Blob;
  filename: string;
};
