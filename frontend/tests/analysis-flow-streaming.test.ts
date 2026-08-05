/**
 * @vitest-environment jsdom
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { AgentEvent, AgentInput } from "../src/modules/analysis/agentClients/types";

const { mockSend, mockCancel, mockCancelTurn } = vi.hoisted(() => ({
  mockSend: vi.fn(),
  mockCancel: vi.fn(),
  mockCancelTurn: vi.fn(),
}));

vi.mock("../src/modules/analysis/agentClients", () => ({
  getAgentClient: () => ({
    send: mockSend,
    cancel: mockCancel,
    cancelTurn: mockCancelTurn,
  }),
}));

import { useFlow, type FlowNode } from "../src/modules/analysis/hooks/use-flow";

const EMPTY_FLOW: FlowNode[] = [];

afterEach(() => {
  mockSend.mockReset();
  mockCancel.mockReset();
  mockCancelTurn.mockReset();
});

describe("analysis flow streaming", () => {
  test("keeps a live stream error when terminal reconciliation returns no persisted turn", async () => {
    mockSend.mockImplementation(async function* (): AsyncIterable<AgentEvent> {
      yield { type: "error", message: "no rollout found" };
      yield { type: "done" };
    });
    const onTurnSettled = vi.fn().mockResolvedValue([]);
    const { result } = renderHook(() => useFlow("session-without-rollout", EMPTY_FLOW, { onTurnSettled }));

    act(() => {
      void result.current.send("继续分析");
    });

    await waitFor(() => expect(result.current.running).toBe(false));
    expect(onTurnSettled).toHaveBeenCalledWith("session-without-rollout");
    expect(result.current.nodes).toEqual(expect.arrayContaining([
      expect.objectContaining({ role: "user", content: "继续分析" }),
      expect.objectContaining({
        id: expect.stringMatching(/^agent-error-/),
        role: "agent",
        content: "no rollout found",
        mode: "replace",
      }),
    ]));
  });

  test("keeps a running session alive while another session is selected", async () => {
    let releaseSessionA: (() => void) | undefined;
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      if (!("sessionId" in input) || input.sessionId !== "session-a") return;
      yield { type: "user", nodeId: "user-a", content: "question a", turnId: "turn-a", threadId: "session-a" };
      yield { type: "thinking", nodeId: "agent-a", codexItemId: "reasoning-a" };
      await new Promise<void>((resolve) => {
        releaseSessionA = resolve;
      });
      yield { type: "agent", nodeId: "agent-a", content: "answer a", mode: "replace", codexItemId: "message-a" };
      yield { type: "done", turnId: "turn-a", threadId: "session-a" };
    });
    const sessionBHistory: FlowNode[] = [
      { id: "user-b", role: "user", content: "question b" },
      { id: "agent-b", role: "agent", content: "answer b", mode: "replace", activity: [] },
    ];

    const { result, rerender } = renderHook(
      ({ sessionId, initial }: { sessionId: string; initial: FlowNode[] }) => useFlow(sessionId, initial),
      { initialProps: { sessionId: "session-a", initial: EMPTY_FLOW } },
    );

    act(() => {
      void result.current.send("question a");
    });
    await waitFor(() => {
      expect(result.current.running).toBe(true);
      expect(result.current.nodes.some((node) => node.id === "agent-a" && node.role === "agent" && node.thinking)).toBe(true);
    });
    const cancelCallsBeforeSwitch = mockCancel.mock.calls.length;

    rerender({ sessionId: "session-b", initial: sessionBHistory });

    await waitFor(() => {
      expect(result.current.running).toBe(false);
      expect(result.current.nodes).toEqual(sessionBHistory);
    });
    expect(mockCancel).toHaveBeenCalledTimes(cancelCallsBeforeSwitch);

    act(() => releaseSessionA?.());
    await waitFor(() => {
      expect(result.current.nodes).toEqual(sessionBHistory);
    });

    rerender({ sessionId: "session-a", initial: EMPTY_FLOW });

    await waitFor(() => {
      expect(result.current.running).toBe(false);
      expect(result.current.nodes).toEqual([
        { id: "user-a", role: "user", content: "question a" },
        expect.objectContaining({ id: "agent-a", role: "agent", content: "answer a", thinking: false }),
      ]);
    });
  });

  test("keeps background terminal reconciliation scoped to its original session", async () => {
    let releaseSessionA: (() => void) | undefined;
    let resolveSessionAReconciliation: ((nodes: FlowNode[]) => void) | undefined;
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      if (!("sessionId" in input)) return;
      if (input.sessionId === "session-a") {
        yield { type: "user", nodeId: "user-a", content: "question a", turnId: "turn-a", threadId: "session-a" };
        await new Promise<void>((resolve) => {
          releaseSessionA = resolve;
        });
        yield { type: "agent", nodeId: "agent-a-live", content: "live answer a", mode: "replace", codexItemId: "message-a" };
        yield { type: "done", turnId: "turn-a", threadId: "session-a" };
        return;
      }
      yield { type: "user", nodeId: "user-b", content: "question b", turnId: "turn-b", threadId: "session-b" };
      yield { type: "agent", nodeId: "agent-b", content: "answer b", mode: "replace", codexItemId: "message-b" };
      yield { type: "done", turnId: "turn-b", threadId: "session-b" };
    });
    const onTurnSettled = vi.fn(async (sessionId: string) => {
      if (sessionId !== "session-a") return undefined;
      return new Promise<FlowNode[]>((resolve) => {
        resolveSessionAReconciliation = resolve;
      });
    });

    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string }) => useFlow(sessionId, EMPTY_FLOW, { onTurnSettled }),
      { initialProps: { sessionId: "session-a" } },
    );

    act(() => {
      void result.current.send("question a");
    });
    await waitFor(() => expect(result.current.running).toBe(true));

    rerender({ sessionId: "session-b" });
    act(() => releaseSessionA?.());
    await waitFor(() => expect(onTurnSettled).toHaveBeenCalledWith("session-a"));

    act(() => {
      void result.current.send("question b");
    });
    await waitFor(() => {
      expect(result.current.nodes).toEqual(expect.arrayContaining([
        expect.objectContaining({ id: "agent-b", content: "answer b" }),
      ]));
    });

    await act(async () => {
      resolveSessionAReconciliation?.([
        { id: "user-a", role: "user", content: "question a" },
        { id: "agent-a-reconciled", role: "agent", content: "reconciled answer a" },
      ]);
      await Promise.resolve();
      await Promise.resolve();
    });

    await waitFor(() => {
      expect(result.current.nodes).toEqual(expect.arrayContaining([
        expect.objectContaining({ id: "agent-b", content: "answer b" }),
      ]));
      expect(result.current.nodes.some((node) => node.id === "agent-a-reconciled")).toBe(false);
    });

    rerender({ sessionId: "session-a" });
    await waitFor(() => {
      expect(result.current.nodes).toEqual([
        { id: "user-a", role: "user", content: "question a" },
        { id: "agent-a-reconciled", role: "agent", content: "reconciled answer a" },
      ]);
    });
  });

  test("clears the active thinking state immediately when the user stops a turn", async () => {
    let releaseStream: (() => void) | undefined;
    mockCancel.mockImplementation(() => releaseStream?.());
    mockCancelTurn.mockResolvedValue(undefined);
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "first question", turnId: "turn-1", threadId: "session-1" };
      yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
      await new Promise<void>((resolve) => {
        releaseStream = resolve;
      });
    });

    const { result } = renderHook(() => useFlow("session-1", EMPTY_FLOW));

    act(() => {
      void result.current.send("first question");
    });
    await waitFor(() => {
      expect(result.current.nodes.some((node) => node.role === "agent" && node.thinking)).toBe(true);
    });

    act(() => {
      result.current.stop();
    });

    await waitFor(() => {
      expect(result.current.running).toBe(false);
      expect(result.current.nodes.some((node) => node.role === "agent" && node.thinking)).toBe(false);
    });
  });

  test("accepts a new message in the same session after the previous turn was stopped", async () => {
    let releaseFirstStream: (() => void) | undefined;
    let sendCount = 0;
    mockCancel.mockImplementation(() => releaseFirstStream?.());
    mockCancelTurn.mockResolvedValue(undefined);
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      sendCount += 1;
      if (sendCount === 1) {
        yield { type: "user", nodeId: "user-1", content: "first question", turnId: "turn-1", threadId: "session-1" };
        yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
        await new Promise<void>((resolve) => {
          releaseFirstStream = resolve;
        });
        return;
      }
      yield { type: "user", nodeId: "user-2", content: String(input.kind === "message" ? input.content : ""), turnId: "turn-2", threadId: "session-1" };
      yield { type: "agent", nodeId: "agent-2", content: "second answer", mode: "replace", codexItemId: "message-2" };
      yield { type: "done", turnId: "turn-2", threadId: "session-1" };
    });

    const { result } = renderHook(() => useFlow("session-1", EMPTY_FLOW));

    act(() => {
      void result.current.send("first question");
    });
    await waitFor(() => expect(result.current.running).toBe(true));

    act(() => {
      result.current.stop();
    });
    await waitFor(() => expect(result.current.running).toBe(false));

    act(() => {
      void result.current.send("second question");
    });

    await waitFor(() => {
      expect(result.current.nodes).toEqual(expect.arrayContaining([
        expect.objectContaining({ id: "user-2", role: "user", content: "second question" }),
        expect.objectContaining({ id: "agent-2", role: "agent", content: "second answer" }),
      ]));
    });
  });

  test("waits for the native turn interrupt before starting the next turn", async () => {
    let releaseFirstStream: (() => void) | undefined;
    let resolveInterrupt: (() => void) | undefined;
    let sendCount = 0;
    mockCancel.mockImplementation(() => releaseFirstStream?.());
    mockCancelTurn.mockImplementation(() => new Promise<void>((resolve) => {
      resolveInterrupt = resolve;
    }));
    mockSend.mockImplementation(async function* (input: AgentInput): AsyncIterable<AgentEvent> {
      sendCount += 1;
      if (sendCount === 1) {
        yield { type: "user", nodeId: "user-1", content: "first question", turnId: "turn-1", threadId: "session-1" };
        yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
        await new Promise<void>((resolve) => {
          releaseFirstStream = resolve;
        });
        return;
      }
      yield { type: "user", nodeId: "user-2", content: String(input.kind === "message" ? input.content : ""), turnId: "turn-2", threadId: "session-1" };
      yield { type: "agent", nodeId: "agent-2", content: "second answer", mode: "replace", codexItemId: "message-2" };
      yield { type: "done", turnId: "turn-2", threadId: "session-1" };
    });

    const { result } = renderHook(() => useFlow("session-1", EMPTY_FLOW));

    act(() => {
      void result.current.send("first question");
    });
    await waitFor(() => expect(result.current.running).toBe(true));

    act(() => {
      result.current.stop();
      void result.current.send("second question");
    });

    await waitFor(() => expect(mockCancelTurn).toHaveBeenCalledTimes(1));
    expect(sendCount).toBe(1);

    act(() => resolveInterrupt?.());

    await waitFor(() => {
      expect(sendCount).toBe(2);
      expect(result.current.nodes).toEqual(expect.arrayContaining([
        expect.objectContaining({ id: "user-2", role: "user", content: "second question" }),
        expect.objectContaining({ id: "agent-2", role: "agent", content: "second answer" }),
      ]));
    });
  });

  test("hydrates existing thread nodes when history loads after selecting a task", async () => {
    const historyNodes: FlowNode[] = [
      { id: "user-turn-1", role: "user", content: "历史问题" },
      { id: "agent-turn-1", role: "agent", content: "历史回答", mode: "replace", activity: [] },
    ];
    const { result, rerender } = renderHook(
      ({ threadKey, initial }: { threadKey: string; initial: FlowNode[] }) => useFlow(threadKey, initial),
      { initialProps: { threadKey: "analysis_thread_1", initial: EMPTY_FLOW } },
    );

    expect(result.current.nodes).toEqual([]);

    rerender({ threadKey: "analysis_thread_1", initial: historyNodes });

    await waitFor(() => {
      expect(result.current.nodes).toEqual(historyNodes);
    });
  });

  test("keeps the user message and removes the empty placeholder when the turn completes", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售");
    });

    await waitFor(() => {
      expect(result.current.nodes.map((node) => node.id)).toEqual(["user-1"]);
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
      void result.current.start("first question");
    });

    await waitFor(() => {
      expect(result.current.nodes.map((node) => node.id)).toEqual(["user-turn-1", "agent-turn-1"]);
    });

    act(() => {
      void result.current.send("follow-up question");
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
      void result.current.start("分析渠道销售");
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
      void result.current.start("分析渠道销售");
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
      void result.current.start("分析渠道销售");
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

  test("clears a reasoning placeholder when the turn completes without another display event", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "hello", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
      yield { type: "done", turnId: "turn-1", threadId: "thread-1" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("hello");
    });

    await waitFor(() => {
      expect(result.current.running).toBe(false);
      expect(result.current.nodes.some((node) => node.role === "agent" && node.thinking)).toBe(false);
    });
  });

  test("keeps consuming the first-turn stream when session creation updates the route id", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "session/created", sessionId: "session-1", codexThreadId: "session-1" };
      yield { type: "user", nodeId: "user-1", content: "hello", turnId: "turn-1", threadId: "session-1" };
      yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
      yield { type: "agent", nodeId: "agent-1", content: "hello back", mode: "replace", codexItemId: "message-1" };
      yield { type: "done", turnId: "turn-1", threadId: "session-1" };
    });

    const { result } = renderHook(() => {
      const [sessionId, setSessionId] = useState<string | null>(null);
      return {
        sessionId,
        flow: useFlow(sessionId, EMPTY_FLOW, { onSessionCreated: setSessionId }),
      };
    });

    act(() => {
      void result.current.flow.start("hello");
    });

    await waitFor(() => {
      expect(result.current.sessionId).toBe("session-1");
      expect(result.current.flow.running).toBe(false);
      expect(result.current.flow.nodes).toEqual([
        { id: "user-1", role: "user", content: "hello" },
        expect.objectContaining({ id: "agent-1", role: "agent", content: "hello back", thinking: false }),
      ]);
    });
  });

  test("reconciles the completed turn from backend state when stream events are incomplete", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "session/created", sessionId: "session-1", codexThreadId: "session-1" };
      yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
    });
    const reconciledNodes: FlowNode[] = [
      { id: "user-turn-1", role: "user", content: "hello" },
      { id: "agent-turn-1", role: "agent", content: "persisted answer", mode: "replace", activity: [] },
    ];
    const reconcileTurn = vi.fn().mockResolvedValue(reconciledNodes);

    const { result } = renderHook(() => {
      const [sessionId, setSessionId] = useState<string | null>(null);
      return useFlow(sessionId, EMPTY_FLOW, {
        onSessionCreated: setSessionId,
        onTurnSettled: reconcileTurn,
      });
    });

    act(() => {
      void result.current.start("hello");
    });

    await waitFor(() => {
      expect(result.current.running).toBe(false);
      expect(result.current.nodes).toEqual(reconciledNodes);
    });
    expect(reconcileTurn).toHaveBeenCalledWith("session-1");
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
      void result.current.start("早上好");
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
      void result.current.start("分析渠道销售");
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
      void result.current.start("分析渠道销售");
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

  test("keeps native Codex reasoning summaries and tools ordered outside the final answer", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield {
        type: "process",
        nodeId: "agent-1",
        text: "正在",
        mode: "delta",
        summaryIndex: 0,
        codexItemId: "reasoning-1",
      };
      yield {
        type: "process",
        nodeId: "agent-1",
        text: "查询数据。",
        mode: "delta",
        summaryIndex: 0,
        codexItemId: "reasoning-1",
      };
      yield {
        type: "step",
        nodeId: "agent-1",
        label: "BI_doris / mysql_query",
        state: "running",
        detail: "Arguments:\nSELECT 1",
        itemId: "tool-1",
      };
      yield {
        type: "step",
        nodeId: "agent-1",
        label: "BI_doris / mysql_query",
        state: "done",
        detail: "Arguments:\nSELECT 1\n\nResult:\n1 row",
        itemId: "tool-1",
      };
      yield {
        type: "process",
        nodeId: "agent-1",
        text: "正在生成报告。",
        mode: "replace",
        summaryIndex: 1,
        codexItemId: "reasoning-1",
      };
      yield { type: "tokens", nodeId: "agent-1", text: "最终分析结论。", codexItemId: "message-1" };
      yield { type: "done", turnId: "turn-1", threadId: "thread-1" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售");
    });

    await waitFor(() => {
      const agentNode = result.current.nodes[1];
      expect(agentNode).toMatchObject({ role: "agent" });
      if (agentNode.role !== "agent") throw new Error("expected agent node");
      expect(agentNode.content).toBe("最终分析结论。");
      expect(agentNode.activity).toEqual([
        { kind: "reasoning", itemId: "reasoning-1:0", content: "正在查询数据。" },
        {
          kind: "tool",
          itemId: "tool-1",
          label: "BI_doris / mysql_query",
          state: "done",
          detail: "Arguments:\nSELECT 1\n\nResult:\n1 row",
        },
        { kind: "reasoning", itemId: "reasoning-1:1", content: "正在生成报告。" },
      ]);
      expect(agentNode.processRunning).toBe(false);
      expect(agentNode.processStartedAt).toEqual(expect.any(String));
      expect(agentNode.processCompletedAt).toEqual(expect.any(String));
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
      void result.current.start("渠道销售占比分析");
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
      void result.current.start("渠道销售占比分析");
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
      void result.current.start("查表");
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
      void result.current.start("分析渠道销售");
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

  test("replaces the static thinking placeholder once a native tool item starts", async () => {
    let releaseStream: (() => void) | undefined;
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "查询当前时间", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "thinking", nodeId: "agent-1", codexItemId: "reasoning-1" };
      yield {
        type: "step",
        nodeId: "agent-1",
        label: "BI_doris / mysql_query",
        state: "running",
        detail: "Arguments:\nSELECT NOW()",
        itemId: "tool-1",
      };
      await new Promise<void>((resolve) => {
        releaseStream = resolve;
      });
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("查询当前时间");
    });

    await waitFor(() => {
      expect(result.current.nodes[1]).toMatchObject({
        role: "agent",
        thinking: false,
        processRunning: true,
        activity: [{ kind: "tool", itemId: "tool-1" }],
      });
    });

    act(() => releaseStream?.());
    await waitFor(() => expect(result.current.running).toBe(false));
  });
});
