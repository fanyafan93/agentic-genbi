import { demoKnowledgeItems, demoKnowledgeTags, semanticTypes } from "./mock";
import type {
  KnowledgeApproval,
  KnowledgeBaseItem,
  KnowledgeFilterState,
  KnowledgeItemType,
  KnowledgeSaveInput,
  KnowledgeStatus,
  KnowledgeTag,
  KnowledgeVisibility,
} from "./types";

export type BackendKnowledgeRecord = {
  id: string;
  title: string;
  question?: string;
  conclusion: string;
  scope: string;
  verification: string;
  evidence_refs?: string[];
  turn_id?: string | null;
  created_at: string;
  metadata?: Record<string, unknown>;
};

export function filterKnowledgeItems(items: KnowledgeBaseItem[], filters: KnowledgeFilterState): KnowledgeBaseItem[] {
  const query = filters.query.trim().toLowerCase();
  return items.filter((item) => {
    if (filters.tab === "semantic" && !semanticTypes.includes(item.type as (typeof semanticTypes)[number])) return false;
    if (filters.tab === "certification" && !["pending", "conflicted", "expired"].includes(item.status)) return false;
    if (filters.type !== "all" && item.type !== filters.type) return false;
    if (filters.status !== "all" && item.status !== filters.status) return false;
    if (filters.tag !== "all" && !item.tags.includes(filters.tag)) return false;
    if (filters.owner !== "all" && item.owner !== filters.owner) return false;
    if (!query) return true;
    return [
      item.title,
      item.content,
      item.businessDefinition,
      item.technicalDefinition,
      item.formula,
      item.scope,
      item.excludedScope,
      item.owner,
      item.createdBy,
      ...item.tags,
      ...item.relatedTables,
      ...item.relatedFields,
      ...item.relatedResources,
    ]
      .join(" ")
      .toLowerCase()
      .includes(query);
  });
}

export function deriveKnowledgeTags(items: KnowledgeBaseItem[], backendTags: KnowledgeTag[] = []): KnowledgeTag[] {
  const counts = new Map<string, KnowledgeTag>();
  for (const tag of demoKnowledgeTags) counts.set(tag.name, { ...tag, count: 0 });
  for (const tag of backendTags) counts.set(tag.name, tag);
  for (const item of items) {
    for (const tagName of item.tags) {
      const current = counts.get(tagName);
      counts.set(tagName, {
        name: tagName,
        group: current?.group ?? "未分组",
        count: (current?.count ?? 0) + 1,
      });
    }
  }
  return Array.from(counts.values()).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "zh-CN"));
}

export function mapBackendKnowledgeRecord(record: BackendKnowledgeRecord): KnowledgeBaseItem {
  const metadata = record.metadata ?? {};
  const fallback = demoKnowledgeItems.find((item) => item.id === record.id);
  return {
    id: record.id,
    title: record.title,
    type: asKnowledgeType(metadata.type, fallback?.type ?? "verified_conclusion"),
    status: asKnowledgeStatus(metadata.status, fallback?.status ?? "approved"),
    source: metadata.source === "import" ? "import" : "manual",
    content: stringValue(metadata.content) || record.conclusion,
    businessDefinition: stringValue(metadata.business_definition) || record.conclusion,
    technicalDefinition: stringValue(metadata.technical_definition) || record.verification,
    formula: stringValue(metadata.formula),
    scope: record.scope,
    excludedScope: stringValue(metadata.excluded_scope),
    relatedTables: arrayOfStrings(metadata.related_tables),
    relatedFields: arrayOfStrings(metadata.related_fields),
    relatedResources: arrayOfStrings(metadata.related_resources),
    evidenceRefs: record.evidence_refs ?? [],
    sourceQuestion: record.question,
    createdBy: stringValue(metadata.created_by) || "当前用户",
    owner: stringValue(metadata.owner) || fallback?.owner || "未分配",
    visibility: asVisibility(metadata.visibility, fallback?.visibility ?? "team"),
    approvals: asApprovals(metadata.approvals, fallback?.approvals ?? []),
    tags: arrayOfStrings(metadata.tags).length ? arrayOfStrings(metadata.tags) : fallback?.tags ?? [],
    version: stringValue(metadata.version) || fallback?.version || "v1.0",
    updatedAt: record.created_at.slice(0, 10),
    expiresAt: stringValue(metadata.expires_at) || undefined,
    conflicts: arrayOfStrings(metadata.conflicts),
    agentVisible: typeof metadata.agent_visible === "boolean" ? metadata.agent_visible : fallback?.agentVisible ?? true,
    usageRecords: fallback?.usageRecords ?? [],
    versionHistory: fallback?.versionHistory ?? [
      { version: stringValue(metadata.version) || "v1.0", author: stringValue(metadata.created_by) || "当前用户", changedAt: record.created_at.slice(0, 10), note: "从后端知识记录载入" },
    ],
  };
}

