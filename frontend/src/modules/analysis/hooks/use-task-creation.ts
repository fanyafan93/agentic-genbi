"use client";

import { useCallback, useState } from "react";
import { createBackendAnalysisTask, type BackendAnalysisThreadSummary } from "../agentClients/backendClient";

export type TaskCreationState = {
  /** ``true`` while the POST /api/analysis/tasks is in flight. */
  creating: boolean;
  /** Last error message, or ``null``. */
  error: string | null;
  /**
   * Create a new analysis task. Returns the server-issued task
   * summary. While the promise is pending, ``creating`` is ``true``
   * and the UI must NOT manufacture a draft_* placeholder.
   */
  createTask: (title: string) => Promise<BackendAnalysisThreadSummary | null>;
};

/**
 * Owns the "正在创建" state for the new-task flow.
 *
 * Splitting this out of the workspace keeps the contract clear: there
 * is no client-side taskId until this hook's promise resolves. The
 * UI is expected to show a "正在创建" placeholder during the wait.
 */
export function useTaskCreation(): TaskCreationState {
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createTask = useCallback(async (title: string) => {
    setCreating(true);
    setError(null);
    try {
      const task = await createBackendAnalysisTask(title);
      return task;
    } catch (creationError) {
      setError(creationError instanceof Error ? creationError.message : "创建分析任务失败");
      return null;
    } finally {
      setCreating(false);
    }
  }, []);

  return { creating, error, createTask };
}
