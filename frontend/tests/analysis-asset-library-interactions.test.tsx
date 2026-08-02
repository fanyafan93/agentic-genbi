/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { AnalysisAssetLibrary } from "../src/modules/analysis/components/AnalysisAssetLibrary";
import { AnalysisAssetLibraryPage } from "../src/modules/analysis/components/AnalysisAssetLibraryPage";
import { saveAnalysisAssetMock } from "../src/modules/analysis/components/analysis-asset-contracts";
import type { AnalysisAssetCard } from "../src/modules/analysis/components/analysis-assets";
import type { AnalysisAssetSaveRequest, AnalysisAssetSourceContext } from "../src/modules/analysis/components/analysis-asset-contracts";
import type { ArtifactFile, ArtifactFolder } from "../src/modules/analysis/types/artifact";

const reportFile: ArtifactFile = {
  id: "reports-analysis-report-html",
  name: "analysis_report.html",
  kind: "html",
};

const sqlFile: ArtifactFile = {
  id: "queries-candidate-sql",
  name: "candidate.sql",
  kind: "sql",
};

const folders: ArtifactFolder[] = [
  { id: "reports", name: "reports", children: [reportFile] },
  { id: "queries", name: "queries", children: [sqlFile] },
];

const sourceContext: AnalysisAssetSourceContext = {
  sourceTaskId: "analysis_task_turn_analysis_interaction",
  sourceConversationId: "thread_analysis_interaction",
  sourceCodexThreadId: "codex_thread_interaction",
  sourceCodexTurnId: "codex_turn_interaction",
};

function renderLibrary(options: {
  savedAssetIds?: string[];
  lastSaveRequest?: AnalysisAssetSaveRequest;
  onSaveAsset?: (asset: AnalysisAssetCard) => void;
  onContinueFromAsset?: (asset: AnalysisAssetCard) => void;
} = {}) {
  return render(
    <AnalysisAssetLibrary
      taskTitle="首购后 30 天复购率"
      sourceContext={sourceContext}
      folders={folders}
      files={[reportFile, sqlFile]}
      openFileIds={[]}
      expandedFolders={{ reports: true, queries: true }}
      savedAssetIds={options.savedAssetIds ?? []}
      explorerCollapsed={false}
      mobileHidden={false}
      lastSaveRequest={options.lastSaveRequest}
      onToggleExplorer={vi.fn()}
      onToggleFolder={vi.fn()}
      onOpenFile={vi.fn()}
      onActivateFile={vi.fn()}
      onCloseFile={vi.fn()}
      onSaveAsset={options.onSaveAsset ?? vi.fn()}
      onContinueFromAsset={options.onContinueFromAsset ?? vi.fn()}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("AnalysisAssetLibrary interactions", () => {
  test("keeps the task-side library focused on current analysis assets", () => {
    vi.stubEnv("NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME", "mock");
    const onSaveAsset = vi.fn();
    const onContinueFromAsset = vi.fn();
    const view = renderLibrary({ onSaveAsset, onContinueFromAsset });

    const saveButton = view.container.querySelector<HTMLButtonElement>(".asset-card-action");
    expect(saveButton).not.toBeNull();
    fireEvent.click(saveButton!);

    expect(onSaveAsset).toHaveBeenCalledTimes(1);
    const savedAsset = onSaveAsset.mock.calls[0][0] as AnalysisAssetCard;
    expect(savedAsset.id).toBe("report");

    const saveResult = saveAnalysisAssetMock(savedAsset, "首购后 30 天复购率", sourceContext);
    view.rerender(
      <AnalysisAssetLibrary
        taskTitle="首购后 30 天复购率"
        sourceContext={sourceContext}
        folders={folders}
        files={[reportFile, sqlFile]}
        openFileIds={[]}
        expandedFolders={{ reports: true, queries: true }}
        savedAssetIds={["report"]}
        explorerCollapsed={false}
        mobileHidden={false}
        lastSaveRequest={saveResult.request}
        onToggleExplorer={vi.fn()}
        onToggleFolder={vi.fn()}
        onOpenFile={vi.fn()}
        onActivateFile={vi.fn()}
        onCloseFile={vi.fn()}
        onSaveAsset={onSaveAsset}
        onContinueFromAsset={onContinueFromAsset}
      />,
    );

    expect(view.container.textContent).toContain("MOCK SAVE PAYLOAD");
    expect(view.container.textContent).toContain("asset_mock_report");
    expect(view.container.textContent).toContain("thread_analysis_interaction");
    expect(view.container.textContent).toContain("当前任务资产");
    expect(view.container.textContent).not.toContain("共享资产库");
    expect(view.container.querySelector(".asset-library-view-switch")).toBeNull();
    vi.unstubAllEnvs();
  });

  test("shows reusable assets in the standalone analysis asset library and can continue from one", async () => {
    const onContinueFromAsset = vi.fn();
    const view = render(<AnalysisAssetLibraryPage onContinueFromAsset={onContinueFromAsset} />);

    expect(view.container.textContent).toContain("分析资产库");
    expect(view.container.textContent).toContain("共享分析资产库");
    expect(view.container.textContent).toContain("首购后 30 天复购率分析报告");
    expect(view.container.textContent).toContain("SKILL.md");
    expect(view.container.textContent).toContain("来源任务");
    expect(view.container.textContent).toContain("可见范围");

    const sharedActions = view.container.querySelectorAll<HTMLButtonElement>(".shared-asset-actions button");
    fireEvent.click(sharedActions[1]);

    await waitFor(() => expect(onContinueFromAsset).toHaveBeenCalledTimes(1));
    const continuedAsset = onContinueFromAsset.mock.calls[0][0] as AnalysisAssetCard;
    expect(continuedAsset.id).toBe("asset_shared_rebuy_report");
  });
});