export function buildKnowledgePayload(input: KnowledgeSaveInput) {
  return {
    title: input.title,
    question: input.title,
    conclusion: input.content,
    scope: input.scope || "未限定",
    verification: input.technicalDefinition || input.businessDefinition || "人工维护",
    evidence_refs: input.relatedResources.length ? input.relatedResources : ["manual_knowledge"],
    metadata: {
      type: input.type,
      content: input.content,
      business_definition: input.businessDefinition,
      technical_definition: input.technicalDefinition,
      formula: input.formula,
      excluded_scope: input.excludedScope,
      owner: input.owner,
      visibility: input.visibility,
      status: input.status,
      tags: input.tags,
      related_tables: input.relatedTables,
      related_fields: input.relatedFields,
      related_resources: input.relatedResources,
      agent_visible: input.agentVisible,
      source: "manual",
      version: "v1.0",
    },
  };
}

export function buildKnowledgePatch(input: KnowledgeSaveInput) {
  return {
    ...buildKnowledgePayload(input),
    evidence_refs: input.relatedResources.length ? input.relatedResources : ["manual_knowledge"],
  };
}

function asKnowledgeType(value: unknown, fallback: KnowledgeItemType): KnowledgeItemType {
  const allowed: KnowledgeItemType[] = [
    "metric_definition",
    "dimension_definition",
    "entity_definition",
    "field_mapping",
    "formula_definition",
    "business_rule",
    "lineage_note",
    "report_logic",
    "verified_conclusion",
  ];
  return allowed.includes(value as KnowledgeItemType) ? (value as KnowledgeItemType) : fallback;
}

function asKnowledgeStatus(value: unknown, fallback: KnowledgeStatus): KnowledgeStatus {
  const allowed: KnowledgeStatus[] = ["draft", "pending", "approved", "conflicted", "expired"];
  return allowed.includes(value as KnowledgeStatus) ? (value as KnowledgeStatus) : fallback;
}

function asVisibility(value: unknown, fallback: KnowledgeVisibility): KnowledgeVisibility {
  return value === "personal" || value === "team" || value === "company" ? value : fallback;
}

function asApprovals(value: unknown, fallback: KnowledgeApproval[]): KnowledgeApproval[] {
  if (!Array.isArray(value)) return fallback;
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      role: stringValue(item.role) as KnowledgeApproval["role"],
      approver: stringValue(item.approver) || "未指定",
      status: asApprovalStatus(item.status),
      approvedAt: stringValue(item.approvedAt) || stringValue(item.approved_at) || undefined,
    }))
    .filter((item) => Boolean(item.role));
}

function asApprovalStatus(value: unknown): KnowledgeApproval["status"] {
  if (value === "rejected" || value === "pending" || value === "approved") return value;
  return "approved";
}

function arrayOfStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter(Boolean);
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : "";
}
