import type { InteractiveReport } from "../types/interactive-report";

const storageKey = "agentic-genbi.mock.interactive-reports.v1";

export type SavedInteractiveReport = {
  report: InteractiveReport;
  version: number;
  savedAt: string;
};

export function loadSavedInteractiveReports(): SavedInteractiveReport[] {
  if (typeof window === "undefined") return [];
  try {
    const value = window.localStorage.getItem(storageKey);
    if (!value) return [];
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed as SavedInteractiveReport[] : [];
  } catch {
    return [];
  }
}

export function saveInteractiveReport(report: SavedInteractiveReport): SavedInteractiveReport[] {
  const current = loadSavedInteractiveReports();
  const next = [report, ...current.filter((item) => item.report.id !== report.report.id)];
  if (typeof window !== "undefined") window.localStorage.setItem(storageKey, JSON.stringify(next));
  return next;
}
