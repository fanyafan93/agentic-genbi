import type { InteractiveReport } from "../types/interactive-report";

export type AgentEventSystemContext = {
  threadId?: string;
  turnId?: string;
  itemId?: string;
  codexThreadId?: string;
  codexTurnId?: string;
  codexItemId?: string;
};

export type AgentEvent =
  | ({ type: "user"; nodeId: string; content: string } & AgentEventSystemContext)
  | ({ type: "agent"; nodeId: string; content: string; mode?: "delta" | "replace" } & AgentEventSystemContext)
  | ({ type: "debug"; nodeId: string; title: string; content: string } & AgentEventSystemContext)
  | ({ type: "step"; label: string; state: "queued" | "running" | "done"; nodeId?: string; detail?: string } & AgentEventSystemContext)
  | ({ type: "ask"; nodeId: string; question: string; options: { id: string; label: string }[] } & AgentEventSystemContext)
  | ({ type: "tokens"; nodeId: string; text: string } & AgentEventSystemContext)
  | ({ type: "report-artifact"; report: InteractiveReport } & AgentEventSystemContext)
  | ({ type: "artifact"; path: string; kind: "html" | "sql" | "python" | "csv" | "markdown" | "json" } & AgentEventSystemContext)
  | ({ type: "error"; message: string } & AgentEventSystemContext)
  | ({ type: "done" } & AgentEventSystemContext);

export type AgentInput =
  | { kind: "start"; suggestionId?: string; question?: string }
  | { kind: "message"; content: string }
  | { kind: "reply"; optionId: string }
  | { kind: "reset" };

export interface AgentClient {
  send(input: AgentInput): AsyncIterable<AgentEvent>;
  cancel?(): void;
}
