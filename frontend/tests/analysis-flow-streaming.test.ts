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
    });
  });

  test("replaces the thinking placeholder when the first answer delta arrives", async () => {
    mockSend.mockImplementation(async function* (_input: AgentInput): AsyncIterable<AgentEvent> {
      yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1", threadId: "thread-1" };
      yield { type: "step", nodeId: "agent-1", label: "模型响应", state: "running" };
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
});
