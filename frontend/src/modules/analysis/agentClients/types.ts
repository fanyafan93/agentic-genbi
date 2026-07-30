export type AnalysisMode = "quick" | "deep";

export type AgentEvent =
  | { type: "conversation-init"; runId: string; conversationId?: string; question?: string }
  | { type: "run-init"; runId: string; conversationId?: string }
  | { type: "user"; nodeId: string; content: string }
  | { type: "agent"; nodeId: string; content: string; mode?: "delta" | "replace" }
  | { type: "step"; label: string; state: "queued" | "running" | "done"; nodeId?: string }
  | { type: "ask"; nodeId: string; question: string; options: { id: string; label: string }[] }
  | { type: "tokens"; nodeId: string; text: string }
  | { type: "artifact"; path: string; kind: "html" | "sql" | "python" | "csv" | "markdown" | "json" }
  | { type: "error"; message: string }
  | { type: "done" };

export type AgentInput =
  | { kind: "start"; suggestionId?: string; question?: string; analysisMode?: AnalysisMode }
  | { kind: "message"; content: string; analysisMode?: AnalysisMode }
  | { kind: "reply"; optionId: string; analysisMode?: AnalysisMode }
  | { kind: "reset" };

export interface AgentClient {
  send(input: AgentInput): AsyncIterable<AgentEvent>;
  cancel?(): void;
}
