import type { ArtifactKind } from "@/modules/analysis/types/artifact";
import type { InteractiveReport } from "@/modules/analysis/types/interactive-report";
import type { FlowActivity, FlowNode } from "../hooks/use-flow";
import type { AgentClient, AgentEvent, AgentInput } from "./types";

export type BackendTurnEvent = {
  type: string;
  turn_id: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type BackendAnalysisThreadSummary = {
  id: string;
  title?: string | null;
  status?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  latestQuestion?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type BackendAnalysisThreadDetail = {
  thread: BackendAnalysisThreadSummary;
  turns: Array<{
    id: string;
    question: string;
    inputKind?: string;
    status?: string;
    createdAt?: string;
    updatedAt?: string;
  }>;
  codexItemProjections?: Array<{
    codexItemId: string;
    itemType: string;
    status: string;
    payload: Record<string, unknown>;
    createdAt?: string;
    genbiTurnId?: string | null;
  }>;
};

export type BackendMcpTool = {
  name: string;
  description: string;
  permission: string;
  trusted: boolean;
};

export type BackendMcpServer = {
  name: string;
  command: string;
  args: string[];
  enabled: boolean;
  status: string;
  permission: string;
  trusted: boolean;
  approval: string;
  tools: BackendMcpTool[];
  envKeys: string[];
  message: string;
};

const artifactKinds = new Set<ArtifactKind>(["html", "sql", "python", "csv", "markdown", "json"]);
const DEFAULT_ANALYSIS_REQUEST_TIMEOUT_MS = 300_000;
const DEFAULT_TOKEN_FLUSH_INTERVAL_MS = 14;
const DEFAULT_TOKEN_FLUSH_CHARS = 2;

export class BackendAnalysisAgentClient implements AgentClient {
  // The client intentionally holds no business state. Every ``send`` call
  // owns its own fetch, timeout, and reader, and cancellation goes
  // through the ``AbortSignal`` the caller passes in. See ``use-flow.ts``
  // for the per-task controller registry that replaced the previous
  // module-level singleton.
  constructor(private readonly apiBaseUrl: string) {}

  async *send(input: AgentInput): AsyncIterable<AgentEvent> {
    const question = getInputQuestion(input);
    if (input.signal.aborted) {
      return;
    }
    if (!question) {
      // Empty input is a programming / UI bug, not a default the
      // client should paper over. Surface the failure explicitly so
      // the workspace can show a "请输入问题" message instead of a
      // channel-sales report.
      yield { type: "error", message: "问题不能为空，请输入业务问题后再开始分析。", threadId: input.threadId };
      yield { type: "done", threadId: input.threadId };
      return;
    }

    const controller = new AbortController();
    // Re-export the caller's signal so a timeout on our side cancels
    // the request too.
    const forwardAbort = () => {
      if (!controller.signal.aborted) controller.abort(input.signal.reason);
    };
    if (input.signal.aborted) {
      forwardAbort();
    } else {
      input.signal.addEventListener("abort", forwardAbort, { once: true });
    }

    let timeoutId: ReturnType<typeof globalThis.setTimeout> | null = null;
    const startTimeout = () => {
      if (timeoutId) globalThis.clearTimeout(timeoutId);
      timeoutId = globalThis.setTimeout(() => {
        if (!controller.signal.aborted) controller.abort(new Error("analysis_request_timeout"));
      }, getBackendAnalysisRequestTimeoutMs());
    };
    const clearTimeout2 = () => {
      if (timeoutId) {
        globalThis.clearTimeout(timeoutId);
        timeoutId = null;
      }
    };
    startTimeout();

    let response: Response | null = null;
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
    try {
      const threadTurnUrl = `${this.apiBaseUrl}/api/analysis/threads/${encodeURIComponent(input.threadId)}/turns/stream`;
      response = await fetch(threadTurnUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          turn_kind: input.kind,
          metadata: {
            frontend_client: "analysis_task",
            frontend_task_id: input.taskId,
          },
        }),
        credentials: "include",
        signal: controller.signal,
      });
      if (!response.ok) {
        if (response.status === 401) {
          yield {
            type: "error",
            message: "登录会话已过期，请重新登录后再试。",
            threadId: input.threadId,
          };
          yield { type: "done", threadId: input.threadId };
          return;
        }
        throw new Error(`Analysis SSE API returned ${response.status}`);
      }
      if (controller.signal.aborted) return;
      const decoder = new TextDecoder();
      reader = response.body?.getReader() ?? null;
      if (!reader) {
        // No streaming body — fall back to a synchronous parse.
        const text = await response.text();
        for await (const displayEvent of mapAndSmooth(text, input, () => startTimeout())) {
          yield displayEvent;
        }
        clearTimeout2();
        return;
      }
      let buffer = "";
      while (true) {
        if (controller.signal.aborted) break;
        const { done, value } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        const parts = buffer.split(/\r?\n\r?\n/);
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          for await (const event of mapAndSmooth(part, input, () => startTimeout())) {
            yield event;
          }
        }
        if (done) break;
      }
      if (buffer.trim()) {
        for await (const event of mapAndSmooth(buffer, input, () => startTimeout())) {
          yield event;
        }
      }
    } catch (error) {
      const reasonMessage = (controller.signal.reason as { message?: string } | undefined)?.message;
      // Distinguish timeout (caller's signal untouched) from caller-cancel
      // (caller's signal already aborted).
      const callerCancelled = input.signal.aborted;
      if (controller.signal.aborted && callerCancelled) {
        return;
      }
      if (reasonMessage === "analysis_request_timeout") {
        yield {
          type: "error",
          message: "Analysis backend request timed out. Please retry.",
          threadId: input.threadId,
        };
        yield { type: "done", threadId: input.threadId };
        return;
      }
      yield {
        type: "error",
        message: error instanceof Error ? error.message : "分析任务后端调用失败",
        threadId: input.threadId,
      };
      yield { type: "done", threadId: input.threadId };
    } finally {
      clearTimeout2();
      input.signal.removeEventListener("abort", forwardAbort);
      try {
        if (reader) await reader.cancel();
      } catch {
        // Closing the reader is best-effort; ignore.
      }
    }
  }
}

