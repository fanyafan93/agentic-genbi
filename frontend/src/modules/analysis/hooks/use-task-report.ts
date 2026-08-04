"use client";

import { useEffect, useState } from "react";
import {
  listInteractiveReportsByThreadFromBackend,
  shouldUseBackendInteractiveReports,
  type SavedInteractiveReport,
} from "../api/interactive-report-service";

export type TaskReportState = {
  savedReports: SavedInteractiveReport[];
  loading: boolean;
  error: string | null;
  /**
   * ``reportId`` can be ``null`` to read the latest version; the
   * workspace passes an explicit id when the user opens a saved snapshot.
   */
  refresh: (reportId?: string | null) => Promise<void>;
};

/**
 * Read-only list of saved interactive reports for a single task.
 *
 * Lives next to ``useTaskDetail`` and ``useTurnExecution``; none of
 * the three aborts another's request. ``useTurnExecution`` is the
 * single owner of the in-flight SSE controller.
 */
export function useTaskReport(taskId: string | null): TaskReportState {
  const [savedReports, setSavedReports] = useState<SavedInteractiveReport[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId || !shouldUseBackendInteractiveReports()) {
      setSavedReports([]);
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    listInteractiveReportsByThreadFromBackend(taskId)
      .then((reports) => {
        if (cancelled) return;
        setSavedReports(reports);
      })
      .catch((loadError: unknown) => {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : "加载报表失败");
        setSavedReports([]);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [taskId]);

  const refresh = async (_reportId?: string | null) => {
    if (!taskId) return;
    if (!shouldUseBackendInteractiveReports()) return;
    setLoading(true);
    try {
      const reports = await listInteractiveReportsByThreadFromBackend(taskId);
      setSavedReports(reports);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "加载报表失败");
    } finally {
      setLoading(false);
    }
  };

  return { savedReports, loading, error, refresh };
}
