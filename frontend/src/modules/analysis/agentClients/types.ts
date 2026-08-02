import type { InteractiveReport } from "../types/interactive-report";

export type AgentEventSystemContext = {
  threadId?: string;
  turnId?: string;
  executionAttemptId?: string;
  /** Compatibility mirror for the old Run-based contract. */
  runId?: string;
  itemId?: string;
  codexThreadId?: string;
  codexTurnId?: string;
  codexItemId?: string;
};

export type AgentEvent =
  | ({ type: "conversation-init"; executionAttemptId: string; runId?: string; conversationId?: string; question?: string } & AgentEventSystemContext)
  | ({ type: "run-init"; executionAttemptId: string; runId?: string; conversationId?: string } & AgentEventSystemContext)
  | ({ type: "user"; nodeId: string; content: string } & AgentEventSystemContext)
  | ({ type: "agent"; nodeId: string; content: string; mode?: "delta" | "replace" } & AgentEventSystemContext)
  | ({ type: "debug"; nodeId: string; title: string; content: string } & AgentEventSystemContext)
  | ({ type: "step"; label: string; state: "queued" | "running" | "done"; nodeId?: string } & AgentEventSystemContext)
  | ({ type: "ask"; nodeId: string; question: string; options: { id: string; label: string }[] } & AgentEventSystemContext)
  | ({ type: "tokens"; nodeId: string; text: string } & AgentEventSystemContext)
  | ({ type: "report-draft"; report: InteractiveReport } & AgentEventSystemContext)
  | ({ type: "artifact"; path: string; kind: "html" | "sql" | "python" | "csv" | "markdown" | "json" } & AgentEventSystemContext)
  | ({ type: "error"; message: string } & AgentEventSystemContext)
  | ({ type: "done" } & AgentEventSystemContext);

export type AgentInput =
  | { kind: "start"; suggestionId?: string; question?: string; interactiveReport?: InteractiveReport }
  | { kind: "message"; content: string; interactiveReport?: InteractiveReport }
  | { kind: "reply"; optionId: string; interactiveReport?: InteractiveReport }
  | { kind: "reset" };

export interface AgentClient {
  send(input: AgentInput): AsyncIterable<AgentEvent>;
  cancel?(): void;
}
