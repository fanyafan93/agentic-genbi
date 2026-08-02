import type { ArtifactKind } from "@/modules/analysis/types/artifact";
import type { InteractiveReport } from "@/modules/analysis/types/interactive-report";
import type { AgentClient, AgentEvent, AgentInput } from "./types";

export type BackendTurnEvent = {
  type: string;
  turn_id: string;
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
      yield { type: "conversation-init", turnId: "analysis-reset" };
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
      const threadTurnUrl = this.conversationId && input.kind !== "start"
        ? `${this.apiBaseUrl}/api/analysis/threads/${encodeURIComponent(this.conversationId)}/turns/stream`
        : `${this.apiBaseUrl}/api/analysis/threads/turns/stream`;
      const response = await fetch(threadTurnUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          turn_kind: input.kind,
          metadata: {
            frontend_client: "analysis_task",
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
          message: "Analysis backend request timed out. Please retry.",
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

export async function* readAnalysisSse(response: Response): AsyncIterable<BackendTurnEvent> {
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

export function parseAnalysisSse(text: string): BackendTurnEvent[] {
  return text
    .split(/\r?\n\r?\n/)
    .map((block) => block.split(/\r?\n/).filter((line) => line.startsWith("data: ")))
    .filter((lines) => lines.length > 0)
    .map((lines) => lines.map((line) => line.slice(6)).join("\n"))
    .map((data) => JSON.parse(data) as BackendTurnEvent);
}

function getInputQuestion(input: AgentInput): string {
  if (input.kind === "start") return input.question || "分析一下渠道销售占比";
  if (input.kind === "message") return input.content;
  if (input.kind === "reply") return input.optionId;
  return "";
}

export function* mapBackendEvents(events: BackendTurnEvent[], inputKind: AgentInput["kind"]): Iterable<AgentEvent> {
  let currentAgentNodeId: string | null = null;
  for (const event of events) {
    const context = getSystemContext(event);
    const method = asString(event.payload.codex_method) || event.type;
    const codexItemType = asString(event.payload.codex_item_type);
    if (event.type === "turn/started" || method === "turn/started") {
      const turnId = context.turnId || event.turn_id;
      const conversationId = asString(event.payload.conversation_id);
      const question = asString(event.payload.question);
      if (inputKind === "start") {
        yield { ...context, type: "conversation-init", turnId, conversationId: conversationId || undefined };
      }
      if (question) {
        yield {
          type: "user",
          nodeId: `user-${turnId}`,
          content: question,
          itemId: asString(event.payload.user_item_id) || asString(event.payload.item_id) || undefined,
          ...context,
        };
      }
      yield {
        type: "step",
        label: "模型响应",
        state: "running",
        nodeId: getAgentNodeId(event),
        ...context,
      };
      continue;
    }

    const isToolItemEvent = (
      (event.type === "item/started" || event.type === "item/completed" || method === "item/started" || method === "item/completed")
      && ["toolCall", "toolResult"].includes(codexItemType)
    );
    if (isToolItemEvent) {
      currentAgentNodeId ||= `agent-${event.turn_id}`;
      const toolName = asString(event.payload.tool) || asString(event.payload.name) || "tool";
      yield {
        type: "step",
        label: `工具调用：${toolName}`,
        state: event.type === "item/started" ? "running" : "done",
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      yield {
        type: "debug",
        title: `工具事件：${event.type}`,
        content: JSON.stringify(event.payload, null, 2),
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "item/completed" && method === "item/completed" && codexItemType === "agentMessage") {
      const agentNodeId = getAgentNodeId(event);
      const content = asString(event.payload.content);
      yield {
        type: "agent",
        nodeId: agentNodeId,
        content,
        mode: "replace",
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "item/agentMessage/delta" || method === "item/agentMessage/delta") {
      yield {
        type: "tokens",
        nodeId: getAgentNodeId(event),
        text: asString(event.payload.delta),
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "item/completed" && codexItemType === "agentQuestion") {
      yield {
        type: "ask",
        nodeId: `ask-${event.turn_id}`,
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

    if (event.type === "genbi/artifact/updated" && asString(event.payload.artifactType) === "interactive_report") {
      const report = asInteractiveReport(event.payload);
      if (report) {
        yield {
          type: "report-artifact",
          report,
          ...context,
          threadId: report.source.threadId,
          turnId: report.source.turnId,
        };
      }
      continue;
    }

    if (event.type === "genbi/artifact/created" || event.type === "genbi/artifact/updated") {
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

    if (event.type === "turn/completed" || method === "turn/completed") {
      if (asString(event.payload.status) === "failed") {
        yield {
          type: "error",
          message: asString(event.payload.detail) || asString(event.payload.error) || "Analysis turn failed",
          ...context,
        };
      }
      yield { type: "done", ...context };
      continue;
    }
  }
}

function getAgentNodeId(event: BackendTurnEvent): string {
  const turnId = asString(event.payload.turn_id) || event.turn_id;
  return `agent-${turnId}`;
}

function getSystemContext(event: BackendTurnEvent) {
  const turnId = asString(event.payload.turn_id) || event.turn_id;
  const threadId = asString(event.payload.thread_id) || asString(event.payload.conversation_id);
  const codexThreadId = asString(event.payload.codex_thread_id);
  const codexTurnId = asString(event.payload.codex_turn_id);
  const codexItemId = asString(event.payload.codex_item_id);
  return {
    turnId,
    threadId: threadId || undefined,
    codexThreadId: codexThreadId || undefined,
    codexTurnId: codexTurnId || undefined,
    codexItemId: codexItemId || undefined,
  };
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object") : [];
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
  ) return null;
  return {
    ...payload,
    source: {
      ...source,
      turnId: asString(source.turnId),
    },
  } as unknown as InteractiveReport;
}

function isArtifactKind(value: string): value is ArtifactKind {
  return artifactKinds.has(value as ArtifactKind);
}
