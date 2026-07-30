import { afterEach, describe, expect, test, vi } from "vitest";
import {
  listAnalysisAssetsFromBackend,
  reopenAnalysisAssetFromBackend,
  saveAnalysisAssetToBackend,
  shouldUseBackendAnalysisAssetLibrary,
} from "../src/modules/analysis/api/analysis-asset-library-service";
import type { AnalysisAssetSaveRequest } from "../src/modules/analysis/components/analysis-asset-contracts";

const saveRequest: AnalysisAssetSaveRequest = {
  assetId: "asset_mock_report",
  artifactVersionId: "artifact_version_mock_report_v1",
  sourceTaskId: "analysis_task_run_analysis_abc",
  sourceTaskTitle: "first purchase repurchase",
  sourceConversationId: "conv_analysis_abc",
  sourceRunId: "run_analysis_abc",
  assetType: "report",
  title: "quick_report.html",
  visibility: "team",
  saveReason: "user_confirmed",
  reopenContext: {
    sourceTaskId: "analysis_task_run_analysis_abc",
    sourceConversationId: "conv_analysis_abc",
    sourceRunId: "run_analysis_abc",
    continuationPrompt: "continue from quick report",
    targetFileId: "reports-quick-report-html",
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
      new Response(
        JSON.stringify({
          asset: {
            ...saveRequest,
            label: "report",
            description: "quick_report.html",
            status: "saved",
            latestVersion: "v1-draft",
            fileId: "reports-quick-report-html",
          },
          savedAt: "2026-07-30T20:30:00+08:00",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await saveAnalysisAssetToBackend(saveRequest);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("http://192.168.101.12:8000/api/analysis/assets");
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.assetId).toBe("asset_mock_report");
    expect(body.sourceConversationId).toBe("conv_analysis_abc");
    expect(body.reopenContext.targetFileId).toBe("reports-quick-report-html");
    expect(body.status).toBe("saved");
    expect(result.asset.assetId).toBe("asset_mock_report");
  });

  test("lists and reopens backend analysis assets", async () => {
    vi.stubEnv("NEXT_PUBLIC_GENBI_API_BASE_URL", "http://192.168.101.12:8000");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            assets: [
              {
                ...saveRequest,
                label: "report",
                description: "quick_report.html",
                status: "saved",
                latestVersion: "v1-draft",
                fileId: "reports-quick-report-html",
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            context: saveRequest.reopenContext,
            assetId: saveRequest.assetId,
            artifactVersionId: saveRequest.artifactVersionId,
            openedAt: "2026-07-30T20:40:00+08:00",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    const listed = await listAnalysisAssetsFromBackend({ sourceTaskId: saveRequest.sourceTaskId, limit: 10 });
    const reopened = await reopenAnalysisAssetFromBackend(saveRequest.assetId);

    expect(fetchMock.mock.calls[0][0].toString()).toBe(
      "http://192.168.101.12:8000/api/analysis/assets?source_task_id=analysis_task_run_analysis_abc&limit=10",
    );
    expect(fetchMock.mock.calls[1][0]).toBe("http://192.168.101.12:8000/api/analysis/assets/asset_mock_report/reopen");
    expect(listed.assets[0].sourceConversationId).toBe("conv_analysis_abc");
    expect(reopened.context.continuationPrompt).toBe("continue from quick report");
  });
});
