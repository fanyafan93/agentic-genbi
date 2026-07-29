import type {
  Exploration,
  ExplorationMessage,
  ExplorationRunEvent,
  Knowledge,
  Resource,
  ResourceDetail,
  ResourceExcerpt,
  ResourceIndexStatus,
  ResourceProfileItem,
  ResourceSignalGroup,
  RunTraceSummary,
  RuntimeStatus,
} from "../types";

type ExplorationRunResponse = {
  events: ExplorationRunEvent[];
};

type ExplorationConversationsResponse = {
  conversations: RunTraceResponse[];
};

type ExplorationConversationDetailResponse = {
  conversation_id: string;
  latest_run_id: string;
  run: RunTraceResponse | null;
  events: ExplorationRunEvent[];
};

type ResourceSearchResponse = {
  results: Array<{
    resource_id: string;
    name: string;
    type: string;
    relative_path: string;
    highlights?: string[];
  }>;
};

type KnowledgeResponse = {
  records: Array<{
    id: string;
    title: string;
    question?: string;
    scope: string;
    verification: string;
    evidence_refs?: string[];
    run_id?: string | null;
    created_at: string;
    conclusion: string;
  }>;
};

type KnowledgeSaveResponse = {
  id: string;
  title: string;
  question?: string;
  scope: string;
  verification: string;
  evidence_refs?: string[];
  run_id?: string | null;
  created_at: string;
  conclusion: string;
};

type ResourceStatusResponse = {
  indexed: boolean;
  root: string | null;
  resource_count: number;
  type_counts: Record<string, number>;
  index_modified_at: string | null;
  summary_modified_at: string | null;
};

type ResourceExcerptResponse = {
  resource_id: string;
  relative_path: string;
  section: "head" | "tail" | "match";
  start_line: number;
  end_line: number;
  truncated: boolean;
  encoding: string | null;
  text: string;
};

type ResourceDetailResponse = {
  resource_id: string;
  status: string;
  truncated_summary: boolean;
  size_bytes: number;
  modified_at: string;
  signals: Record<string, unknown>;
  warnings: string[];
};

type RuntimeStatusResponse = {
  env_file: string | null;
  env_loaded: boolean;
  ready: boolean;
  checks: RuntimeStatus["checks"];
};

type RunTraceResponse = {
  run_id: string;
  title: string | null;
  status: string;
  question: string;
  conversation_id?: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  event_count: number;
  tool_call_count: number;
  failed_tool_call_count: number;
  agent_message_count: number;
  token_usage: {
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
  };
  cost: {
    input_usd?: number | null;
    output_usd?: number | null;
    total_usd?: number | null;
  };
  error: string | null;
  metadata?: Record<string, unknown>;
};

type CreateExplorationRunOptions = {
  conversationId?: string | null;
  displayQuestion?: string;
  userId?: string | null;
  metadata?: Record<string, unknown>;
};

export async function createExplorationRun(
  question: string,
  onUpdate?: (exploration: Exploration) => void,
  options: CreateExplorationRunOptions = {},
): Promise<Exploration> {
  const apiBaseUrl = getApiBaseUrl();
  const displayQuestion = options.displayQuestion || question;
  if (!apiBaseUrl) {
    const unavailable = mapRunEventsToExploration(displayQuestion, buildBackendUnavailableEvents(displayQuestion, "未配置真实后端地址。"));
    onUpdate?.(unavailable);
    return unavailable;
  }

  try {
    return await streamExplorationRun(question, onUpdate, options);
  } catch {
    try {
      const response = await fetch(`${apiBaseUrl}/api/explorations/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          conversation_id: options.conversationId,
          user_id: options.userId,
          metadata: options.metadata ?? {},
        }),
      });
      if (!response.ok) throw new Error(`Exploration API returned ${response.status}`);
      const payload = (await response.json()) as ExplorationRunResponse;
      const exploration = mapRunEventsToExploration(displayQuestion, payload.events);
      onUpdate?.(exploration);
      return exploration;
    } catch {
      const unavailable = mapRunEventsToExploration(displayQuestion, buildBackendUnavailableEvents(displayQuestion, "真实后端请求失败。"));
      onUpdate?.(unavailable);
      return unavailable;
    }
  }
}

export async function listExplorationRuns(userId?: string | null): Promise<Exploration[]> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return [];
  try {
    const url = new URL(`${apiBaseUrl}/api/explorations/conversations`);
    url.searchParams.set("limit", "30");
    if (userId) url.searchParams.set("user_id", userId);
    const response = await fetch(url.toString());
    if (!response.ok) throw new Error(`Exploration conversation list API returned ${response.status}`);
    const payload = (await response.json()) as ExplorationConversationsResponse;
    return payload.conversations.filter((run) => !isContinuationRunTrace(run)).map(mapRunTraceToExplorationSummary);
  } catch {
    return [];
  }
}

export async function readExplorationRun(runId: string): Promise<Exploration | null> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl || !runId.trim()) return null;
  try {
    const response = await fetch(`${apiBaseUrl}/api/explorations/conversations/${encodeURIComponent(runId)}`);
    if (!response.ok) throw new Error(`Exploration conversation detail API returned ${response.status}`);
    const payload = (await response.json()) as ExplorationConversationDetailResponse;
    if (payload.events.length > 0) {
      const question = stringValue(payload.events.find((event) => event.type === "run.created")?.payload.question) || payload.run?.question || "";
      const exploration = mapRunEventsToExploration(question, payload.events);
      return payload.run
        ? {
            ...exploration,
            updatedAt: formatTraceUpdatedAt(payload.run.completed_at || payload.run.started_at),
          }
        : exploration;
    }
    return payload.run ? mapRunTraceToExplorationSummary(payload.run) : null;
  } catch {
    return null;
  }
}

export async function deleteExplorationRun(runId: string): Promise<boolean> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl || !runId.trim() || (!runId.startsWith("conv_") && !runId.startsWith("run_"))) return false;
  try {
    const response = await fetch(`${apiBaseUrl}/api/explorations/conversations/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    });
    return response.ok || response.status === 404;
  } catch {
    return false;
  }
}

