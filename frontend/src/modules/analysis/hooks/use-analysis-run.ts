"use client";

import { useEffect, useState } from "react";
import { analysisApi } from "../api/analysis-api";
import type { AnalysisRun } from "../types/analysis";

export function useAnalysisRun() {
  const [run, setRun] = useState<AnalysisRun | null>(null);

  useEffect(() => {
    let alive = true;
    analysisApi.getCurrentRun().then((nextRun) => {
      if (alive) setRun(nextRun);
    });
    return () => {
      alive = false;
    };
  }, []);

  return { run, isLoading: !run };
}
