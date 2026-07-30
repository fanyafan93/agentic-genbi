"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { getAgentClient } from "@/modules/analysis/agentClients";
import type { AgentEvent, AgentInput, AnalysisMode } from "@/modules/analysis/agentClients";
import type { ArtifactFolder, ArtifactKind } from "../types/artifact";

export type FlowRole = "user" | "agent" | "ask";

export type FlowNode =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "agent"; content: string; mode?: "replace" | "delta"; steps?: { label: string; state: "queued" | "running" | "done" }[] }
  | { id: string; role: "ask"; question: string; options: { id: string; label: string }[]; current?: boolean };

export const STEP_INITIAL = ["识别业务口径", "查询可用数据表", "生成并校验 SQL", "整理图表与结论"];

export function useFlow(conversationKey: string | null, initial: FlowNode[] = []) {
  const agent = useMemo(() => getAgentClient(), []);
  const [runId, setRunId] = useState<string | null>(conversationKey);
  const [conversationId, setConversationId] = useState<string | null>(conversationKey);
  const [nodes, setNodes] = useState<FlowNode[]>(initial);
  const [artifacts, setArtifacts] = useState<ArtifactFolder[]>([]);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    cancelled = false;
    setRunId(conversationKey);
    setConversationId(conversationKey);
    setNodes([...initial]);
    setArtifacts([]);
    setRunning(false);
    return () => { cancelled = true; };
  }, [conversationKey, initial]);

  const applyEvent = useCallback((event: AgentEvent, currentNodes: FlowNode[]): FlowNode[] => {
    if (event.type === "conversation-init") {
      setRunId(event.runId);
      setConversationId(event.conversationId ?? event.runId);
      setNodes([]);
      setArtifacts([]);
      return [];
    }

    if (event.type === "run-init") {
      setRunId(event.runId);
      if (event.conversationId) setConversationId(event.conversationId);
      return currentNodes;
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

    if (event.type === "artifact") {
      setArtifacts((folders) => upsertArtifact(folders, event.path, event.kind));
      return currentNodes;
    }

    if (event.type === "error") {
      const next: FlowNode[] = [
        ...currentNodes,
        { id: `agent-error-${Date.now()}`, role: "agent", content: event.message, mode: "replace" },
      ];
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

  const start = useCallback((question?: string, analysisMode?: AnalysisMode) => consume({ kind: "start", question, analysisMode }), [consume]);
  const send = useCallback((content: string, analysisMode?: AnalysisMode) => consume({ kind: "message", content, analysisMode }), [consume]);
  const reply = useCallback((optionId: string, analysisMode?: AnalysisMode) => consume({ kind: "reply", optionId, analysisMode }), [consume]);

  return { runId, conversationId, nodes, artifacts, running, start, send, reply };
}

let cancelled = false;

function upsertArtifact(folders: ArtifactFolder[], path: string, kind: ArtifactKind): ArtifactFolder[] {
  const [folderName = "assets", fileName = path] = path.split("/");
  const fileId = path.replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "");
  const next = folders.map((folder) => ({
    ...folder,
    children: folder.children.map((file) => ({ ...file })),
  }));
  let folder = next.find((item) => item.id === folderName);
  if (!folder) {
    folder = { id: folderName, name: folderName, children: [] };
    next.push(folder);
  }
  const existing = folder.children.findIndex((file) => file.id === fileId);
  const file = { id: fileId, name: fileName, kind };
  if (existing >= 0) {
    folder.children[existing] = file;
  } else {
    folder.children.push(file);
  }
  return next;
}