async function* mapAndSmooth(
  block: string,
  input: AgentInput,
  refreshTimeout: () => void,
): AsyncIterable<AgentEvent> {
  if (!block.trim()) return;
  const events = parseAnalysisSse(block);
  for (const backendEvent of events) {
    refreshTimeout();
    for (const event of mapBackendEvents([backendEvent], input.kind)) {
      for await (const displayEvent of smoothTokenEvent(event)) {
        yield displayEvent;
      }
    }
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

/**
 * Returns a fresh client per call. The shared singleton previously caused
 * cross-task aborts and thread-id overwrites; per the multi-task contract
 * each ``useFlow`` now owns its own controllers and creates the client it
 * needs. Cheap to construct, no hidden state.
 */
export function createBackendAnalysisAgentClient(): BackendAnalysisAgentClient {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!shouldUseBackendAnalysisClient() || !apiBaseUrl) {
    throw new Error("Analysis backend is not configured.");
  }
  return new BackendAnalysisAgentClient(apiBaseUrl);
}

export async function listBackendAnalysisThreads(): Promise<BackendAnalysisThreadSummary[]> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) return [];
  const response = await fetch(`${apiBaseUrl}/api/analysis/threads`, { credentials: "include" });
  if (response.status === 401) {
    return [];
  }
  if (!response.ok) throw new Error(`Analysis threads API returned ${response.status}`);
  const payload = await response.json() as { threads?: BackendAnalysisThreadSummary[] };
  return Array.isArray(payload.threads) ? payload.threads : [];
}

export async function createBackendAnalysisThread(title: string): Promise<BackendAnalysisThreadSummary> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
    credentials: "include",
  });
  if (!response.ok) throw new Error(`Analysis thread create API returned ${response.status}`);
  const payload = await response.json() as { thread: BackendAnalysisThreadSummary };
  return payload.thread;
}

