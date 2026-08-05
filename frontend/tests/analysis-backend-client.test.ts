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

  test("streams assistant deltas into one Codex turn message and replaces it with the final content", () => {
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
      expect.objectContaining({ type: "agent", nodeId: "agent-turn_analysis_stream", content: "hello, complete reply.", mode: "replace" }),
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

  test("maps an interactive report artifact as a dedicated result event", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "genbi/artifact/updated",
        turn_id: "turn_analysis_report",
        created_at: "2026-08-01T00:00:00Z",
        payload: {
          artifactType: "interactive_report",
          schemaVersion: "1.0",
          id: "report_turn_analysis_report",
          title: "channel sales analysis",
          subtitle: "pending query validation",
          renderer: "puck",
          document: { root: { props: {} }, content: [], zones: {} },
          filters: [],
          queries: {},
          chartSpecs: {},
          gridSpecs: {},
          datasets: { channel_sales: { rows: [{ channel: "direct", salesAmount: 1000 }] } },
          source: {
            threadId: "thread_analysis_report",
            turnId: "turn_analysis_report",
          },
        },
      },
    ], "start"));

    expect(events).toEqual([expect.objectContaining({
      type: "report-artifact",
      report: expect.objectContaining({
        id: "report_turn_analysis_report",
        title: "channel sales analysis",
        datasets: { channel_sales: { rows: [{ channel: "direct", salesAmount: 1000 }] } },
      }),
      turnId: "turn_analysis_report",
      threadId: "thread_analysis_report",
    })]);
  });

  test("requires an explicit sessionId on continuation messages", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        session_id: "thread_analysis_456",
        turn_id: "turn_analysis_123",
        events: [
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
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        session_id: "thread_analysis_456",
        turn_id: "turn_analysis_789",
        events: [
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
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
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
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/analysis/sessions/turns");
    // Every continuation must carry the Codex session id in the URL;
    // the body never re-asserts the id.
    expect(fetchMock.mock.calls[1][0]).toBe("http://backend.test/api/analysis/sessions/thread_analysis_456/turns");
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
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      session_id: "thread_existing",
      turn_id: "turn_existing",
      events: [
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
      ],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "message", content: "follow up", sessionId: "thread_existing" }));

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions/thread_existing/turns");
  });

  test("starts the first turn inside an existing session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      session_id: "thread_waiting",
      turn_id: "turn_waiting_first",
      events: [
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
      ],
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "start", question: "first question", sessionId: "thread_waiting" }));

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions/thread_waiting/turns");
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
      .mockResolvedValueOnce(new Response(JSON.stringify({
        session_id: "codex_thread_session",
        turn_id: "turn_first",
        events: [
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
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        session_id: "codex_thread_session",
        turn_id: "turn_second",
        events: [
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
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    const firstEvents = await collect(client.send({ kind: "start", question: "first", sessionId: null }));
    const sessionId = (firstEvents.find((e) => e.type === "session/created") as { sessionId: string } | undefined)?.sessionId;
    expect(sessionId).toBe("codex_thread_session");
    // The second turn passes the explicit session id — there is no
    // implicit memory of the previous turn.
    await collect(client.send({ kind: "message", content: "second", sessionId: sessionId! }));

    expect(fetchMock.mock.calls[1][0]).toBe(
      "http://backend.test/api/analysis/sessions/codex_thread_session/turns",
    );
  });

  test("never leaks the previous session id into the next request (A → B → send)", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        session_id: "codex_thread_a",
        turn_id: "turn_a",
        events: [
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
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        session_id: "codex_thread_b",
        turn_id: "turn_b",
        events: [
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
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        session_id: "codex_thread_b",
        turn_id: "turn_b_2",
        events: [
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
        ],
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
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
    expect(urlA).toBe("http://backend.test/api/analysis/sessions/turns");
    expect(urlB).toBe("http://backend.test/api/analysis/sessions/turns");
    // The third request must hit B's session-scoped endpoint and never
    // mention A anywhere on the wire.
    expect(urlBCont).toBe("http://backend.test/api/analysis/sessions/codex_thread_b/turns");
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
    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions");
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
            details: ["SELECT 1", "SELECT 2"],
          },
        ],
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
      detail: "SELECT 1 AS one",
      itemId: undefined,
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

