export type AnalysisMode = "quick" | "deep";

export type AgentEventSystemContext = {
  threadId?: string;
  turnId?: string;
  runId?: string;
  itemId?: string;
};

export type AgentEvent =
  | ({ type: "conversation-init"; runId: string; conversationId?: string; question?: string } & AgentEventSystemContext)
  | ({ type: "run-init"; runId: string; conversationId?: string } & AgentEventSystemContext)
  | ({ type: "user"; nodeId: string; content: string } & AgentEventSystemContext)
  | ({ type: "agent"; nodeId: string; content: string; mode?: "delta" | "replace" } & AgentEventSystemContext)
  | ({ type: "step"; label: string; state: "queued" | "running" | "done"; nodeId?: string } & AgentEventSystemContext)
  | ({ type: "ask"; nodeId: string; question: string; options: { id: string; label: string }[] } & AgentEventSystemContext)
  | ({ type: "tokens"; nodeId: string; text: string } & AgentEventSystemContext)
  | ({ type: "artifact"; path: string; kind: "html" | "sql" | "python" | "csv" | "markdown" | "json" } & AgentEventSystemContext)
  | ({ type: "error"; message: string } & AgentEventSystemContext)
  | ({ type: "done" } & AgentEventSystemContext);

export type AgentInput =
  | { kind: "start"; suggestionId?: string; question?: string; analysisMode?: AnalysisMode }
  | { kind: "message"; content: string; analysisMode?: AnalysisMode }
  | { kind: "reply"; optionId: string; analysisMode?: AnalysisMode }
  | { kind: "reset" };

export interface AgentClient {
  send(input: AgentInput): AsyncIterable<AgentEvent>;
  cancel?(): void;
}
