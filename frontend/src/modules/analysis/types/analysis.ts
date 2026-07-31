export type ChartSpec = {
  type: "bar" | "line" | "pie";
  title: string;
  categoryField: string;
  series: Array<{ field: string; name: string; format?: "currency" | "percent" | "number" }>;
};

export type AnalysisRow = Record<string, string | number>;

export type AnalysisStep = {
  label: string;
  state: "done" | "running" | "queued";
};

export type AnalysisSystemItemKind =
  | "message"
  | "tool_call"
  | "tool_result"
  | "plan"
  | "question"
  | "artifact"
  | "sql"
  | "chart"
  | "report";

export type AnalysisSystemThread = {
  id: string;
  productKind: "analysis_task" | "knowledge_exploration" | "asset_continuation";
  title?: string;
};

export type AnalysisSystemTurn = {
  id: string;
  threadId: string;
  inputKind: "start" | "message" | "reply";
  status: "running" | "needs_input" | "complete" | "failed";
};

export type AnalysisSystemRun = {
  id: string;
  threadId: string;
  turnId: string;
  status: "running" | "complete" | "failed";
};

export type AnalysisSystemItem = {
  id: string;
  threadId: string;
  turnId: string;
  runId?: string;
  kind: AnalysisSystemItemKind;
  payload: Record<string, unknown>;
};

export type AnalysisRun = {
  id: string;
  question: string;
  status: "running" | "needs_input" | "complete";
  steps: AnalysisStep[];
  insight: string[];
  sql: string;
  table: AnalysisRow[];
  chart: ChartSpec;
};
