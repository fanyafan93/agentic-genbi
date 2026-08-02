import { afterEach, describe, expect, test, vi } from "vitest";
import { BackendAnalysisAgentClient, getBackendAnalysisRequestTimeoutMs, mapBackendEvents, parseAnalysisSse } from "../src/modules/analysis/agentClients/backendClient";
import { mockInteractiveReport } from "../src/modules/analysis/mocks/interactive-report";

async function collect<T>(items: AsyncIterable<T>): Promise<T[]> {
  const collected: T[] = [];
  for await (const item of items) collected.push(item);
  return collected;
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete process.env.NEXT_PUBLIC_ANALYSIS_AGENT_TIMEOUT_MS;
});

function sseEvent(event: { type: string; run_id: string; created_at?: string; payload?: Record<string, unknown> }) {
  const payload = {
    created_at: event.created_at ?? "2026-07-30T00:00:00Z",
    payload: event.payload ?? {},
    ...event,
  };
  return `event: ${event.type}\ndata: ${JSON.stringify(payload)}\n\n`;
}

describe("analysis backend client event mapping", () => {
  test("preserves backend conversation id on new analysis runs", () => {
    const events = Array.from(
      mapBackendEvents(
        [
          {
            type: "turn/started",
            run_id: "run_analysis_123",
            created_at: "2026-07-30T00:00:00Z",
            payload: {
              conversation_id: "conv_analysis_456",
              question: "first purchase 30d repurchase definition",
            },
          },
        ],
        "start",
      ),
    );

    expect(events[0]).toMatchObject({
      type: "conversation-init",
      executionAttemptId: "run_analysis_123",
      runId: "run_analysis_123",
      conversationId: "conv_analysis_456",
    });
    expect(events[1]).toMatchObject({
      type: "user",
      nodeId: "user-run_analysis_123",
      content: "first purchase 30d repurchase definition",
    });
  });

  test("parses analysis SSE data blocks", () => {
    const events = parseAnalysisSse(
      sseEvent({
        type: "turn/started",
        run_id: "run_analysis_sse",
        payload: { conversation_id: "conv_analysis_sse", question: "stream question" },
      }),
    );

    expect(events).toEqual([
      {
        type: "turn/started",
        run_id: "run_analysis_sse",
        created_at: "2026-07-30T00:00:00Z",
        payload: { conversation_id: "conv_analysis_sse", question: "stream question" },
      },
    ]);
  });

  test("maps continuation runs without clearing the existing conversation", () => {
    const events = Array.from(
      mapBackendEvents(
        [
          {
            type: "turn/started",
            run_id: "run_analysis_789",
            created_at: "2026-07-30T00:01:00Z",
            payload: {
              conversation_id: "conv_analysis_456",
              question: "continue question",
            },
          },
        ],
        "message",
      ),
    );

    expect(events[0]).toMatchObject({
      type: "run-init",
      executionAttemptId: "run_analysis_789",
      runId: "run_analysis_789",
      conversationId: "conv_analysis_456",
    });
    expect(events[1]).toMatchObject({
      type: "user",
      nodeId: "user-run_analysis_789",
      content: "continue question",
    });
  });

  test("maps codex-style turn events before compatibility run events", () => {
    const events = Array.from(
      mapBackendEvents(
        [
          {
            type: "turn/started",
            run_id: "run_analysis_turn",
            created_at: "2026-07-30T00:01:00Z",
            payload: {
              conversation_id: "conv_analysis_turn",
              question: "continue question",
              codex_method: "turn/started",
            },
          },
          {
            type: "turn/completed",
            run_id: "run_analysis_turn",
            created_at: "2026-07-30T00:01:01Z",
            payload: {
              status: "completed",
              codex_method: "turn/completed",
            },
          },
        ],
        "message",
      ),
    );

    expect(events.map((event) => event.type)).toEqual(["run-init", "user", "done"]);
    expect(events[0]).toMatchObject({
      executionAttemptId: "run_analysis_turn",
      runId: "run_analysis_turn",
      conversationId: "conv_analysis_turn",
    });
  });

  test("maps streamed assistant deltas to token events on the final agent node", () => {
    const events = Array.from(
      mapBackendEvents(
        [
          {
            type: "agent.message.delta",
            run_id: "run_analysis_stream",
            created_at: "2026-07-30T00:01:00Z",
            payload: {
              run_id: "run_analysis_stream",
              thread_id: "conv_analysis_stream",
              turn_id: "turn_analysis_stream",
              codex_thread_id: "codex_thread_stream",
              codex_turn_id: "codex_turn_stream",
              codex_item_id: "codex_item_message",
              delta: "hello, ",
            },
          },
          {
            type: "agent.message.created",
            run_id: "run_analysis_stream",
            created_at: "2026-07-30T00:01:01Z",
            payload: {
              run_id: "run_analysis_stream",
              thread_id: "conv_analysis_stream",
              turn_id: "turn_analysis_stream",
              codex_thread_id: "codex_thread_stream",
              codex_turn_id: "codex_turn_stream",
              codex_item_id: "codex_item_message",
              content: "hello, complete reply.",
            },
          },
        ],
        "message",
      ),
    );

    expect(events).toMatchObject([
      {
        type: "debug",
        nodeId: "agent-run_analysis_stream",
        title: "模型流式片段",
        content: "hello, ",
        runId: "run_analysis_stream",
        threadId: "conv_analysis_stream",
        turnId: "turn_analysis_stream",
      },
      {
        type: "tokens",
        nodeId: "agent-run_analysis_stream",
        text: "hello, ",
        runId: "run_analysis_stream",
        threadId: "conv_analysis_stream",
        turnId: "turn_analysis_stream",
      },
      {
        type: "debug",
        nodeId: "agent-run_analysis_stream",
        title: "模型最终返回",
        content: "hello, complete reply.",
        runId: "run_analysis_stream",
        threadId: "conv_analysis_stream",
        turnId: "turn_analysis_stream",
      },
      {
        type: "agent",
        nodeId: "agent-run_analysis_stream",
        content: "hello, complete reply.",
        mode: "replace",
        runId: "run_analysis_stream",
        threadId: "conv_analysis_stream",
        turnId: "turn_analysis_stream",
      },
    ]);
    expect(events[0]).toMatchObject({
      codexThreadId: "codex_thread_stream",
      codexTurnId: "codex_turn_stream",
      codexItemId: "codex_item_message",
    });
  });

  test("maps native item events before compatibility message events", () => {
    const events = Array.from(
      mapBackendEvents(
        [
          {
            type: "item/agentMessage/delta",
            run_id: "run_analysis_item_stream",
            created_at: "2026-07-30T00:01:00Z",
            payload: {
              compatibility_source_event: "agent.message.delta",
              codex_method: "item/agentMessage/delta",
              codex_item_type: "agentMessage",
              codex_item_id: "item_agent_message",
              delta: "hello, ",
            },
          },
          {
            type: "agent.message.delta",
            run_id: "run_analysis_item_stream",
            created_at: "2026-07-30T00:01:00Z",
            payload: { delta: "hello, " },
          },
          {
            type: "item/completed",
            run_id: "run_analysis_item_stream",
            created_at: "2026-07-30T00:01:01Z",
            payload: {
              compatibility_source_event: "agent.message.created",
              codex_method: "item/completed",
              codex_item_type: "agentMessage",
              codex_item_id: "item_agent_message",
              content: "hello, complete reply.",
            },
          },
          {
            type: "agent.message.created",
            run_id: "run_analysis_item_stream",
            created_at: "2026-07-30T00:01:01Z",
            payload: { content: "hello, complete reply." },
          },
        ],
        "message",
      ),
    );

    expect(events.map((event) => event.type)).toEqual(["debug", "tokens", "debug", "agent"]);
    expect(events[0]).toMatchObject({ codexItemId: "item_agent_message", content: "hello, " });
    expect(events[3]).toMatchObject({ content: "hello, complete reply." });
  });

  test("shows retrieval plans as debug context instead of completed fake steps", () => {
    const events = Array.from(
      mapBackendEvents(
        [
          {
            type: "analysis.retrieval.plan",
            run_id: "run_analysis_plan",
            created_at: "2026-07-30T00:01:00Z",
            payload: {
              items: [
                { id: "semantic_sql_examples", label: "SQL example semantic model", source: "historical SQL" },
              ],
            },
          },
        ],
        "message",
      ),
    );

    expect(events).toEqual([
      {
        type: "debug",
        nodeId: "agent-run_analysis_plan",
        title: "候选上下文计划（未执行工具）",
        content: JSON.stringify([{ id: "semantic_sql_examples", label: "SQL example semantic model", source: "historical SQL" }], null, 2),
        executionAttemptId: "run_analysis_plan",
        runId: "run_analysis_plan",
        threadId: undefined,
        turnId: "run_analysis_plan",
        itemId: undefined,
        codexThreadId: undefined,
        codexTurnId: undefined,
        codexItemId: undefined,
      },
    ]);
  });

  test("maps prompt and real tool events for debugging", () => {
    const events = Array.from(
      mapBackendEvents(
        [
          {
            type: "agent.prompt.created",
            run_id: "run_analysis_debug",
            created_at: "2026-07-30T00:01:00Z",
            payload: { prompt: "user question: channel sales share" },
          },
          {
            type: "tool.call.started",
            run_id: "run_analysis_debug",
            created_at: "2026-07-30T00:01:01Z",
            payload: { tool: "query_report", queryRef: "channel-sales" },
          },
          {
            type: "tool.call.completed",
            run_id: "run_analysis_debug",
            created_at: "2026-07-30T00:01:02Z",
            payload: { tool: "query_report", rowCount: 12 },
          },
        ],
        "message",
      ),
    );

    expect(events).toEqual([
      expect.objectContaining({ type: "debug", title: "发送给模型的 prompt", content: "user question: channel sales share" }),
      expect.objectContaining({ type: "step", label: "工具调用：query_report", state: "running" }),
      expect.objectContaining({ type: "debug", title: "工具事件：tool.call.started" }),
      expect.objectContaining({ type: "step", label: "工具调用：query_report", state: "done" }),
      expect.objectContaining({ type: "debug", title: "工具事件：tool.call.completed" }),
    ]);
  });

  test("maps native tool item events before compatibility tool events", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "item/started",
        run_id: "run_tool_item",
        created_at: "2026-07-30T00:01:00Z",
        payload: {
          compatibility_source_event: "tool.call.started",
          codex_method: "item/started",
          codex_item_type: "toolCall",
          tool: "query_report",
        },
      },
      {
        type: "tool.call.started",
        run_id: "run_tool_item",
        created_at: "2026-07-30T00:01:00Z",
        payload: { tool: "query_report" },
      },
      {
        type: "item/completed",
        run_id: "run_tool_item",
        created_at: "2026-07-30T00:01:01Z",
        payload: {
          compatibility_source_event: "tool.call.completed",
          codex_method: "item/completed",
          codex_item_type: "toolResult",
          tool: "query_report",
          rowCount: 12,
        },
      },
      {
        type: "tool.call.completed",
        run_id: "run_tool_item",
        created_at: "2026-07-30T00:01:01Z",
        payload: { tool: "query_report", rowCount: 12 },
      },
    ], "message"));

    expect(events).toEqual([
      expect.objectContaining({ type: "step", label: "工具调用：query_report", state: "running" }),
      expect.objectContaining({ type: "debug", title: "工具事件：tool.call.started" }),
      expect.objectContaining({ type: "step", label: "工具调用：query_report", state: "done" }),
      expect.objectContaining({ type: "debug", title: "工具事件：tool.call.completed" }),
    ]);
  });

  test("maps a validated interactive report draft as a dedicated result event", () => {
    const events = Array.from(mapBackendEvents([
      {
        type: "interactive_report.draft",
        run_id: "run_analysis_report",
        created_at: "2026-08-01T00:00:00Z",
        payload: {
          artifactType: "interactive_report",
          schemaVersion: "1.0",
          id: "report_draft_run_analysis_report",
          title: "channel sales analysis",
          subtitle: "pending query validation",
          renderer: "puck",
          document: { root: { props: {} }, content: [], zones: {} },
          filters: [], queries: {}, chartSpecs: {}, gridSpecs: {},
          source: {
            threadId: "conv_analysis_report",
            turnId: "turn_analysis_report",
            executionAttemptId: "run_analysis_report",
            runId: "run_analysis_report",
          },
        },
      },
    ], "start"));

    expect(events).toEqual([expect.objectContaining({
      type: "report-draft",
      report: expect.objectContaining({ id: "report_draft_run_analysis_report", title: "channel sales analysis" }),
      runId: "run_analysis_report",
      threadId: "conv_analysis_report",
    })]);
  });

  test("maps native genbi artifact events before compatibility artifact events", () => {
    const reportPayload = {
      compatibility_source_event: "interactive_report.draft",
      artifactType: "interactive_report",
      schemaVersion: "1.0",
      id: "report_draft_run_analysis_report",
      title: "channel sales analysis",
      subtitle: "pending query validation",
      renderer: "puck",
      document: { root: { props: {} }, content: [], zones: {} },
      filters: [], queries: {}, chartSpecs: {}, gridSpecs: {},
      source: {
        threadId: "conv_analysis_report",
        turnId: "turn_analysis_report",
        executionAttemptId: "run_analysis_report",
        runId: "run_analysis_report",
      },
    };
    const events = Array.from(mapBackendEvents([
      {
        type: "genbi/artifact/updated",
        run_id: "run_analysis_report",
        created_at: "2026-08-01T00:00:00Z",
        payload: reportPayload,
      },
      {
        type: "interactive_report.draft",
        run_id: "run_analysis_report",
        created_at: "2026-08-01T00:00:00Z",
        payload: { ...reportPayload, compatibility_source_event: undefined },
      },
      {
        type: "genbi/artifact/created",
        run_id: "run_analysis_report",
        created_at: "2026-08-01T00:00:01Z",
        payload: { compatibility_source_event: "artifact.created", path: "queries/candidate.sql", kind: "sql" },
      },
      {
        type: "artifact.created",
        run_id: "run_analysis_report",
        created_at: "2026-08-01T00:00:01Z",
        payload: { path: "queries/candidate.sql", kind: "sql" },
      },
    ], "start"));

    expect(events).toEqual([
      expect.objectContaining({ type: "report-draft" }),
      expect.objectContaining({ type: "artifact", path: "queries/candidate.sql", kind: "sql" }),
    ]);
  });

  test("sends the stored conversation id on continuation messages", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(
        sseEvent({
              type: "turn/started",
              run_id: "run_analysis_123",
              payload: { conversation_id: "conv_analysis_456", question: "start question" },
            }) +
          sseEvent({
              type: "turn/completed",
              run_id: "run_analysis_123",
              created_at: "2026-07-30T00:00:01Z",
              payload: {},
            }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ))
      .mockResolvedValueOnce(new Response(
        sseEvent({
              type: "turn/started",
              run_id: "run_analysis_789",
              created_at: "2026-07-30T00:01:00Z",
              payload: { conversation_id: "conv_analysis_456", question: "continue question" },
            }) +
          sseEvent({
              type: "turn/completed",
              run_id: "run_analysis_789",
              created_at: "2026-07-30T00:01:01Z",
              payload: {},
            }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "start", question: "start question", interactiveReport: mockInteractiveReport }));
    const messageEvents = await collect(client.send({ kind: "message", content: "continue question" }));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const startBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    const messageBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/analysis/threads/turns/stream");
    expect(fetchMock.mock.calls[1][0]).toBe("http://backend.test/api/analysis/threads/conv_analysis_456/turns/stream");
    expect(startBody.conversation_id).toBeUndefined();
    expect(startBody.metadata).toMatchObject({
      frontend_client: "analysis_task",
    });
    expect(startBody.metadata.interactive_report_context).toEqual(mockInteractiveReport);
    expect(startBody.analysis_mode).toBeUndefined();
    expect(startBody.metadata.data_egress_authorized).toBeUndefined();
    expect(startBody.metadata.semantic_context_egress_authorized).toBeUndefined();
    expect(messageBody.conversation_id).toBeUndefined();
    expect(messageBody.metadata.data_egress_authorized).toBeUndefined();
    expect(messageBody.metadata.semantic_context_egress_authorized).toBeUndefined();
    expect(messageBody.turn_kind).toBe("message");
    expect(messageEvents[0]).toMatchObject({
      type: "run-init",
      runId: "run_analysis_789",
      conversationId: "conv_analysis_456",
    });
  });

  test("sends reply turns with stored conversation id", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(
        sseEvent({
              type: "turn/started",
              run_id: "run_analysis_deep_start",
              payload: { conversation_id: "conv_analysis_deep", question: "define metric" },
            }) +
          sseEvent({
              type: "agent.question.requested",
              run_id: "run_analysis_deep_start",
              created_at: "2026-07-30T00:00:01Z",
              payload: { question: "choose grain", options: [{ id: "member_id", label: "member id" }] },
            }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ))
      .mockResolvedValueOnce(new Response(
        sseEvent({
              type: "turn/started",
              run_id: "run_analysis_deep_reply",
              created_at: "2026-07-30T00:01:00Z",
              payload: { conversation_id: "conv_analysis_deep", question: "member_id" },
            }) +
          sseEvent({
              type: "turn/completed",
              run_id: "run_analysis_deep_reply",
              created_at: "2026-07-30T00:01:01Z",
              payload: {},
            }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "start", question: "define metric" }));
    const replyEvents = await collect(client.send({ kind: "reply", optionId: "member_id" }));

    const replyBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(fetchMock.mock.calls[1][0]).toBe("http://backend.test/api/analysis/threads/conv_analysis_deep/turns/stream");
    expect(replyBody.conversation_id).toBeUndefined();
    expect(replyBody.turn_kind).toBe("reply");
    expect(replyBody.analysis_mode).toBeUndefined();
    expect(replyEvents[0]).toMatchObject({
      type: "run-init",
      runId: "run_analysis_deep_reply",
      conversationId: "conv_analysis_deep",
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
      {
        type: "error",
        message: "Analysis backend request timed out. Please retry.",
      },
      { type: "done" },
    ]);
  });
});

