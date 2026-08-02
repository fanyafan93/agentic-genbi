import { afterEach, describe, expect, test, vi } from "vitest";
import {
  getAnalysisAssetLineageFromBackend,
  listArtifactLineageFromBackend,
  listAnalysisAssetsFromBackend,
  reopenAnalysisAssetFromBackend,
  saveAnalysisAssetToBackend,
  shouldUseBackendAnalysisAssetLibrary,
} from "../src/modules/analysis/api/analysis-asset-library-service";
import type { AnalysisAssetSaveRequest } from "../src/modules/analysis/components/analysis-asset-contracts";

const saveRequest: AnalysisAssetSaveRequest = {
  assetId: "asset_mock_report",
  artifactVersionId: "artifact_version_mock_report_v1",
  sourceTaskId: "analysis_task_turn_abc",
  sourceTaskTitle: "channel sales share",
  sourceConversationId: "thread_abc",
  sourceCodexThreadId: "codex_thread_abc",
  sourceCodexTurnId: "codex_turn_abc",
  sourceCodexItemId: "codex_item_report",
  assetType: "report",
  title: "analysis_report.html",
  visibility: "team",
  saveReason: "user_confirmed",
  reopenContext: {
    sourceTaskId: "analysis_task_turn_abc",
    sourceConversationId: "thread_abc",
    continuationPrompt: "continue from analysis report",
    targetFileId: "reports-analysis-report-html",
    sourceCodexThreadId: "codex_thread_abc",
    sourceCodexTurnId: "codex_turn_abc",
    sourceCodexItemId: "codex_item_report",
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("analysis asset backend API client", () => {
  test("is enabled only when analysis backend runtime is configured", () => {
    vi.stubEnv("NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME", "mock");
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    expect(shouldUseBackendAnalysisAssetLibrary()).toBe(false);

    vi.stubEnv("NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME", "backend");
    expect(shouldUseBackendAnalysisAssetLibrary()).toBe(true);
  });

  test("posts save requests to the backend asset API", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        asset: { ...saveRequest, label: "report", description: "analysis_report.html", status: "saved", latestVersion: "v1-draft", fileId: "reports-analysis-report-html" },
        savedAt: "2026-07-30T20:30:00+08:00",
      }), { status: 200, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await saveAnalysisAssetToBackend(saveRequest);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://192.168.101.12:8000/api/analysis/assets");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.assetId).toBe("asset_mock_report");
    expect(body.sourceConversationId).toBe("thread_abc");
    expect(body.sourceCodexThreadId).toBe("codex_thread_abc");
    expect(body.sourceCodexTurnId).toBe("codex_turn_abc");
    expect(body.sourceCodexItemId).toBe("codex_item_report");
    expect(body.reopenContext.targetFileId).toBe("reports-analysis-report-html");
    expect(body.status).toBe("saved");
    expect(result.asset.assetId).toBe("asset_mock_report");
  });

  test("lists and reopens backend analysis assets", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ assets: [{ ...saveRequest, label: "report", description: "analysis_report.html", status: "saved", latestVersion: "v1-draft", fileId: "reports-analysis-report-html" }] }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ context: saveRequest.reopenContext, assetId: saveRequest.assetId, artifactVersionId: saveRequest.artifactVersionId, openedAt: "2026-07-30T20:40:00+08:00" }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const listed = await listAnalysisAssetsFromBackend({ sourceTaskId: saveRequest.sourceTaskId, limit: 10 });
    const reopened = await reopenAnalysisAssetFromBackend(saveRequest.assetId);

    expect(fetchMock.mock.calls[0][0].toString()).toBe("http://192.168.101.12:8000/api/analysis/assets?source_task_id=analysis_task_turn_abc&limit=10");
    expect(fetchMock.mock.calls[1][0]).toBe("http://192.168.101.12:8000/api/analysis/assets/asset_mock_report/reopen");
    expect(listed.assets[0].sourceConversationId).toBe("thread_abc");
    expect(reopened.context.continuationPrompt).toBe("continue from analysis report");
  });

  test("queries artifact lineage by Codex item and asset id", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const lineage = {
      artifactId: saveRequest.assetId,
      artifactVersionId: saveRequest.artifactVersionId,
      assetId: saveRequest.assetId,
      assetType: saveRequest.assetType,
      title: saveRequest.title,
      sourceTaskId: saveRequest.sourceTaskId,
      sourceConversationId: saveRequest.sourceConversationId,
      codexThreadId: saveRequest.sourceCodexThreadId,
      codexTurnId: saveRequest.sourceCodexTurnId,
      codexItemId: saveRequest.sourceCodexItemId,
      createdAt: "2026-07-30T20:30:00+08:00",
      updatedAt: "2026-07-30T20:30:00+08:00",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ lineage: [lineage] }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ lineage }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    const listed = await listArtifactLineageFromBackend({ codexItemId: "codex_item_report", limit: 5 });
    const single = await getAnalysisAssetLineageFromBackend("asset_mock_report");

    expect(fetchMock.mock.calls[0][0].toString()).toBe("http://192.168.101.12:8000/api/analysis/artifact-lineage?codex_item_id=codex_item_report&limit=5");
    expect(fetchMock.mock.calls[1][0]).toBe("http://192.168.101.12:8000/api/analysis/assets/asset_mock_report/lineage");
    expect(listed.lineage[0].codexItemId).toBe("codex_item_report");
    expect(listed.lineage[0].artifactId).toBe("asset_mock_report");
    expect(single.lineage?.assetId).toBe("asset_mock_report");
  });
});
