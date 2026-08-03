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
        label: "工具调用：BI_doris / read_mcp_resource",
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

  test("sends the stored thread id on continuation messages", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(
        sseEvent({
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
    await collect(client.send({ kind: "start", question: "start question" }));
    const messageEvents = await collect(client.send({ kind: "message", content: "continue question" }));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const startBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    const messageBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/analysis/threads/turns/stream");
    expect(fetchMock.mock.calls[1][0]).toBe("http://backend.test/api/analysis/threads/thread_analysis_456/turns/stream");
    expect(startBody.conversation_id).toBeUndefined();
    expect(startBody.metadata).toMatchObject({ frontend_client: "analysis_task" });
    expect(startBody.metadata).toEqual({ frontend_client: "analysis_task" });
    expect(messageBody.conversation_id).toBeUndefined();
    expect(messageBody.turn_kind).toBe("message");
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
    expect(getBackendAnalysisRequestTimeoutMs()).toBe(95_000);
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
    const eventsPromise = collect(client.send({ kind: "start", question: "slow question" }));
    await vi.advanceTimersByTimeAsync(25);
    const events = await eventsPromise;

    expect(events).toEqual([
      { type: "error", message: "Analysis backend request timed out. Please retry." },
      { type: "done" },
    ]);
  });

  test("can send a continuation message to an already opened backend thread", async () => {
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
    await collect(client.send({ kind: "message", content: "follow up", threadId: "thread_existing" }));

    expect(fetchMockUrl()).toBe("http://backend.test/api/analysis/threads/thread_existing/turns/stream");
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
            label: "工具调用：BI_doris / mysql_query",
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
    const eventsPromise = collect(client.send({ kind: "start", question: "slow but active" }));
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
      label: "工具调用：BI_doris / mysql_query",
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

