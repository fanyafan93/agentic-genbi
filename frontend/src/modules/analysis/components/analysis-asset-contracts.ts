import type { AnalysisAssetCard } from "./analysis-assets";

export type AnalysisAssetLibraryStatus = "draft" | "saved" | "reusable" | "published_mock";
export type AnalysisAssetVisibility = "private" | "team" | "org";

export type AnalysisAssetReopenContext = {
  sourceTaskId: string;
  sourceConversationId: string;
  sourceRunId: string;
  continuationPrompt: string;
  targetFileId?: string;
};

export type AnalysisAssetLibraryEntry = {
  assetId: string;
  artifactVersionId: string;
  sourceTaskId: string;
  sourceTaskTitle: string;
  sourceConversationId: string;
  sourceRunId: string;
  assetType: string;
  title: string;
  label: string;
  description: string;
  visibility: AnalysisAssetVisibility;
  status: AnalysisAssetLibraryStatus;
  latestVersion: string;
  fileId?: string;
  reopenContext: AnalysisAssetReopenContext;
};

export type AnalysisAssetSaveRequest = {
  assetId: string;
  artifactVersionId: string;
  sourceTaskId: string;
  sourceTaskTitle: string;
  sourceConversationId: string;
  sourceRunId: string;
  assetType: string;
  title: string;
  visibility: AnalysisAssetVisibility;
  saveReason: "user_confirmed" | "skill_published_mock";
  reopenContext: AnalysisAssetReopenContext;
};

export type AnalysisAssetSaveResult = {
  request: AnalysisAssetSaveRequest;
  entry: AnalysisAssetLibraryEntry;
  savedAt: string;
};

export type AnalysisAssetSourceContext = {
  sourceTaskId: string;
  sourceConversationId: string;
  sourceRunId: string;
};

type BuildMockAnalysisAssetLibraryEntriesInput = {
  taskTitle: string;
  sourceContext: AnalysisAssetSourceContext;
  assets: AnalysisAssetCard[];
  savedAssetIds: string[];
};

function getStatus(asset: AnalysisAssetCard, savedAssetIds: string[]): AnalysisAssetLibraryStatus {
  if (asset.intent === "edit-skill") return "published_mock";
  if (savedAssetIds.includes(asset.id)) return "saved";
  if (asset.status === "reusable") return "reusable";
  return "draft";
}

function getLatestVersion(asset: AnalysisAssetCard) {
  if (asset.intent === "edit-skill") return "v0.1-draft";
  return "v1-draft";
}

function getContinuationPrompt(asset: AnalysisAssetCard) {
  if (asset.intent === "edit-skill") {
    return "继续编辑 Skill.md：请基于当前分析资产，整理适用场景、需要确认的业务口径、推荐步骤和复用权限。";
  }
  return `基于分析资产「${asset.title}」继续分析，并在需要时修改相关 SQL、图表、报告或 Skill。`;
}

function buildEntry(
  asset: AnalysisAssetCard,
  taskTitle: string,
  sourceContext: AnalysisAssetSourceContext,
  savedAssetIds: string[],
): AnalysisAssetLibraryEntry {
  const sourceRunId = asset.intent === "edit-skill" ? `${sourceContext.sourceRunId}_skill` : sourceContext.sourceRunId;
  const latestVersion = getLatestVersion(asset);
  return {
    assetId: `asset_mock_${asset.id}`,
    artifactVersionId: `artifact_version_mock_${asset.id}_${latestVersion}`,
    sourceTaskId: sourceContext.sourceTaskId,
    sourceTaskTitle: taskTitle,
    sourceConversationId: sourceContext.sourceConversationId,
    sourceRunId,
    assetType: asset.label,
    title: asset.title,
    label: asset.label,
    description: asset.description,
    visibility: "team",
    status: getStatus(asset, savedAssetIds),
    latestVersion,
    fileId: asset.fileId,
    reopenContext: {
      sourceTaskId: sourceContext.sourceTaskId,
      sourceConversationId: sourceContext.sourceConversationId,
      sourceRunId,
      continuationPrompt: getContinuationPrompt(asset),
      targetFileId: asset.fileId,
    },
  };
}

export function buildMockAnalysisAssetLibraryEntries({
  taskTitle,
  sourceContext,
  assets,
  savedAssetIds,
}: BuildMockAnalysisAssetLibraryEntriesInput): AnalysisAssetLibraryEntry[] {
  return assets
    .filter((asset) => savedAssetIds.includes(asset.id) || asset.status === "reusable" || asset.intent === "edit-skill")
    .map((asset) => buildEntry(asset, taskTitle, sourceContext, savedAssetIds));
}

export function saveAnalysisAssetMock(
  asset: AnalysisAssetCard,
  taskTitle: string,
  sourceContext: AnalysisAssetSourceContext,
): AnalysisAssetSaveResult {
  const savedAssetIds = [asset.id];
  const entry = buildEntry(asset, taskTitle, sourceContext, savedAssetIds);
  const request: AnalysisAssetSaveRequest = {
    assetId: entry.assetId,
    artifactVersionId: entry.artifactVersionId,
    sourceTaskId: entry.sourceTaskId,
    sourceTaskTitle: entry.sourceTaskTitle,
    sourceConversationId: entry.sourceConversationId,
    sourceRunId: entry.sourceRunId,
    assetType: entry.assetType,
    title: entry.title,
    visibility: entry.visibility,
    saveReason: asset.intent === "edit-skill" ? "skill_published_mock" : "user_confirmed",
    reopenContext: entry.reopenContext,
  };
  return {
    request,
    entry,
    savedAt: "2026-07-30T18:18:00+08:00",
  };
}
