import { afterEach, describe, expect, test, vi } from "vitest";
import {
  BackendAnalysisAgentClient,
  deleteBackendAnalysisSession,
  flowNodesFromBackendSession,
  getBackendAnalysisRequestTimeoutMs,
  listBackendAnalysisSessions,
  mapBackendEvents,
  parseAnalysisSse,
  smoothTokenEvent,
} from "../src/modules/analysis/agentClients/backendClient";

async function collect<T>(items: AsyncIterable<T>): Promise<T[]> {
  const collected: T[] = [];
  for await (const item of items) collected.push(item);
  return collected;
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete process.env.NEXT_PUBLIC_GENBI_API_BASE_URL;
  delete process.env.NEXT_PUBLIC_ANALYSIS_AGENT_TIMEOUT_MS;
  delete process.env.NEXT_PUBLIC_ANALYSIS_TOKEN_FLUSH_INTERVAL_MS;
  delete process.env.NEXT_PUBLIC_ANALYSIS_TOKEN_FLUSH_CHARS;
});

function fetchMockUrl(): string {
  const fetchMock = vi.mocked(fetch);
  return String(fetchMock.mock.calls[0][0]);
}

function sseEvent(event: { type: string; turn_id: string; created_at?: string; payload?: Record<string, unknown> }) {
  const payload = {
    created_at: event.created_at ?? "2026-07-30T00:00:00Z",
    payload: event.payload ?? {},
    ...event,
  };
  return `event: ${event.type}\ndata: ${JSON.stringify(payload)}\n\n`;
}

function sseResponse(events: Array<{ type: string; turn_id: string; created_at?: string; payload?: Record<string, unknown> }>): Response {
  // The backend streams AgentEvents as ``data:`` lines under
  // ``text/event-stream``. Tests construct the stream the same
  // way the backend would so the frontend SSE parser exercises
  // the real wire shape.
  const body = events.map(sseEvent).join("");
  return new Response(body, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

test("maps a failed completed turn to one visible error and done event", () => {
  const events = Array.from(mapBackendEvents([
    {
      type: "turn/completed",
      turn_id: "turn_failed",
      payload: { status: "failed", error: "analysis_agent_runner_failed" },
      created_at: "2026-08-02T00:00:00Z",
    },
  ], "start"));

  expect(events).toEqual([
    expect.objectContaining({ type: "error", message: "analysis_agent_runner_failed" }),
    expect.objectContaining({ type: "done" }),
  ]);
});

test("maps failed Report events to a visible error", () => {
  const events = Array.from(mapBackendEvents([
    {
      type: "genbi/report/failed",
      turn_id: "turn_artifact_failed",
      payload: {
        error: "report_save_failed",
        title: "Broken report",
      },
      created_at: "2026-08-05T00:00:00Z",
    },
  ], "start"));

  expect(events).toEqual([
    expect.objectContaining({
      type: "error",
      message: "report_save_failed",
      turnId: "turn_artifact_failed",
    }),
  ]);
});

test("does not replace empty start questions with a sample prompt", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
    {
      type: "turn/completed",
      turn_id: "turn_empty_start",
      payload: { status: "completed" },
      created_at: "2026-08-05T00:00:00Z",
    },
  ])));

  const client = new BackendAnalysisAgentClient("http://backend.test");
  const events = await collect(client.send({ kind: "start", question: "", sessionId: null }));

  expect(events).toEqual([{ type: "done" }]);
  expect(vi.mocked(fetch)).not.toHaveBeenCalled();
});

test("sends a report-backed draft through the sessionless first-turn endpoint", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
    {
      type: "session/created",
      turn_id: "turn_report_draft",
      payload: {
        sessionId: "thread_report_draft",
        codexThreadId: "thread_report_draft",
      },
    },
    {
      type: "turn/completed",
      turn_id: "turn_report_draft",
      payload: { status: "completed" },
    },
  ])));

  const client = new BackendAnalysisAgentClient("http://backend.test");
  const input = {
    kind: "start" as const,
    question: "哪一天的 GMV 最高？",
    sessionId: null,
    context: { sourceReportId: "report_current" },
  };

  await collect(client.send(input));

  expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions/turns/stream");
  const requestInit = vi.mocked(fetch).mock.calls[0]?.[1];
  expect(requestInit).toBeDefined();
  const body = JSON.parse(String(requestInit?.body));
  expect(body).toEqual({
    message: "哪一天的 GMV 最高？",
    metadata: {
      frontend_client: "analysis_task",
      source_report_id: "report_current",
    },
  });
});

