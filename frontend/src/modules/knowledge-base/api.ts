import { demoKnowledgeItems } from "./mock";
import { buildKnowledgePatch, buildKnowledgePayload, mapBackendKnowledgeRecord, type BackendKnowledgeRecord } from "./logic";
import type { KnowledgeBaseItem, KnowledgeSaveInput, KnowledgeTag } from "./types";

type KnowledgeListResponse = {
  records: BackendKnowledgeRecord[];
};

type KnowledgeTagsResponse = {
  tags: KnowledgeTag[];
};

export async function listKnowledgeBaseItems(): Promise<KnowledgeBaseItem[]> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return demoKnowledgeItems;
  try {
    const response = await fetch(`${apiBaseUrl}/api/knowledge?limit=200`);
    if (!response.ok) throw new Error(`Knowledge API returned ${response.status}`);
    const payload = (await response.json()) as KnowledgeListResponse;
    const records = payload.records.map(mapBackendKnowledgeRecord);
    return records.length ? mergeDemoWithBackend(records) : demoKnowledgeItems;
  } catch {
    return demoKnowledgeItems;
  }
}

export async function listKnowledgeBaseTags(): Promise<KnowledgeTag[]> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return [];
  try {
    const response = await fetch(`${apiBaseUrl}/api/knowledge/tags`);
    if (!response.ok) throw new Error(`Knowledge tags API returned ${response.status}`);
    const payload = (await response.json()) as KnowledgeTagsResponse;
    return payload.tags;
  } catch {
    return [];
  }
}

export async function createKnowledgeBaseItem(input: KnowledgeSaveInput): Promise<KnowledgeBaseItem | null> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return null;
  try {
    const response = await fetch(`${apiBaseUrl}/api/knowledge`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildKnowledgePayload(input)),
    });
    if (!response.ok) throw new Error(`Knowledge create API returned ${response.status}`);
    return mapBackendKnowledgeRecord((await response.json()) as BackendKnowledgeRecord);
  } catch {
    return null;
  }
}

export async function updateKnowledgeBaseItem(id: string, input: KnowledgeSaveInput): Promise<KnowledgeBaseItem | null> {
  const apiBaseUrl = getApiBaseUrl();
  if (!apiBaseUrl) return null;
  try {
    const response = await fetch(`${apiBaseUrl}/api/knowledge/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildKnowledgePatch(input)),
    });
    if (!response.ok) throw new Error(`Knowledge update API returned ${response.status}`);
    return mapBackendKnowledgeRecord((await response.json()) as BackendKnowledgeRecord);
  } catch {
    return null;
  }
}

function mergeDemoWithBackend(records: KnowledgeBaseItem[]) {
  const backendIds = new Set(records.map((item) => item.id));
  return [...records, ...demoKnowledgeItems.filter((item) => !backendIds.has(item.id))];
}

function getApiBaseUrl() {
  return process.env.NEXT_PUBLIC_GENBI_API_BASE_URL;
}
