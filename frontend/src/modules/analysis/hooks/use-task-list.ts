"use client";

import { useEffect, useState } from "react";
import {
  listBackendAnalysisThreads,
  shouldUseBackendAnalysisClient,
  type BackendAnalysisThreadSummary,
} from "../agentClients/backendClient";

export type TaskListState = {
  threads: BackendAnalysisThreadSummary[];
  loading: boolean;
  error: string | null;
  /** Re-fetch the list. Each call returns a new ``requestId`` for deduping. */
  refresh: () => Promise<void>;
  /** Inject a thread into the list (e.g. right after a successful create). */
  upsert: (thread: BackendAnalysisThreadSummary) => void;
};

/**
 * Source of truth for the left-side "analysis tasks" sidebar.
 *
 * Owned by the workspace. Switching the active task on the canvas does
 * NOT re-fetch this list — the list and the canvas are separate.
 */
export function useTaskList(): TaskListState {
  const [threads, setThreads] = useState<BackendAnalysisThreadSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState(0);

  useEffect(() => {
    if (!shouldUseBackendAnalysisClient()) {
      setThreads([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    listBackendAnalysisThreads()
      .then((rows) => {
        if (cancelled) return;
        setThreads(rows);
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "加载分析任务列表失败");
        setThreads([]);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requestId]);

  const refresh = async () => {
    setRequestId((id) => id + 1);
  };

  const upsert = (thread: BackendAnalysisThreadSummary) => {
    setThreads((current) => {
      const existing = current.find((item) => item.id === thread.id);
      if (existing) {
        return current.map((item) => (item.id === thread.id ? thread : item));
      }
      return [thread, ...current];
    });
  };

  return { threads, loading, error, refresh, upsert };
}
