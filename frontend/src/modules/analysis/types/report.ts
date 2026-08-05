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

export type ReportQuery = {
  dataSource: "doris" | "mysql";
  sql: string;
  parameters: Record<string, ReportQueryParameter>;
  pagination: boolean;
};

export type ReportChart = {
  queryId: string;
  option: Record<string, unknown>;
};

export type ReportTable = {
  queryId: string;
  options: Record<string, unknown>;
};

export type Report = {
  id: string;
  title: string;
  subtitle: string;
  ownerId: string;
  turnId: string | null;
  sourceSessionId?: string | null;
  layout: Data;
  filters: Record<string, ReportFilterDefinition>;
  charts: Record<string, ReportChart>;
  tables: Record<string, ReportTable>;
  queries: Record<string, ReportQuery>;
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
};

export type ReportQueryRequest = {
  filters: Record<string, ReportFilterValue>;
  page?: number;
  pageSize?: number;
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
