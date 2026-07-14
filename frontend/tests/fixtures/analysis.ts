import type { AnalysisTaskStatus } from "../../src/types/analysis";

export const queuedTask: AnalysisTaskStatus = {
  task_id: "task-1",
  status: "queued",
  steps: [],
  report: null,
  error: null,
  created_at: "2026-07-14T06:00:00Z",
  updated_at: "2026-07-14T06:00:00Z",
  completed_at: null,
};

export const fixedTask: AnalysisTaskStatus = {
  ...queuedTask,
  status: "succeeded",
  report: {
    title: "固定销售概览",
    summary: ["这是用于验证任务状态流转的固定报告。"],
    sql: "SELECT 'fixed' AS report_name",
    table: {
      columns: [{ name: "report_name", data_type: "varchar" }],
      rows: [{ report_name: "fixed" }],
      row_count: 1,
      truncated: false,
    },
    chart: null,
    assumptions: [],
    warnings: [],
    query_duration_ms: 0,
    sql_attempts: 1,
  },
  completed_at: "2026-07-14T06:00:01Z",
};

export const failedTask: AnalysisTaskStatus = {
  ...queuedTask,
  status: "failed",
  error: { code: "QUERY_FAILED", message: "查询失败，请调整问题后重试。", retryable: false, details: null },
  completed_at: "2026-07-14T06:00:01Z",
};
