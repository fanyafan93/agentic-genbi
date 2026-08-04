"use client";

import { useEffect } from "react";
import type { FlowNode } from "./use-turn-execution";
import { useTaskDetail } from "./use-task-detail";
import { useTurnExecution } from "./use-turn-execution";

export type { FlowNode, FlowActivity, FlowCodexLineage } from "./use-turn-execution";

/**
 * Compose the four single-purpose hooks into a single facade.
 *
 * The facade is intentionally small: it does NOT bundle history loading
 * with turn execution. ``useTaskDetail`` reads history; ``useTurnExecution``
 * owns the live SSE. The "initial messages" prop is only used as a
 * bootstrap hint: once ``useTaskDetail`` resolves, its hydrated nodes
 * become the source of truth for the renderer.
 *
 * Code paths that previously passed ``initial`` to ``useFlow`` should
 * switch to ``useTaskDetail`` directly. The facade still accepts
 * ``initial`` for backward compatibility with existing call sites and
 * tests; the value is rendered for the first paint only.
 */
export function useFlow(threadKey: string | null, initial: FlowNode[] = []) {
  const detail = useTaskDetail(threadKey);
  const turn = useTurnExecution(initial);

  // Hydrate: when the detail hook reports a fresh snapshot, push it into
  // the live turn renderer. We only do this when there's no in-flight
  // stream — otherwise we'd clobber the streaming state.
  useEffect(() => {
    if (!threadKey) return;
    if (turn.running) return;
    if (detail.nodes.length === 0) return;
    if (sameNodes(turn.nodes, detail.nodes)) return;
    turn.replaceNodes(detail.nodes);
  }, [threadKey, detail.nodes, detail.requestId, turn.running, turn]);

  return {
    threadId: threadKey,
    nodes: turn.nodes,
    artifacts: turn.artifacts,
    reportArtifact: turn.reportArtifact,
    codexLineage: turn.codexLineage,
    running: turn.running,
    start: (question: string | undefined, taskId: string, _threadId: string) => {
      turn.start(question, taskId, _threadId);
    },
    send: (content: string, taskId: string, _threadId: string) => {
      turn.send(content, taskId, _threadId);
    },
    reply: (optionId: string, taskId: string, _threadId: string) => {
      turn.reply(optionId, taskId, _threadId);
    },
    stop: (taskId?: string) => {
      if (taskId) turn.stop(taskId);
    },
  };
}

function sameNodes(a: FlowNode[], b: FlowNode[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].id !== b[i].id) return false;
    if (a[i].role !== b[i].role) return false;
    const aNode = a[i];
    const bNode = b[i];
    const aHas = "content" in aNode;
    const bHas = "content" in bNode;
    if (aHas !== bHas) return false;
    if (aHas && bHas && aNode.content !== bNode.content) return false;
  }
  return true;
}
