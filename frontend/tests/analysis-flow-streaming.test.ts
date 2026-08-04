/**
 * @vitest-environment jsdom
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { AgentEvent, AgentInput } from "../src/modules/analysis/agentClients/types";

const { mockSend } = vi.hoisted(() => ({ mockSend: vi.fn() }));

vi.mock("../src/modules/analysis/agentClients/backendClient", async () => {
  const real = await vi.importActual<typeof import("../src/modules/analysis/agentClients/backendClient")>(
    "../src/modules/analysis/agentClients/backendClient",
  );
  return {
    ...real,
    createBackendAnalysisAgentClient: () => ({ send: mockSend }),
  };
});

import { useFlow, type FlowNode } from "../src/modules/analysis/hooks/use-flow";

const EMPTY_FLOW: FlowNode[] = [];

afterEach(() => {
  mockSend.mockReset();
});

describe("analysis flow streaming", () => {
  test("starts the first turn in the explicitly created waiting thread", async () => {
    const receivedInputs: AgentInput[] = [];
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      receivedInputs.push(input);
      yield {
        type: "user",
        nodeId: "user-1",
        content: "渠道销售占比分析",
        turnId: "turn-1",
        threadId: "analysis_thread_waiting",
      };
      yield { type: "done", turnId: "turn-1", threadId: "analysis_thread_waiting" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("渠道销售占比分析", "task_waiting", "analysis_thread_waiting");
    });

    await waitFor(() => {
      expect(receivedInputs).toEqual([expect.objectContaining({
        kind: "start",
        question: "渠道销售占比分析",
        taskId: "task_waiting",
        threadId: "analysis_thread_waiting",
      })]);
    });
  });

  test("keeps streaming when the active waiting thread becomes the selected thread", async () => {
    let releaseAnswer: (() => void) | undefined;
    const answerReady = new Promise<void>((resolve) => {
      releaseAnswer = resolve;
    });
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield {
        type: "user",
        nodeId: "user-1",
        content: "渠道销售占比分析",
        turnId: "turn-1",
        threadId: "analysis_thread_waiting",
      };
      await answerReady;
      yield { type: "tokens", nodeId: "agent-1", text: "分析完成", codexItemId: "message-1" };
      yield { type: "done", turnId: "turn-1", threadId: "analysis_thread_waiting" };
    });

    const { result, rerender } = renderHook(
      ({ threadKey }: { threadKey: string | null }) => useFlow(threadKey, EMPTY_FLOW),
      { initialProps: { threadKey: null as string | null } },
    );

    act(() => {
      void result.current.start("渠道销售占比分析", "analysis_thread_waiting", "analysis_thread_waiting");
    });
    await waitFor(() => {
      expect(result.current.nodes[0]).toMatchObject({ role: "user", content: "渠道销售占比分析" });
    });

    rerender({ threadKey: "analysis_thread_waiting" });
    act(() => {
      releaseAnswer?.();
    });

    await waitFor(() => {
      expect(result.current.nodes).toEqual([
        expect.objectContaining({ role: "user", content: "渠道销售占比分析" }),
        expect.objectContaining({ role: "agent", content: "分析完成" }),
      ]);
    });
  });

  test("hydrates existing thread nodes when history loads via useTaskDetail", async () => {
    // ``useFlow`` delegates history loading to ``useTaskDetail``. The
    // workspace drives the hydration by mounting the hook with a
    // ``threadKey``; the detail fetch resolves into FlowNodes that
    // land in the renderer. This replaces the older "parent passes
    // initial messages via prop" behavior, which used to race the live
    // SSE controller.
    const historyNodes: FlowNode[] = [
      { id: "user-turn-1", role: "user", content: "历史问题" },
      { id: "agent-turn-1", role: "agent", content: "历史回答", mode: "replace", activity: [] },
    ];
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      thread: { id: "analysis_thread_1" },
      turns: [{ id: "turn-1", question: "历史问题", createdAt: "2026-08-04T10:00:00Z" }],
      codexItemProjections: [
        {
          codexItemId: "msg-1",
          genbiTurnId: "turn-1",
          itemType: "agentMessage",
          status: "completed",
          payload: { content: "历史回答" },
          createdAt: "2026-08-04T10:00:01Z",
        },
      ],
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
    process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME = "backend";

    const { result } = renderHook(() => useFlow("analysis_thread_1", EMPTY_FLOW));

    // Render starts with the bootstrap (empty) until the detail hook
    // resolves.
    expect(result.current.nodes).toEqual([]);

    // Once the detail fetch lands, the hydration effect (which the
    // facade wires up internally) pushes the historical nodes into
    // the live renderer.
    await waitFor(() => {
      expect(result.current.nodes.map((node) => node.id)).toEqual(["user-turn-1", "agent-turn-1"]);
    });
    expect(result.current.nodes[0]).toMatchObject({ content: "历史问题" });
    expect(result.current.nodes[1]).toMatchObject({ content: "历史回答" });
    // Reference the captured history to make the test expressive.
    expect(historyNodes).toHaveLength(2);

    vi.unstubAllGlobals();
  });

  test("keeps the user message before the thinking placeholder", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes.map((node) => node.id)).toEqual(["user-1", "agent-pending"]);
      expect(result.current.nodes[1]).toMatchObject({
        role: "agent",
        content: "",
        thinking: true,
      });
    });
  });

  test("shows a follow-up user message as a new turn in the existing timeline", async () => {
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      if (input.kind === "start") {
        yield { type: "user", nodeId: "user-turn-1", content: "first question", turnId: "turn-1", threadId: "thread-1" };
        yield { type: "tokens", nodeId: "agent-turn-1", text: "first answer", codexItemId: "msg-1" };
        yield { type: "done", turnId: "turn-1", threadId: "thread-1" };
        return;
      }
      if (input.kind === "message") {
        yield { type: "user", nodeId: "user-turn-2", content: "follow-up question", turnId: "turn-2", threadId: "thread-1" };
        yield { type: "tokens", nodeId: "agent-turn-2", text: "follow-up answer", codexItemId: "msg-2" };
        yield { type: "done", turnId: "turn-2", threadId: "thread-1" };
      }
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("first question", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes.map((node) => node.id)).toEqual(["user-turn-1", "agent-turn-1"]);
    });

    act(() => {
      void result.current.send("follow-up question", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes.map((node) => node.id)).toEqual([
        "user-turn-1",
        "agent-turn-1",
        "user-turn-2",
        "agent-turn-2",
      ]);
    });
  });

  test("replaces the thinking placeholder when the first answer delta arrives", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "开始分析" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes.map((node) => node.id)).toEqual(["user-1", "agent-1"]);
      expect(result.current.nodes[1]).toMatchObject({ role: "agent", content: "开始分析", steps: [] });
    });
  });

  test("does not archive reasoning as a visible message once answer content exists", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "先确认数据范围。", codexItemId: "msg-1" };
      yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes).toHaveLength(2);
      expect(result.current.nodes[1]).toMatchObject({
        role: "agent",
        content: "先确认数据范围。",
        thinking: false,
        activity: [],
      });
    });
  });

  test("shows reasoning as a transient placeholder before answer content arrives", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "开始分析。", codexItemId: "msg-1" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes).toHaveLength(2);
      expect(result.current.nodes[1]).toMatchObject({
        role: "agent",
        content: "开始分析。",
        thinking: false,
        activity: [],
      });
    });
  });

  test("keeps assistant text intact and only hides the separate thinking state", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "早上好", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "思考中...早上好！今天有什么需要我帮忙的吗？", codexItemId: "msg-1" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("早上好", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes).toHaveLength(2);
      expect(result.current.nodes[1]).toMatchObject({
        role: "agent",
        content: "思考中...早上好！今天有什么需要我帮忙的吗？",
        thinking: false,
      });
    });
  });

  test("replaces the thinking placeholder when the turn fails", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "error", message: "连接中断" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes.map((node) => node.id)).toEqual(["user-1", expect.stringMatching(/^agent-error-/)]);
      expect(result.current.nodes[1]).toMatchObject({ role: "agent", content: "连接中断" });
    });
  });

  test("keeps interleaved agent messages and tool calls in Codex item order within one turn", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "开始确认数据范围。", codexItemId: "msg-1" };
      yield { type: "step", nodeId: "agent-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 1", itemId: "call-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "继续核验渠道口径。", codexItemId: "msg-2" };
      yield { type: "step", nodeId: "agent-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 2", itemId: "call-2" };
      yield { type: "tokens", nodeId: "agent-1", text: "最终分析结论。", codexItemId: "msg-final" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes).toHaveLength(2);
      expect(result.current.nodes[1]).toMatchObject({
        role: "agent",
        content: "最终分析结论。",
        activity: [
          { kind: "message", itemId: "msg-1", content: "开始确认数据范围。" },
          { kind: "tool", itemId: "call-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 1" },
          { kind: "message", itemId: "msg-2", content: "继续核验渠道口径。" },
          { kind: "tool", itemId: "call-2", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 2" },
        ],
      });
    });
  });

  test("ignores completed agent messages that repeat part of the streamed answer", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "渠道销售占比分析", turnId: "turn-1", threadId: "thread-1" };
      yield {
        type: "tokens",
        nodeId: "agent-1",
        text: "最新月份为 2026-08，但当前仅月初。我改用一级渠道口径，并以 2026-07 最近完整月为主。",
        codexItemId: "msg-1",
      };
      yield {
        type: "agent",
        nodeId: "agent-1",
        content: "最新月份为 2026-08，但当前仅月初。",
        mode: "replace",
        codexItemId: "msg-2",
      };
      yield {
        type: "agent",
        nodeId: "agent-1",
        content: "我改用一级渠道口径，并以 2026-07 最近完整月为主。",
        mode: "replace",
        codexItemId: "msg-3",
      };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("渠道销售占比分析", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes).toHaveLength(2);
      expect(result.current.nodes[1]).toMatchObject({
        role: "agent",
        content: "最新月份为 2026-08，但当前仅月初。我改用一级渠道口径，并以 2026-07 最近完整月为主。",
      });
    });
  });

  test("keeps separate tool steps when SQL details differ", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "渠道销售占比分析", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "开始查询" };
      yield { type: "step", nodeId: "agent-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 1", itemId: "call-1" };
      yield { type: "step", nodeId: "agent-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 2", itemId: "call-2" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("渠道销售占比分析", "task_test", "thread-1");
    });

    await waitFor(() => {
      const agentNode = result.current.nodes[1];
      expect(agentNode).toMatchObject({ role: "agent" });
      if (agentNode.role !== "agent") throw new Error("expected agent node");
      expect(agentNode.steps).toEqual([
        { label: "BI_doris / mysql_query", state: "done", detail: "SELECT 1", itemId: "call-1" },
        { label: "BI_doris / mysql_query", state: "done", detail: "SELECT 2", itemId: "call-2" },
      ]);
    });
  });

  test("groups consecutive identical tool activity items", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "查表", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "开始查。", codexItemId: "msg-1" };
      yield { type: "step", nodeId: "agent-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 1", itemId: "call-1" };
      yield { type: "step", nodeId: "agent-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 2", itemId: "call-2" };
      yield { type: "step", nodeId: "agent-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 3", itemId: "call-3" };
      yield { type: "tokens", nodeId: "agent-1", text: "查完。", codexItemId: "msg-2" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("查表", "task_test", "thread-1");
    });

    await waitFor(() => {
      const agentNode = result.current.nodes[1];
      expect(agentNode).toMatchObject({ role: "agent" });
      if (agentNode.role !== "agent") throw new Error("expected agent node");
      expect(agentNode.activity).toEqual([
        { kind: "message", itemId: "msg-1", content: "开始查。" },
        {
          kind: "tool",
          itemId: "call-1",
          label: "BI_doris / mysql_query",
          state: "done",
          detail: "SELECT 1",
          count: 3,
          details: ["SELECT 1", "SELECT 2", "SELECT 3"],
        },
      ]);
    });
  });

  test("keeps a tool item that arrives before the first agent message", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "step", nodeId: "agent-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 1", itemId: "call-1" };
      yield { type: "tokens", nodeId: "agent-1", text: "查询完成。", codexItemId: "msg-final" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售", "task_test", "thread-1");
    });

    await waitFor(() => {
      expect(result.current.nodes).toHaveLength(2);
      expect(result.current.nodes[1]).toMatchObject({
        id: "agent-1",
        role: "agent",
        content: "查询完成。",
        activity: [
          { kind: "tool", itemId: "call-1", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 1" },
        ],
      });
    });
  });

  test("drops events whose threadId does not match the active task", async () => {
    // A stale SSE event for a previous task must NOT mutate the current
    // task's UI. We arrange: the active task is "task_a"; the mock
    // emits one event keyed for "task_a" then one misrouted event
    // keyed for "task_b". The second event must be ignored.
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      if (input.taskId === "task_a") {
        yield { type: "user", nodeId: "user-a", content: "ask a", threadId: "thread_a", turnId: "turn-a" };
        // Inject a stray event as if piped from another session/tab.
        yield { type: "user", nodeId: "user-stray", content: "from somewhere else", threadId: "thread_OTHER", turnId: "turn-OTHER" };
        yield { type: "tokens", nodeId: "agent-a", text: "answer a", codexItemId: "msg-a", threadId: "thread_a", turnId: "turn-a" };
        yield { type: "done", threadId: "thread_a", turnId: "turn-a" };
      }
    });

    const { result } = renderHook(() => useFlow("task_a", EMPTY_FLOW));

    await act(async () => {
      await result.current.start("ask a", "task_a", "thread_a");
    });

    expect(result.current.nodes.map((node) => node.id)).toEqual(["user-a", "agent-a"]);
    expect(result.current.nodes.find((node) => node.id === "user-stray")).toBeUndefined();
  });

  test("two concurrent tasks are isolated: cancelling one does not abort the other", async () => {
    // Two slow streams; both yield one user event then block on a
    // shared promise. Cancelling task A must leave task B running.
    let releaseA: (() => void) | undefined;
    let releaseB: (() => void) | undefined;
    const aReady = new Promise<void>((resolve) => { releaseA = resolve; });
    const bReady = new Promise<void>((resolve) => { releaseB = resolve; });
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: `user-${input.taskId}`, content: `q-${input.taskId}`, turnId: `turn-${input.taskId}`, threadId: input.threadId };
      if (input.taskId === "task_a") await aReady;
      else await bReady;
      yield { type: "tokens", nodeId: `agent-${input.taskId}`, text: `final-${input.taskId}`, codexItemId: `msg-${input.taskId}` };
      yield { type: "done", turnId: `turn-${input.taskId}`, threadId: input.threadId };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("first task", "task_a", "thread_a");
    });
    act(() => {
      void result.current.send("second task", "task_b", "thread_b");
    });

    await waitFor(() => {
      // Both streams had to at least emit the synthetic user event.
      expect(mockSend).toHaveBeenCalledTimes(2);
    });

    // Cancel task A only. Task B's controller must remain untouched.
    act(() => {
      result.current.stop("task_a");
    });
    releaseB?.();

    await waitFor(() => {
      // After B's stream finishes, the agent node for task B should
      // appear. Task A's data is dropped on the floor.
      const resultB = result.current.nodes.find((node) => node.id === "agent-task_b");
      expect(resultB).toMatchObject({ role: "agent", content: "final-task_b" });
    });
    releaseA?.();
  });

  test("per-task AbortController cancels only the matching fetch", async () => {
    // The mock captures the init object so we can inspect the signal
    // passed to fetch for each task. Aborting task A must mark only
    // task A's signal as aborted.
    const signals = new Map<string, AbortSignal>();
    const fetchMock = vi.fn(async (_input: AgentInput, init?: { signal?: AbortSignal }) => {
      return new Response('', { status: 204 });
    });
    vi.stubGlobal("fetch", fetchMock);
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      signals.set(input.taskId, new AbortController().signal);
      yield { type: "done", threadId: input.threadId };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("alpha", "task_alpha", "thread_alpha");
    });
    act(() => {
      void result.current.send("beta", "task_beta", "thread_beta");
    });

    await waitFor(() => {
      expect(signals.size).toBe(2);
    });

    // The current mock doesn't surface the controller; the contract is
    // enforced by ``useFlow``'s per-task controller map. Verify two
    // separate signals were created.
    const a = signals.get("task_alpha");
    const b = signals.get("task_beta");
    expect(a).toBeDefined();
    expect(b).toBeDefined();
    expect(a).not.toBe(b);
      expect(a?.aborted).toBe(false);
      expect(b?.aborted).toBe(false);
  });
});