/**
 * Create a new analysis task via the ``/api/analysis/tasks`` endpoint.
 *
 * The endpoint returns the server-issued ``thread.id``; the frontend
 * never fabricates a draft_* placeholder. While the request is in
 * flight the caller should display a "正在创建" placeholder, and only
 * treat the returned id as the canonical task id once the promise
 * resolves.
 */
export async function createBackendAnalysisTask(title: string): Promise<BackendAnalysisThreadSummary> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
    credentials: "include",
  });
  if (!response.ok) throw new Error(`Analysis task create API returned ${response.status}`);
  const payload = await response.json() as { task: BackendAnalysisThreadSummary };
  return payload.task;
}

export async function getBackendAnalysisThread(threadId: string): Promise<BackendAnalysisThreadDetail> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/threads/${encodeURIComponent(threadId)}`, {
    credentials: "include",
  });
  if (!response.ok) throw new Error(`Analysis thread API returned ${response.status}`);
  return await response.json() as BackendAnalysisThreadDetail;
}

export async function deleteBackendAnalysisThread(threadId: string): Promise<void> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!response.ok && response.status !== 404) {
    throw new Error(`Analysis thread delete API returned ${response.status}`);
  }
}

export async function listBackendMcpServers(): Promise<BackendMcpServer[]> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) return [];
  const response = await fetch(`${apiBaseUrl}/api/system/mcp/servers`, { credentials: "include" });
  if (!response.ok) throw new Error(`MCP servers API returned ${response.status}`);
  const payload = await response.json() as { servers?: BackendMcpServer[] };
  return Array.isArray(payload.servers) ? payload.servers : [];
}

export async function testBackendMcpServer(serverName: string): Promise<{ ok: boolean; status: string; message: string }> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/system/mcp/servers/${encodeURIComponent(serverName)}/test`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) throw new Error(`MCP server test API returned ${response.status}`);
  return await response.json() as { ok: boolean; status: string; message: string };
}

export function flowNodesFromBackendThread(detail: BackendAnalysisThreadDetail): FlowNode[] {
  const projections = [...(detail.codexItemProjections ?? [])].sort((left, right) => compareIsoText(left.createdAt, right.createdAt));
  return [...(detail.turns ?? [])]
    .sort((left, right) => compareIsoText(left.createdAt, right.createdAt))
    .flatMap((turn) => {
      const nodes: FlowNode[] = [{ id: `user-${turn.id}`, role: "user", content: turn.question || "历史问题无法恢复" }];
      const turnProjections = projections.filter((item) => item.genbiTurnId === turn.id);
      const agentNode = agentNodeFromTurnProjections(turn.id, turnProjections);
      if (agentNode) nodes.push(agentNode);
      return nodes;
    });
}

export function getBackendAnalysisRequestTimeoutMs(): number {
  const raw = process.env.NEXT_PUBLIC_ANALYSIS_AGENT_TIMEOUT_MS;
  const parsed = raw ? Number(raw) : DEFAULT_ANALYSIS_REQUEST_TIMEOUT_MS;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_ANALYSIS_REQUEST_TIMEOUT_MS;
}

export function getTokenFlushIntervalMs(): number {
  const raw = process.env.NEXT_PUBLIC_ANALYSIS_TOKEN_FLUSH_INTERVAL_MS;
  const parsed = raw ? Number(raw) : DEFAULT_TOKEN_FLUSH_INTERVAL_MS;
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : DEFAULT_TOKEN_FLUSH_INTERVAL_MS;
}

export function getTokenFlushChars(): number {
  const raw = process.env.NEXT_PUBLIC_ANALYSIS_TOKEN_FLUSH_CHARS;
  const parsed = raw ? Number(raw) : DEFAULT_TOKEN_FLUSH_CHARS;
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : DEFAULT_TOKEN_FLUSH_CHARS;
}

