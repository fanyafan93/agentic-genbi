"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { createBackendAnalysisAgentClient } from "@/modules/analysis/agentClients/backendClient";
import type { AgentClient, AgentEvent, AgentInput } from "@/modules/analysis/agentClients";
import type { ArtifactFolder, ArtifactKind } from "../types/artifact";
import type { InteractiveReport } from "../types/interactive-report";

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
      thinking?: boolean;
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

/**
 * One in-flight AbortController per task. Cancellation is keyed by
 * taskId rather than by a global counter, so cancelling task A never
 * touches task B even if both are currently streaming.
 */
type Controllers = Map<string, AbortController>;

export type TurnExecution = {
  nodes: FlowNode[];
  artifacts: ArtifactFolder[];
  reportArtifact: InteractiveReport | null;
  codexLineage: FlowCodexLineage;
  running: boolean;
  start: (question: string | undefined, taskId: string, threadId: string) => Promise<void>;
  send: (content: string, taskId: string, threadId: string) => Promise<void>;
  reply: (optionId: string, taskId: string, threadId: string) => Promise<void>;
  stop: (taskId: string) => void;
  /**
   * Replace the rendered nodes with a historical snapshot. Used by the
   * workspace to hydrate the timeline after ``useTaskDetail`` finishes
   * loading.
   */
  replaceNodes: (next: FlowNode[]) => void;
};

/**
 * Hook for the **currently running turn** of a single analysis task.
 *
 * Owns:
 *  - the per-task ``AbortController`` (created fresh on every
 *    ``start``/``send``/``reply`` so the SSE stream can be aborted
 *    without leaking to siblings);
 *  - the optimistic ``user-pending`` / ``agent-pending`` placeholders;
 *  - the live ``nodes`` / ``artifacts`` / ``reportArtifact`` / ``codexLineage``
 *    state for the SSE response.
 *
 * Does NOT own:
 *  - the thread's history (that is ``useTaskDetail``);
 *  - the cross-task list (that is ``useTaskList``);
 *  - the saved report metadata (that is ``useTaskReport``).
 *
 * The hook does not pin a single ``taskId``; the ``start`` / ``send`` /
 * ``reply`` / ``stop`` calls accept the taskId at call time. This is
 * what lets the workspace route multiple concurrent tasks through one
 * instance.
 */
