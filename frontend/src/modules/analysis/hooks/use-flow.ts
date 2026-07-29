"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getAgentClient } from "@/modules/analysis/agentClients";
import type { AgentEvent, AgentInput } from "@/modules/analysis/agentClients";

export type FlowRole = "user" | "agent" | "ask";

export type FlowNode =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "agent"; content: string; mode?: "replace" | "delta"; steps?: { label: string; state: "queued" | "running" | "done" }[] }
  | { id: string; role: "ask"; question: string; options: { id: string; label: string }[]; current?: boolean };

export const STEP_INITIAL = ["识别业务口径", "查询可用数据表", "生成并校验 SQL", "整理图表与结论"];

export function useFlow(sessionKey: string | null, initial: FlowNode[] = []) {
  const agent = useMemo(() => getAgentClient(), []);
  const [runId, setRunId] = useState<string | null>(sessionKey);
  const [nodes, setNodes] = useState<FlowNode[]>(initial);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    cancelled = false;
    setRunId(sessionKey);
    setNodes([...initial]);
    setRunning(false);
    return () => { cancelled = true; };
  }, [sessionKey, initial]);

  const applyEvent = useCallback((event: AgentEvent, currentNodes: FlowNode[]): FlowNode[] => {
    if (event.type === "session-init") {
      setRunId(event.runId);
      setNodes([]);
      return [];
    }

    if (event.type === "user") {
      const next = [...currentNodes, { id: event.nodeId, role: "user", content: event.content } as FlowNode];
      setNodes(next);
      return next;
    }

    if (event.type === "agent") {
      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const existing = next.findIndex((n) => n.id === event.nodeId && n.role === "agent");
      if (existing >= 0) {
        const target = next[existing];
        if (target.role === "agent") {
          next[existing] = { ...target, content: event.content, mode: event.mode };
        }
      } else {
        next.push({ id: event.nodeId, role: "agent", content: event.content, mode: event.mode, steps: [] });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "tokens") {
      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const idx = next.findIndex((n) => n.id === event.nodeId && n.role === "agent");
      if (idx >= 0) {
        const target = next[idx];
        if (target.role === "agent") {
          next[idx] = { ...target, content: target.content + event.text };
        }
      }
      setNodes(next);
      return next;
    }

    if (event.type === "step") {
      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const idx = [...next].reverse().findIndex((n) => n.role === "agent");
      if (idx >= 0) {
        const target = next[next.length - 1 - idx];
        if (target.role === "agent") {
          const steps = [...(target.steps ?? [])];
          const existing = steps.findIndex((s) => s.label === event.label);
          if (existing >= 0) {
            steps[existing] = { label: event.label, state: event.state };
          } else {
            steps.push({ label: event.label, state: event.state });
          }
          next[next.length - 1 - idx] = { ...target, steps, content: target.content };
        }
      }
      setNodes(next);
      return next;
    }

    if (event.type === "ask") {
      const next = currentNodes.map((n) => (n.role === "ask" ? { ...n, current: false } : n));
      next.push({ id: event.nodeId, role: "ask", question: event.question, options: event.options, current: true });
      setNodes(next);
      return next;
    }

    return currentNodes;
  }, []);

  const consume = useCallback(async (input: AgentInput) => {
    if (cancelled) return;
    setRunning(true);
    let snapshot: FlowNode[] = nodes;
    try {
      for await (const event of agent.send(input)) {
        if (cancelled) break;
        snapshot = applyEvent(event, snapshot);
      }
    } finally {
      setRunning(false);
    }
  }, [agent, applyEvent, nodes]);

  const start = useCallback((question?: string) => consume({ kind: "start", question }), [consume]);
  const send = useCallback((content: string) => consume({ kind: "message", content }), [consume]);
  const reply = useCallback((optionId: string) => consume({ kind: "reply", optionId }), [consume]);

  return { runId, nodes, running, start, send, reply };
}

let cancelled = false;
