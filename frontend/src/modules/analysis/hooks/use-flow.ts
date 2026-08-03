"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { getAgentClient } from "@/modules/analysis/agentClients";
import type { AgentEvent, AgentInput } from "@/modules/analysis/agentClients";
import type { ArtifactFolder, ArtifactKind } from "../types/artifact";
import type { InteractiveReport } from "../types/interactive-report";

export type FlowRole = "user" | "agent" | "ask";

export type FlowActivity =
  | { kind: "message"; content: string; itemId?: string }
  | {
      kind: "tool";
      label: string;
      state: "queued" | "running" | "done";
      detail?: string;
      details?: string[];
      itemId?: string;
      count?: number;
    };

export type FlowNode =
  | { id: string; role: "user"; content: string }
  | {
      id: string;
      role: "agent";
      content: string;
      mode?: "replace" | "delta";
      steps?: { label: string; state: "queued" | "running" | "done"; detail?: string; itemId?: string }[];
      activity?: FlowActivity[];
      activeItemId?: string;
      debug?: { title: string; content: string }[];
    }
  | { id: string; role: "ask"; question: string; options: { id: string; label: string }[]; current?: boolean };

export type FlowCodexLineage = {
  sourceCodexThreadId?: string;
  sourceCodexTurnId?: string;
  sourceCodexItemId?: string;
};

export const STEP_INITIAL = ["识别业务口径", "查询可用数据表", "生成并校验 SQL", "整理图表与结论"];

export function useFlow(threadKey: string | null, initial: FlowNode[] = []) {
  const agent = useMemo(() => getAgentClient(), []);
  const [turnId, setTurnId] = useState<string | null>(threadKey);
  const [threadId, setThreadId] = useState<string | null>(threadKey);
  const [nodes, setNodes] = useState<FlowNode[]>(initial);
  const [artifacts, setArtifacts] = useState<ArtifactFolder[]>([]);
  const [reportArtifact, setReportArtifact] = useState<InteractiveReport | null>(null);
  const [codexLineage, setCodexLineage] = useState<FlowCodexLineage>({});
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);

  useEffect(() => {
    cancelled = false;
    setTurnId(threadKey);
    setThreadId(threadKey);
    setNodes([...initial]);
    setArtifacts([]);
    setReportArtifact(null);
    setCodexLineage({});
    setRunning(false);
    runningRef.current = false;
    agent.cancel?.();
    return () => { cancelled = true; };
  }, [agent, threadKey, initial]);

  const applyEvent = useCallback((event: AgentEvent, currentNodes: FlowNode[]): FlowNode[] => {
    if (event.turnId) setTurnId(event.turnId);
    if (event.threadId) setThreadId(event.threadId);
    updateCodexLineage(event, setCodexLineage);

    if (event.type === "user") {
      const userNode: FlowNode = { id: event.nodeId, role: "user", content: cleanDisplayText(event.content) };
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
          const itemId = getAgentEventItemId(event);
          const itemChanged = Boolean(itemId && target.activeItemId && itemId !== target.activeItemId);
          const content = cleanDisplayText(event.content);
          if (isDuplicateAgentContent(target.content, content)) {
            next[existing] = { ...target, mode: event.mode };
          } else {
            const withArchivedMessage = itemChanged ? archiveAgentMessage(target) : target;
            next[existing] = {
              ...withArchivedMessage,
              content,
              mode: event.mode,
              activeItemId: itemId ?? withArchivedMessage.activeItemId,
            };
          }
        }
      } else {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: cleanDisplayText(event.content),
          mode: event.mode,
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "thinking") {
      const pendingIndex = currentNodes.findIndex((node) => node.id === "agent-pending");
      if (pendingIndex >= 0) {
        const thinkingNode: FlowNode = {
          id: event.nodeId,
          role: "agent",
          content: "思考中...",
          mode: "replace",
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        };
        const next = currentNodes.map((node, index) => (index === pendingIndex ? thinkingNode : node));
        setNodes(next);
        return next;
      }

      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const exactIndex = next.findIndex((node) => node.id === event.nodeId && node.role === "agent");
      const reverseIndex = [...next].reverse().findIndex((node) => node.role === "agent");
      const targetIndex = exactIndex >= 0 ? exactIndex : reverseIndex >= 0 ? next.length - 1 - reverseIndex : -1;
      if (targetIndex >= 0) {
        const target = next[targetIndex];
        if (target.role === "agent") {
          const withArchivedMessage = target.content.trim() && target.content !== "思考中..."
            ? archiveAgentMessage(target)
            : target;
          next[targetIndex] = {
            ...withArchivedMessage,
            id: event.nodeId,
            content: "思考中...",
            mode: "replace",
            activeItemId: getAgentEventItemId(event) ?? withArchivedMessage.activeItemId,
          };
        }
      } else {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: "思考中...",
          mode: "replace",
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        });
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
          content: cleanDisplayText(event.text),
          mode: "delta",
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
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
          const itemId = getAgentEventItemId(event);
          const itemChanged = Boolean(itemId && target.activeItemId && itemId !== target.activeItemId);
          const withArchivedMessage = itemChanged ? archiveAgentMessage(target) : target;
          next[idx] = {
            ...withArchivedMessage,
            content: withArchivedMessage.content + cleanDisplayText(event.text),
            activeItemId: itemId ?? withArchivedMessage.activeItemId,
          };
        }
      } else {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: cleanDisplayText(event.text),
          mode: "delta",
          steps: [],
          activity: [],
          activeItemId: getAgentEventItemId(event),
        });
      }
      setNodes(next);
      return next;
    }

    if (event.type === "step") {
      const next: FlowNode[] = currentNodes.map((node) => ({ ...node }) as FlowNode);
      const exactIndex = event.nodeId
        ? next.findIndex((node) => node.id === event.nodeId && node.role === "agent")
        : -1;
      const reverseIndex = [...next].reverse().findIndex((node) => node.role === "agent");
      const targetIndex = exactIndex >= 0 ? exactIndex : reverseIndex >= 0 ? next.length - 1 - reverseIndex : -1;
      if (targetIndex >= 0) {
        const target = next[targetIndex];
        if (target.role === "agent") {
          const withArchivedMessage = target.id === "agent-pending"
            ? { ...target, content: "", activity: [] }
            : archiveAgentMessage(target);
          const steps = [...(target.steps ?? [])];
          const existing = steps.findIndex((s) => (
            event.itemId
              ? s.itemId === event.itemId
              : s.label === event.label && s.detail === event.detail
          ));
          if (existing >= 0) {
            steps[existing] = { label: event.label, state: event.state, detail: event.detail, itemId: event.itemId };
          } else {
            steps.push({ label: event.label, state: event.state, detail: event.detail, itemId: event.itemId });
          }
          const activity = [...(withArchivedMessage.activity ?? [])];
          const activityIndex = activity.findIndex((item) => item.kind === "tool" && (
            event.itemId ? item.itemId === event.itemId : item.label === event.label && item.detail === event.detail
          ));
          const toolActivity: Extract<FlowActivity, { kind: "tool" }> = {
            kind: "tool",
            label: event.label,
            state: event.state,
            detail: event.detail,
            itemId: event.itemId,
          };
          if (activityIndex >= 0) activity[activityIndex] = toolActivity;
          else appendToolActivity(activity, toolActivity);
          next[targetIndex] = { ...withArchivedMessage, id: event.nodeId ?? target.id, steps, activity };
        }
      } else if (event.nodeId) {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: "",
          mode: "delta",
          steps: [{ label: event.label, state: event.state, detail: event.detail, itemId: event.itemId }],
          activity: [{ kind: "tool", label: event.label, state: event.state, detail: event.detail, itemId: event.itemId }],
        });
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
      const errorNode: FlowNode = { id: `agent-error-${Date.now()}`, role: "agent", content: cleanDisplayText(event.message), mode: "replace" };
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
    runningRef.current = true;
    let snapshot: FlowNode[] = withOptimisticTurn(nodes, input);
    if (snapshot !== nodes) setNodes(snapshot);
    try {
      const inputWithThread = input.kind === "reset" || input.threadId
        ? input
        : { ...input, threadId };
      for await (const event of agent.send(inputWithThread)) {
        if (cancelled) break;
        snapshot = applyEvent(event, snapshot);
      }
    } finally {
      setRunning(false);
      runningRef.current = false;
    }
  }, [agent, applyEvent, nodes, threadId]);

  const start = useCallback((question?: string) => consume({ kind: "start", question }), [consume]);
  const send = useCallback((content: string) => consume({ kind: "message", content }), [consume]);
  const reply = useCallback((optionId: string) => consume({ kind: "reply", optionId }), [consume]);
  const stop = useCallback(() => {
    if (!runningRef.current) return;
    agent.cancel?.();
    runningRef.current = false;
    setRunning(false);
    setNodes((current) => current.filter((node) => node.id !== "agent-pending"));
  }, [agent]);

  return {
    turnId,
    threadId,
    nodes,
    artifacts,
    reportArtifact,
    codexLineage,
    running,
    start,
    send,
    reply,
    stop,
  };
}

