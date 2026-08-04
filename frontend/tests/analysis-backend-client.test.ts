import { afterEach, describe, expect, test, vi } from "vitest";
import {
  BackendAnalysisAgentClient,
  deleteBackendAnalysisThread,
  flowNodesFromBackendThread,
  getBackendAnalysisRequestTimeoutMs,
  listBackendAnalysisThreads,
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
      .mockResolvedValueOnce(new Response(
        sseEvent({
          type: "session/created",
          turn_id: "turn_analysis_123",
          payload: {
            sessionId: "thread_analysis_456",
            codexThreadId: "thread_analysis_456",
            codexTurnId: "turn_analysis_123",
          },
        }) + sseEvent({
          type: "turn/started",
          turn_id: "turn_analysis_123",
          payload: { conversation_id: "thread_analysis_456", question: "start question" },
        }) + sseEvent({
          type: "turn/completed",
          turn_id: "turn_analysis_123",
          created_at: "2026-07-30T00:00:01Z",
          payload: {},
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ))
      .mockResolvedValueOnce(new Response(
        sseEvent({
          type: "turn/started",
          turn_id: "turn_analysis_789",
          created_at: "2026-07-30T00:01:00Z",
          payload: { conversation_id: "thread_analysis_456", question: "continue question" },
        }) + sseEvent({
          type: "turn/completed",
          turn_id: "turn_analysis_789",
          created_at: "2026-07-30T00:01:01Z",
          payload: {},
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ));
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
    // Every continuation must carry the Codex session id in the URL and
    // in the body — no client-side memory, no agent-side memory.
    expect(fetchMock.mock.calls[1][0]).toBe("http://backend.test/api/analysis/sessions/thread_analysis_456/turns/stream");
    expect(startBody.message).toBe("start question");
    expect(startBody.question).toBeUndefined();
    expect(startBody.metadata).toMatchObject({ frontend_client: "analysis_task" });
    expect(messageBody.sessionId).toBe("thread_analysis_456");
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
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      sseEvent({
        type: "turn/started",
        turn_id: "turn_existing",
        payload: { conversation_id: "thread_existing", question: "follow up" },
      }) + sseEvent({
        type: "turn/completed",
        turn_id: "turn_existing",
        payload: {},
      }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    )));

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "message", content: "follow up", sessionId: "thread_existing" }));

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions/thread_existing/turns/stream");
  });

  test("starts the first turn inside an existing session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      sseEvent({
        type: "turn/started",
        turn_id: "turn_waiting_first",
        payload: { conversation_id: "thread_waiting", question: "first question" },
      }) + sseEvent({
        type: "turn/completed",
        turn_id: "turn_waiting_first",
        payload: {},
      }),
      { status: 200, headers: { "Content-Type": "text/event-stream" } },
    )));

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "start", question: "first question", sessionId: "thread_waiting" }));

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/sessions/thread_waiting/turns/stream");
  });

  test("never leaks the previous session id into the next request (A → B → send)", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(
        // Open session A via the sessionless entry point.
        sseEvent({
          type: "session/created",
          turn_id: "turn_a",
          payload: {
            sessionId: "codex_thread_a",
            codexThreadId: "codex_thread_a",
            codexTurnId: "turn_a",
          },
        }) + sseEvent({
          type: "turn/started",
          turn_id: "turn_a",
          payload: { conversation_id: "codex_thread_a", question: "open A" },
        }) + sseEvent({
          type: "turn/completed",
          turn_id: "turn_a",
          payload: {},
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ))
      .mockResolvedValueOnce(new Response(
        // Open session B via the sessionless entry point. The page
        // router swapped to B; we pass ``sessionId: null``.
        sseEvent({
          type: "session/created",
          turn_id: "turn_b",
          payload: {
            sessionId: "codex_thread_b",
            codexThreadId: "codex_thread_b",
            codexTurnId: "turn_b",
          },
        }) + sseEvent({
          type: "turn/started",
          turn_id: "turn_b",
          payload: { conversation_id: "codex_thread_b", question: "open B" },
        }) + sseEvent({
          type: "turn/completed",
          turn_id: "turn_b",
          payload: {},
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ))
      .mockResolvedValueOnce(new Response(
        // Continuation turn on B. The caller is responsible for
        // passing B's id explicitly. A's id must NOT appear in the
        // request body or the URL.
        sseEvent({
          type: "turn/started",
          turn_id: "turn_b_2",
          payload: { conversation_id: "codex_thread_b", question: "continue on B" },
        }) + sseEvent({
          type: "turn/completed",
          turn_id: "turn_b_2",
          payload: {},
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ));
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
    expect(bodyBCont).toContain("codex_thread_b");
  });

  test("loads backend analysis threads for the real sidebar", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      threads: [{ id: "thread_real", latestQuestion: "real question", updatedAt: "2026-08-03T10:00:00Z" }],
    }), { status: 200 })));

    await expect(listBackendAnalysisThreads()).resolves.toEqual([
      { id: "thread_real", latestQuestion: "real question", updatedAt: "2026-08-03T10:00:00Z" },
    ]);
    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/threads");
  });

  test("deletes backend analysis threads for sidebar bulk delete", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ deleted: true }), { status: 200 })));

    await expect(deleteBackendAnalysisThread("thread_delete")).resolves.toBeUndefined();

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/threads/thread_delete");
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({ method: "DELETE" });
  });

  test("hydrates a backend thread into user, assistant, and grouped tool nodes", () => {
    const nodes = flowNodesFromBackendThread({
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

  test("refreshes the backend request timeout when SSE events arrive", async () => {
    vi.useFakeTimers();
    process.env.NEXT_PUBLIC_ANALYSIS_AGENT_TIMEOUT_MS = "50";
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(
          'event: item/agentMessage/delta\ndata: {"type":"item/agentMessage/delta","turn_id":"turn_1","payload":{"turn_id":"turn_1","delta":"hello"}}\n\n',
        ));
        globalThis.setTimeout(() => {
          controller.enqueue(new TextEncoder().encode(
            'event: turn/completed\ndata: {"type":"turn/completed","turn_id":"turn_1","payload":{"turn_id":"turn_1","status":"completed"}}\n\n',
          ));
          controller.close();
        }, 40);
      },
    });
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(stream, { status: 200 }))));

    const client = new BackendAnalysisAgentClient("http://backend.test");
    const eventsPromise = collect(client.send({ kind: "start", question: "slow but active", sessionId: null }));
    await vi.advanceTimersByTimeAsync(40);
    const events = await eventsPromise;

    expect(events.filter((event) => event.type === "tokens").map((event) => event.text).join("")).toBe("hello");
    expect(events.at(-1)).toEqual(expect.objectContaining({ type: "done" }));
    expect(events.some((event) => event.type === "error")).toBe(false);
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