async function streamExplorationRun(
  question: string,
  onUpdate?: (exploration: Exploration) => void,
  options: CreateExplorationRunOptions = {},
): Promise<Exploration> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) throw new Error("api_base_url_required");
  const displayQuestion = options.displayQuestion || question;
  const response = await fetch(`${apiBaseUrl}/api/explorations/conversations/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      conversation_id: options.conversationId,
      user_id: options.userId,
      metadata: options.metadata ?? {},
    }),
  });
  if (!response.ok) throw new Error(`Exploration SSE API returned ${response.status}`);
  const events: ExplorationRunEvent[] = [];
  await readExplorationSse(response, (event) => {
    events.push(event);
    onUpdate?.(mapRunEventsToExploration(displayQuestion, events));
  });
  if (events.length === 0) throw new Error("Exploration SSE stream returned no events.");
  return mapRunEventsToExploration(displayQuestion, events);
}

async function readExplorationSse(response: Response, onEvent: (event: ExplorationRunEvent) => void): Promise<void> {
  if (!response.body) {
    for (const event of parseExplorationSse(await response.text())) {
      onEvent(event);
    }
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
      for (const event of parseExplorationSse(part)) {
        onEvent(event);
      }
    }
    if (done) break;
  }
  for (const event of parseExplorationSse(buffer)) {
    onEvent(event);
  }
}

export function parseExplorationSse(text: string): ExplorationRunEvent[] {
  return text
    .split(/\r?\n\r?\n/)
    .map((block) => block.split(/\r?\n/).filter((line) => line.startsWith("data: ")))
    .filter((lines) => lines.length > 0)
    .map((lines) => lines.map((line) => line.slice(6)).join("\n"))
    .map((data) => JSON.parse(data) as ExplorationRunEvent);
}

export async function searchResources(query: string): Promise<Resource[]> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return [];
  try {
    const url = new URL(`${apiBaseUrl}/api/resources/search`);
    url.searchParams.set("q", query || "dm");
    url.searchParams.set("limit", "30");
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Resource API returned ${response.status}`);
    const payload = (await response.json()) as ResourceSearchResponse;
    return payload.results.map((item) => ({
      id: item.resource_id,
      type: mapResourceType(item.type),
      name: item.name,
      location: item.relative_path,
      description: item.highlights?.join("；") || "来自本地资源库索引。",
    }));
  } catch {
    return [];
  }
}

export function filterResources(resources: Resource[], query: string, type: Resource["type"] | "全部"): Resource[] {
  const normalizedQuery = query.trim().toLowerCase();
  return resources.filter((item) => {
    const matchesType = type === "全部" || item.type === type;
    const matchesQuery =
      !normalizedQuery ||
      `${item.name} ${item.type} ${item.location} ${item.description}`.toLowerCase().includes(normalizedQuery);
    return matchesType && matchesQuery;
  });
}

