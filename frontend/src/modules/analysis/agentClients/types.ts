export type AgentEvent =
  | { type: "session-init"; runId: string; question?: string }
  | { type: "user"; nodeId: string; content: string }
  | { type: "agent"; nodeId: string; content: string; mode?: "delta" | "replace" }
  | { type: "step"; label: string; state: "queued" | "running" | "done"; nodeId?: string }
  | { type: "ask"; nodeId: string; question: string; options: { id: string; label: string }[] }
  | { type: "tokens"; nodeId: string; text: string }
  | { type: "artifact"; path: string; kind: "html" | "sql" | "python" | "csv" | "markdown" | "json" }
  | { type: "error"; message: string }
  | { type: "done" };

export type AgentInput =
  | { kind: "start"; suggestionId?: string; question?: string }
  | { kind: "message"; content: string }
  | { kind: "reply"; optionId: string }
  | { kind: "reset" };

export interface AgentClient {
  send(input: AgentInput): AsyncIterable<AgentEvent>;
  cancel?(): void;
}
