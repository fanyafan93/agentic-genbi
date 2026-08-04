import type { InteractiveReport } from "../types/interactive-report";

export type AgentEventSystemContext = {
  threadId?: string | null;
  turnId?: string;
  itemId?: string;
  codexThreadId?: string;
  codexTurnId?: string;
  codexItemId?: string;
};

export type AgentEvent =
  | ({ type: "user"; nodeId: string; content: string } & AgentEventSystemContext)
  | ({ type: "agent"; nodeId: string; content: string; mode?: "delta" | "replace" } & AgentEventSystemContext)
  | ({ type: "thinking"; nodeId: string } & AgentEventSystemContext)
  | ({ type: "debug"; nodeId: string; title: string; content: string } & AgentEventSystemContext)
  | ({ type: "step"; label: string; state: "queued" | "running" | "done"; nodeId?: string; detail?: string } & AgentEventSystemContext)
  | ({ type: "ask"; nodeId: string; question: string; options: { id: string; label: string }[] } & AgentEventSystemContext)
  | ({ type: "tokens"; nodeId: string; text: string } & AgentEventSystemContext)
  | ({ type: "report-artifact"; report: InteractiveReport } & AgentEventSystemContext)
  | ({ type: "artifact"; path: string; kind: "html" | "sql" | "python" | "csv" | "markdown" | "json" } & AgentEventSystemContext)
  | ({ type: "error"; message: string } & AgentEventSystemContext)
  | ({ type: "done" } & AgentEventSystemContext);

export type AgentTurnKind = "start" | "message" | "reply";

/**
 * A single agent invocation request.
 *
 * Every input MUST carry enough routing context to identify the analysis
 * task (a stable client-side id) and the backend thread that should own
 * the new turn. ``signal`` MUST always be supplied by the caller; the
 * client never owns the lifecycle of the underlying fetch.
 *
 * The client keeps no business state across calls; each request is a
 * self-contained (turn = request = AbortController = threadId) unit.
 */
export type AgentInput = {
  kind: AgentTurnKind;
  /** Client-side task identifier used by the caller for cancellation tracking. */
  taskId: string;
  /** Backend thread that owns this turn. Required: never silently default. */
  threadId: string;
  /** Caller-owned AbortSignal that cancels this exact request. */
  signal: AbortSignal;
} & (
  | { kind: "start"; question?: string; suggestionId?: string }
  | { kind: "message"; content: string }
  | { kind: "reply"; optionId: string }
);

export interface AgentClient {
  send(input: AgentInput): AsyncIterable<AgentEvent>;
}
