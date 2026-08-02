import type { ArtifactKind } from "@/modules/analysis/types/artifact";
import type { InteractiveReport } from "@/modules/analysis/types/interactive-report";
import type { AgentClient, AgentEvent, AgentInput } from "./types";

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
      yield { type: "conversation-init", executionAttemptId: "analysis-reset", runId: "analysis-reset" };
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
            ...(input.interactiveReport ? { interactive_report_context: input.interactiveReport } : {}),
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

export function* mapBackendEvents(events: BackendRunEvent[], inputKind: AgentInput["kind"]): Iterable<AgentEvent> {
  let currentAgentNodeId: string | null = null;
  const compatibilitySources = new Set(events.map((event) => asString(event.payload.compatibility_source_event)).filter(Boolean));
  for (const event of events) {
    const context = getSystemContext(event);
    const method = asString(event.payload.codex_method) || event.type;
    const codexItemType = asString(event.payload.codex_item_type);
    if (event.type === "turn/started" || method === "turn/started") {
      const executionAttemptId = context.executionAttemptId || event.run_id;
      const conversationId = asString(event.payload.conversation_id);
      const question = asString(event.payload.question);
      if (inputKind === "start") {
        yield { ...context, type: "conversation-init", executionAttemptId, runId: context.runId, conversationId: conversationId || undefined };
      } else {
        yield { ...context, type: "run-init", executionAttemptId, runId: context.runId, conversationId: conversationId || undefined };
      }
      if (question) {
        yield {
          type: "user",
          nodeId: `user-${executionAttemptId}`,
          content: question,
          itemId: asString(event.payload.user_item_id) || asString(event.payload.item_id) || undefined,
          ...context,
        };
      }
      continue;
    }

    if (event.type === "analysis.problem.classified") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield {
        type: "debug",
        title: "本地问题分类",
        content: JSON.stringify({
          problem_type: event.payload.problem_type,
          label: event.payload.label,
          confidence: event.payload.confidence,
        }, null, 2),
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "analysis.retrieval.plan") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield {
        type: "debug",
        title: "候选上下文计划（未执行工具）",
        content: JSON.stringify(asRecordArray(event.payload.items), null, 2),
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "agent.prompt.created") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield {
        type: "debug",
        title: "发送给模型的 prompt",
        content: asString(event.payload.prompt),
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "agent.runner.started" || event.type === "agent.runner.completed") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield {
        type: "step",
        label: `模型调用：${asString(event.payload.runtime) || "agent runner"}`,
        state: event.type === "agent.runner.started" ? "running" : "done",
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "agent.runner.raw") {
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield {
        type: "debug",
        title: `模型运行事件：${asString(event.payload.phase) || "raw"}`,
        content: JSON.stringify(event.payload, null, 2),
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    const isToolItemEvent = (
      (event.type === "item/started" || event.type === "item/completed" || method === "item/started" || method === "item/completed")
      && ["toolCall", "toolResult"].includes(codexItemType)
    );
    if (isToolItemEvent || event.type === "tool.call.started" || event.type === "tool.call.completed" || event.type === "tool.call.failed") {
      if (!event.type.startsWith("item/") && compatibilitySources.has(event.type)) continue;
      currentAgentNodeId ||= `agent-${event.run_id}`;
      const toolName = asString(event.payload.tool) || asString(event.payload.name) || "tool";
      const sourceEventType = asString(event.payload.compatibility_source_event) || event.type;
      yield {
        type: "step",
        label: `工具调用：${toolName}`,
        state: sourceEventType === "tool.call.started" || event.type === "item/started" ? "running" : "done",
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      yield {
        type: "debug",
        title: `工具事件：${sourceEventType}`,
        content: JSON.stringify(event.payload, null, 2),
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if ((event.type === "item/completed" && method === "item/completed" && codexItemType === "agentMessage") || event.type === "agent.message.created") {
      if (event.type === "agent.message.created" && compatibilitySources.has(event.type)) continue;
      currentAgentNodeId ||= `agent-${event.run_id}`;
      const content = asString(event.payload.content);
      if (content) {
        yield {
          type: "debug",
          title: "模型最终返回",
          content,
          nodeId: currentAgentNodeId,
          itemId: asString(event.payload.item_id) || undefined,
          ...context,
        };
      }
      yield {
        type: "agent",
        nodeId: currentAgentNodeId,
        content,
        mode: "replace",
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "item/agentMessage/delta" || method === "item/agentMessage/delta" || event.type === "agent.message.delta") {
      if (event.type === "agent.message.delta" && compatibilitySources.has(event.type)) continue;
      currentAgentNodeId ||= `agent-${event.run_id}`;
      yield {
        type: "debug",
        title: "模型流式片段",
        content: asString(event.payload.delta),
        nodeId: currentAgentNodeId,
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      yield {
        type: "tokens",
        nodeId: currentAgentNodeId,
        text: asString(event.payload.delta),
        itemId: asString(event.payload.item_id) || undefined,
        ...context,
      };
      continue;
    }

    if ((event.type === "item/completed" && codexItemType === "agentQuestion") || event.type === "agent.question.requested") {
      if (event.type === "agent.question.requested" && compatibilitySources.has(event.type)) continue;
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

    if ((event.type === "genbi/artifact/updated" && asString(event.payload.artifactType) === "interactive_report") || event.type === "interactive_report.draft") {
      if (event.type === "interactive_report.draft" && compatibilitySources.has(event.type)) continue;
      const report = asInteractiveReport(event.payload);
      if (report) {
        yield {
          type: "report-draft",
          report,
          ...context,
          threadId: report.source.threadId,
          turnId: report.source.turnId,
          runId: report.source.executionAttemptId,
        };
      }
      continue;
    }

    if (event.type === "genbi/artifact/created" || event.type === "genbi/artifact/updated" || event.type === "artifact.created" || event.type === "artifact.updated") {
      if ((event.type === "artifact.created" || event.type === "artifact.updated") && compatibilitySources.has(event.type)) continue;
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

    if (event.type === "turn/completed" || method === "turn/completed") {
      yield { type: "done", ...context };
      continue;
    }
  }
}

function getSystemContext(event: BackendRunEvent) {
  const runId = asString(event.payload.run_id) || event.run_id;
  const threadId = asString(event.payload.thread_id) || asString(event.payload.conversation_id);
  const turnId = asString(event.payload.turn_id) || runId;
  const codexThreadId = asString(event.payload.codex_thread_id);
  const codexTurnId = asString(event.payload.codex_turn_id);
  const codexItemId = asString(event.payload.codex_item_id);
  return {
    executionAttemptId: runId,
    runId,
    threadId: threadId || undefined,
    turnId: turnId || undefined,
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
    || (typeof source.executionAttemptId !== "string" && typeof source.runId !== "string")
  ) return null;
  const executionAttemptId = asString(source.executionAttemptId) || asString(source.runId);
  return {
    ...payload,
    source: {
      ...source,
      executionAttemptId,
      runId: asString(source.runId) || executionAttemptId,
    },
  } as unknown as InteractiveReport;
}

function isArtifactKind(value: string): value is ArtifactKind {
  return artifactKinds.has(value as ArtifactKind);
}
