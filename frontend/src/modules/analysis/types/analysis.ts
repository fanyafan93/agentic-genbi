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
