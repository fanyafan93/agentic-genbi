import { demoRun } from "../mocks/analysis-scenarios";
import type { AnalysisRun } from "../types/analysis";

export const analysisApi = {
  async getCurrentRun(): Promise<AnalysisRun> {
    await new Promise((resolve) => setTimeout(resolve, 120));
    return demoRun;
  },
};