export async function* smoothTokenEvent(event: AgentEvent): AsyncIterable<AgentEvent> {
  if (event.type !== "tokens" || event.text.length <= getTokenFlushChars()) {
    yield event;
    return;
  }
  const chunks = splitTextForStreaming(event.text, getTokenFlushChars());
  for (let index = 0; index < chunks.length; index += 1) {
    if (index > 0) await sleep(getTokenFlushIntervalMs());
    yield { ...event, text: chunks[index] };
  }
}

function splitTextForStreaming(text: string, charsPerChunk: number): string[] {
  const chars = Array.from(text);
  const chunks: string[] = [];
  for (let index = 0; index < chars.length; index += charsPerChunk) {
    chunks.push(chars.slice(index, index + charsPerChunk).join(""));
  }
  return chunks;
}

function sleep(ms: number): Promise<void> {
  return ms > 0 ? new Promise((resolve) => globalThis.setTimeout(resolve, ms)) : Promise.resolve();
}

function compareIsoText(left?: string, right?: string): number {
  return (left ?? "").localeCompare(right ?? "");
}

function agentNodeFromTurnProjections(
  turnId: string,
  projections: NonNullable<BackendAnalysisThreadDetail["codexItemProjections"]>,
): FlowNode | null {
  let content = "";
  let activeItemId: string | undefined;
  const activity: FlowActivity[] = [];
  for (const item of projections) {
    if (item.itemType === "agentMessage") {
      const messageContent = asString(item.payload.content);
      if (messageContent) {
        if (content) activity.push({ kind: "message", content, itemId: activeItemId });
        content = messageContent;
        activeItemId = item.codexItemId;
      }
      continue;
    }
    if (["toolCall", "toolResult", "mcpToolCall"].includes(item.itemType)) {
      appendHistoricalToolActivity(activity, {
        kind: "tool",
        label: toolLabelFromPayload(item.payload),
        state: item.status === "completed" ? "done" : item.status === "running" ? "running" : "queued",
        detail: toolCallDetail(item.payload),
        itemId: item.codexItemId,
      });
    }
  }
  if (!content && activity.length === 0) return null;
  return {
    id: `agent-${turnId}`,
    role: "agent",
    content,
    mode: "replace",
    activity,
    activeItemId,
  };
}

function toolLabelFromPayload(payload: Record<string, unknown>): string {
  const toolName = asString(payload.mcp_tool) || asString(payload.tool) || asString(payload.name) || "tool";
  const toolServer = asString(payload.mcp_server);
  return `${toolServer ? `${toolServer} / ` : ""}${toolName}`;
}

function appendHistoricalToolActivity(activity: FlowActivity[], toolActivity: Extract<FlowActivity, { kind: "tool" }>): void {
  const previous = activity.at(-1);
  if (previous?.kind === "tool" && previous.label === toolActivity.label && previous.state === toolActivity.state) {
    activity[activity.length - 1] = {
      ...previous,
      count: (previous.count ?? 1) + 1,
      details: [
        ...(previous.details ?? (previous.detail ? [previous.detail] : [])),
        ...(toolActivity.detail ? [toolActivity.detail] : []),
      ],
    };
    return;
  }
  activity.push(toolActivity);
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
  if (input.kind === "start") return input.question || "";
  if (input.kind === "message") return input.content;
  if (input.kind === "reply") return input.optionId;
  return "";
}

type BackendEventMappingContext = {
  currentAgentNodeId?: string;
};

