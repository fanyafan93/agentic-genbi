/**
 * @vitest-environment jsdom
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { AgentEvent, AgentInput } from "../src/modules/analysis/agentClients/types";

const { mockSend } = vi.hoisted(() => ({ mockSend: vi.fn() }));

vi.mock("../src/modules/analysis/agentClients", () => ({
  getAgentClient: () => ({ send: mockSend }),
}));

import { useFlow, type FlowNode } from "../src/modules/analysis/hooks/use-flow";

const EMPTY_FLOW: FlowNode[] = [];

afterEach(() => {
  mockSend.mockReset();
});

describe("analysis flow streaming", () => {
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

  test("keeps the user message before the thinking placeholder", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "done" };
    });

    const { result } = renderHook(() => useFlow(null, EMPTY_FLOW));

    act(() => {
      void result.current.start("分析渠道销售");
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
});
