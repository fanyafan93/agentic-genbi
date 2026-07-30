/**
 * @vitest-environment jsdom
 */
import { cleanup, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { AnalysisAssetLibrary } from "../src/modules/analysis/components/AnalysisAssetLibrary";
import { saveAnalysisAssetMock } from "../src/modules/analysis/components/analysis-asset-contracts";
import type { AnalysisAssetCard } from "../src/modules/analysis/components/analysis-assets";
import type { AnalysisAssetSaveRequest, AnalysisAssetSourceContext } from "../src/modules/analysis/components/analysis-asset-contracts";
import type { ArtifactFile, ArtifactFolder } from "../src/modules/analysis/types/artifact";

const reportFile: ArtifactFile = {
  id: "reports-quick-report-html",
  name: "quick_report.html",
  kind: "html",
};

const sqlFile: ArtifactFile = {
  id: "queries-quick-candidate-sql",
  name: "quick_candidate.sql",
  kind: "sql",
};

const folders: ArtifactFolder[] = [
  { id: "reports", name: "reports", children: [reportFile] },
  { id: "queries", name: "queries", children: [sqlFile] },
];

const sourceContext: AnalysisAssetSourceContext = {
  sourceTaskId: "analysis_task_run_analysis_interaction",
  sourceConversationId: "conv_analysis_interaction",
  sourceRunId: "run_analysis_interaction",
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
  test("saves a report asset with current source context and reopens it from the shared view", () => {
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
    expect(view.container.textContent).toContain("conv_analysis_interaction");

    const sharedTab = view.container.querySelectorAll<HTMLButtonElement>(".asset-library-view-switch button")[1];
    expect(sharedTab).not.toBeNull();
    fireEvent.click(sharedTab!);

    expect(view.container.textContent).toContain("SHARED ASSETS");
    expect(view.container.textContent).toContain("asset_mock_report");
    expect(view.container.textContent).toContain("run_analysis_interaction");

    const sharedActions = view.container.querySelectorAll<HTMLButtonElement>(".shared-asset-actions button");
    expect(sharedActions.length).toBeGreaterThanOrEqual(2);
    fireEvent.click(sharedActions[1]);

    expect(onContinueFromAsset).toHaveBeenCalledTimes(1);
    const continuedAsset = onContinueFromAsset.mock.calls[0][0] as AnalysisAssetCard;
    expect(continuedAsset.id).toBe("report");
    vi.unstubAllEnvs();
  });

  test("loads shared assets from backend and reopens backend context", async () => {
    vi.stubEnv("NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME", "backend");
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const onContinueFromAsset = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            assets: [
              {
                assetId: "asset_backend_report",
                artifactVersionId: "artifact_version_backend_report_v1",
                sourceTaskId: sourceContext.sourceTaskId,
                sourceTaskTitle: "首购后 30 天复购率",
                sourceConversationId: sourceContext.sourceConversationId,
                sourceRunId: sourceContext.sourceRunId,
                assetType: "报告",
                title: "后端保存的分析报告",
                label: "报告",
                description: "来自后端资产索引",
                visibility: "team",
                status: "saved",
                latestVersion: "v1-draft",
                fileId: "reports-quick-report-html",
                reopenContext: {
                  ...sourceContext,
                  continuationPrompt: "continue from backend report",
                  targetFileId: "reports-quick-report-html",
                },
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            context: {
              ...sourceContext,
              continuationPrompt: "continue from backend report",
              targetFileId: "reports-quick-report-html",
            },
            assetId: "asset_backend_report",
            artifactVersionId: "artifact_version_backend_report_v1",
            openedAt: "2026-07-30T20:45:00+08:00",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const view = renderLibrary({ savedAssetIds: [], onContinueFromAsset });

    const sharedTab = view.container.querySelectorAll<HTMLButtonElement>(".asset-library-view-switch button")[1];
    fireEvent.click(sharedTab!);

    await waitFor(() => expect(view.container.textContent).toContain("后端资产索引已连接"));
    expect(view.container.textContent).toContain("后端保存的分析报告");
    expect(fetchMock.mock.calls[0][0].toString()).toBe("http://192.168.101.12:8000/api/analysis/assets?limit=50");

    const sharedActions = view.container.querySelectorAll<HTMLButtonElement>(".shared-asset-actions button");
    fireEvent.click(sharedActions[1]);

    await waitFor(() => expect(onContinueFromAsset).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[1][0]).toBe("http://192.168.101.12:8000/api/analysis/assets/asset_backend_report/reopen");
    const continuedAsset = onContinueFromAsset.mock.calls[0][0] as AnalysisAssetCard;
    expect(continuedAsset.id).toBe("report");
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });
});
