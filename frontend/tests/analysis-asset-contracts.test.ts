import { describe, expect, test } from "vitest";
import { buildMockAnalysisAssetLibraryEntries, saveAnalysisAssetMock } from "../src/modules/analysis/components/analysis-asset-contracts";
import type { AnalysisAssetCard } from "../src/modules/analysis/components/analysis-assets";

const reportAsset: AnalysisAssetCard = {
  id: "report",
  title: "分析报告",
  label: "报告",
  description: "可分享给业务方的结论页",
  status: "draft",
  intent: "save",
  fileId: "reports-quick-report-html",
};

const sourceContext = {
  sourceTaskId: "analysis_task_run_analysis_abc123",
  sourceConversationId: "run_analysis_abc123",
  sourceRunId: "run_analysis_abc123",
};

describe("analysis asset contract helpers", () => {
  test("save requests preserve the current analysis task source context", () => {
    const result = saveAnalysisAssetMock(reportAsset, "首购后30天复购率", sourceContext);

    expect(result.request.sourceTaskId).toBe(sourceContext.sourceTaskId);
    expect(result.request.sourceConversationId).toBe(sourceContext.sourceConversationId);
    expect(result.request.sourceRunId).toBe(sourceContext.sourceRunId);
    expect(result.request.reopenContext.sourceTaskId).toBe(sourceContext.sourceTaskId);
    expect(result.request.reopenContext.sourceConversationId).toBe(sourceContext.sourceConversationId);
    expect(result.request.reopenContext.sourceRunId).toBe(sourceContext.sourceRunId);
  });

  test("shared entries are derived from saved assets and the supplied source context", () => {
    const entries = buildMockAnalysisAssetLibraryEntries({
      taskTitle: "首购后30天复购率",
      sourceContext,
      assets: [reportAsset],
      savedAssetIds: ["report"],
    });

    expect(entries).toHaveLength(1);
    expect(entries[0].sourceTaskTitle).toBe("首购后30天复购率");
    expect(entries[0].sourceTaskId).toBe(sourceContext.sourceTaskId);
    expect(entries[0].reopenContext.targetFileId).toBe("reports-quick-report-html");
  });
});
