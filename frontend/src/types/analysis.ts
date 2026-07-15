export type TaskState = "queued" | "running" | "succeeded" | "failed" | "requires_input";

export type StepState = "started" | "succeeded" | "failed";

export interface AgentExecutionStep {
  step_id: string;
  sequence: number;
  kind: string;
  status: StepState;
  title: string;
  detail: string | null;
  attempt: number | null;
  started_at: string;
  finished_at: string | null;
}

export interface ResultColumn {
  name: string;
  data_type: string;
}

export interface ReportTable {
  columns: ResultColumn[];
  rows: Array<Record<string, unknown>>;
  row_count: number;
  truncated: boolean;
}

export interface ChartSpec {
  type: "line" | "bar" | "pie";
  title: string;
  x_field: string;
  y_fields: string[];
  series_field: string | null;
}

export interface AnalysisReport {
  title: string;
  summary: string[];
  sql: string;
  table: ReportTable;
  chart: ChartSpec | null;
  assumptions: string[];
  warnings: string[];
  query_duration_ms: number;
  sql_attempts: number;
}

export interface ApiError {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown> | null;
}

export interface AnalysisTaskStatus {
  task_id: string;
  status: TaskState;
  steps: AgentExecutionStep[];
  report: AnalysisReport | null;
  error: ApiError | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

