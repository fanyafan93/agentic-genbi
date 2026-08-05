import type { InteractiveReport } from "../types/interactive-report";

export type AgentEventSystemContext = {
  // ``sessionId`` is the only durable id a frontend has to track a
  // session. It is the Codex-issued thread id (and equals
  // ``analysis_threads.id`` and ``analysis_threads.codex_thread_id``).
  // ``threadId`` is kept for backward compatibility with events that
  // still surface the legacy field name and is always equal to
  // ``sessionId`` for new sessions.
  sessionId?: string;
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
  | ({ type: "thinking"; nodeId: string } & AgentEventSystemContext)
  | ({ type: "debug"; nodeId: string; title: string; content: string } & AgentEventSystemContext)
  | ({ type: "step"; label: string; state: "queued" | "running" | "done"; nodeId?: string; detail?: string } & AgentEventSystemContext)
  | ({ type: "ask"; nodeId: string; question: string; options: { id: string; label: string }[] } & AgentEventSystemContext)
  | ({ type: "tokens"; nodeId: string; text: string } & AgentEventSystemContext)
  | ({ type: "report-artifact"; report: InteractiveReport } & AgentEventSystemContext)
  | ({ type: "artifact"; path: string; kind: "html" | "sql" | "python" | "csv" | "markdown" | "json" } & AgentEventSystemContext)
  | ({ type: "error"; message: string } & AgentEventSystemContext)
  | ({ type: "session/created"; sessionId: string } & AgentEventSystemContext)
  | ({ type: "done" } & AgentEventSystemContext);

// ``sessionId`` is the only durable id we let the caller pass in. It is
// ``null`` for the very first message of a brand-new session
// (sessionless flow, ``POST /api/analysis/sessions/turns``). After the
// first turn completes it is the Codex-issued thread id and any
// continuation call must echo the same id explicitly — the agent
// client must not remember a previous session across calls.
export type AgentInput =
  | { kind: "start"; suggestionId?: string; question?: string; sessionId: string | null }
  | { kind: "message"; content: string; sessionId: string | null }
  | { kind: "reply"; optionId: string; sessionId: string | null }
  | { kind: "reset" };

export interface AgentClient {
  send(input: AgentInput): AsyncIterable<AgentEvent>;
  cancel?(): void;
  // Optional: backend-only hook that asks the server to
  // interrupt the live Codex turn. Local in-page agents
  // (Codex SDK / mock clients) implement ``cancel`` only.
  cancelTurn?(sessionId: string, turnId: string): Promise<void>;
}