export function findResourceByEvidenceRef(resources: Resource[], evidenceRef: string): Resource | null {
  const normalizedRef = normalizeSearchText(evidenceRef);
  if (!normalizedRef) return null;
  let best: { resource: Resource; score: number } | null = null;
  for (const resource of resources) {
    const name = normalizeSearchText(resource.name);
    const location = normalizeSearchText(resource.location);
    const description = normalizeSearchText(resource.description);
    const haystack = `${name} ${location} ${description}`;
    let score = 0;
    if (name === normalizedRef) score = 100;
    else if (name.includes(normalizedRef) || normalizedRef.includes(name)) score = 80;
    else if (location.includes(normalizedRef) || normalizedRef.includes(location)) score = 60;
    else if (haystack.includes(normalizedRef)) score = 40;
    if (score > 0 && (!best || score > best.score)) {
      best = { resource, score };
    }
  }
  return best?.resource ?? null;
}

export function buildResourceExplorationPrompt(resource: Resource): string {
  return `基于资源「${resource.name}」（${resource.type}，${resource.location}），帮我探索它能支持哪些业务问题，并核验里面涉及的数据集、表引用和口径。`;
}

export async function readResourceExcerpt(resourceId: string, query?: string): Promise<ResourceExcerpt | null> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return null;
  try {
    const url = new URL(`${apiBaseUrl}/api/resources/${encodeURIComponent(resourceId)}/excerpt`);
    url.searchParams.set("section", query ? "match" : "head");
    url.searchParams.set("max_lines", "80");
    if (query) url.searchParams.set("q", query);
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Resource excerpt API returned ${response.status}`);
    const payload = (await response.json()) as ResourceExcerptResponse;
    return {
      resourceId: payload.resource_id,
      relativePath: payload.relative_path,
      section: payload.section,
      startLine: payload.start_line,
      endLine: payload.end_line,
      truncated: payload.truncated,
      encoding: payload.encoding,
      text: payload.text,
    };
  } catch {
    return null;
  }
}

export async function readResourceDetail(resourceId: string): Promise<ResourceDetail | null> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return null;
  try {
    const response = await fetch(`${apiBaseUrl}/api/resources/${encodeURIComponent(resourceId)}`);
    if (!response.ok) throw new Error(`Resource detail API returned ${response.status}`);
    const payload = (await response.json()) as ResourceDetailResponse;
    return {
      resourceId: payload.resource_id,
      status: payload.status,
      truncatedSummary: payload.truncated_summary,
      sizeBytes: payload.size_bytes,
      modifiedAt: payload.modified_at,
      warnings: payload.warnings,
      profileItems: buildResourceProfileItems(payload),
      signalGroups: buildResourceSignalGroups(payload.signals),
    };
  } catch {
    return null;
  }
}

export async function listKnowledge(): Promise<Knowledge[]> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return [];
  try {
    const response = await fetch(`${apiBaseUrl}/api/knowledge?limit=50`);
    if (!response.ok) throw new Error(`Knowledge API returned ${response.status}`);
    const payload = (await response.json()) as KnowledgeResponse;
    return payload.records.map((item) => ({
      id: item.id,
      title: item.title,
      question: item.question,
      scope: item.scope,
      verified: item.created_at.slice(0, 10),
      verification: item.verification,
      note: item.conclusion || item.verification,
      evidenceRefs: item.evidence_refs ?? [],
      runId: item.run_id ?? null,
    }));
  } catch {
    return [];
  }
}

export async function deleteKnowledge(recordId: string): Promise<boolean> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return false;
  try {
    const response = await fetch(`${apiBaseUrl}/api/knowledge/${encodeURIComponent(recordId)}`, {
      method: "DELETE",
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function saveKnowledgeFromExploration(exploration: Exploration, message: ExplorationMessage): Promise<Knowledge | null> {
  const payload = buildKnowledgePayload(exploration, message);
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return null;
  try {
    const response = await fetch(`${apiBaseUrl}/api/knowledge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Knowledge save API returned ${response.status}`);
    const saved = (await response.json()) as KnowledgeSaveResponse;
    return {
      id: saved.id,
      title: saved.title,
      question: saved.question ?? payload.question,
      scope: saved.scope,
      verified: saved.created_at.slice(0, 10),
      verification: saved.verification,
      note: saved.conclusion || saved.verification,
      evidenceRefs: saved.evidence_refs ?? payload.evidence_refs,
      runId: saved.run_id ?? payload.run_id,
    };
  } catch {
    return null;
  }
}

export function buildKnowledgePayload(exploration: Exploration, message: ExplorationMessage) {
  const userQuestion = exploration.messages.find((item) => item.role === "user")?.body || exploration.title;
  const scope =
    message.details?.find((group) => group.label.includes("范围"))?.items.join("、") ||
    exploration.summary ||
    "知识探索";
  const evidenceRefs = dedupeStrings(
    exploration.messages.flatMap((item) =>
      item.details?.flatMap((group) => (group.label.includes("资源") || group.label.includes("证据") ? group.items : [])) ?? [],
    ),
  );
  return {
    title: exploration.title,
    question: userQuestion,
    conclusion: message.body,
    scope,
    verification: message.title || "探索过程结论",
    evidence_refs: evidenceRefs.length > 0 ? evidenceRefs : [exploration.id],
    run_id: exploration.id,
    metadata: {
      source: "knowledge_exploration_ui",
      message_id: message.id,
      agent: exploration.agent,
    },
  };
}

function mapSavedKnowledge(
  payload: ReturnType<typeof buildKnowledgePayload>,
  id: string,
  createdAt: string,
): Knowledge {
  return {
    id,
    title: payload.title,
    question: payload.question,
    scope: payload.scope,
    verified: createdAt.slice(0, 10),
    verification: payload.verification,
    note: payload.conclusion,
    evidenceRefs: payload.evidence_refs,
    runId: payload.run_id,
  };
}

export async function getResourceStatus(): Promise<ResourceIndexStatus | null> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return null;
  try {
    const response = await fetch(`${apiBaseUrl}/api/resources/status`);
    if (!response.ok) throw new Error(`Resource status API returned ${response.status}`);
    const payload = (await response.json()) as ResourceStatusResponse;
    return {
      indexed: payload.indexed,
      root: payload.root,
      resourceCount: payload.resource_count,
      typeCounts: payload.type_counts,
      indexModifiedAt: payload.index_modified_at,
      summaryModifiedAt: payload.summary_modified_at,
    };
  } catch {
    return null;
  }
}

export async function getRuntimeStatus(): Promise<RuntimeStatus> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) {
    return buildLocalRuntimeStatus();
  }
  try {
    const response = await fetch(`${apiBaseUrl}/api/runtime/status`);
    if (!response.ok) throw new Error(`Runtime status API returned ${response.status}`);
    const payload = (await response.json()) as RuntimeStatusResponse;
    return {
      connected: true,
      ready: payload.ready,
      envFile: payload.env_file,
      envLoaded: payload.env_loaded,
      checks: payload.checks,
    };
  } catch {
    return {
      connected: false,
      ready: false,
      envFile: null,
      envLoaded: false,
      checks: [
        {
          name: "frontend_api_base",
          ok: false,
          message: "探索后端暂不可用，知识探索不会使用本地模拟降级。",
          detail: apiBaseUrl,
        },
      ],
    };
  }
}

export async function reindexResources(): Promise<ResourceIndexStatus | null> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return null;
  try {
    const response = await fetch(`${apiBaseUrl}/api/resources/reindex`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!response.ok) throw new Error(`Resource reindex API returned ${response.status}`);
    return getResourceStatus();
  } catch {
    return null;
  }
}

export async function readRunTrace(runId: string): Promise<RunTraceSummary | null> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl || !runId.trim()) return null;
  try {
    const response = await fetch(`${apiBaseUrl}/api/explorations/run-traces/${encodeURIComponent(runId)}`);
    if (!response.ok) throw new Error(`Run trace API returned ${response.status}`);
    const payload = (await response.json()) as RunTraceResponse;
    return mapRunTraceSummary(payload);
  } catch {
    return null;
  }
}

export function mapRunTraceSummary(trace: RunTraceResponse): RunTraceSummary {
  return {
    runId: trace.run_id,
    title: trace.title || trace.run_id,
    status: mapRunTraceStatus(trace.status),
    question: trace.question,
    startedAt: trace.started_at,
    completedAt: trace.completed_at,
    error: trace.error,
    metrics: [
      { label: "耗时", value: formatDuration(trace.duration_ms) },
      { label: "事件", value: `${trace.event_count} 个` },
      { label: "工具调用", value: `${trace.tool_call_count} 次` },
      { label: "失败工具", value: `${trace.failed_tool_call_count} 次` },
      { label: "Agent 消息", value: `${trace.agent_message_count} 条` },
      { label: "Token", value: formatInteger(trace.token_usage.total_tokens ?? 0) },
      { label: "成本", value: formatUsd(trace.cost.total_usd) },
    ],
  };
}

function mapRunTraceToExplorationSummary(trace: RunTraceResponse): Exploration {
  const explorationId = trace.conversation_id || trace.run_id;
  return {
    id: explorationId,
    title: trace.title || explorationId,
    agent: "知识探索 Agent",
    status: mapTraceStatusToExplorationStatus(trace.status),
    updatedAt: formatTraceUpdatedAt(trace.completed_at || trace.started_at),
    resources: trace.tool_call_count,
    summary: trace.error || trace.question,
    messages: [
      {
        id: `${explorationId}-user`,
        role: "user",
        body: trace.question,
      },
      {
        id: `${explorationId}-summary`,
        role: "agent",
        title: "已保存探索",
        body: trace.error
          ? `这次探索失败：${trace.error}`
          : "这次探索已保存。点击任务后会从后端恢复完整探索过程。",
      },
    ],
  };
}

function isContinuationRunTrace(trace: RunTraceResponse) {
  if (trace.metadata?.conversation_root) return false;
  return (
    Boolean(trace.metadata?.continuation_of) ||
    trace.title?.startsWith("这是同一个知识探索会话中的继续追问或补充") ||
    trace.question.startsWith("这是同一个知识探索会话中的继续追问或补充")
  );
}

function mapTraceStatusToExplorationStatus(status: string): Exploration["status"] {
  if (status === "completed") return "已完成";
  if (status === "failed") return "待确认";
  if (status === "awaiting_user_confirmation") return "待确认";
  return "进行中";
}

function formatTraceUpdatedAt(value: string | null) {
  if (!value) return "未知";
  return value.slice(0, 10);
}

function getApiBaseUrl() {
  return process.env.NEXT_PUBLIC_GENBI_API_BASE_URL;
}

function buildLocalRuntimeStatus(): RuntimeStatus {
  return {
    connected: false,
    ready: false,
    envFile: null,
    envLoaded: false,
    checks: [
      {
        name: "frontend_api_base",
        ok: false,
        message: "未配置 NEXT_PUBLIC_GENBI_API_BASE_URL，知识探索后端未连接。",
        detail: null,
      },
    ],
  };
}

export function mapRunEventsToExploration(question: string, events: ExplorationRunEvent[]): Exploration {
  const rootRunId = events[0]?.run_id ?? `unavailable_${Date.now()}`;
  const conversationId = stringValue(events.find((event) => event.type === "run.created")?.payload.conversation_id);
  const explorationId = conversationId || rootRunId;
  const title = getStringPayload(events, "agent.title.generated", "title") || generateLocalTitle(question);
  const messages: ExplorationMessage[] = [
    {
      id: `${rootRunId}-user`,
      role: "user",
      body: question,
    },
  ];
  let resources = 0;
  let status: Exploration["status"] = "进行中";
  const toolNamesByCallId = new Map<string, string>();
  let pendingTools: ToolCallSummary[] = [];
  let displayedRunnerFailure = false;

  const pushAgentMessage = (message: ExplorationMessage) => {
    const previous = messages[messages.length - 1];
    if (previous?.role === "agent" && previous.body.trim() === message.body.trim()) {
      if (message.title?.includes("结论") && previous.title !== message.title) {
        previous.title = message.title;
      }
      if (!previous.action && message.action) {
        previous.action = message.action;
      }
      return;
    }
    messages.push(message);
  };

  const flushToolSummary = () => {
    if (pendingTools.length === 0) return;
    const completed = pendingTools.filter((tool) => tool.output || tool.error);
    messages.push({
        id: `${rootRunId}-tool-summary-${messages.length}`,
      role: "agent",
      title: `工具调用摘要（${pendingTools.length} 次）`,
      body: summarizeToolBatch(pendingTools),
      details: completed.length
        ? [
            {
              label: "工具与结果",
              items: completed.map((tool) => `${tool.displayName}：${summarizeToolOutput(tool.output || tool.error || "")}`),
            },
          ]
        : undefined,
    });
    pendingTools = [];
  };

  for (const event of events) {
    if (event.type === "run.created" && event.run_id !== rootRunId) {
      const followUp = stringValue(event.payload.question).trim();
      if (followUp) {
        messages.push({
          id: `${event.run_id}-user-${messages.length}`,
          role: "user",
          body: followUp,
        });
      }
    }
    if (event.type === "agent.message.created") {
      const body = sanitizeAgentMessageBody(stringValue(event.payload.content).trim());
      if (!body) continue;
      if (pendingTools.some((tool) => tool.output || tool.error)) flushToolSummary();
      pushAgentMessage({
        id: `${event.run_id}-${messages.length}`,
        role: "agent",
        title: normalizeMessageTitle(stringValue(event.payload.title)),
        body,
      });
    }
    if (event.type === "agent.evidence.available") {
      const items = arrayValue(event.payload.items).map((item) => evidenceLabel(item));
      resources += items.length;
      messages.push({
        id: `${event.run_id}-evidence-${messages.length}`,
        role: "agent",
        title: stringValue(event.payload.title) || "发现候选证据",
        body: "我找到了一些可以继续核验的候选资源，先折叠在当前会话里。",
        details: [{ label: "候选资源", items }],
      });
    }
    if (event.type === "tool.call.failed") {
      flushToolSummary();
      messages.push({
        id: `${event.run_id}-tool-failed-${messages.length}`,
        role: "agent",
        title: "工具调用未完成",
        body: stringValue(event.payload.error) || "工具暂时不可用，已保留当前探索上下文。",
      });
    }
    if (event.type === "tool.call.started") {
      const callId = stringValue(event.payload.call_id);
      const displayName = toolDisplayName(event.payload);
      if (pendingTools.some((tool) => tool.output || tool.error)) flushToolSummary();
      if (callId) toolNamesByCallId.set(callId, displayName);
      pendingTools.push({
        callId,
        displayName,
      });
    }
    if (event.type === "tool.call.completed") {
      const callId = stringValue(event.payload.call_id);
      const displayName = toolDisplayName(event.payload, callId ? toolNamesByCallId.get(callId) : undefined);
      const existing = callId ? pendingTools.find((tool) => tool.callId === callId) : undefined;
      if (existing) {
        existing.displayName = displayName;
        existing.output = stringValue(event.payload.output) || `${numberValue(event.payload.result_count)} 项结果`;
      } else {
        pendingTools.push({
          callId,
          displayName,
          output: stringValue(event.payload.output) || `${numberValue(event.payload.result_count)} 项结果`,
        });
      }
    }
    if (event.type === "agent.runner.failed") {
      flushToolSummary();
      displayedRunnerFailure = true;
      messages.push({
        id: `${event.run_id}-runner-failed-${messages.length}`,
        role: "agent",
        title: "探索未完成",
        body: humanizeRunError(stringValue(event.payload.error) || "Runner 返回失败。"),
      });
    }
    if (event.type === "agent.runner.item") {
      flushToolSummary();
      messages.push({
        id: `${event.run_id}-runner-item-${messages.length}`,
        role: "agent",
        title: "探索过程",
        body: stringValue(event.payload.sdk_event) || "Agent 产生了新的中间事件。",
      });
    }
    if (event.type === "agent.question.requested") {
      flushToolSummary();
      status = "待确认";
      messages.push({
        id: `${event.run_id}-question-${messages.length}`,
        role: "agent",
        title: "需要你确认",
        body: stringValue(event.payload.question) || "",
        details: [{ label: "追问原因", items: [stringValue(event.payload.reason) || "证据不足或口径冲突"] }],
      });
    }
    if (event.type === "run.completed") {
      flushToolSummary();
      status = event.payload.status === "awaiting_user_confirmation" ? "待确认" : "已完成";
    }
    if (event.type === "run.failed") {
      flushToolSummary();
      status = "待确认";
      if (displayedRunnerFailure && stringValue(event.payload.error) === "agent_runner_failed") continue;
      messages.push({
        id: `${event.run_id}-run-failed-${messages.length}`,
        role: "agent",
        title: "探索已停止",
        body: humanizeRunError(stringValue(event.payload.detail) || stringValue(event.payload.error) || "后端返回失败"),
      });
    }
  }
  flushToolSummary();

  return {
    id: explorationId,
    title,
    agent: "知识探索 Agent",
    status,
    updatedAt: "刚刚",
    resources,
    summary: getStringPayload(events, "run.completed", "next_action") || getStringPayload(events, "run.failed", "detail") || "探索过程已创建。",
    messages,
  };
}

type ToolCallSummary = {
  callId: string;
  displayName: string;
  output?: string;
  error?: string;
};

const TOOL_LABELS: Record<string, string> = {
  search_resources: "搜索资源库",
  inspect_resource: "查看资源结构",
  read_resource_excerpt: "读取资源片段",
  search_db_tables: "搜索数据表",
  get_table_schema: "查看表结构",
  inspect_table_profile: "查看表画像",
  run_readonly_query: "执行只读 SQL",
  save_verified_knowledge: "沉淀知识",
};

function toolDisplayName(payload: Record<string, unknown>, fallback?: string) {
  const full = stringValue(payload.tool_label_full);
  if (full) return full;
  const tool = stringValue(payload.tool);
  const label = stringValue(payload.tool_label);
  if (label && tool && label !== tool) return `${label} ${tool}`;
  if (tool && TOOL_LABELS[tool]) return `${TOOL_LABELS[tool]} ${tool}`;
  return fallback || tool || "未知工具 unknown_tool";
}

function sanitizeAgentMessageBody(body: string) {
  return body.replaceAll("数据探索 Agent", "知识探索 Agent");
}

function summarizeToolBatch(tools: ToolCallSummary[]) {
  const names = Array.from(new Set(tools.map((tool) => tool.displayName)));
  const completed = tools.filter((tool) => tool.output || tool.error).length;
  const namesText = names.slice(0, 3).join("、");
  const suffix = names.length > 3 ? ` 等 ${names.length} 类工具` : "";
  return `已调用 ${namesText}${suffix}，${completed > 0 ? `收到 ${completed} 个返回。` : "正在等待返回。"}`;
}

function summarizeToolOutput(output: string) {
  if (!output) return "已完成。";
  if (output.includes("select_star_forbidden")) return "查询被安全规则拒绝：禁止 select *。";
  const rowCount = output.match(/['"]row_count['"]:\s*(\d+)/)?.[1];
  const truncated = output.match(/['"]truncated['"]:\s*(True|False|true|false)/)?.[1];
  if (output.includes("'results': []") || output.includes('"results": []')) return "未命中结果。";
  if (rowCount) return `返回 ${rowCount} 行${truncated?.toLowerCase() === "true" ? "，结果已截断" : ""}。`;
  if (output.includes("approximate_rows")) return "已读取表画像元数据。";
  return output.length > 160 ? `${output.slice(0, 160)}...` : output;
}

function normalizeMessageTitle(title: string) {
  if (title === "阶段输出") return "探索进展";
  return title;
}

function humanizeRunError(error: string) {
  const maxTurns = error.match(/Max turns \((\d+)\) exceeded/i)?.[1];
  if (maxTurns) {
    return `本次探索已达到最多 ${maxTurns} 个模型/工具回合。系统已保留当前发现，可以继续追问让 Agent 接着查，或缩小问题后重新运行。`;
  }
  if (/connection error/i.test(error)) {
    return "模型服务连接失败：本地后端已收到请求，但连接 MiniMax / OpenAI-compatible 模型接口时失败。常见原因是网络、代理、模型服务临时不可用或 base URL 不可达；当前发现已保留，可以稍后重试。";
  }
  return `原因：${error}。已保留当前发现，可继续追问或重新运行。`;
}

function buildBackendUnavailableEvents(question: string, reason: string): ExplorationRunEvent[] {
  const runId = `unavailable_${Date.now()}`;
  const createdAt = new Date().toISOString();
  const title = generateLocalTitle(question);
  return [
    { type: "run.created", run_id: runId, created_at: createdAt, payload: { question } },
    { type: "agent.title.generated", run_id: runId, created_at: createdAt, payload: { title } },
    {
      type: "run.failed",
      run_id: runId,
      created_at: createdAt,
      payload: {
        error: "backend_unavailable",
        detail: `${reason} 知识探索不再使用本地模拟降级，请先启动并配置真实后端。`,
      },
    },
  ];
}

function generateLocalTitle(question: string) {
  const text = question
    .replace(/现在应该怎么计算|应该怎么计算|怎么计算|如何计算|先看看公司里有没有已有实现/g, "")
    .replace(/[。！？!?]/g, "")
    .trim();
  return text.slice(0, 24) || "新的知识探索";
}

function getStringPayload(events: ExplorationRunEvent[], type: ExplorationRunEvent["type"], key: string) {
  const event = events.find((item) => item.type === type);
  return event ? stringValue(event.payload[key]) : "";
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}

function numberValue(value: unknown) {
  return typeof value === "number" ? value : 0;
}

function arrayValue(value: unknown) {
  return Array.isArray(value) ? value : [];
}

function evidenceLabel(value: unknown) {
  if (!value || typeof value !== "object") return String(value);
  const item = value as Record<string, unknown>;
  const name = stringValue(item.name) || stringValue(item.table_name) || stringValue(item.resource_id) || "候选证据";
  const path = stringValue(item.relative_path) || stringValue(item.table_schema);
  return path ? `${name} - ${path}` : name;
}

function mapResourceType(type: string): Resource["type"] {
  if (type.includes("hop")) return "ETL";
  if (type.includes("sql")) return "SQL";
  if (type.includes("table")) return "数据表";
  return "报表";
}

export function buildResourceProfileItems(detail: {
  status: string;
  truncated_summary: boolean;
  size_bytes: number;
  modified_at: string;
  warnings: string[];
}): ResourceProfileItem[] {
  return [
    { label: "读取状态", value: detail.status || "未知" },
    { label: "文件大小", value: formatBytes(detail.size_bytes) },
    { label: "文件更新时间", value: detail.modified_at ? detail.modified_at.slice(0, 19).replace("T", " ") : "未知" },
    { label: "摘要范围", value: detail.truncated_summary ? "已按限制截断" : "完整摘要" },
    { label: "读取告警", value: detail.warnings.length > 0 ? `${detail.warnings.length} 条` : "无" },
  ];
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "未知";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const precision = value >= 10 ? 1 : 2;
  return `${value.toFixed(precision)} ${units[unitIndex]}`;
}

export function buildResourceSignalGroups(signals: Record<string, unknown>): ResourceSignalGroup[] {
  const groups: ResourceSignalGroup[] = [];
  addGroup(groups, "表引用", [
    ...arrayOfStrings(signals.table_refs),
    ...arrayOfStrings(getNested(signals, ["finereport", "lineage_table_refs"])),
    ...arrayOfStrings(getNested(signals, ["hop", "lineage_table_refs"])),
  ]);
  addGroup(groups, "读表", [
    ...arrayOfStrings(signals.read_table_refs),
    ...arrayOfStrings(getNested(signals, ["finereport", "read_table_refs"])),
    ...arrayOfStrings(getNested(signals, ["hop", "read_table_refs"])),
  ]);
  addGroup(groups, "写表", [
    ...arrayOfStrings(signals.write_table_refs),
    ...arrayOfStrings(getNested(signals, ["finereport", "write_table_refs"])),
    ...arrayOfStrings(getNested(signals, ["hop", "write_table_refs"])),
  ]);
  addGroup(groups, "数据集候选", arrayOfStrings(getNested(signals, ["finereport", "dataset_candidates"])));
  addGroup(groups, "参数候选", arrayOfStrings(getNested(signals, ["finereport", "parameter_candidates"])));
  addGroup(groups, "Hop 节点", arrayOfStrings(getNested(signals, ["hop", "action_or_transform_names"])));
  addGroup(groups, "输出字段", [
    ...arrayOfStrings(signals.field_candidates),
    ...arrayOfStrings(getNested(signals, ["hop", "field_candidates"])),
  ]);
  addGroup(groups, "字段候选", [
    ...arrayOfStrings(getNested(signals, ["finereport", "field_candidates"])),
    ...arrayOfStrings(getNested(signals, ["dictionary", "field_candidates"])),
  ]);
  addGroup(groups, "表达式候选", arrayOfStrings(getNested(signals, ["finereport", "formula_candidates"])));
  addGroup(groups, "命名节点", arrayOfNamedNodes(signals.named_nodes));
  return groups;
}

function addGroup(groups: ResourceSignalGroup[], label: string, values: string[]) {
  const items = dedupeStrings(values).slice(0, 8);
  if (items.length > 0) groups.push({ label, items });
}

function arrayOfStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function arrayOfNamedNodes(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (!item || typeof item !== "object") return "";
      const node = item as Record<string, unknown>;
      return [node.tag, node.attribute, node.value].map((part) => (part ? String(part) : "")).filter(Boolean).join(" · ");
    })
    .filter(Boolean);
}

function getNested(source: Record<string, unknown>, path: string[]): unknown {
  let current: unknown = source;
  for (const key of path) {
    if (!current || typeof current !== "object") return undefined;
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

function dedupeStrings(values: string[]) {
  return [...new Set(values.map((item) => item.trim()).filter(Boolean))];
}

function normalizeSearchText(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function mapRunTraceStatus(status: string) {
  if (status === "completed") return "已完成";
  if (status === "failed") return "失败";
  if (status === "running") return "运行中";
  if (status === "awaiting_user_confirmation") return "待确认";
  return status || "未知";
}

function formatDuration(durationMs: number | null) {
  if (durationMs === null || !Number.isFinite(durationMs)) return "未知";
  if (durationMs < 1000) return `${durationMs} ms`;
  return `${(durationMs / 1000).toFixed(durationMs >= 10_000 ? 1 : 2)} s`;
}

function formatInteger(value: number) {
  return Number.isFinite(value) ? value.toLocaleString("en-US") : "0";
}

function formatUsd(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "未估算";
  return `$${value.toFixed(value >= 0.01 ? 4 : 6)}`;
}
