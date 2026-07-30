export type KnowledgeBaseTab = "all" | "semantic" | "exploration" | "certification" | "tags";

export type KnowledgeItemType =
  | "metric_definition"
  | "dimension_definition"
  | "entity_definition"
  | "field_mapping"
  | "formula_definition"
  | "business_rule"
  | "lineage_note"
  | "report_logic"
  | "verified_conclusion";

export type KnowledgeSource = "manual" | "exploration" | "import";
export type KnowledgeStatus = "draft" | "pending" | "approved" | "conflicted" | "expired";
export type KnowledgeVisibility = "personal" | "team" | "company";
export type ApprovalRole = "BI 工程师" | "财务" | "运营" | "数据负责人" | "管理层";

export type KnowledgeApproval = {
  role: ApprovalRole;
  approver: string;
  status: "approved" | "pending" | "rejected";
  approvedAt?: string;
};

export type KnowledgeVersion = {
  version: string;
  author: string;
  changedAt: string;
  note: string;
};

export type KnowledgeUsage = {
  agent: string;
  usedAt: string;
  context: string;
};

export type KnowledgeBaseItem = {
  id: string;
  title: string;
  type: KnowledgeItemType;
  status: KnowledgeStatus;
  source: KnowledgeSource;
  content: string;
  businessDefinition: string;
  technicalDefinition: string;
  formula: string;
  scope: string;
  excludedScope: string;
  relatedTables: string[];
  relatedFields: string[];
  relatedResources: string[];
  evidenceRefs: string[];
  sourceQuestion?: string;
  sourceExplorationId?: string | null;
  createdBy: string;
  owner: string;
  visibility: KnowledgeVisibility;
  approvals: KnowledgeApproval[];
  tags: string[];
  version: string;
  updatedAt: string;
  expiresAt?: string;
  conflicts: string[];
  agentVisible: boolean;
  usageRecords: KnowledgeUsage[];
  versionHistory: KnowledgeVersion[];
};

export type KnowledgeTag = {
  name: string;
  group: string;
  count: number;
};

export type KnowledgeFilterState = {
  tab: KnowledgeBaseTab;
  query: string;
  type: KnowledgeItemType | "all";
  status: KnowledgeStatus | "all";
  tag: string | "all";
  owner: string | "all";
};

export type KnowledgeSaveInput = {
  title: string;
  type: KnowledgeItemType;
  content: string;
  businessDefinition: string;
  technicalDefinition: string;
  formula: string;
  scope: string;
  excludedScope: string;
  owner: string;
  visibility: KnowledgeVisibility;
  status: KnowledgeStatus;
  tags: string[];
  relatedTables: string[];
  relatedFields: string[];
  relatedResources: string[];
  agentVisible: boolean;
};