let cancelled = false;

function isDuplicateAgentContent(currentContent: string, nextContent: string): boolean {
  return Boolean(currentContent && nextContent && currentContent.includes(nextContent));
}

function cleanDisplayText(value: string): string {
  return value.replace(/\uFFFD+/g, "");
}

function withOptimisticTurn(nodes: FlowNode[], input: AgentInput): FlowNode[] {
  const content = input.kind === "start" ? input.question : input.kind === "message" ? input.content : "";
  if (!content || nodes.some((node) => node.id === "user-pending" || node.id === "agent-pending")) return nodes;
  return [
    ...nodes,
    { id: "user-pending", role: "user", content: cleanDisplayText(content) },
    { id: "agent-pending", role: "agent", content: "正在思考...", mode: "replace", steps: [] },
  ];
}

function getAgentEventItemId(event: AgentEvent): string | undefined {
  return event.codexItemId ?? event.itemId;
}

function archiveAgentMessage(node: Extract<FlowNode, { role: "agent" }>): Extract<FlowNode, { role: "agent" }> {
  if (!node.content.trim()) return node;
  const activity = [...(node.activity ?? [])];
  const existing = activity.findIndex((item) => item.kind === "message" && node.activeItemId && item.itemId === node.activeItemId);
  const message: FlowActivity = { kind: "message", content: node.content, itemId: node.activeItemId };
  if (existing >= 0) activity[existing] = message;
  else activity.push(message);
  return { ...node, content: "", activity };
}

function appendToolActivity(activity: FlowActivity[], toolActivity: Extract<FlowActivity, { kind: "tool" }>): void {
  const previous = activity.at(-1);
  if (
    previous?.kind === "tool"
    && previous.label === toolActivity.label
    && previous.state === toolActivity.state
  ) {
    const details = [
      ...(previous.details ?? (previous.detail ? [previous.detail] : [])),
      ...(toolActivity.detail ? [toolActivity.detail] : []),
    ];
    activity[activity.length - 1] = {
      ...previous,
      count: (previous.count ?? 1) + 1,
      details,
    };
    return;
  }
  activity.push(toolActivity);
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
