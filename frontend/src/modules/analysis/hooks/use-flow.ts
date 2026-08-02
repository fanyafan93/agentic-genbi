"use client";

import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { getAgentClient } from "@/modules/analysis/agentClients";
import type { AgentEvent, AgentInput } from "@/modules/analysis/agentClients";
import type { ArtifactFolder, ArtifactKind } from "../types/artifact";
import type { InteractiveReport } from "../types/interactive-report";

export type FlowRole = "user" | "agent" | "ask";

export type FlowNode =
  | { id: string; role: "user"; content: string }
  | {
      id: string;
      role: "agent";
      content: string;
      mode?: "replace" | "delta";
      steps?: { label: string; state: "queued" | "running" | "done" }[];
      debug?: { title: string; content: string }[];
    }
  | { id: string; role: "ask"; question: string; options: { id: string; label: string }[]; current?: boolean };

export type FlowCodexLineage = {
  sourceCodexThreadId?: string;
  sourceCodexTurnId?: string;
  sourceCodexItemId?: string;
};

export const STEP_INITIAL = ["识别业务口径", "查询可用数据表", "生成并校验 SQL", "整理图表与结论"];

export function useFlow(conversationKey: string | null, initial: FlowNode[] = []) {
  const agent = useMemo(() => getAgentClient(), []);
  const [turnId, setTurnId] = useState<string | null>(conversationKey);
  const [conversationId, setConversationId] = useState<string | null>(conversationKey);
  const [nodes, setNodes] = useState<FlowNode[]>(initial);
  const [artifacts, setArtifacts] = useState<ArtifactFolder[]>([]);
  const [reportArtifact, setReportArtifact] = useState<InteractiveReport | null>(null);
  const [codexLineage, setCodexLineage] = useState<FlowCodexLineage>({});
  const [running, setRunning] = useState(false);

  useEffect(() => {
    cancelled = false;
    setTurnId(conversationKey);
    setConversationId(conversationKey);
    setNodes([...initial]);
    setArtifacts([]);
    setReportArtifact(null);
    setCodexLineage({});
    setRunning(false);
    return () => { cancelled = true; };
  }, [conversationKey, initial]);

  const applyEvent = useCallback((event: AgentEvent, currentNodes: FlowNode[]): FlowNode[] => {
    updateCodexLineage(event, setCodexLineage);

    if (event.type === "conversation-init") {
      setTurnId(event.turnId);
      setConversationId(event.conversationId ?? event.threadId ?? event.turnId);
      const next = currentNodes.some((node) => node.id === "user-pending" || node.id === "agent-pending") ? currentNodes : [];
      setNodes(next);
      setArtifacts([]);
      setReportArtifact(null);
      setCodexLineage(codexLineageFromEvent(event));
      return next;
    }

    if (event.type === "user") {
      const userNode: FlowNode = { id: event.nodeId, role: "user", content: event.content };
      const pendingIndex = currentNodes.findIndex((node) => node.id === "user-pending");
      const next = pendingIndex >= 0
        ? currentNodes.map((node, index) => (index === pendingIndex ? userNode : node))
        : [...currentNodes, userNode];
      setNodes(next);
      return next;
    }

    if (event.type === "agent") {
      const next: FlowNode[] = currentNodes.filter((node) => node.id !== "agent-pending").map((node) => ({ ...node }) as FlowNode);
      const existing = next.findIndex((n) => n.id === event.nodeId && n.role === "agent");
      if (existing >= 0) {
        const target = next[existing];
        if (target.role === "agent") {
          next[existing] = target.content === event.content ? { ...target, mode: event.mode } : { ...target, content: event.content, mode: event.mode };
        }
      } else {
        next.push({ id: event.nodeId, role: "agent", content: event.content, mode: event.mode, steps: [] });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "tokens") {
      const pendingIndex = currentNodes.findIndex((node) => node.id === "agent-pending");
      if (pendingIndex >= 0) {
        const streamedNode: FlowNode = {
          id: event.nodeId,
          role: "agent",
          content: event.text,
          mode: "delta",
          steps: [],
        };
        const next = currentNodes.map((node, index) => (index === pendingIndex ? streamedNode : node));
        setNodes(next);
        return next;
      }

      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const idx = next.findIndex((n) => n.id === event.nodeId && n.role === "agent");
      if (idx >= 0) {
        const target = next[idx];
        if (target.role === "agent") {
          next[idx] = { ...target, content: target.content + event.text };
        }
      } else {
        next.push({ id: event.nodeId, role: "agent", content: event.text, mode: "delta", steps: [] });
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
      } else if (event.nodeId) {
        next.push({ id: event.nodeId, role: "agent", content: "", mode: "delta", steps: [{ label: event.label, state: event.state }] });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "debug") {
      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const idx = next.findIndex((n) => n.id === event.nodeId && n.role === "agent");
      const debugItem = { title: event.title, content: event.content };
      if (idx >= 0) {
        const target = next[idx];
        if (target.role === "agent") {
          next[idx] = { ...target, debug: [...(target.debug ?? []), debugItem] };
        }
      } else {
        next.push({ id: event.nodeId, role: "agent", content: "", mode: "delta", steps: [], debug: [debugItem] });
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

    if (event.type === "report-artifact") {
      setReportArtifact(event.report);
      return currentNodes;
    }

    if (event.type === "error") {
      const errorNode: FlowNode = { id: `agent-error-${Date.now()}`, role: "agent", content: event.message, mode: "replace" };
      const pendingIndex = currentNodes.findIndex((node) => node.id === "agent-pending");
      const next = pendingIndex >= 0
        ? currentNodes.map((node, index) => (index === pendingIndex ? errorNode : node))
        : [...currentNodes, errorNode];
      setNodes(next);
      return next;
    }

    return currentNodes;
  }, []);

  const consume = useCallback(async (input: AgentInput) => {
    if (cancelled) return;
    setRunning(true);
    let snapshot: FlowNode[] = withOptimisticTurn(nodes, input);
    if (snapshot !== nodes) setNodes(snapshot);
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

  return {
    turnId,
    conversationId,
    nodes,
    artifacts,
    reportArtifact,
    codexLineage,
    running,
    start,
    send,
    reply,
  };
}

let cancelled = false;

function withOptimisticTurn(nodes: FlowNode[], input: AgentInput): FlowNode[] {
  const content = input.kind === "start" ? input.question : input.kind === "message" ? input.content : "";
  if (!content || nodes.some((node) => node.id === "user-pending" || node.id === "agent-pending")) return nodes;
  return [
    ...nodes,
    { id: "user-pending", role: "user", content },
    { id: "agent-pending", role: "agent", content: "正在思考...", mode: "replace", steps: [] },
  ];
}

function updateCodexLineage(
  event: AgentEvent,
  setCodexLineage: Dispatch<SetStateAction<FlowCodexLineage>>,
) {
  const next = codexLineageFromEvent(event);
  if (Object.keys(next).length === 0) return;
  setCodexLineage((current) => ({ ...current, ...next }));
}

function codexLineageFromEvent(event: AgentEvent): FlowCodexLineage {
  const lineage: FlowCodexLineage = {};
  if (event.codexThreadId) lineage.sourceCodexThreadId = event.codexThreadId;
  if (event.codexTurnId) lineage.sourceCodexTurnId = event.codexTurnId;
  if (event.codexItemId) lineage.sourceCodexItemId = event.codexItemId;
  return lineage;
}

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