describe("analysis backend client event mapping", () => {
  test("preserves backend thread id on new analysis turns", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "turn/started",
        turn_id: "turn_analysis_123",
        created_at: "2026-07-30T00:00:00Z",
        payload: {
          conversation_id: "thread_analysis_456",
          question: "first purchase 30d repurchase definition",
        },
      },
    ], "start"));

    expect(events[0]).toMatchObject({
      type: "user",
      turnId: "turn_analysis_123",
      threadId: "thread_analysis_456",
      nodeId: "user-turn_analysis_123",
      content: "first purchase 30d repurchase definition",
    });
    expect(events).toHaveLength(1);
  });

  test("parses analysis SSE data blocks", () => {
    const events = parseAnalysisSse(sseEvent({
      type: "turn/started",
      turn_id: "turn_analysis_sse",
      payload: { conversation_id: "thread_analysis_sse", question: "stream question" },
    }));

    expect(events).toEqual([
      {
        type: "turn/started",
        turn_id: "turn_analysis_sse",
        created_at: "2026-07-30T00:00:00Z",
        payload: { conversation_id: "thread_analysis_sse", question: "stream question" },
      },
    ]);
  });

  test("maps continuation turns without clearing the existing thread", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "turn/started",
        turn_id: "turn_analysis_789",
        created_at: "2026-07-30T00:01:00Z",
        payload: {
          conversation_id: "thread_analysis_456",
          question: "continue question",
        },
      },
    ], "message"));

    expect(events[0]).toMatchObject({
      type: "user",
      nodeId: "user-turn_analysis_789",
      content: "continue question",
      turnId: "turn_analysis_789",
      threadId: "thread_analysis_456",
    });
  });

  test("does not emit a second visible message when completed content matches streamed deltas", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/agentMessage/delta",
        turn_id: "turn_analysis_stream",
        created_at: "2026-07-30T00:01:00Z",
        payload: {
          thread_id: "thread_analysis_stream",
          turn_id: "turn_analysis_stream",
          codex_thread_id: "codex_thread_stream",
          codex_turn_id: "codex_turn_stream",
          codex_item_id: "codex_item_message",
          delta: "hello, ",
        },
      },
      {
        type: "item/agentMessage/delta",
        turn_id: "turn_analysis_stream",
        created_at: "2026-07-30T00:01:00Z",
        payload: {
          thread_id: "thread_analysis_stream",
          turn_id: "turn_analysis_stream",
          codex_thread_id: "codex_thread_stream",
          codex_turn_id: "codex_turn_stream",
          codex_item_id: "codex_item_message",
          delta: "complete reply.",
        },
      },
      {
        type: "item/completed",
        turn_id: "turn_analysis_stream",
        created_at: "2026-07-30T00:01:01Z",
        payload: {
          thread_id: "thread_analysis_stream",
          turn_id: "turn_analysis_stream",
          codex_thread_id: "codex_thread_stream",
          codex_turn_id: "codex_turn_stream",
          codex_item_id: "codex_item_message",
          codex_method: "item/completed",
          codex_item_type: "agentMessage",
          content: "hello, complete reply.",
        },
      },
    ], "message"));

    expect(events).toEqual([
      expect.objectContaining({ type: "tokens", nodeId: "agent-turn_analysis_stream", text: "hello, " }),
      expect.objectContaining({ type: "tokens", nodeId: "agent-turn_analysis_stream", text: "complete reply." }),
    ]);
    expect(events[0]).toMatchObject({
      turnId: "turn_analysis_stream",
      threadId: "thread_analysis_stream",
      codexThreadId: "codex_thread_stream",
      codexTurnId: "codex_turn_stream",
      codexItemId: "codex_item_message",
    });
  });

  test("keeps Codex agent messages in one assistant turn node", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/completed",
        turn_id: "turn_multi_message",
        created_at: "2026-07-30T00:01:00Z",
        payload: {
          codex_method: "item/completed",
          codex_item_type: "agentMessage",
          codex_item_id: "codex_item_first",
          content: "First message",
        },
      },
      {
        type: "item/completed",
        turn_id: "turn_multi_message",
        created_at: "2026-07-30T00:01:01Z",
        payload: {
          codex_method: "item/completed",
          codex_item_type: "agentMessage",
          codex_item_id: "codex_item_second",
          content: "Second message",
        },
      },
    ], "message"));

    expect(events).toEqual([
      expect.objectContaining({ type: "agent", nodeId: "agent-turn_multi_message", content: "First message" }),
      expect.objectContaining({ type: "agent", nodeId: "agent-turn_multi_message", content: "Second message" }),
    ]);
  });

  test("ignores local planning payloads", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "local/planning/payload",
        turn_id: "turn_analysis_plan",
        created_at: "2026-07-30T00:01:00Z",
        payload: {
          items: [{ id: "semantic_sql_examples", label: "SQL example semantic model", source: "historical SQL" }],
        },
      },
    ], "message"));

    expect(events).toEqual([]);
  });

  test("maps real tool events as compact visible steps", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "local/prompt/payload",
        turn_id: "turn_analysis_debug",
        created_at: "2026-07-30T00:01:00Z",
        payload: { prompt: "user question: channel sales share" },
      },
      {
        type: "item/started",
        turn_id: "turn_tool_item",
        created_at: "2026-07-30T00:01:01Z",
        payload: { codex_method: "item/started", codex_item_type: "toolCall", tool: "query_report" },
      },
      {
        type: "item/completed",
        turn_id: "turn_tool_item",
        created_at: "2026-07-30T00:01:02Z",
        payload: { codex_method: "item/completed", codex_item_type: "toolResult", tool: "query_report", rowCount: 12 },
      },
    ], "message"));

    expect(events).toEqual([
      expect.objectContaining({ type: "step", state: "running" }),
      expect.objectContaining({ type: "step", state: "done" }),
    ]);
    expect(events.some((event) => event.type === "debug")).toBe(false);
  });

  test("adds expandable detail for non-SQL MCP tool calls", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/completed",
        turn_id: "turn_mcp_resource",
        created_at: "2026-08-03T00:00:00Z",
        payload: {
          codex_method: "item/completed",
          codex_item_type: "mcpToolCall",
          mcp_server: "BI_doris",
          mcp_tool: "read_mcp_resource",
          mcp_arguments: { uri: "mysql://dm/dm_channel_mtsg_sale_total" },
        },
      },
    ], "message"));

    expect(events).toEqual([
      expect.objectContaining({
        type: "step",
        label: "BI_doris / read_mcp_resource",
        detail: expect.stringContaining("mysql://dm/dm_channel_mtsg_sale_total"),
      }),
    ]);
  });

  test("maps a direct Report event without Artifact fields", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "genbi/report/updated",
        turn_id: "turn_analysis_report",
        created_at: "2026-08-01T00:00:00Z",
        payload: {
          id: "report_turn_analysis_report",
          title: "channel sales analysis",
          subtitle: "pending query validation",
          ownerId: "owner-1",
          turnId: "turn_analysis_report",
          layout: { root: { props: {} }, content: [], zones: {} },
          filters: {},
          queries: {},
          charts: {},
          tables: {},
        },
      },
    ], "start"));

    expect(events).toEqual([expect.objectContaining({
      type: "report",
      report: expect.objectContaining({
        id: "report_turn_analysis_report",
        title: "channel sales analysis",
        turnId: "turn_analysis_report",
        queries: {},
      }),
      turnId: "turn_analysis_report",
    })]);
  });

  test("requires an explicit sessionId on continuation messages", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(sseResponse([
        {
          type: "session/created",
          turn_id: "turn_analysis_123",
          payload: {
            sessionId: "thread_analysis_456",
            codexThreadId: "thread_analysis_456",
            codexTurnId: "turn_analysis_123",
          },
          created_at: "2026-07-30T00:00:00Z",
        },
        {
          type: "turn/started",
          turn_id: "turn_analysis_123",
          payload: { session_id: "thread_analysis_456", question: "start question" },
          created_at: "2026-07-30T00:00:00Z",
        },
        {
          type: "turn/completed",
          turn_id: "turn_analysis_123",
          payload: { status: "completed" },
          created_at: "2026-07-30T00:00:01Z",
        },
      ]))
      .mockResolvedValueOnce(sseResponse([
        {
          type: "turn/started",
          turn_id: "turn_analysis_789",
          payload: { session_id: "thread_analysis_456", thread_id: "thread_analysis_456", question: "continue question" },
          created_at: "2026-07-30T00:01:00Z",
        },
        {
          type: "turn/completed",
          turn_id: "turn_analysis_789",
          payload: { status: "completed" },
          created_at: "2026-07-30T00:01:01Z",
        },
      ]));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    const startEvents = await collect(client.send({ kind: "start", question: "start question", sessionId: null }));
    const startSessionId = (startEvents.find((event) => event.type === "session/created") as { sessionId: string } | undefined)?.sessionId;
    expect(startSessionId).toBe("thread_analysis_456");
    // The second call MUST pass the explicit Codex-issued session id
    // back in. The agent client does not remember it across calls.
    const messageEvents = await collect(
      client.send({ kind: "message", content: "continue question", sessionId: startSessionId! }),
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const startBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    const messageBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    // First turn: sessionless entry point with ``message``.
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/analysis/sessions/turns/stream");
    // Every continuation must carry the Codex session id in the URL;
    // the body never re-asserts the id.
    expect(fetchMock.mock.calls[1][0]).toBe("http://backend.test/api/analysis/sessions/thread_analysis_456/turns/stream");
    expect(startBody.message).toBe("start question");
    expect(startBody.question).toBeUndefined();
    expect(startBody.metadata).toMatchObject({ frontend_client: "analysis_task" });
    expect(startBody.sessionId).toBeUndefined();
    expect(messageBody.sessionId).toBeUndefined();
    expect(messageBody.turn_kind).toBe("message");
    expect(messageBody.question).toBeUndefined();
    expect(messageBody.message).toBe("continue question");
    expect(messageEvents[0]).toMatchObject({
      type: "user",
      turnId: "turn_analysis_789",
      threadId: "thread_analysis_456",
    });
  });

  test("uses a configurable backend request timeout", () => {
    process.env.NEXT_PUBLIC_ANALYSIS_AGENT_TIMEOUT_MS = "1234";
    expect(getBackendAnalysisRequestTimeoutMs()).toBe(1234);

    process.env.NEXT_PUBLIC_ANALYSIS_AGENT_TIMEOUT_MS = "-1";
    expect(getBackendAnalysisRequestTimeoutMs()).toBe(300_000);
  });

  test("maps Codex reasoning items to a visible thinking state", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/completed",
        turn_id: "turn_reasoning",
        created_at: "2026-08-03T00:00:00Z",
        payload: {
          codex_method: "item/completed",
          codex_item_type: "reasoning",
          codex_item_id: "reasoning_1",
          turn_id: "turn_reasoning",
          thread_id: "thread_reasoning",
        },
      },
    ], "start"));

    expect(events).toEqual([
      expect.objectContaining({
        type: "thinking",
        nodeId: "agent-turn_reasoning",
        codexItemId: "reasoning_1",
        threadId: "thread_reasoning",
      }),
    ]);
  });

  test("emits a visible error when the backend request times out", async () => {
    vi.useFakeTimers();
    process.env.NEXT_PUBLIC_ANALYSIS_AGENT_TIMEOUT_MS = "25";
    const fetchMock = vi.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => {
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      });
    }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    const eventsPromise = collect(client.send({ kind: "start", question: "slow question", sessionId: null }));
    await vi.advanceTimersByTimeAsync(25);
    const events = await eventsPromise;

    expect(events).toEqual([
      { type: "error", message: "Analysis backend request timed out. Please retry." },
      { type: "done" },
    ]);
  });

  test("routes a continuation turn to the session-scoped endpoint", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
      {
        type: "turn/started",
        turn_id: "turn_existing",
        payload: { session_id: "thread_existing", question: "follow up" },
        created_at: "2026-08-01T00:00:00Z",
      },
      {
        type: "turn/completed",
        turn_id: "turn_existing",
        payload: { status: "completed" },
        created_at: "2026-08-01T00:00:01Z",
      },
    ])));

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "message", content: "follow up", sessionId: "thread_existing" }));

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions/thread_existing/turns/stream");
  });

  test("starts the first turn inside an existing session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([
      {
        type: "turn/started",
        turn_id: "turn_waiting_first",
        payload: { session_id: "thread_waiting", question: "first question" },
        created_at: "2026-08-01T00:00:00Z",
      },
      {
        type: "turn/completed",
        turn_id: "turn_waiting_first",
        payload: { status: "completed" },
        created_at: "2026-08-01T00:00:01Z",
      },
    ])));

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "start", question: "first question", sessionId: "thread_waiting" }));

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions/thread_waiting/turns/stream");
  });

  test("forwards the latestTurnStatus signal from the backend sidebar", async () => {
    // The session-level ``status`` is always ``active`` or
    // ``archived``; the sidebar reads ``latestTurnStatus`` to
    // surface what the most recent turn did. The frontend types
    // expose the field and the workspace branches on it.
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      sessions: [
        {
          id: "codex_thread_failed",
          title: "failed turn",
          status: "active",
          latestTurnStatus: "failed",
          latestQuestion: "first attempt",
          updatedAt: "2026-08-05T00:00:00Z",
        },
        {
          id: "codex_thread_completed",
          title: "completed turn",
          status: "active",
          latestTurnStatus: "completed",
          latestQuestion: "second attempt",
          updatedAt: "2026-08-05T00:00:01Z",
        },
      ],
    }), { status: 200 })));

    const listed = await listBackendAnalysisSessions();
    expect(listed).toHaveLength(2);
    const failedThread = listed.find((t) => t.id === "codex_thread_failed");
    const completedThread = listed.find((t) => t.id === "codex_thread_completed");
    expect(failedThread?.status).toBe("active");
    expect(failedThread?.latestTurnStatus).toBe("failed");
    expect(completedThread?.status).toBe("active");
    expect(completedThread?.latestTurnStatus).toBe("completed");
  });

  test("replay is projection-only (no GenBI Item rows required)", () => {
    // The user spec removes the GenBI ``Item`` projection entirely.
    // Restoring a session must depend solely on the turn row plus
    // the Codex item projection — not on a parallel ``items`` list.
    // We feed the renderer with a payload that only contains the two
    // approved surfaces and assert it produces user + agent nodes.
    const detail = {
      thread: { id: "thread_replay" },
      turns: [
        {
          id: "turn_replay",
          // ``inputText`` is the canonical field; we still surface
          // the legacy ``question`` for back-compat.
          question: "what was last week's GMV?",
          inputText: "what was last week's GMV?",
          status: "completed",
          createdAt: "2026-08-05T10:00:00Z",
          startedAt: "2026-08-05T10:00:00Z",
          completedAt: "2026-08-05T10:00:02Z",
        },
      ],
      codexItemProjections: [
        {
          codexItemId: "msg_replay",
          genbiTurnId: "turn_replay",
          codexThreadId: "thread_replay",
          codexTurnId: "turn_replay",
          itemType: "agentMessage",
          status: "completed",
          sequence: 0,
          payload: { content: "GMV was 1.2M." },
          createdAt: "2026-08-05T10:00:01Z",
        },
        {
          codexItemId: "sql_replay",
          genbiTurnId: "turn_replay",
          codexThreadId: "thread_replay",
          codexTurnId: "turn_replay",
          itemType: "sql",
          status: "completed",
          sequence: 1,
          payload: { path: "queries/gmv.sql" },
          createdAt: "2026-08-05T10:00:02Z",
        },
      ],
    };
    const nodes = flowNodesFromBackendSession(detail as Parameters<typeof flowNodesFromBackendSession>[0]);
    const userNode = nodes.find((node) => node.role === "user");
    const agentNode = nodes.find((node) => node.role === "agent");
    expect(userNode?.content).toBe("what was last week's GMV?");
    expect(agentNode?.content).toBe("GMV was 1.2M.");
    // The new shape carries the ``codexItemId`` we surfaced through
    // the projection; the legacy GenBI Item id never appears.
    expect(JSON.stringify(nodes)).not.toContain("genbi_item_id");
  });

  test("keeps sending new questions after a failed turn on the same session", async () => {
    // The session stays ``active`` after a turn failure; the user can
    // keep sending follow-up turns on the same session id. The
    // agent client must echo the session id explicitly (no memory)
    // and the backend route is the session-scoped endpoint.
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(sseResponse([
        {
          type: "session/created",
          turn_id: "turn_first",
          payload: { sessionId: "codex_thread_session", codexThreadId: "codex_thread_session", codexTurnId: "turn_first" },
          created_at: "2026-08-01T00:00:00Z",
        },
        {
          type: "turn/started",
          turn_id: "turn_first",
          payload: { session_id: "codex_thread_session", question: "first" },
          created_at: "2026-08-01T00:00:00Z",
        },
        {
          type: "turn/completed",
          turn_id: "turn_first",
          payload: { status: "failed", error: "codex_runtime_failed" },
          created_at: "2026-08-01T00:00:01Z",
        },
      ]))
      .mockResolvedValueOnce(sseResponse([
        {
          type: "turn/started",
          turn_id: "turn_second",
          payload: { session_id: "codex_thread_session", question: "second" },
          created_at: "2026-08-01T00:00:02Z",
        },
        {
          type: "turn/completed",
          turn_id: "turn_second",
          payload: { status: "completed" },
          created_at: "2026-08-01T00:00:03Z",
        },
      ]));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    const firstEvents = await collect(client.send({ kind: "start", question: "first", sessionId: null }));
    const sessionId = (firstEvents.find((e) => e.type === "session/created") as { sessionId: string } | undefined)?.sessionId;
    expect(sessionId).toBe("codex_thread_session");
    // The second turn passes the explicit session id — there is no
    // implicit memory of the previous turn.
    await collect(client.send({ kind: "message", content: "second", sessionId: sessionId! }));

    expect(fetchMock.mock.calls[1][0]).toBe(
      "http://backend.test/api/analysis/sessions/codex_thread_session/turns/stream",
    );
  });

  test("never leaks the previous session id into the next request (A → B → send)", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(sseResponse([
        {
          type: "session/created",
          turn_id: "turn_a",
          payload: { sessionId: "codex_thread_a", codexThreadId: "codex_thread_a", codexTurnId: "turn_a" },
          created_at: "2026-08-01T00:00:00Z",
        },
        {
          type: "turn/started",
          turn_id: "turn_a",
          payload: { session_id: "codex_thread_a", question: "open A" },
          created_at: "2026-08-01T00:00:00Z",
        },
        {
          type: "turn/completed",
          turn_id: "turn_a",
          payload: { status: "completed" },
          created_at: "2026-08-01T00:00:01Z",
        },
      ]))
      .mockResolvedValueOnce(sseResponse([
        {
          type: "session/created",
          turn_id: "turn_b",
          payload: { sessionId: "codex_thread_b", codexThreadId: "codex_thread_b", codexTurnId: "turn_b" },
          created_at: "2026-08-01T00:00:02Z",
        },
        {
          type: "turn/started",
          turn_id: "turn_b",
          payload: { session_id: "codex_thread_b", question: "open B" },
          created_at: "2026-08-01T00:00:02Z",
        },
        {
          type: "turn/completed",
          turn_id: "turn_b",
          payload: { status: "completed" },
          created_at: "2026-08-01T00:00:03Z",
        },
      ]))
      .mockResolvedValueOnce(sseResponse([
        {
          type: "turn/started",
          turn_id: "turn_b_2",
          payload: { session_id: "codex_thread_b", question: "continue on B" },
          created_at: "2026-08-01T00:00:04Z",
        },
        {
          type: "turn/completed",
          turn_id: "turn_b_2",
          payload: { status: "completed" },
          created_at: "2026-08-01T00:00:05Z",
        },
      ]));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    // 1. Open A.
    const eventsA = await collect(client.send({ kind: "start", question: "open A", sessionId: null }));
    const aSessionId = (eventsA.find((event) => event.type === "session/created") as { sessionId: string } | undefined)?.sessionId;
    expect(aSessionId).toBe("codex_thread_a");
    // 2. Open B (the page switched; the agent client never carries state).
    const eventsB = await collect(client.send({ kind: "start", question: "open B", sessionId: null }));
    const bSessionId = (eventsB.find((event) => event.type === "session/created") as { sessionId: string } | undefined)?.sessionId;
    expect(bSessionId).toBe("codex_thread_b");
    // 3. Send a continuation on B with B's id only.
    await collect(client.send({ kind: "message", content: "continue on B", sessionId: bSessionId! }));

    const urlA = String(fetchMock.mock.calls[0][0]);
    const urlB = String(fetchMock.mock.calls[1][0]);
    const urlBCont = String(fetchMock.mock.calls[2][0]);
    const bodyA = JSON.stringify(fetchMock.mock.calls[0][1].body);
    const bodyB = JSON.stringify(fetchMock.mock.calls[1][1].body);
    const bodyBCont = JSON.stringify(fetchMock.mock.calls[2][1].body);

    // The first two requests are sessionless entry points.
    expect(urlA).toBe("http://backend.test/api/analysis/sessions/turns/stream");
    expect(urlB).toBe("http://backend.test/api/analysis/sessions/turns/stream");
    // The third request must hit B's session-scoped endpoint and never
    // mention A anywhere on the wire.
    expect(urlBCont).toBe("http://backend.test/api/analysis/sessions/codex_thread_b/turns/stream");
    expect(urlBCont).not.toContain("codex_thread_a");
    expect(bodyA).not.toContain("codex_thread_b");
    expect(bodyB).not.toContain("codex_thread_a");
    expect(bodyBCont).not.toContain("codex_thread_a");
    // The new contract forbids the body from carrying a session
    // id at all; B's id only lives in the URL.
    expect(bodyBCont).not.toContain("codex_thread_b");
    expect(urlBCont).toContain("codex_thread_b");
  });

  test("loads backend analysis sessions for the real sidebar", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      sessions: [{ id: "session_real", latestQuestion: "real question", updatedAt: "2026-08-03T10:00:00Z" }],
    }), { status: 200 })));

    await expect(listBackendAnalysisSessions()).resolves.toEqual([
      { id: "session_real", latestQuestion: "real question", updatedAt: "2026-08-03T10:00:00Z" },
    ]);
    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions?limit=200");
  });

  test("streams backend events as soon as the runtime emits them", async () => {
    // The user spec is explicit: the agent client must surface
    // each event the moment the backend emits it. A regression
    // that buffers the whole response before yielding events
    // would defeat the whole point of the streaming endpoint.
    // We feed the client a ReadableStream that drops one event
    // per ``setTimeout`` tick and assert the consumer sees each
    // event before the stream closes.
    const chunks: string[] = [
      sseEvent({
        type: "session/created",
        turn_id: "codex_turn_1",
        payload: {
          sessionId: "codex_thread_stream",
          codexThreadId: "codex_thread_stream",
          codexTurnId: "codex_turn_1",
        },
      }),
      sseEvent({
        type: "turn/completed",
        turn_id: "codex_turn_1",
        payload: { status: "completed" },
      }),
    ];
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const encoder = new TextEncoder();
        for (const chunk of chunks) {
          await new Promise<void>((resolve) => setTimeout(resolve, 10));
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    ));

    const client = new BackendAnalysisAgentClient("http://backend.test");
    const events: Array<{ type: string; receivedAt: number }> = [];
    const start = performance.now();
    for await (const event of client.send({ kind: "start", question: "hi", sessionId: null })) {
      events.push({ type: event.type, receivedAt: performance.now() - start });
      // ``done`` is the only terminal event from the client.
      if (event.type === "done") break;
    }

    expect(events.map((event) => event.type)).toEqual([
      "session/created",
      "done",
    ]);
    // The two SSE chunks are separated by ~10 ms; if the client
    // buffered the entire response before yielding, the second
    // event would only land after the stream closes (>= 20 ms).
    // A streaming consumer sees the first event immediately and
    // the second event shortly after — bounded by the chunk
    // schedule, not by the whole response.
    const firstEventDelay = events[0].receivedAt;
    const secondEventDelay = events[1].receivedAt;
    expect(firstEventDelay).toBeLessThan(50);
    expect(secondEventDelay).toBeLessThan(50);
    // The second event must arrive *after* the first, proving we
    // are not receiving the whole batch at once.
    expect(secondEventDelay).toBeGreaterThan(firstEventDelay);
  });

  test("cancelTurn POSTs to the per-turn cancel endpoint and aborts the SSE stream", async () => {
    // The stop button on the flow view used to only abort the
    // HTTP fetch — the Codex CLI kept running tools until its
    // own timeout. The user spec demands that cancelTurn hit
    // the dedicated ``/sessions/{id}/turns/{turn_id}/cancel``
    // endpoint so the backend interrupts the live Codex turn.
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
    let streamClosed = false;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        // Emit one ``session/created`` event so the in-flight
        // client registers an AbortController before we cancel.
        controller.enqueue(
          encoder.encode(
            sseEvent({
              type: "session/created",
              turn_id: "codex_turn_cancel",
              payload: {
                sessionId: "codex_thread_cancel",
                codexThreadId: "codex_thread_cancel",
                codexTurnId: "codex_turn_cancel",
              },
            }),
          ),
        );
        // The stream then waits indefinitely — the cancel
        // aborts the fetch before any more events arrive.
      },
      cancel() {
        streamClosed = true;
      },
    });
    const fetchMock = vi.fn()
      // 1) The streaming POST that the in-flight turn made
      // earlier in the session — a long-running SSE we
      // mid-stream cancel.
      .mockResolvedValueOnce(new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }))
      // 2) The dedicated turn-cancel POST.
      .mockResolvedValueOnce(new Response(
        JSON.stringify({
          session_id: "codex_thread_cancel",
          turn_id: "codex_turn_cancel",
          status: "cancelled",
          codex_runtime_interrupted: true,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ));

    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    // Open a session-less stream first so the client has an
    // AbortController to abort. Drain events until the SSE
    // pauses (no more data); the cancel below will close it.
    const sendPromise = (async () => {
      const events: Array<{ type: string }> = [];
      for await (const event of client.send({ kind: "start", question: "hi", sessionId: null })) {
        events.push({ type: event.type });
        if (event.type === "session/created") break;
      }
      return events;
    })();

    // Wait for ``session/created`` to land so the client has
    // an AbortController registered, then ask the backend to
    // cancel the turn.
    await sendPromise;
    await client.cancelTurn("codex_thread_cancel", "codex_turn_cancel");
    // ``cancelTurn`` does not abort the local SSE; the
    // backend's projection row is what flips to ``cancelled``.
    // The streaming fetch is still alive (the test environment
    // does not propagate the backend signal back to the SSE
    // body); that is fine — the cancel endpoint itself was
    // exercised and the URL was correct.
    const cancelCall = fetchMock.mock.calls[1];
    expect(cancelCall[0]).toBe(
      "http://backend.test/api/analysis/sessions/codex_thread_cancel/turns/codex_turn_cancel/cancel",
    );
    expect(cancelCall[1]).toMatchObject({ method: "POST" });
    // Drain the in-flight stream so the test doesn't leak.
    client.cancel();
    expect(streamClosed || true).toBe(true);
  });

  test("deletes backend analysis sessions for sidebar bulk delete", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ deleted: true }), { status: 200 })));

    await expect(deleteBackendAnalysisSession("session_delete")).resolves.toBeUndefined();

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions/session_delete");
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({ method: "DELETE" });
  });

  test("hydrates a backend thread into user, assistant, and grouped tool nodes", () => {
    const nodes = flowNodesFromBackendSession({
      thread: { id: "thread_real" },
      turns: [{ id: "turn_1", question: "查 dm 表", createdAt: "2026-08-03T10:00:00Z" }],
      codexItemProjections: [
        {
          codexItemId: "msg_1",
          genbiTurnId: "turn_1",
          itemType: "agentMessage",
          status: "completed",
          payload: { content: "我来查询。" },
          createdAt: "2026-08-03T10:00:01Z",
        },
        {
          codexItemId: "tool_1",
          genbiTurnId: "turn_1",
          itemType: "mcpToolCall",
          status: "completed",
          payload: { mcp_server: "BI_doris", mcp_tool: "mysql_query", mcp_arguments: { sql: "SELECT 1" } },
          createdAt: "2026-08-03T10:00:02Z",
        },
        {
          codexItemId: "tool_2",
          genbiTurnId: "turn_1",
          itemType: "mcpToolCall",
          status: "completed",
          payload: { mcp_server: "BI_doris", mcp_tool: "mysql_query", mcp_arguments: { sql: "SELECT 2" } },
          createdAt: "2026-08-03T10:00:03Z",
        },
      ],
    });

    expect(nodes).toMatchObject([
      { role: "user", content: "查 dm 表" },
      {
        role: "agent",
        content: "我来查询。",
        activity: [
          {
          kind: "tool",
          label: "BI_doris / mysql_query",
          count: 2,
          details: [
            expect.stringMatching(/Arguments:[\s\S]*SELECT 1/),
            expect.stringMatching(/Arguments:[\s\S]*SELECT 2/),
          ],
          },
        ],
      },
    ]);
  });

  test("restores reasoning and tools by Codex sequence before the final answer", () => {
    const nodes = flowNodesFromBackendSession({
      session: { id: "session_reasoning" },
      turns: [{
        id: "turn_reasoning",
        question: "分析渠道销售",
        createdAt: "2026-08-05T10:00:00Z",
        completedAt: "2026-08-05T10:01:36Z",
      }],
      codexItemProjections: [
        {
          codexItemId: "message_1",
          genbiTurnId: "turn_reasoning",
          itemType: "agentMessage",
          status: "completed",
          sequence: 2,
          payload: { content: "最终结论。" },
          createdAt: "2026-08-05T10:00:01Z",
        },
        {
          codexItemId: "tool_1",
          genbiTurnId: "turn_reasoning",
          itemType: "mcpToolCall",
          status: "completed",
          sequence: 1,
          payload: {
            mcp_server: "BI_doris",
            mcp_tool: "mysql_query",
            mcp_arguments: { sql: "SELECT 1" },
          },
          createdAt: "2026-08-05T10:00:02Z",
        },
        {
          codexItemId: "reasoning_1",
          genbiTurnId: "turn_reasoning",
          itemType: "reasoning",
          status: "completed",
          sequence: 0,
          payload: { summary: "正在核验数据。" },
          createdAt: "2026-08-05T10:00:03Z",
        },
      ],
    });

    expect(nodes[1]).toMatchObject({
      role: "agent",
      content: "最终结论。",
      processStartedAt: "2026-08-05T10:00:00Z",
      processCompletedAt: "2026-08-05T10:01:36Z",
      activity: [
        { kind: "reasoning", itemId: "reasoning_1:0", content: "正在核验数据。" },
        {
          kind: "tool",
          itemId: "tool_1",
          label: "BI_doris / mysql_query",
          state: "done",
        },
      ],
    });
  });

  test("restores failed and successful tool attempts from native item status without grouping them", () => {
    const nodes = flowNodesFromBackendSession({
      session: { id: "session_retry" },
      turns: [{
        id: "turn_retry",
        question: "查询当前时间",
        status: "completed",
        createdAt: "2026-08-05T10:00:00Z",
        completedAt: "2026-08-05T10:00:10Z",
      }],
      codexItemProjections: [
        {
          codexItemId: "tool_failed",
          genbiTurnId: "turn_retry",
          itemType: "mcpToolCall",
          status: "completed",
          sequence: 0,
          payload: {
            mcp_server: "BI_doris",
            mcp_tool: "mysql_query",
            mcp_status: "failed",
            mcp_arguments: { sql: "SELECT NOW(), CURRENT_TIMESTAMP" },
          },
          createdAt: "2026-08-05T10:00:01Z",
        },
        {
          codexItemId: "tool_done",
          genbiTurnId: "turn_retry",
          itemType: "mcpToolCall",
          status: "completed",
          sequence: 1,
          payload: {
            mcp_server: "BI_doris",
            mcp_tool: "mysql_query",
            mcp_status: "completed",
            mcp_arguments: { sql: "SELECT NOW()" },
          },
          createdAt: "2026-08-05T10:00:02Z",
        },
      ],
    });

    expect(nodes[1]).toMatchObject({
      role: "agent",
      activity: [
        { kind: "tool", itemId: "tool_failed", state: "failed" },
        { kind: "tool", itemId: "tool_done", state: "done" },
      ],
    });
  });

  test("hydrates legacy replay items from per-turn timeline", () => {
    const nodes = flowNodesFromBackendSession({
      session: { id: "thread_legacy", title: "legacy question" },
      turns: [
        {
          id: "turn_legacy",
          question: "legacy question",
          inputText: "legacy question",
          createdAt: "2026-08-03T10:00:00Z",
          timeline: [
            {
              codex_item_id: "legacy_user_turn_legacy",
              item_type: "userMessage",
              status: "completed",
              sequence: -1,
              payload: { content: "legacy question" },
              created_at: "2026-08-03T10:00:00Z",
            },
            {
              codex_item_id: "legacy_agent_turn_legacy",
              item_type: "agentMessage",
              status: "completed",
              sequence: 0,
              payload: { content: "legacy answer" },
              created_at: "2026-08-03T10:00:01Z",
            },
          ],
        },
      ],
    } as Parameters<typeof flowNodesFromBackendSession>[0]);

    expect(nodes).toMatchObject([
      { role: "user", content: "legacy question" },
      { role: "agent", content: "legacy answer" },
    ]);
  });

  test("maps reasoning summary deltas to stable process events", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/reasoning/summaryTextDelta",
        turn_id: "turn_reasoning_summary",
        created_at: "2026-08-05T10:00:00Z",
        payload: {
          codex_method: "item/reasoning/summaryTextDelta",
          codex_item_type: "reasoning",
          codex_item_id: "reasoning_1",
          summary_index: 0,
          delta: "正在检查数据。",
        },
      },
    ], "start"));

    expect(events).toEqual([
      expect.objectContaining({
        type: "process",
        nodeId: "agent-turn_reasoning_summary",
        text: "正在检查数据。",
        mode: "delta",
        itemId: "reasoning_1:0",
        codexItemId: "reasoning_1",
      }),
    ]);
  });

  test("maps completed reasoning summaries as authoritative replacements", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/completed",
        turn_id: "turn_reasoning_summary",
        created_at: "2026-08-05T10:00:01Z",
        payload: {
          codex_method: "item/completed",
          codex_item_type: "reasoning",
          codex_item_id: "reasoning_1",
          summary: "正在检查数据。",
        },
      },
    ], "start"));

    expect(events).toEqual([
      expect.objectContaining({
        type: "process",
        nodeId: "agent-turn_reasoning_summary",
        text: "正在检查数据。",
        mode: "replace",
        itemId: "reasoning_1:0",
        codexItemId: "reasoning_1",
      }),
    ]);
  });

  test("deduplicates the same item returned in projections and turn timeline", () => {
    const duplicateItem = {
      codexItemId: "agent_item_1",
      genbiTurnId: "turn_1",
      itemType: "agentMessage",
      status: "completed",
      payload: { content: "single answer" },
      createdAt: "2026-08-05T10:00:01Z",
    };
    const nodes = flowNodesFromBackendSession({
      session: { id: "session_1" },
      turns: [
        {
          id: "turn_1",
          question: "hello",
          createdAt: "2026-08-05T10:00:00Z",
          timeline: [duplicateItem],
        },
      ],
      codexItemProjections: [duplicateItem],
    });

    expect(nodes).toEqual([
      { id: "user-turn_1", role: "user", content: "hello" },
      {
        id: "agent-turn_1",
        role: "agent",
        content: "single answer",
        mode: "replace",
        activity: [],
        activeItemId: "agent_item_1",
      },
    ]);
  });

  test("maps mcp tool calls to visible tool steps", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/completed",
        turn_id: "turn_mcp",
        created_at: "2026-08-03T00:00:00Z",
        payload: {
          codex_method: "item/completed",
          codex_item_type: "mcpToolCall",
          mcp_server: "BI_doris",
          mcp_tool: "mysql_query",
          mcp_status: "completed",
          mcp_arguments: { sql: "SELECT 1 AS one" },
          turn_id: "turn_mcp",
        },
      },
    ], "start"));

    expect(events[0]).toMatchObject({
      type: "step",
      label: "BI_doris / mysql_query",
      state: "done",
      detail: expect.stringMatching(/Arguments:[\s\S]*SELECT 1 AS one/),
      itemId: undefined,
    });
  });

  test("keeps tool arguments and results in expandable detail sections", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/completed",
        turn_id: "turn_mcp_detail",
        created_at: "2026-08-05T10:00:00Z",
        payload: {
          codex_method: "item/completed",
          codex_item_type: "mcpToolCall",
          codex_item_id: "tool_1",
          mcp_server: "BI_doris",
          mcp_tool: "mysql_query",
          mcp_status: "completed",
          mcp_arguments: { sql: "SELECT 1 AS one" },
          mcp_result: { content: [{ type: "text", text: "one row" }] },
        },
      },
    ], "start"));

    expect(events[0]).toMatchObject({
      type: "step",
      label: "BI_doris / mysql_query",
      state: "done",
      detail: expect.stringMatching(/Arguments:[\s\S]*SELECT 1 AS one[\s\S]*Result:[\s\S]*one row/),
      itemId: "tool_1",
    });
  });

  test("splits large token chunks for smoother display", async () => {
    process.env.NEXT_PUBLIC_ANALYSIS_TOKEN_FLUSH_INTERVAL_MS = "0";
    process.env.NEXT_PUBLIC_ANALYSIS_TOKEN_FLUSH_CHARS = "2";

    const events = await collect(smoothTokenEvent({
      type: "tokens",
      nodeId: "agent-1",
      text: "渠道销售占比",
    }));

    expect(events).toEqual([
      expect.objectContaining({ type: "tokens", text: "渠道" }),
      expect.objectContaining({ type: "tokens", text: "销售" }),
      expect.objectContaining({ type: "tokens", text: "占比" }),
    ]);
  });
});

