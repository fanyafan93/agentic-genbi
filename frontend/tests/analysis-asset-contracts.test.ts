import { describe, expect, test } from "vitest";
import { buildMockAnalysisAssetLibraryEntries, saveAnalysisAssetMock } from "../src/modules/analysis/components/analysis-asset-contracts";
import type { AnalysisAssetCard } from "../src/modules/analysis/components/analysis-assets";

const reportAsset: AnalysisAssetCard = {
  id: "report",
  title: "analysis report",
  label: "report",
  description: "shareable analysis conclusion",
  status: "draft",
  intent: "save",
  fileId: "reports-quick-report-html",
};

const sourceContext = {
  sourceTaskId: "analysis_task_turn_abc123",
  sourceConversationId: "thread_abc123",
  sourceCodexThreadId: "codex_thread_abc123",
  sourceCodexTurnId: "codex_turn_abc123",
  sourceCodexItemId: "codex_item_report",
};

describe("analysis asset contract helpers", () => {
  test("save requests preserve the Codex source context", () => {
    const result = saveAnalysisAssetMock(reportAsset, "channel sales share", sourceContext);

    expect(result.request.sourceTaskId).toBe(sourceContext.sourceTaskId);
    expect(result.request.sourceConversationId).toBe(sourceContext.sourceConversationId);
    expect(result.request.sourceCodexThreadId).toBe(sourceContext.sourceCodexThreadId);
    expect(result.request.sourceCodexTurnId).toBe(sourceContext.sourceCodexTurnId);
    expect(result.request.sourceCodexItemId).toBe(sourceContext.sourceCodexItemId);
    expect(result.request.reopenContext.sourceTaskId).toBe(sourceContext.sourceTaskId);
    expect(result.request.reopenContext.sourceConversationId).toBe(sourceContext.sourceConversationId);
    expect(result.request.reopenContext.sourceCodexThreadId).toBe(sourceContext.sourceCodexThreadId);
    expect(result.request.reopenContext.sourceCodexTurnId).toBe(sourceContext.sourceCodexTurnId);
    expect(result.request.reopenContext.sourceCodexItemId).toBe(sourceContext.sourceCodexItemId);
  });

  test("shared entries are derived from saved assets and the supplied source context", () => {
    const entries = buildMockAnalysisAssetLibraryEntries({
      taskTitle: "channel sales share",
      sourceContext,
      assets: [reportAsset],
      savedAssetIds: ["report"],
    });

    expect(entries).toHaveLength(1);
    expect(entries[0].sourceTaskTitle).toBe("channel sales share");
    expect(entries[0].sourceTaskId).toBe(sourceContext.sourceTaskId);
    expect(entries[0].sourceCodexItemId).toBe(sourceContext.sourceCodexItemId);
    expect(entries[0].reopenContext.targetFileId).toBe("reports-quick-report-html");
  });
});
