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
            type: "run.created",
            run_id: "run_analysis_123",
            created_at: "2026-07-30T00:00:00Z",
            payload: {
              conversation_id: "conv_analysis_456",
              question: "首购后 30 天复购率怎么定义？",
            },
          },
        ],
        "start",
      ),
    );

    expect(events[0]).toMatchObject({
      type: "conversation-init",
      runId: "run_analysis_123",
      conversationId: "conv_analysis_456",
    });
    expect(events[1]).toMatchObject({
      type: "user",
      nodeId: "user-run_analysis_123",
      content: "首购后 30 天复购率怎么定义？",
    });
  });

  test("parses analysis SSE data blocks", () => {
    const events = parseAnalysisSse(
      sseEvent({
        type: "run.created",
        run_id: "run_analysis_sse",
        payload: { conversation_id: "conv_analysis_sse", question: "stream question" },
      }),
    );

    expect(events).toEqual([
      {
        type: "run.created",
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
            type: "run.created",
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
      runId: "run_analysis_789",
      conversationId: "conv_analysis_456",
    });
    expect(events[1]).toMatchObject({
      type: "user",
      nodeId: "user-run_analysis_789",
      content: "continue question",
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
              delta: "你好，",
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
              content: "你好，完整回复。",
            },
          },
        ],
        "message",
      ),
    );

    expect(events).toEqual([
      {
        type: "tokens",
        nodeId: "agent-run_analysis_stream",
        text: "你好，",
        runId: "run_analysis_stream",
        threadId: "conv_analysis_stream",
        turnId: "turn_analysis_stream",
      },
      {
        type: "agent",
        nodeId: "agent-run_analysis_stream",
        content: "你好，完整回复。",
        mode: "replace",
        runId: "run_analysis_stream",
        threadId: "conv_analysis_stream",
        turnId: "turn_analysis_stream",
      },
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
          title: "渠道销售分析",
          subtitle: "待数据查询验证",
          renderer: "puck",
          document: { root: { props: {} }, content: [], zones: {} },
          filters: [], queries: {}, chartSpecs: {}, gridSpecs: {},
          source: { threadId: "conv_analysis_report", turnId: "turn_analysis_report", runId: "run_analysis_report" },
        },
      },
    ], "start"));

    expect(events).toEqual([expect.objectContaining({
      type: "report-draft",
      report: expect.objectContaining({ id: "report_draft_run_analysis_report", title: "渠道销售分析" }),
      runId: "run_analysis_report",
      threadId: "conv_analysis_report",
    })]);
  });

  test("sends the stored conversation id on continuation messages", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(
        sseEvent({
              type: "run.created",
              run_id: "run_analysis_123",
              payload: { conversation_id: "conv_analysis_456", question: "start question" },
            }) +
          sseEvent({
              type: "run.completed",
              run_id: "run_analysis_123",
              created_at: "2026-07-30T00:00:01Z",
              payload: {},
            }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ))
      .mockResolvedValueOnce(new Response(
        sseEvent({
              type: "run.created",
              run_id: "run_analysis_789",
              created_at: "2026-07-30T00:01:00Z",
              payload: { conversation_id: "conv_analysis_456", question: "continue question" },
            }) +
          sseEvent({
              type: "run.completed",
              run_id: "run_analysis_789",
              created_at: "2026-07-30T00:01:01Z",
              payload: {},
            }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "start", question: "start question", analysisMode: "quick", dataEgressAuthorized: true, interactiveReport: mockInteractiveReport }));
    const messageEvents = await collect(client.send({ kind: "message", content: "continue question", analysisMode: "quick" }));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const startBody = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    const messageBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(fetchMock.mock.calls[0][0]).toBe("http://backend.test/api/analysis/tasks/runs/stream");
    expect(startBody.conversation_id).toBeUndefined();
    expect(startBody.metadata).toMatchObject({
      frontend_client: "analysis_task",
      data_egress_authorized: true,
      semantic_context_egress_authorized: true,
    });
    expect(startBody.metadata.interactive_report_context).toEqual(mockInteractiveReport);
    expect(messageBody.conversation_id).toBe("conv_analysis_456");
    expect(messageBody.metadata.data_egress_authorized).toBeUndefined();
    expect(messageBody.metadata.semantic_context_egress_authorized).toBeUndefined();
    expect(messageBody.turn_kind).toBe("message");
    expect(messageEvents[0]).toMatchObject({
      type: "run-init",
      runId: "run_analysis_789",
      conversationId: "conv_analysis_456",
    });
  });

  test("sends reply turns with stored conversation id and current analysis mode", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(
        sseEvent({
              type: "run.created",
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
              type: "run.created",
              run_id: "run_analysis_deep_reply",
              created_at: "2026-07-30T00:01:00Z",
              payload: { conversation_id: "conv_analysis_deep", question: "member_id" },
            }) +
          sseEvent({
              type: "run.completed",
              run_id: "run_analysis_deep_reply",
              created_at: "2026-07-30T00:01:01Z",
              payload: {},
            }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(client.send({ kind: "start", question: "define metric", analysisMode: "deep" }));
    const replyEvents = await collect(client.send({ kind: "reply", optionId: "member_id", analysisMode: "deep" }));

    const replyBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(replyBody.conversation_id).toBe("conv_analysis_deep");
    expect(replyBody.turn_kind).toBe("reply");
    expect(replyBody.analysis_mode).toBe("deep");
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
    const eventsPromise = collect(client.send({ kind: "start", question: "slow question", analysisMode: "deep" }));
    await vi.advanceTimersByTimeAsync(25);
    const events = await eventsPromise;

    expect(events).toEqual([
      {
        type: "error",
        message: "Analysis backend request timed out. Please retry or switch to quick analysis.",
      },
      { type: "done" },
    ]);
  });
});