export function* mapBackendEvents(
  events: BackendTurnEvent[],
  inputKind: AgentInput["kind"],
  mappingContext: BackendEventMappingContext = {},
): Iterable<AgentEvent> {
  for (const event of events) {
    const context = getSystemContext(event);
    const method = asString(event.payload.codex_method) || event.type;
    const codexItemType = asString(event.payload.codex_item_type);
    if (event.type === "turn/started" || method === "turn/started") {
      const question = asString(event.payload.question);
      if (question) {
        yield {
          type: "user",
          nodeId: `user-${context.turnId || event.turn_id}`,
          content: question,
          itemId: asString(event.payload.user_item_id) || asString(event.payload.item_id) || undefined,
          ...context,
        };
      }
      continue;
    }

    const isToolItemEvent = (
      (event.type === "item/started" || event.type === "item/completed" || method === "item/started" || method === "item/completed")
      && ["toolCall", "toolResult", "mcpToolCall"].includes(codexItemType)
    );
    if (isToolItemEvent) {
      const toolNodeId = mappingContext.currentAgentNodeId || getAgentNodeId(event);
      const toolName = asString(event.payload.mcp_tool) || asString(event.payload.tool) || asString(event.payload.name) || "tool";
      const toolServer = asString(event.payload.mcp_server);
      const itemId = asString(event.payload.item_id) || asString(event.payload.codex_item_id) || undefined;
      yield {
        type: "step",
        label: `${toolServer ? `${toolServer} / ` : ""}${toolName}`,
        state: event.type === "item/started" ? "running" : "done",
        nodeId: toolNodeId,
        detail: toolCallDetail(event.payload),
        itemId,
        ...context,
      };
      continue;
    }

    if (
      (event.type === "item/started" || event.type === "item/completed" || method === "item/started" || method === "item/completed")
      && codexItemType === "reasoning"
    ) {
      const agentNodeId = getAgentNodeId(event);
      mappingContext.currentAgentNodeId = agentNodeId;
      yield {
        type: "thinking",
        nodeId: agentNodeId,
        itemId: asString(event.payload.item_id) || asString(event.payload.codex_item_id) || undefined,
        ...context,
      };
      continue;
    }

    if (event.type === "item/completed" && method === "item/completed" && codexItemType === "agentMessage") {
      const agentNodeId = getAgentNodeId(event);
      mappingContext.currentAgentNodeId = agentNodeId;
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
      const agentNodeId = getAgentNodeId(event);
      mappingContext.currentAgentNodeId = agentNodeId;
      yield {
        type: "tokens",
        nodeId: agentNodeId,
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

    if ((event.type === "genbi/artifact/created" || event.type === "genbi/artifact/updated") && asString(event.payload.artifactType) === "interactive_report") {
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

    if (event.type === "genbi/artifact/failed") {
      // The runtime tried to persist the artifact but failed at
      // validation / save / version conflict. Surface the failure
      // explicitly: the report must NOT show on the right side as
      // if it had been saved.
      const error_code = asString(event.payload.error) || "report_artifact_save_failed";
      const detail = asString(event.payload.detail) || error_code;
      const issues = event.payload.errors;
      const issueText = Array.isArray(issues) && issues.length > 0
        ? ` (${issues.map((item) => (asString((item as { path?: unknown }).path))).join(", ")})`
        : "";
      yield {
        type: "error",
        message: `ReportArtifact 保存失败：${detail}${issueText}`,
        ...context,
      };
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

function toolCallDetail(payload: Record<string, unknown>): string | undefined {
  const args = asRecord(payload.mcp_arguments) || asRecord(payload.arguments);
  const sql = args ? asString(args.sql) : "";
  if (sql) return sql;
  const error = asString(payload.mcp_error);
  if (error) return error;
  if (args && Object.keys(args).length > 0) return formatToolDetail(args);
  const result = asRecord(payload.mcp_result) || asRecord(payload.result);
  if (result) return formatToolResult(result);
  return undefined;
}

function formatToolDetail(value: Record<string, unknown>): string {
  return truncateToolDetail(JSON.stringify(value, null, 2));
}

function formatToolResult(value: Record<string, unknown>): string {
  const contentItems = asRecordArray(value.content)
    .map((item) => asString(item.text))
    .filter(Boolean);
  if (contentItems.length > 0) return truncateToolDetail(contentItems.join("\n\n"));
  return truncateToolDetail(JSON.stringify(value, null, 2));
}

function truncateToolDetail(value: string): string {
  const text = value.trim();
  return text.length > 2000 ? `${text.slice(0, 2000)}\n...` : text;
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
    datasets: asRecord(payload.datasets) || undefined,
  } as unknown as InteractiveReport;
}

function isArtifactKind(value: string): value is ArtifactKind {
  return artifactKinds.has(value as ArtifactKind);
}

