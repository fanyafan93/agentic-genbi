import {
  buildMockAnalysisAssetLibraryEntries,
  saveAnalysisAssetMock,
  type AnalysisAssetLibraryEntry,
  type AnalysisAssetReopenContext,
  type AnalysisAssetSaveResult,
  type AnalysisAssetSourceContext,
} from "../components/analysis-asset-contracts";
import type { AnalysisAssetCard } from "../components/analysis-assets";

export type AnalysisAssetLibraryListRequest = {
  taskTitle: string;
  sourceContext: AnalysisAssetSourceContext;
  assets: AnalysisAssetCard[];
  savedAssetIds: string[];
};

export type AnalysisAssetReopenResult = {
  context: AnalysisAssetReopenContext;
  assetId: string;
  artifactVersionId: string;
  openedAt: string;
};

export type BackendAnalysisAssetSaveResponse = {
  asset: AnalysisAssetLibraryEntry & {
    createdAt?: string;
    updatedAt?: string;
    metadata?: Record<string, unknown>;
  };
  savedAt: string;
};

export type BackendAnalysisAssetListResponse = {
  assets: BackendAnalysisAssetSaveResponse["asset"][];
};

export type AnalysisArtifactLineageRecord = {
  artifactId: string;
  artifactVersionId: string;
  assetId: string;
  assetType: string;
  title: string;
  sourceTaskId: string;
  sourceConversationId: string;
  sourceExecutionAttemptId?: string;
  sourceRunId?: string;
  codexThreadId?: string | null;
  codexTurnId?: string | null;
  codexItemId?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type BackendArtifactLineageListResponse = {
  lineage: AnalysisArtifactLineageRecord[];
};

export type BackendArtifactLineageResponse = {
  lineage: AnalysisArtifactLineageRecord | null;
};

export type AnalysisAssetLibraryService = {
  listEntries: (request: AnalysisAssetLibraryListRequest) => AnalysisAssetLibraryEntry[];
  saveAsset: (asset: AnalysisAssetCard, taskTitle: string, sourceContext: AnalysisAssetSourceContext) => AnalysisAssetSaveResult;
  reopenEntry: (entry: AnalysisAssetLibraryEntry) => AnalysisAssetReopenResult;
};

export const mockAnalysisAssetLibraryService: AnalysisAssetLibraryService = {
  listEntries(request) {
    return buildMockAnalysisAssetLibraryEntries(request);
  },
  saveAsset(asset, taskTitle, sourceContext) {
    return saveAnalysisAssetMock(asset, taskTitle, sourceContext);
  },
  reopenEntry(entry) {
    return {
      context: entry.reopenContext,
      assetId: entry.assetId,
      artifactVersionId: entry.artifactVersionId,
      openedAt: "2026-07-30T18:28:00+08:00",
    };
  },
};

export function shouldUseBackendAnalysisAssetLibrary(): boolean {
  return (
    process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME === "backend" &&
    Boolean(process.env.NEXT_PUBLIC_GENBI_API_BASE_URL)
  );
}

export function getBackendAnalysisAssetApiBaseUrl(): string | null {
  return process.env.NEXT_PUBLIC_GENBI_API_BASE_URL ?? null;
}

export async function saveAnalysisAssetToBackend(
  request: AnalysisAssetSaveResult["request"],
): Promise<BackendAnalysisAssetSaveResponse> {
  const apiBaseUrl = getBackendAnalysisAssetApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis asset API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/assets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...request,
      label: request.assetType,
      description: request.title,
      status: request.saveReason === "skill_published_mock" ? "published_mock" : "saved",
      latestVersion: request.artifactVersionId.includes("v0.1") ? "v0.1-draft" : "v1-draft",
      fileId: request.reopenContext.targetFileId,
    }),
  });
  if (!response.ok) {
    throw new Error(`Analysis asset API returned ${response.status}`);
  }
  return (await response.json()) as BackendAnalysisAssetSaveResponse;
}

export async function listAnalysisAssetsFromBackend(params: {
  sourceTaskId?: string;
  q?: string;
  limit?: number;
} = {}): Promise<BackendAnalysisAssetListResponse> {
  const apiBaseUrl = getBackendAnalysisAssetApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis asset API base URL is not configured.");
  const url = new URL(`${apiBaseUrl}/api/analysis/assets`);
  if (params.sourceTaskId) url.searchParams.set("source_task_id", params.sourceTaskId);
  if (params.q) url.searchParams.set("q", params.q);
  if (params.limit) url.searchParams.set("limit", String(params.limit));
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Analysis asset API returned ${response.status}`);
  }
  return (await response.json()) as BackendAnalysisAssetListResponse;
}

export async function reopenAnalysisAssetFromBackend(assetId: string): Promise<AnalysisAssetReopenResult> {
  const apiBaseUrl = getBackendAnalysisAssetApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis asset API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/assets/${encodeURIComponent(assetId)}/reopen`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Analysis asset API returned ${response.status}`);
  }
  return (await response.json()) as AnalysisAssetReopenResult;
}

export async function listArtifactLineageFromBackend(params: {
  artifactId?: string;
  codexThreadId?: string;
  codexTurnId?: string;
  codexItemId?: string;
  limit?: number;
} = {}): Promise<BackendArtifactLineageListResponse> {
  const apiBaseUrl = getBackendAnalysisAssetApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis asset API base URL is not configured.");
  const url = new URL(`${apiBaseUrl}/api/analysis/artifact-lineage`);
  if (params.artifactId) url.searchParams.set("artifact_id", params.artifactId);
  if (params.codexThreadId) url.searchParams.set("codex_thread_id", params.codexThreadId);
  if (params.codexTurnId) url.searchParams.set("codex_turn_id", params.codexTurnId);
  if (params.codexItemId) url.searchParams.set("codex_item_id", params.codexItemId);
  if (params.limit) url.searchParams.set("limit", String(params.limit));
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Analysis artifact lineage API returned ${response.status}`);
  }
  return (await response.json()) as BackendArtifactLineageListResponse;
}

export async function getAnalysisAssetLineageFromBackend(assetId: string): Promise<BackendArtifactLineageResponse> {
  const apiBaseUrl = getBackendAnalysisAssetApiBaseUrl();
  if (!apiBaseUrl) throw new Error("Analysis asset API base URL is not configured.");
  const response = await fetch(`${apiBaseUrl}/api/analysis/assets/${encodeURIComponent(assetId)}/lineage`);
  if (!response.ok) {
    throw new Error(`Analysis artifact lineage API returned ${response.status}`);
  }
  return (await response.json()) as BackendArtifactLineageResponse;
}