export function useTurnExecution(bootstrap: FlowNode[] = []): TurnExecution {
  const agent = useMemo<AgentClient>(() => {
    try {
      return createBackendAnalysisAgentClient();
    } catch {
      return createStubAgentClient();
    }
  }, []);

  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);
  const [nodes, setNodes] = useState<FlowNode[]>(bootstrap);
  const [artifacts, setArtifacts] = useState<ArtifactFolder[]>([]);
  const [reportArtifact, setReportArtifact] = useState<InteractiveReport | null>(null);
  const [codexLineage, setCodexLineage] = useState<FlowCodexLineage>({});

  const controllersRef = useRef<Controllers>(new Map());

  // Cleanup on unmount: cancel every in-flight task.
  useEffect(() => () => {
    abortAll(controllersRef.current);
  }, []);

  const applyEvent = useCallback((event: AgentEvent, currentNodes: FlowNode[]): FlowNode[] => {
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
              thinking: false,
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
          thinking: false,
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
          content: "",
          mode: "replace",
          thinking: true,
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
          if (target.content.trim() || (target.activity?.length ?? 0) > 0) {
            return currentNodes;
          }
          next[targetIndex] = {
            ...target,
            id: event.nodeId,
            content: "",
            mode: "replace",
            thinking: true,
            activeItemId: getAgentEventItemId(event) ?? target.activeItemId,
          };
        }
      } else {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: "",
          mode: "replace",
          thinking: true,
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
          thinking: false,
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
          const currentContent = withArchivedMessage.content;
          next[idx] = {
            ...withArchivedMessage,
            content: currentContent + cleanDisplayText(event.text),
            thinking: false,
            activeItemId: itemId ?? withArchivedMessage.activeItemId,
          };
        }
      } else {
        next.push({
          id: event.nodeId,
          role: "agent",
          content: cleanDisplayText(event.text),
          mode: "delta",
          thinking: false,
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

  const consume = useCallback(async (input: {
    kind: AgentInput["kind"];
    taskId: string;
    threadId: string;
    question?: string;
    content?: string;
    optionId?: string;
  }) => {
    const { taskId, threadId: targetThreadId } = input;
    abortAndDelete(controllersRef.current, taskId);
    const controller = new AbortController();
    controllersRef.current.set(taskId, controller);

    let snapshot: FlowNode[] = [];
    setNodes((current) => {
      snapshot = withOptimisticTurn(current, input);
      return snapshot;
    });
    runningRef.current = true;
    setRunning(true);

    try {
      const agentInput = {
        ...input,
        taskId,
        threadId: targetThreadId,
        signal: controller.signal,
      } as AgentInput;
      for await (const event of agent.send(agentInput)) {
        if (controller.signal.aborted || controllersRef.current.get(taskId) !== controller) break;
        if (event.threadId && event.threadId !== targetThreadId) continue;
        setNodes((current) => {
          snapshot = applyEvent(event, current);
          return snapshot;
        });
      }
    } finally {
      controllersRef.current.delete(taskId);
      if (controllersRef.current.size === 0) {
        setRunning(false);
        runningRef.current = false;
      }
    }
  }, [agent, applyEvent]);

  const start = useCallback(
    (question: string | undefined, taskId: string, threadId: string) =>
      consume({ kind: "start", taskId, threadId, question }),
    [consume],
  );
  const send = useCallback(
    (content: string, taskId: string, threadId: string) =>
      consume({ kind: "message", taskId, threadId, content }),
    [consume],
  );
  const reply = useCallback(
    (optionId: string, taskId: string, threadId: string) =>
      consume({ kind: "reply", taskId, threadId, optionId }),
    [consume],
  );

  const stop = useCallback((taskId: string) => {
    if (!taskId) return;
    abortAndDelete(controllersRef.current, taskId);
    if (controllersRef.current.size === 0) {
      setRunning(false);
      runningRef.current = false;
    }
    setNodes((current) => current.filter((node) => node.id !== "agent-pending"));
  }, []);

  const replaceNodes = useCallback((next: FlowNode[]) => {
    setNodes(next);
  }, []);

  return {
    nodes,
    artifacts,
    reportArtifact,
    codexLineage,
    running,
    start,
    send,
    reply,
    stop,
    replaceNodes,
  };
}

function createStubAgentClient(): AgentClient {
  return {
    async *send() {
      yield { type: "error", message: "分析后端未配置，无法继续。" };
      yield { type: "done" };
    },
  };
}

function abortAndDelete(controllers: Controllers, taskId: string): void {
  const controller = controllers.get(taskId);
  if (!controller) return;
  controllers.delete(taskId);
  if (!controller.signal.aborted) {
    controller.abort();
  }
}

function abortAll(controllers: Controllers): void {
  for (const [taskId, controller] of controllers) {
    if (!controller.signal.aborted) {
      controller.abort();
    }
    controllers.delete(taskId);
  }
}

function isDuplicateAgentContent(currentContent: string, nextContent: string): boolean {
  return Boolean(currentContent && nextContent && currentContent.includes(nextContent));
}

function cleanDisplayText(value: string): string {
  // The previous implementation silently stripped U+FFFD
  // replacement characters. That hides upstream encoding bugs
  // (latin1 bytes re-decoded as utf-8, missing fonts in the model
  // provider, etc.) and lets a report look "fine" while its text is
  // actually corrupted. We now surface the replacement char in the
  // UI and log a warning so the source of the corruption is
  // traceable. The escape pattern (\uFFFD) is intentional: the
  // character is real, the operator needs to see it.
  if (value.includes("\uFFFD") && typeof console !== "undefined") {
    // eslint-disable-next-line no-console
    console.warn(
      "use-turn-execution: received text containing U+FFFD replacement char(s). " +
        "This usually means the upstream service double-decoded text. The UI shows the character verbatim; fix the encoder at the source.",
    );
  }
  return value;
}

function withOptimisticTurn(
  nodes: FlowNode[],
  input: { kind: AgentInput["kind"]; question?: string; content?: string; optionId?: string },
): FlowNode[] {
  const content = input.kind === "start"
    ? (input.question ?? "")
    : input.kind === "message"
    ? input.content ?? ""
    : "";
  if (!content || nodes.some((node) => node.id === "user-pending" || node.id === "agent-pending")) return nodes;
  return [
    ...nodes,
    { id: "user-pending", role: "user", content: cleanDisplayText(content) },
    { id: "agent-pending", role: "agent", content: "", mode: "replace", thinking: true, steps: [] },
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
