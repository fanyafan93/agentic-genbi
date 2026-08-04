"use client";

import { useEffect, useState } from "react";
import {
  flowNodesFromBackendThread,
  getBackendAnalysisThread,
  type BackendAnalysisThreadDetail,
  type BackendAnalysisThreadSummary,
} from "../agentClients/backendClient";
import type { FlowNode } from "./use-turn-execution";

export type TaskDetailState = {
  /** The thread summary as last loaded. ``null`` until first load completes. */
  thread: BackendAnalysisThreadSummary | null;
  /** Hydrated timeline of turns + tool projections for the renderer. */
  nodes: FlowNode[];
  /** ``true`` while a request is in flight. */
  loading: boolean;
  /** Last error message, or ``null`` if no error. */
  error: string | null;
  /** Bumped every time a refresh kicks off; consumers can use this to dedupe. */
  requestId: number;
};

/**
 * Read-only hydration of a task's persisted history.
 *
 * Decoupled from ``useTurnExecution``: this hook only reads, it never
 * aborts a live stream. Changing ``taskId`` kicks off a fresh fetch;
 * the in-flight stream on the previous task is left alone.
 */
export function useTaskDetail(taskId: string | null): TaskDetailState {
  const [thread, setThread] = useState<BackendAnalysisThreadSummary | null>(null);
  const [nodes, setNodes] = useState<FlowNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState(0);

  useEffect(() => {
    if (!taskId) {
      setThread(null);
      setNodes([]);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    const currentRequest = requestId + 1;
    setRequestId(currentRequest);
    setLoading(true);
    setError(null);
    getBackendAnalysisThread(taskId)
      .then((detail) => {
        if (cancelled) return;
        setThread(detail.thread);
        setNodes(flowNodesFromBackendThread(detail));
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "加载历史任务失败");
        setThread(null);
        setNodes([]);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  return { thread, nodes, loading, error, requestId };
}
