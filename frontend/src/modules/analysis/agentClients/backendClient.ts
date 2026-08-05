import type { ArtifactKind } from "@/modules/analysis/types/artifact";
import type { Report } from "@/modules/analysis/types/report";
import type { FlowActivity, FlowNode } from "../hooks/use-flow";
import type { AgentClient, AgentEvent, AgentInput } from "./types";

export type BackendTurnEvent = {
  type: string;
  turn_id: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type BackendAnalysisSessionSummary = {
  id: string;
  title?: string | null;
  status?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  latestQuestion?: string | null;
  // The user spec splits session and turn state machines: the
  // session-level ``status`` is always ``active`` or ``archived`` and
  // the sidebar reads the latest turn's state here. The backend
  // returns both the snake_case and camelCase shapes for back-compat.
  latestTurnStatus?: string | null;
  latestTurnId?: string | null;
  latest_turn_status?: string | null;
  latest_turn_id?: string | null;
  metadata?: Record<string, unknown> | null;
};

export type BackendAnalysisSessionDetail = {
  // The new contract returns ``session`` (canonical) plus
  // ``thread`` (back-compat alias).
  session?: BackendAnalysisSessionSummary;
  thread?: BackendAnalysisSessionSummary;
  turns: Array<{
    id: string;
    question: string;
    inputText?: string;
    inputKind?: string;
    status?: string;
    createdAt?: string;
    updatedAt?: string;
    completedAt?: string;
    timeline?: BackendTimelineItem[];
  }>;
  codexItemProjections?: Array<{
    codexItemId: string;
    itemType: string;
    status: string;
    payload: Record<string, unknown>;
    createdAt: string;
    genbiTurnId?: string | null;
    sequence?: number;
  }>;
};

type BackendTimelineItem = {
  codexItemId?: string;
  codex_item_id?: string;
  itemType?: string;
  item_type?: string;
  status?: string;
  sequence?: number;
  payload?: Record<string, unknown>;
  createdAt?: string;
  created_at?: string;
  genbiTurnId?: string | null;
  genbi_turn_id?: string | null;
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
  // The client is session-agnostic: it never remembers a session id
  // across calls. Every ``send`` is scoped to the ``sessionId`` the
  // caller passed in (``null`` for the first turn of a brand-new
  // session, the Codex-issued id for any continuation). The route is
  // always one of two:
  //   * ``POST /api/analysis/sessions/turns/stream`` — first turn
  //   * ``POST /api/analysis/sessions/{sessionId}/turns/stream`` — every turn after
  private abortController: AbortController | null = null;

  constructor(private readonly apiBaseUrl: string) {}

  async *send(input: AgentInput): AsyncIterable<AgentEvent> {
    if (input.kind === "reset") {
      this.cancel();
      yield { type: "done" };
      return;
    }

    const question = getInputQuestion(input);
    if (!question) {
      yield { type: "done" };
      return;
    }

    this.abortController = new AbortController();
    let timedOut = false;
    let timeoutId: ReturnType<typeof globalThis.setTimeout> | null = null;
    const refreshTimeout = () => {
      if (timeoutId) globalThis.clearTimeout(timeoutId);
      timeoutId = globalThis.setTimeout(() => {
        timedOut = true;
        this.abortController?.abort();
      }, getBackendAnalysisRequestTimeoutMs());
    };
    refreshTimeout();
    const clearRequestTimeout = () => {
      if (timeoutId) globalThis.clearTimeout(timeoutId);
      timeoutId = null;
    };
    try {
      const sessionId = input.sessionId;
      // The sessionless flow is reserved for the very first turn of
      // a brand-new session. Any later turn carries the session id
      // through the URL path; the body never re-asserts it.
      const isSessionlessStart = sessionId == null;
      const sessionTurnUrl = isSessionlessStart
        ? `${this.apiBaseUrl}/api/analysis/sessions/turns/stream`
        : `${this.apiBaseUrl}/api/analysis/sessions/${encodeURIComponent(sessionId)}/turns/stream`;
      const firstTurnMetadata = {
        frontend_client: "analysis_task",
        ...(input.kind === "start" && input.context?.sourceReportId
          ? { source_report_id: input.context.sourceReportId }
          : {}),
      };
      const requestBody: Record<string, unknown> = isSessionlessStart
        ? {
            message: question,
            metadata: firstTurnMetadata,
          }
        : {
            message: question,
            turn_kind: input.kind,
            metadata: { frontend_client: "analysis_task" },
          };
      const response = await fetch(sessionTurnUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
        signal: this.abortController.signal,
      });
      if (!response.ok) {
        throw new Error(`Analysis API returned ${response.status}`);
      }
      if (!response.body) {
        throw new Error("Analysis API returned no stream body");
      }
      // The backend writes ``text/event-stream``: each non-empty
      // ``data:`` line carries a JSON-encoded AgentEvent. The
      // shared ``readAnalysisSse`` helper parses the stream into
      // backend events the moment they arrive, so token deltas,
      // tool calls, and the resolved turn id surface in real time
      // — not after the whole turn completes.
      let resolvedSessionId = asString(input.sessionId) || "";
      const mappingContext: BackendEventMappingContext = {};
      for await (const backendEvent of readAnalysisSse(response)) {
        refreshTimeout();
        // The first business event on the sessionless flow is
        // ``session/created`` with the Codex-issued session id;
        // we forward it as an AgentEvent so the page can navigate
        // from ``/analysis/new`` to ``/analysis/{session_id}``.
        if (backendEvent.type === "session/created") {
          const newSessionId =
            asString(backendEvent.payload.sessionId) ||
            asString(backendEvent.payload.codexThreadId) ||
            resolvedSessionId;
          if (newSessionId) {
            resolvedSessionId = newSessionId;
            yield {
              type: "session/created",
              sessionId: newSessionId,
              codexThreadId: newSessionId,
              codexTurnId:
                asString(backendEvent.payload.codexTurnId) || undefined,
            };
            continue;
          }
        }
        for (const event of mapBackendEvents([backendEvent], input.kind, mappingContext)) {
          for await (const displayEvent of smoothTokenEvent(event)) {
            yield displayEvent;
          }
        }
      }
      clearRequestTimeout();
    } catch (error) {
      if ((error as Error).name === "AbortError" && !timedOut) {
        clearRequestTimeout();
        return;
      }
      clearRequestTimeout();
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

  async cancelTurn(sessionId: string, turnId: string): Promise<void> {
    // Stop button handler: ask the backend to interrupt the live
    // Codex turn (separate from ``session/archived``). The
    // backend endpoint POSTs to
    // ``/api/analysis/sessions/{id}/turns/{turn_id}/cancel``,
    // which calls ``CodexSdkAnalysisRuntime.interrupt_turn``
    // and stamps the projection row ``cancelled`` so the UI sees
    // the terminal transition without waiting for the SSE
    // stream to close.
    if (!sessionId || !turnId) return;
    const url = `${this.apiBaseUrl}/api/analysis/sessions/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/cancel`;
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!response.ok) {
        // The cancel request itself failed; the SSE stream is
        // still being aborted by ``cancel()``, but the runtime
        // is not asked to stop. Surface the failure so the
        // caller's ``catch`` block can decide what to do.
        throw new Error(`Cancel turn returned ${response.status}`);
      }
    } catch (error) {
      // Don't propagate — the SSE abort in ``cancel()`` still
      // cleans up the local stream. We log so the operator can
      // see the failed cancel against the live Codex turn.
      if (typeof console !== "undefined") {
        console.warn("backend_cancel_turn_failed", error);
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

export async function listBackendAnalysisSessions(): Promise<BackendAnalysisSessionSummary[]> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) return [];
  const response = await fetch(`${apiBaseUrl}/api/analysis/sessions?limit=200`);
  if (!response.ok) throw new Error(`Analysis sessions API returned ${response.status}`);
  const payload = await response.json() as { sessions?: BackendAnalysisSessionSummary[] };
  return Array.isArray(payload.sessions) ? payload.sessions : [];
}

export async function getBackendAnalysisSession(sessionId: string): Promise<BackendAnalysisSessionDetail> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/sessions/${encodeURIComponent(sessionId)}`);
  if (!response.ok) throw new Error(`Analysis session API returned ${response.status}`);
  return await response.json() as BackendAnalysisSessionDetail;
}

export async function deleteBackendAnalysisSession(sessionId: string): Promise<void> {
  const apiBaseUrl = getBackendAnalysisApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
  if (!response.ok && response.status !== 404) {
    throw new Error(`Analysis session delete API returned ${response.status}`);
  }
}

export async function listBackendMcpServers(): Promise<BackendMcpServer[]> {
  const response = await fetch("/api/system/mcp/servers");
  if (!response.ok) throw new Error(`MCP servers API returned ${response.status}`);
  const payload = await response.json() as { servers?: BackendMcpServer[] };
  return Array.isArray(payload.servers) ? payload.servers : [];
}

export async function testBackendMcpServer(serverName: string): Promise<{ ok: boolean; status: string; message: string }> {
  const response = await fetch(`/api/system/mcp/servers/${encodeURIComponent(serverName)}/test`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(`MCP server test API returned ${response.status}`);
  return await response.json() as { ok: boolean; status: string; message: string };
}

export function flowNodesFromBackendSession(detail: BackendAnalysisSessionDetail): FlowNode[] {
  const projections = normalizeBackendProjections(detail);
  return [...(detail.turns ?? [])]
    .sort((left, right) => compareIsoText(left.createdAt, right.createdAt))
    .flatMap((turn) => {
      const nodes: FlowNode[] = [{ id: `user-${turn.id}`, role: "user", content: turn.inputText || turn.question || "历史问题无法恢复" }];
      const turnProjections = projections.filter((item) => item.genbiTurnId === turn.id);
      const agentNode = agentNodeFromTurnProjections(turn, turnProjections);
      if (agentNode) nodes.push(agentNode);
      return nodes;
    });
}

function normalizeBackendProjections(
  detail: BackendAnalysisSessionDetail,
): NonNullable<BackendAnalysisSessionDetail["codexItemProjections"]> {
  const topLevel = detail.codexItemProjections ?? [];
  const fromTimeline = (detail.turns ?? []).flatMap((turn) => (turn.timeline ?? []).map((item) => ({
    codexItemId: asString(item.codexItemId) || asString(item.codex_item_id),
    genbiTurnId: asString(item.genbiTurnId) || asString(item.genbi_turn_id) || turn.id,
    itemType: asString(item.itemType) || asString(item.item_type) || "unknown",
    status: asString(item.status) || "completed",
    sequence: item.sequence,
    payload: item.payload ?? {},
    createdAt: asString(item.createdAt) || asString(item.created_at) || turn.createdAt || "",
  })));
  const seenItemIds = new Set<string>();
  return [...topLevel, ...fromTimeline]
    .filter((item) => item.itemType !== "userMessage")
    .filter((item) => {
      const itemId = asString(item.codexItemId);
      if (!itemId) return true;
      if (seenItemIds.has(itemId)) return false;
      seenItemIds.add(itemId);
      return true;
    })
    .sort((left, right) => compareIsoText(left.createdAt, right.createdAt));
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
  turn: BackendAnalysisSessionDetail["turns"][number],
  projections: NonNullable<BackendAnalysisSessionDetail["codexItemProjections"]>,
): FlowNode | null {
  let content = "";
  let activeItemId: string | undefined;
  const activity: FlowActivity[] = [];
  const orderedProjections = [...projections].sort((left, right) => {
    const leftSequence = typeof left.sequence === "number" ? left.sequence : Number.MAX_SAFE_INTEGER;
    const rightSequence = typeof right.sequence === "number" ? right.sequence : Number.MAX_SAFE_INTEGER;
    return leftSequence - rightSequence
      || compareIsoText(left.createdAt, right.createdAt)
      || left.codexItemId.localeCompare(right.codexItemId);
  });
  for (const item of orderedProjections) {
    if (item.itemType === "reasoning") {
      const summary = asString(item.payload.summary);
      if (summary) {
        activity.push({
          kind: "reasoning",
          content: summary,
          itemId: `${item.codexItemId}:0`,
        });
      }
      continue;
    }
    if (item.itemType === "agentMessage") {
      const messageContent = asString(item.payload.content);
      if (messageContent) {
        if (content) activity.push({ kind: "message", content, itemId: activeItemId });
        content = messageContent;
        activeItemId = item.codexItemId;
      }
      continue;
    }
    if (["toolCall", "toolResult", "mcpToolCall", "commandExecution", "fileChange"].includes(item.itemType)) {
      const normalizedStatus = (
        asString(item.payload.mcp_status)
        || asString(item.payload.command_status)
        || asString(item.payload.file_change_status)
        || item.status
      ).toLowerCase();
      appendHistoricalToolActivity(activity, {
        kind: "tool",
        label: toolLabelFromPayload(item.payload),
        state: ["failed", "error", "cancelled", "declined"].includes(normalizedStatus)
          ? "failed"
          : normalizedStatus === "completed"
            ? "done"
            : normalizedStatus === "running"
              ? "running"
              : "queued",
        detail: toolCallDetail(item.payload),
        itemId: item.codexItemId,
      });
    }
  }
  if (!content && activity.length === 0) return null;
  return {
    id: `agent-${turn.id}`,
    role: "agent",
    content,
    mode: "replace",
    activity,
    activeItemId,
    ...(activity.length > 0 ? {
      processRunning: turn.status === "running",
      processStartedAt: turn.createdAt,
      processCompletedAt: turn.completedAt
        || (turn.status && turn.status !== "running" ? turn.updatedAt : undefined),
    } : {}),
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
  if (input.kind === "start") return input.question ?? "";
  if (input.kind === "message") return input.content;
  if (input.kind === "reply") return input.optionId;
  return "";
}

type BackendEventMappingContext = {
  currentAgentNodeId?: string;
  streamedAgentTextByNode?: Map<string, string>;
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

    if (
      event.type === "item/reasoning/summaryTextDelta"
      || method === "item/reasoning/summaryTextDelta"
    ) {
      const summaryIndex = Number(event.payload.summary_index ?? 0);
      const codexItemId = asString(event.payload.codex_item_id);
      const delta = asString(event.payload.delta);
      if (codexItemId && delta) {
        yield {
          type: "process",
          nodeId: getAgentNodeId(event),
          text: delta,
          mode: "delta",
          summaryIndex,
          itemId: `${codexItemId}:${summaryIndex}`,
          ...context,
        };
      }
      continue;
    }

    if (
      (event.type === "item/completed" || method === "item/completed")
      && codexItemType === "reasoning"
      && asString(event.payload.summary)
    ) {
      const codexItemId = asString(event.payload.codex_item_id);
      yield {
        type: "process",
        nodeId: getAgentNodeId(event),
        text: asString(event.payload.summary),
        mode: "replace",
        summaryIndex: 0,
        itemId: `${codexItemId}:0`,
        ...context,
      };
      continue;
    }

    const isToolItemEvent = (
      (event.type === "item/started" || event.type === "item/completed" || method === "item/started" || method === "item/completed")
      && ["toolCall", "toolResult", "mcpToolCall", "commandExecution", "fileChange"].includes(codexItemType)
    );
    if (isToolItemEvent) {
      const toolNodeId = mappingContext.currentAgentNodeId || getAgentNodeId(event);
      const toolName = toolNameFromPayload(event.payload, codexItemType);
      const toolServer = asString(event.payload.mcp_server);
      const itemId = asString(event.payload.item_id) || asString(event.payload.codex_item_id) || undefined;
      const completedStatus = (
        asString(event.payload.mcp_status)
        || asString(event.payload.command_status)
        || asString(event.payload.file_change_status)
      ).toLowerCase();
      yield {
        type: "step",
        label: `${toolServer ? `${toolServer} / ` : ""}${toolName}`,
        state: (event.type === "item/started" || method === "item/started")
          ? "running"
          : ["failed", "error", "cancelled", "declined"].includes(completedStatus)
            ? "failed"
            : "done",
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
      const streamedContent = mappingContext.streamedAgentTextByNode?.get(agentNodeId);
      mappingContext.streamedAgentTextByNode?.delete(agentNodeId);
      if (streamedContent === content) {
        continue;
      }
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
      const delta = asString(event.payload.delta);
      const streamedTextByNode = mappingContext.streamedAgentTextByNode ?? new Map<string, string>();
      mappingContext.streamedAgentTextByNode = streamedTextByNode;
      streamedTextByNode.set(agentNodeId, (streamedTextByNode.get(agentNodeId) ?? "") + delta);
      yield {
        type: "tokens",
        nodeId: agentNodeId,
        text: delta,
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

    if (
      event.type === "genbi/report/created"
      || event.type === "genbi/report/updated"
    ) {
      const report = asReport(event.payload);
      if (report) {
        yield {
          type: "report",
          report,
          ...context,
          threadId: report.sourceSessionId || context.threadId,
          turnId: report.turnId || context.turnId,
        };
      }
      continue;
    }

    if (event.type === "genbi/report/failed") {
      yield {
        type: "error",
        message: asString(event.payload.error) || "Report save failed",
        ...context,
      };
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

function toolCallDetail(payload: Record<string, unknown>): string | undefined {
  const sections: string[] = [];
  const args = asRecord(payload.mcp_arguments) || asRecord(payload.arguments);
  const result = asRecord(payload.mcp_result) || asRecord(payload.result);
  const command = asString(payload.command);
  const output = asString(payload.aggregated_output);
  if (command) sections.push(`Command:\n${command}`);
  if (args && Object.keys(args).length > 0) sections.push(`Arguments:\n${formatToolDetail(args)}`);
  if (result) sections.push(`Result:\n${formatToolResult(result)}`);
  if (output) sections.push(`Output:\n${output}`);
  if (Array.isArray(payload.changes)) {
    sections.push(`Changes:\n${truncateToolDetail(JSON.stringify(payload.changes, null, 2))}`);
  }
  if (payload.exit_code != null) sections.push(`Exit code: ${String(payload.exit_code)}`);
  const error = asString(payload.mcp_error) || asString(payload.error);
  if (error) sections.push(`Error:\n${error}`);
  return sections.length > 0 ? truncateToolDetail(sections.join("\n\n")) : undefined;
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
  return text.length > 20_000 ? `${text.slice(0, 20_000)}\n...[truncated]` : text;
}

function toolNameFromPayload(payload: Record<string, unknown>, itemType: string): string {
  const named = asString(payload.mcp_tool) || asString(payload.tool) || asString(payload.name);
  if (named) return named;
  if (itemType === "commandExecution") {
    const command = asString(payload.command).split(/\r?\n/, 1)[0]?.trim();
    return command ? `Command: ${command.slice(0, 100)}` : "Command";
  }
  if (itemType === "fileChange") return "File changes";
  return "tool";
}

function getAgentNodeId(event: BackendTurnEvent): string {
  const turnId = asString(event.payload.turn_id) || event.turn_id;
  return `agent-${turnId}`;
}

function getSystemContext(event: BackendTurnEvent) {
  const turnId = asString(event.payload.turn_id) || event.turn_id;
  // The new contract uses ``session_id`` everywhere; the legacy
  // ``thread_id`` / ``conversation_id`` aliases are kept so older
  // fixtures still parse.
  const threadId =
    asString(event.payload.session_id) ||
    asString(event.payload.thread_id) ||
    asString(event.payload.conversation_id);
  const codexThreadId =
    asString(event.payload.codex_session_id) ||
    asString(event.payload.codex_thread_id);
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

function asReport(payload: Record<string, unknown>): Report | null {
  const layout = asRecord(payload.layout);
  if (
    typeof payload.id !== "string"
    || typeof payload.title !== "string"
    || typeof payload.subtitle !== "string"
    || typeof payload.ownerId !== "string"
    || !layout
    || !asRecord(layout.root)
    || !Array.isArray(layout.content)
    || !asRecord(layout.zones)
    || !asRecord(payload.filters)
    || !asRecord(payload.queries)
    || !asRecord(payload.charts)
    || !asRecord(payload.tables)
  ) return null;
  return payload as unknown as Report;
}

function isArtifactKind(value: string): value is ArtifactKind {
  return artifactKinds.has(value as ArtifactKind);
}
