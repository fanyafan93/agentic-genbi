import type { ArtifactKind } from "@/modules/analysis/types/artifact";
import type { InteractiveReport } from "@/modules/analysis/types/interactive-report";
import type { AgentClient, AgentEvent, AgentInput, AnalysisMode } from "./types";

export type BackendRunEvent = {
  type: string;
  run_id: string;
  payload: Record<string, unknown>;
  created_at: string;
};

const artifactKinds = new Set<ArtifactKind>(["html", "sql", "python", "csv", "markdown", "json"]);
const DEFAULT_ANALYSIS_REQUEST_TIMEOUT_MS = 95_000;

export class BackendAnalysisAgentClient implements AgentClient {
  private conversationId: string | null = null;
  private abortController: AbortController | null = null;

  constructor(private readonly apiBaseUrl: string) {}

  async *send(input: AgentInput): AsyncIterable<AgentEvent> {
    if (input.kind === "reset") {
      this.cancel();
      this.conversationId = null;
      yield { type: "conversation-init", runId: "analysis-reset" };
      return;
    }

    const question = getInputQuestion(input);
    if (!question) {
      yield { type: "done" };
      return;
    }

    this.abortController = new AbortController();
    let timedOut = false;
    const timeoutId = globalThis.setTimeout(() => {
      timedOut = true;
      this.abortController?.abort();
    }, getBackendAnalysisRequestTimeoutMs());
    try {
      const response = await fetch(`${this.apiBaseUrl}/api/analysis/tasks/runs/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          conversation_id: input.kind === "start" ? undefined : this.conversationId,
          analysis_mode: getAnalysisMode(input),
          turn_kind: input.kind,
          metadata: {
            frontend_client: "analysis_task",
            ...(getDataEgressAuthorized(input) ? { data_egress_authorized: true } : {}),
            ...(getDataEgressAuthorized(input) ? { semantic_context_egress_authorized: true } : {}),
            ...(getDataEgressAuthorized(input) && input.interactiveReport ? { interactive_report_context: input.interactiveReport } : {}),
          },
        }),
        signal: this.abortController.signal,
      });
      if (!response.ok) {
        throw new Error(`Analysis SSE API returned ${response.status}`);
      }
      for await (const backendEvent of readAnalysisSse(response)) {
        const conversationId = asString(backendEvent.payload.conversation_id);
        if (conversationId) this.conversationId = conversationId;
        for (const event of mapBackendEvents([backendEvent], input.kind)) {
          yield event;
        }
      }
      globalThis.clearTimeout(timeoutId);
    } catch (error) {
      if ((error as Error).name === "AbortError" && !timedOut) {
        globalThis.clearTimeout(timeoutId);
        return;
      }
      globalThis.clearTimeout(timeoutId);
      if (timedOut) {
        yield {
          type: "error",
          message: "Analysis backend request timed out. Please retry or switch to quick analysis.",
        };
        yield { type: "done" };
        return;
      }
      yield {
        type: "error",
        message: error instanceof Error ? error.message : "分析任务后端调用失败",
      };
      yield { type: "done" };
    }
  }

  cancel(): void {
    this.abortController?.abort();
    this.abortController = null;
  }
}

export function shouldUseBackendAnalysisClient(): boolean {
  return (
    process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME === "backend" &&
    Boolean(process.env.NEXT_PUBLIC_GENBI_API_BASE_URL)
  );
}

export function getBackendAnalysisApiBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ?? null;
}

export function getBackendAnalysisRequestTimeoutMs(): number {
  const raw = process.env.NEXT_PUBLIC_ANALYSIS_AGENT_TIMEOUT_MS;
  const parsed = raw ? Number(raw) : DEFAULT_ANALYSIS_REQUEST_TIMEOUT_MS;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_ANALYSIS_REQUEST_TIMEOUT_MS;
}

export async function* readAnalysisSse(response: Response): AsyncIterable<BackendRunEvent> {
  if (!response.body) {
    yield* parseAnalysisSse(await response.text());
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const parts = buffer.split(/\r?\n\r?\n/);
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      yield* parseAnalysisSse(part);
    }
    if (done) break;
  }
  yield* parseAnalysisSse(buffer);
}

export function parseAnalysisSse(text: string): BackendRunEvent[] {
  return text
    .split(/\r?\n\r?\n/)
    .map((block) => block.split(/\r?\n/).filter((line) => line.startsWith("data: ")))
    .filter((lines) => lines.length > 0)
    .map((lines) => lines.map((line) => line.slice(6)).join("\n"))
    .map((data) => JSON.parse(data) as BackendRunEvent);
}

function getInputQuestion(input: AgentInput): string {
  if (input.kind === "start") return input.question || "分析一下渠道销售占比";
  if (input.kind === "message") return input.content;
  if (input.kind === "reply") return input.optionId;
  return "";
}

function getAnalysisMode(input: AgentInput): AnalysisMode {
  if (input.kind === "start" || input.kind === "message" || input.kind === "reply") return input.analysisMode ?? "quick";
  return "quick";
}

export function* mapBackendEvents(events: BackendRunEvent[], inputKind: AgentInput["kind"]): Iterable<AgentEvent> {
  let currentAgentNodeId: string | null = null;
  for (const event of events) {
    const context = getSystemContext(event);
    if (event.type === "run.created") {
      const runId = event.run_id;
      const conversationId = asString(event.payload.conversation_id);
      const question = asString(event.payload.question);
      if (inputKind === "start") {
        yield { ...context, type: "conversation-init", runId, conversationId: conversationId || undefined };
      } else {
        yield { ...context, type: "run-init", runId, conversationId: conversationId || undefined };
      }
      if (question) {
        yield {
          type: "user",
          nodeId: `user-${runId}`,
          content: question,
          itemId: asString(event.payload.user_item_id) || asString(event.payload.item_id) || undefined,
          ...context,
        };
      }
      continue;
    }

    if (event.type === "analysis.problem.classified") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield { type: "agent", nodeId: currentAgentNodeId, content: "", mode: "delta", ...context };
      yield {
        type: "step",
        label: `识别问题类型：${asString(event.payload.label) || "业务分析"}`,
        state: "done",
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "analysis.retrieval.plan") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield { type: "agent", nodeId: currentAgentNodeId, content: "", mode: "delta", ...context };
      for (const item of asRecordArray(event.payload.items)) {
        yield {
          type: "step",
          label: `检索${asString(item.label) || "语义模型"}`,
          state: "done",
          nodeId: currentAgentNodeId,
          itemId: asString(item.item_id) || undefined,
          ...context,
        };
      }
      continue;
    }

    if (event.type === "agent.message.created") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield {
        type: "agent",
        nodeId: currentAgentNodeId,
        content: asString(event.payload.content),
        mode: "replace",
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "agent.message.delta") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield {
        type: "tokens",
        nodeId: currentAgentNodeId,
        text: asString(event.payload.delta),
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "agent.question.requested") {
      yield {
        type: "ask",
        nodeId: `ask-${event.run_id}`,
        question: asString(event.payload.question),
        options: asRecordArray(event.payload.options).map((item) => ({
          id: asString(item.id) || asString(item.label),
          label: asString(item.label) || asString(item.id),
        })),
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "interactive_report.draft") {
      const report = asInteractiveReport(event.payload);
      if (report) {
        yield {
          type: "report-draft",
          report,
          ...context,
          threadId: report.source.threadId,
          turnId: report.source.turnId,
          runId: report.source.runId,
        };
      }
      continue;
    }

    if (event.type === "artifact.created" || event.type === "artifact.updated") {
      const kind = asString(event.payload.kind);
      const path = asString(event.payload.path);
      if (isArtifactKind(kind) && path) {
        yield {
          type: "artifact",
          path,
          kind,
          itemId: asString(event.payload.item_id) || undefined,
          ...context,
        };
      }
      continue;
    }

    if (event.type === "run.failed") {
      yield { type: "error", message: asString(event.payload.detail) || asString(event.payload.error), ...context };
      yield { type: "done", ...context };
      continue;
    }

    if (event.type === "run.completed") {
      yield { type: "done", ...context };
    }
  }
}

function getSystemContext(event: BackendRunEvent) {
  const runId = asString(event.payload.run_id) || event.run_id;
  const threadId = asString(event.payload.thread_id) || asString(event.payload.conversation_id);
  const turnId = asString(event.payload.turn_id) || runId;
  return {
    runId,
    threadId: threadId || undefined,
    turnId: turnId || undefined,
  };
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
}

function getDataEgressAuthorized(input: AgentInput): boolean {
  return input.kind !== "reset" && input.dataEgressAuthorized === true;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function asInteractiveReport(payload: Record<string, unknown>): InteractiveReport | null {
  const source = asRecord(payload.source);
  const document = asRecord(payload.document);
  if (
    payload.artifactType !== "interactive_report"
    || payload.schemaVersion !== "1.0"
    || typeof payload.id !== "string"
    || typeof payload.title !== "string"
    || typeof payload.subtitle !== "string"
    || payload.renderer !== "puck"
    || !document
    || !asRecord(document.root)
    || !Array.isArray(document.content)
    || !asRecord(document.zones)
    || !Array.isArray(payload.filters)
    || !asRecord(payload.queries)
    || !asRecord(payload.chartSpecs)
    || !asRecord(payload.gridSpecs)
    || !source
    || typeof source.threadId !== "string"
    || typeof source.turnId !== "string"
    || typeof source.runId !== "string"
  ) return null;
  return payload as unknown as InteractiveReport;
}

function isArtifactKind(value: string): value is ArtifactKind {
  return artifactKinds.has(value as ArtifactKind);
}
