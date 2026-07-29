export type ExplorationStatus = "进行中" | "待确认" | "已完成";
export type ExplorationTab = "explorations" | "resources" | "knowledge";

export type ExplorationMessage = {
  id: string;
  role: "user" | "agent";
  title?: string;
  body: string;
  details?: {
    label: string;
    items: string[];
  }[];
  action?: "沉淀为知识";
};

export type Exploration = {
  id: string;
  title: string;
  agent: string;
  status: ExplorationStatus;
  updatedAt: string;
  resources: number;
  summary: string;
  messages: ExplorationMessage[];
};

export type Resource = {
  id: string;
  type: "报表" | "ETL" | "SQL" | "数据表";
  name: string;
  location: string;
  description: string;
};

export type ResourceExcerpt = {
  resourceId: string;
  relativePath: string;
  section: "head" | "tail" | "match";
  startLine: number;
  endLine: number;
  truncated: boolean;
  encoding: string | null;
  text: string;
};

export type ResourceSignalGroup = {
  label: string;
  items: string[];
};

export type ResourceProfileItem = {
  label: string;
  value: string;
};

export type ResourceDetail = {
  resourceId: string;
  status: string;
  truncatedSummary: boolean;
  sizeBytes: number;
  modifiedAt: string;
  warnings: string[];
  profileItems: ResourceProfileItem[];
  signalGroups: ResourceSignalGroup[];
};

export type RunTraceMetric = {
  label: string;
  value: string;
};

export type RunTraceSummary = {
  runId: string;
  title: string;
  status: string;
  question: string;
  startedAt: string | null;
  completedAt: string | null;
  error: string | null;
  metrics: RunTraceMetric[];
};

export type Knowledge = {
  id: string;
  title: string;
  question?: string;
  scope: string;
  verified: string;
  verification?: string;
  note: string;
  evidenceRefs?: string[];
  runId?: string | null;
};

export type ResourceIndexStatus = {
  indexed: boolean;
  root: string | null;
  resourceCount: number;
  typeCounts: Record<string, number>;
  indexModifiedAt: string | null;
  summaryModifiedAt: string | null;
};

export type RuntimeCheck = {
  name: "llm" | "openai" | "mysql" | "resource_library" | "frontend_api_base" | "cost_config";
  ok: boolean;
  message: string;
  detail: string | null;
};

export type RuntimeStatus = {
  connected: boolean;
  ready: boolean;
  envFile: string | null;
  envLoaded: boolean;
  checks: RuntimeCheck[];
};

export type ExplorationRunEvent = {
  type:
    | "run.created"
    | "agent.title.generated"
    | "agent.message.created"
    | "agent.message.delta"
    | "agent.runner.started"
    | "agent.runner.completed"
    | "agent.runner.failed"
    | "agent.runner.agent_updated"
    | "agent.runner.item"
    | "agent.runner.raw"
    | "tool.call.started"
    | "tool.call.completed"
    | "tool.call.failed"
    | "agent.evidence.available"
    | "agent.question.requested"
    | "run.completed"
    | "run.failed";
  run_id: string;
  created_at: string;
  payload: Record<string, unknown>;
};
