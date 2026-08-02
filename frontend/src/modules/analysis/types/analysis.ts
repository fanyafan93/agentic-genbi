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
  productKind: "analysis_task" | "asset_continuation";
  title?: string;
};

export type AnalysisSystemTurn = {
  id: string;
  threadId: string;
  inputKind: "start" | "message" | "reply";
  status: "running" | "needs_input" | "complete" | "failed";
};

export type AnalysisSystemItem = {
  id: string;
  threadId: string;
  turnId: string;
  kind: AnalysisSystemItemKind;
  payload: Record<string, unknown>;
};
