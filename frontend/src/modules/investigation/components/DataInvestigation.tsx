"use client";

import { useSession } from "next-auth/react";
import { createContext, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent, type KeyboardEvent, type ReactNode } from "react";

import {
  buildResourceExplorationPrompt,
  createExplorationRun,
  deleteExplorationRun,
  deleteKnowledge,
  filterResources,
  findResourceByEvidenceRef,
  getRuntimeStatus,
  getResourceStatus,
  listExplorationRuns,
  listKnowledge,
  readExplorationRun,
  readResourceDetail,
  readResourceExcerpt,
  readRunTrace,
  reindexResources,
  saveKnowledgeFromExploration,
  searchResources,
} from "@/modules/investigation/api/exploration-runs";
import { getComposerKeyIntent } from "@/modules/investigation/composer-keys";
import { shouldContinueExploration } from "@/modules/investigation/exploration-continuation";
import { shouldShowExplorationWaiting } from "@/modules/investigation/exploration-waiting";
import { MarkdownContent } from "@/modules/investigation/components/MarkdownContent";
import { isExplorationStarterMessage, shouldShowExplorationMessage } from "@/modules/investigation/message-visibility";
import type { Exploration, ExplorationMessage, ExplorationTab, Knowledge, Resource, ResourceDetail, ResourceExcerpt, ResourceIndexStatus, RunTraceSummary, RuntimeStatus } from "@/modules/investigation/types";

const initialExplorations: Exploration[] = [
  {
    id: "rebuy",
    title: "首购后 30 天复购率",
    agent: "经营指标调查 Agent",
    status: "进行中",
    updatedAt: "刚刚",
    resources: 4,
    summary: "正在核验复购口径、观察期和可复用结论。",
    messages: [
      { id: "rebuy-user", role: "user", body: "首购后 30 天复购率现在应该怎么计算？先看看公司里有没有已有实现。" },
      {
        id: "rebuy-search",
        role: "agent",
        title: "已检索资源库",
        body: "我找到了复购分析报表、候选 DM 宽表、历史 SQL 和 ETL 片段，先按已有实现还原口径。",
        details: [
          { label: "引用资源", items: ["剃须刀复购分析.cpt", "dm.dm_consr_shaver_rebuy_analysis_v2", "etl/consumer/shaver_rebuy.sql", "consumer_rebuy_30d.sql"] },
          { label: "初步证据", items: ["首购日来自 paid_time", "复购窗口以首购后 30 天为观察期", "历史 SQL 排除了未支付订单"] },
        ],
      },
      {
        id: "rebuy-question",
        role: "agent",
        title: "需要确认一个口径",
        body: "我发现历史报表按会员 ID 去重，但有一版 SQL 按手机号去重。当前探索先按会员 ID 继续核验。",
        details: [{ label: "待确认点", items: ["是否排除退款订单", "是否排除未满 30 天观察期的新首购用户"] }],
      },
      {
        id: "rebuy-knowledge",
        role: "agent",
        title: "可沉淀结论",
        body: "首购后 30 天复购率应以会员 ID 去重，排除未支付订单和未满观察期首购用户；退款口径需要在正式计算前由业务确认。",
        details: [{ label: "沉淀范围", items: ["剃须刀品类", "消费者复购分析", "经营指标探索"] }],
        action: "保存到知识库",
      },
    ],
  },
  {
    id: "inventory",
    title: "库存周转异常 SKU",
    agent: "库存溯源 Agent",
    status: "待确认",
    updatedAt: "今天 10:18",
    resources: 7,
    summary: "等待确认新品和断货排除范围。",
    messages: [
      { id: "inventory-user", role: "user", body: "帮我找出库存周转异常 SKU 的已有排查方法。" },
      {
        id: "inventory-agent",
        role: "agent",
        title: "已定位异常排查资源",
        body: "资源库里有库存周转日报、仓库 SKU 快照和一段异常检测 SQL。当前方法先比较近 14 天周转天数环比，再排除新品和断货。",
        details: [
          { label: "引用资源", items: ["库存周转日报.cpt", "ads_inventory_turnover_sku.sql", "dim_warehouse_sku_snapshot"] },
          { label: "待确认点", items: ["新品上市 14 天内是否排除", "断货 SKU 是否作为异常或单独归因"] },
        ],
      },
    ],
  },
  {
    id: "channel",
    title: "华东 GMV 下滑原因",
    agent: "经营指标调查 Agent",
    status: "已完成",
    updatedAt: "昨天",
    resources: 6,
    summary: "已沉淀区域 GMV 对账知识。",
    messages: [
      { id: "channel-user", role: "user", body: "华东 GMV 最近下滑，看看以前怎么分析。" },
      {
        id: "channel-agent",
        role: "agent",
        title: "已复用历史分析路径",
        body: "历史结论显示线下直营网点拖累 GMV，需要与区域经营日报使用相同门店归属和数据截止时间。",
        details: [
          { label: "引用资源", items: ["华东区域经营日报", "store_region_mapping.sql", "gmv_region_reconcile.sql"] },
          { label: "已验证结论", items: ["门店归属要按日报快照", "数据截止时间统一到 T+1 09:00"] },
        ],
        action: "保存到知识库",
      },
    ],
  },
];

const draftExplorationId = "exploration-draft";
const defaultExplorationStorageKey = "genbi.explorations";
const draftExploration: Exploration = {
  id: draftExplorationId,
  title: "新的知识探索",
  agent: "知识探索 Agent",
  status: "待确认",
  updatedAt: "草稿",
  resources: 0,
  summary: "输入问题后才会创建探索过程。",
  messages: [
    { id: "draft-user", role: "user", body: "输入一个想探索的问题，Agent 会优先检查资源库里的报表、代码、SQL 和已沉淀知识。" },
    { id: "draft-agent", role: "agent", title: "等待问题", body: "发送问题后，我会在探索过程中展示检索过程、关键证据和需要你确认的问题。" },
  ],
};

const initialResources: Resource[] = [
  { id: "report", type: "报表", name: "剃须刀复购分析.cpt", location: "FineReport / 消费者分析", description: "包含首购人数、复购人数和复购率的数据集 SQL。" },
  { id: "table", type: "数据表", name: "dm.dm_consr_shaver_rebuy_analysis_v2", location: "Doris / dm", description: "消费者复购分析宽表，含首购时间、购买次序和复购间隔。" },
  { id: "etl", type: "ETL", name: "etl/consumer/shaver_rebuy.sql", location: "数据仓库代码库", description: "生成首购时间、购买次序和复购间隔字段的 ETL SQL。" },
  { id: "sql", type: "SQL", name: "consumer_rebuy_30d.sql", location: "历史查询 / 经营分析", description: "按首购 cohort 计算 30 天复购率的历史验证查询。" },
];

const emptyResource: Resource = {
  id: "empty",
  type: "报表",
  name: "暂无资源",
  location: "等待搜索结果",
  description: "搜索资源库或刷新索引后，可在这里查看资源摘要和受控证据片段。",
};

const initialKnowledge: Knowledge[] = [
  {
    id: "rebuy",
    title: "首购后 30 天复购率",
    question: "首购后 30 天复购率现在应该怎么计算？",
    scope: "剃须刀品类",
    verified: "2026-06-30",
    verification: "历史报表与 DM 宽表交叉核验",
    note: "需排除未满 30 天观察期的首购用户。",
    evidenceRefs: ["剃须刀复购分析.cpt", "dm.dm_consr_shaver_rebuy_analysis_v2"],
    runId: "rebuy",
  },
  {
    id: "inventory",
    title: "库存周转异常定位",
    question: "库存周转异常 SKU 的已有排查方法是什么？",
    scope: "仓库 + SKU",
    verified: "2026-07-18",
    verification: "日报、快照表和异常 SQL 对照",
    note: "先比较近 14 天周转天数环比，再排除新品和断货影响。",
    evidenceRefs: ["库存周转日报.cpt", "ads_inventory_turnover_sku.sql"],
    runId: "inventory",
  },
  {
    id: "gmv",
    title: "区域 GMV 趋势",
    question: "华东 GMV 下滑时以前怎么分析？",
    scope: "华东区域",
    verified: "2026-07-20",
    verification: "历史分析路径复用",
    note: "需与区域经营日报使用相同的门店归属和数据截止时间。",
    evidenceRefs: ["华东区域经营日报", "store_region_mapping.sql", "gmv_region_reconcile.sql"],
    runId: "channel",
  },
];

const emptyKnowledge: Knowledge = {
  id: "empty",
  title: "暂无知识沉淀",
  question: "",
  scope: "等待探索结论",
  verified: "-",
  verification: "",
  note: "完成探索并确认结论后，可在这里查看已沉淀的知识。",
  evidenceRefs: [],
  runId: null,
};

type ExplorationContextValue = {
  tab: ExplorationTab;
  setTab: (tab: ExplorationTab) => void;
  explorations: Exploration[];
  selectedExploration: Exploration;
  selectedExplorationId: string;
  setSelectedExplorationId: (id: string) => void;
  selectedResource: Resource;
  resourceDetail: ResourceDetail | null;
  resourceDetailLoading: boolean;
  loadSelectedResourceDetail: () => Promise<void>;
  resourceExcerpt: ResourceExcerpt | null;
  resourceExcerptLoading: boolean;
  loadSelectedResourceExcerpt: () => Promise<void>;
  resourceStatus: ResourceIndexStatus | null;
  runtimeStatus: RuntimeStatus | null;
  refreshResourceIndex: () => Promise<void>;
  resourceRefreshing: boolean;
  selectedResourceId: string;
  setSelectedResourceId: (id: string) => void;
  filteredResources: Resource[];
  query: string;
  setQuery: (query: string) => void;
  resourceTypeFilter: Resource["type"] | "全部";
  setResourceTypeFilter: (type: Resource["type"] | "全部") => void;
  searchResourceLibrary: () => Promise<void>;
  resourceSearching: boolean;
  selectedKnowledge: Knowledge;
  knowledge: Knowledge[];
  selectedKnowledgeId: string;
  setSelectedKnowledgeId: (id: string) => void;
  deleteSelectedKnowledge: () => Promise<void>;
  saveExplorationKnowledge: (message: ExplorationMessage) => Promise<void>;
  openEvidenceResource: (evidenceRef: string) => Promise<void>;
  selectedRunTrace: RunTraceSummary | null;
  runTraceLoading: boolean;
  runTraceMissing: boolean;
  loadSelectedKnowledgeRunTrace: () => Promise<void>;
  knowledgeDeleting: boolean;
  knowledgeSavingId: string | null;
  createExploration: () => void;
  deleteExplorations: (ids: string[]) => Promise<void>;
  runExploration: (question: string, shouldStop?: () => boolean, onActiveExplorationId?: (id: string) => void) => Promise<void>;
};

const ExplorationContext = createContext<ExplorationContextValue | null>(null);

function useExploration() {
  const value = useContext(ExplorationContext);
  if (!value) throw new Error("Knowledge exploration components must be wrapped in KnowledgeExplorationProvider.");
  return value;
}

export function KnowledgeExplorationProvider({ children }: { children: ReactNode }) {
  const { data: session } = useSession();
  const sessionUserId = session?.user?.id ?? null;
  const explorationStorageKey = useMemo(
    () => (sessionUserId ? `${defaultExplorationStorageKey}.${sessionUserId}` : defaultExplorationStorageKey),
    [sessionUserId],
  );
  const [tab, setTab] = useState<ExplorationTab>("explorations");
  const [explorations, setExplorations] = useState<Exploration[]>(initialExplorations);
  const [resources, setResources] = useState(initialResources);
  const [knowledge, setKnowledge] = useState(initialKnowledge);
  const [resourceStatus, setResourceStatus] = useState<ResourceIndexStatus | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const [resourceRefreshing, setResourceRefreshing] = useState(false);
  const [resourceSearching, setResourceSearching] = useState(false);
  const [resourceDetail, setResourceDetail] = useState<ResourceDetail | null>(null);
  const [resourceDetailLoading, setResourceDetailLoading] = useState(false);
  const [resourceExcerpt, setResourceExcerpt] = useState<ResourceExcerpt | null>(null);
  const [resourceExcerptLoading, setResourceExcerptLoading] = useState(false);
  const [knowledgeDeleting, setKnowledgeDeleting] = useState(false);
  const [knowledgeSavingId, setKnowledgeSavingId] = useState<string | null>(null);
  const [selectedRunTrace, setSelectedRunTrace] = useState<RunTraceSummary | null>(null);
  const [runTraceLoading, setRunTraceLoading] = useState(false);
  const [runTraceMissing, setRunTraceMissing] = useState(false);
  const [loadedExplorationIds, setLoadedExplorationIds] = useState<Set<string>>(new Set());
  const [selectedExplorationId, setSelectedExplorationId] = useState(initialExplorations[0].id);
  const [selectedResourceId, setSelectedResourceId] = useState(initialResources[0].id);
  const [selectedKnowledgeId, setSelectedKnowledgeId] = useState(initialKnowledge[0].id);
  const [query, setQuery] = useState("");
  const [resourceTypeFilter, setResourceTypeFilter] = useState<Resource["type"] | "全部">("全部");
  const filteredResources = useMemo(() => filterResources(resources, query, resourceTypeFilter), [query, resourceTypeFilter, resources]);
  const selectedExploration = selectedExplorationId === draftExplorationId ? draftExploration : explorations.find((item) => item.id === selectedExplorationId) ?? explorations[0];
  const selectedResource = resources.find((item) => item.id === selectedResourceId) ?? resources[0] ?? emptyResource;
  const selectedKnowledge = knowledge.find((item) => item.id === selectedKnowledgeId) ?? knowledge[0] ?? emptyKnowledge;

  useEffect(() => {
    const cleaned = cleanExplorationList(explorations);
    if (cleaned.length === explorations.length) return;
    const nextItems = cleaned.length > 0 ? cleaned : initialExplorations;
    setExplorations(nextItems);
    setSelectedExplorationId((current) => (nextItems.some((item) => item.id === current) ? current : nextItems[0].id));
  }, []);

  useEffect(() => {
    let alive = true;
    if (!sessionUserId) return () => {
      alive = false;
    };
    searchResources("dm").then((items) => {
      if (alive && items.length > 0) {
        setResources(items);
        setSelectedResourceId((current) => (items.some((item) => item.id === current) ? current : items[0].id));
      }
    });
    getResourceStatus().then((status) => {
      if (alive) setResourceStatus(status);
    });
    getRuntimeStatus().then((status) => {
      if (alive) setRuntimeStatus(status);
    });
    listExplorationRuns(sessionUserId).then((items) => {
      if (alive && items.length > 0) {
        const cleanedItems = cleanExplorationList(items);
        setExplorations((current) => mergeExplorations(cleanedItems, current));
        setSelectedExplorationId((current) => (cleanedItems.some((item) => item.id === current) ? current : cleanedItems[0]?.id ?? current));
      }
    });
    listKnowledge().then((items) => {
      if (alive && items.length > 0) {
        setKnowledge(items);
        setSelectedKnowledgeId((current) => (items.some((item) => item.id === current) ? current : items[0].id));
      }
    });
    return () => {
      alive = false;
    };
  }, [sessionUserId]);

  useEffect(() => {
    if (typeof window === "undefined" || !sessionUserId) return;
    try {
      const cached = window.localStorage.getItem(explorationStorageKey);
      if (!cached) return;
      const parsed = JSON.parse(cached) as Exploration[];
      const cleaned = cleanExplorationList(parsed);
      if (cleaned.length === 0) return;
      setExplorations(cleaned);
      setSelectedExplorationId((current) => (cleaned.some((item) => item.id === current) ? current : cleaned[0].id));
    } catch {
      // Ignore corrupt per-user demo cache.
    }
  }, [explorationStorageKey, sessionUserId]);

  useEffect(() => {
    if (typeof window === "undefined" || !sessionUserId) return;
    try {
      window.localStorage.setItem(explorationStorageKey, JSON.stringify(cleanExplorationList(explorations)));
    } catch {
      // localStorage 不可用 (隐私模式 / 配额) 时忽略
    }
  }, [explorationStorageKey, explorations, sessionUserId]);

  useEffect(() => {
    setResourceDetail(null);
    setResourceExcerpt(null);
  }, [selectedResourceId]);

  useEffect(() => {
    let alive = true;
    const current = explorations.find((item) => item.id === selectedExplorationId);
    const shouldLoad =
      (current?.id.startsWith("conv_") || current?.id.startsWith("run_")) &&
      current.messages.some((message) => message.title === "已保存探索") &&
      !loadedExplorationIds.has(current.id);
    if (!shouldLoad || !current) return;
    readExplorationRun(current.id).then((restored) => {
      if (!alive || !restored) return;
      setExplorations((items) => upsertExploration(items, restored));
      setLoadedExplorationIds((ids) => new Set(ids).add(restored.id));
    });
    return () => {
      alive = false;
    };
  }, [explorations, loadedExplorationIds, selectedExplorationId]);

  useEffect(() => {
    setSelectedRunTrace(null);
    setRunTraceMissing(false);
  }, [selectedKnowledgeId]);

  function createExploration() {
    setExplorations((items) => items.filter((item) => !isDraftPlaceholderExploration(item)));
    setSelectedExplorationId(draftExplorationId);
    setTab("explorations");
  }

  async function deleteExplorations(ids: string[]) {
    const targets = new Set(ids);
    if (targets.size === 0) return;
    await Promise.all(ids.map((id) => deleteExplorationRun(id)));
    setExplorations((items) => {
      const nextItems = items.filter((item) => !targets.has(item.id));
      const fallbackItems = nextItems.length > 0 ? nextItems : initialExplorations;
      setSelectedExplorationId((current) => (targets.has(current) ? fallbackItems[0].id : current));
      return fallbackItems;
    });
  }

  async function runExploration(question: string, shouldStop?: () => boolean, onActiveExplorationId?: (id: string) => void) {
    setTab("explorations");
    const baseExploration = selectedExploration;
    const shouldContinue = baseExploration && shouldContinueExploration(baseExploration);
    const continuationUserMessageId = shouldContinue ? `${baseExploration.id}-user-${Date.now()}` : "";
    const next = await createExplorationRun(question, (partial) => {
      if (shouldStop?.()) return;
      const merged = shouldContinue ? mergeContinuationExploration(baseExploration, question, partial, continuationUserMessageId) : partial;
      onActiveExplorationId?.(merged.id);
      setExplorations((items) => upsertExploration(items, merged));
      setSelectedExplorationId((current) => (current === baseExploration.id || current === partial.id ? merged.id : current));
    }, {
      conversationId: shouldContinue ? baseExploration.id : undefined,
      displayQuestion: shouldContinue ? question : undefined,
      userId: sessionUserId,
      metadata: shouldContinue ? { continuation_of: baseExploration.id, parent_title: baseExploration.title } : undefined,
    });
    if (shouldStop?.()) {
      const stopped = markExplorationStopped(baseExploration, question);
      setExplorations((items) => upsertExploration(items, stopped));
      setSelectedExplorationId((current) => (current === baseExploration.id ? stopped.id : current));
      return;
    }
    const merged = shouldContinue ? mergeContinuationExploration(baseExploration, question, next, continuationUserMessageId) : next;
    onActiveExplorationId?.(merged.id);
    setExplorations((items) => upsertExploration(items, merged));
    setSelectedExplorationId((current) => (current === baseExploration.id || current === next.id ? merged.id : current));
  }

  async function refreshResourceIndex() {
    if (resourceRefreshing) return;
    setResourceRefreshing(true);
    try {
      const status = await reindexResources();
      if (status) setResourceStatus(status);
      const items = await searchResources("dm");
      if (items.length > 0) {
        setResources(items);
        setSelectedResourceId(items[0].id);
      }
    } finally {
      setResourceRefreshing(false);
    }
  }

  async function searchResourceLibrary() {
    if (resourceSearching) return;
    setResourceSearching(true);
    try {
      const items = await searchResources(query || "dm");
      if (items.length > 0) {
        setResources(items);
        setSelectedResourceId((current) => (items.some((item) => item.id === current) ? current : items[0].id));
      } else {
        setResources([]);
        setSelectedResourceId("");
      }
    } finally {
      setResourceSearching(false);
    }
  }

  async function loadSelectedResourceExcerpt() {
    if (resourceExcerptLoading || selectedResource.id === emptyResource.id) return;
    setResourceExcerptLoading(true);
    try {
      const excerpt = await readResourceExcerpt(selectedResource.id, selectedResource.name);
      setResourceExcerpt(excerpt);
    } finally {
      setResourceExcerptLoading(false);
    }
  }

  async function loadSelectedResourceDetail() {
    if (resourceDetailLoading || selectedResource.id === emptyResource.id) return;
    setResourceDetailLoading(true);
    try {
      const detail = await readResourceDetail(selectedResource.id);
      setResourceDetail(detail);
    } finally {
      setResourceDetailLoading(false);
    }
  }

  async function deleteSelectedKnowledge() {
    if (knowledgeDeleting || selectedKnowledge.id === emptyKnowledge.id) return;
    setKnowledgeDeleting(true);
    try {
      const deleted = await deleteKnowledge(selectedKnowledge.id);
      if (!deleted) return;
      setKnowledge((items) => {
        const remaining = items.filter((item) => item.id !== selectedKnowledge.id);
        setSelectedKnowledgeId(remaining[0]?.id ?? emptyKnowledge.id);
        return remaining;
      });
    } finally {
      setKnowledgeDeleting(false);
    }
  }

  async function saveExplorationKnowledge(message: ExplorationMessage) {
    if (knowledgeSavingId || !message.action) return;
    setKnowledgeSavingId(message.id);
    try {
      const saved = await saveKnowledgeFromExploration(selectedExploration, message);
      if (!saved) return;
      setKnowledge((items) => upsertKnowledge(items, saved));
      setSelectedKnowledgeId(saved.id);
      setTab("knowledge");
    } finally {
      setKnowledgeSavingId(null);
    }
  }

  async function openEvidenceResource(evidenceRef: string) {
    const queryText = evidenceRef.trim();
    if (!queryText) return;
    setTab("resources");
    setResourceTypeFilter("全部");
    setQuery(queryText);
    const localMatch = findResourceByEvidenceRef(resources, queryText);
    if (localMatch) setSelectedResourceId(localMatch.id);
    if (resourceSearching) return;
    setResourceSearching(true);
    try {
      const items = await searchResources(queryText);
      if (items.length > 0) {
        setResources(items);
        setSelectedResourceId(items[0].id);
      }
    } finally {
      setResourceSearching(false);
    }
  }

  async function loadSelectedKnowledgeRunTrace() {
    if (runTraceLoading || !selectedKnowledge.runId) return;
    setRunTraceLoading(true);
    setRunTraceMissing(false);
    try {
      const trace = await readRunTrace(selectedKnowledge.runId);
      setSelectedRunTrace(trace);
      setRunTraceMissing(!trace);
    } finally {
      setRunTraceLoading(false);
    }
  }

  return (
    <ExplorationContext.Provider
      value={{
        tab,
        setTab,
        explorations,
        selectedExploration,
        selectedExplorationId,
        setSelectedExplorationId,
        selectedResource,
        resourceDetail,
        resourceDetailLoading,
        loadSelectedResourceDetail,
        resourceExcerpt,
        resourceExcerptLoading,
        loadSelectedResourceExcerpt,
        resourceStatus,
        runtimeStatus,
        refreshResourceIndex,
        resourceRefreshing,
        selectedResourceId,
        setSelectedResourceId,
        filteredResources,
        query,
        setQuery,
        resourceTypeFilter,
        setResourceTypeFilter,
        searchResourceLibrary,
        resourceSearching,
        selectedKnowledge,
        knowledge,
        selectedKnowledgeId,
        setSelectedKnowledgeId,
        deleteSelectedKnowledge,
        saveExplorationKnowledge,
        openEvidenceResource,
        selectedRunTrace,
        runTraceLoading,
        runTraceMissing,
        loadSelectedKnowledgeRunTrace,
        knowledgeDeleting,
        knowledgeSavingId,
        createExploration,
        deleteExplorations,
        runExploration,
      }}
    >
      {children}
    </ExplorationContext.Provider>
  );
}

function upsertExploration(items: Exploration[], next: Exploration) {
  const existingIndex = items.findIndex((item) => item.id === next.id);
  if (existingIndex === -1) return [next, ...items];
  return items.map((item, index) => (index === existingIndex ? next : item));
}

function mergeContinuationExploration(base: Exploration, userMessage: string, next: Exploration, userMessageId: string): Exploration {
  const continuationMessages = next.messages
    .filter((message) => message.role !== "user" && !isExplorationStarterMessage(message))
    .map((message) => ({
      ...message,
      id: `${base.id}-continued-${message.id}`,
    }));
  return {
    ...base,
    status: next.status,
    updatedAt: "刚刚",
    createdAt: base.createdAt ?? next.createdAt,
    lastMessageAt: next.lastMessageAt ?? new Date().toISOString(),
    resources: base.resources + next.resources,
    summary: next.summary || base.summary,
    messages: [
      ...base.messages,
      {
        id: userMessageId,
        role: "user",
        body: userMessage,
      },
      ...continuationMessages,
    ],
  };
}

function markExplorationStopped(base: Exploration, userMessage: string): Exploration {
  const stoppedId = base.id === draftExplorationId ? `stopped_${Date.now()}` : base.id;
  return {
    ...base,
    id: stoppedId,
    title: base.id === draftExplorationId ? userMessage.slice(0, 18) || base.title : base.title,
    status: "待确认",
    updatedAt: "刚刚",
    createdAt: base.createdAt ?? new Date().toISOString(),
    lastMessageAt: new Date().toISOString(),
    summary: "用户已停止本次对话。",
    messages: [
      ...base.messages,
      {
        id: `${stoppedId}-user-stop-${Date.now()}`,
        role: "user",
        body: userMessage,
      },
      {
        id: `${stoppedId}-agent-stop-${Date.now()}`,
        role: "agent",
        title: "已停止对话",
        body: "我已停止继续等待本次探索结果。当前已保留已有上下文，你可以调整问题后继续。",
      },
    ],
  };
}

function isDraftPlaceholderExploration(item: Exploration) {
  return item.id === draftExplorationId || item.id.startsWith("exploration-") || item.id.startsWith("local-");
}

function isContinuationExploration(item: Exploration) {
  return (
    item.title.startsWith("这是同一个知识探索会话中的继续追问或补充") ||
    item.summary.startsWith("这是同一个知识探索会话中的继续追问或补充") ||
    item.messages.some((message) => message.role === "user" && message.body.startsWith("这是同一个知识探索会话中的继续追问或补充"))
  );
}

function cleanExplorationList(items: Exploration[]) {
  return items.filter((item) => !isDraftPlaceholderExploration(item) && !isContinuationExploration(item));
}

function getExplorationTimeValue(value?: string) {
  if (!value) return 0;
  const normalized = value.trim();
  if (!normalized || normalized === "草稿") return 0;
  if (normalized === "刚刚") return Date.now();
  if (normalized.startsWith("今天")) {
    const timePart = normalized.replace("今天", "").trim();
    const [hour = "23", minute = "59"] = timePart.split(":");
    const date = new Date();
    date.setHours(Number(hour) || 23, Number(minute) || 59, 0, 0);
    return date.getTime();
  }
  if (normalized === "昨天") return Date.now() - 24 * 60 * 60 * 1000;
  const parsed = Date.parse(normalized);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function getExplorationLastMessageTime(item: Exploration) {
  return getExplorationTimeValue(item.lastMessageAt ?? item.updatedAt ?? item.createdAt);
}

function formatExplorationTime(value?: string) {
  if (!value) return "未知";
  const normalized = value.trim();
  if (!normalized) return "未知";
  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) return normalized;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return normalized;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function messageTitleClass(title: string) {
  if (title.includes("结论")) return "is-conclusion";
  if (title.includes("进展") || title.includes("过程")) return "is-progress";
  if (title.includes("工具")) return "is-tool";
  return "";
}

function mergeExplorations(incoming: Exploration[], current: Exploration[]) {
  const cleanedIncoming = cleanExplorationList(incoming);
  const cleanedCurrent = cleanExplorationList(current);
  const seen = new Set(cleanedIncoming.map((item) => item.id));
  return [...cleanedIncoming, ...cleanedCurrent.filter((item) => !seen.has(item.id))];
}

function upsertKnowledge(items: Knowledge[], next: Knowledge) {
  const existingIndex = items.findIndex((item) => item.id === next.id || item.title === next.title);
  if (existingIndex === -1) return [next, ...items.filter((item) => item.id !== emptyKnowledge.id)];
  return items.map((item, index) => (index === existingIndex ? next : item));
}

function RuntimeStatusBar({ status }: { status: RuntimeStatus | null }) {
  const missing = status?.checks.filter((item) => !item.ok) ?? [];
  const label = !status
    ? "检测运行环境中"
    : status.connected
      ? status.ready
        ? "真实后端已就绪"
        : "后端已连接，配置待补"
      : "后端未连接";
  const detail = !status
    ? "正在读取资源库和 Agent Runtime 状态。"
    : status.connected
      ? missing.length > 0
        ? missing.map((item) => item.message).slice(0, 2).join("；")
        : "OpenAI / MySQL / 资源库关键配置已通过检查。"
      : status.checks[0]?.message || "未连接探索后端。";

  return (
    <div className={`runtime-status ${status?.ready ? "ready" : status?.connected ? "partial" : "local"}`} aria-label="运行环境状态">
      <strong>{label}</strong>
      <span>{detail}</span>
      {status?.envFile && <em>{status.envFile}</em>}
    </div>
  );
}

export function KnowledgeExplorationSidebar() {
  const {
    tab,
    setTab,
    explorations,
    selectedExplorationId,
    setSelectedExplorationId,
    filteredResources,
    query,
    setQuery,
    resourceTypeFilter,
    setResourceTypeFilter,
    searchResourceLibrary,
    resourceSearching,
    selectedResourceId,
    setSelectedResourceId,
    selectedKnowledgeId,
    setSelectedKnowledgeId,
    knowledge,
    createExploration,
    deleteExplorations,
  } = useExploration();
  const [managingExplorations, setManagingExplorations] = useState(false);
  const [selectedDeleteIds, setSelectedDeleteIds] = useState<Set<string>>(new Set());
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const orderedExplorations = useMemo(
    () => [...explorations].sort((left, right) => getExplorationLastMessageTime(right) - getExplorationLastMessageTime(left)),
    [explorations],
  );

  function toggleExplorationDelete(id: string) {
    setConfirmingDelete(false);
    setSelectedDeleteIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function exitExplorationManageMode() {
    setManagingExplorations(false);
    setSelectedDeleteIds(new Set());
    setConfirmingDelete(false);
  }

  async function deleteSelectedExplorations() {
    const ids = Array.from(selectedDeleteIds);
    if (ids.length === 0) return;
    if (!confirmingDelete) {
      setConfirmingDelete(true);
      return;
    }
    await deleteExplorations(ids);
    exitExplorationManageMode();
  }

  return (
    <div className="exploration-sidebar">
      <header className="panel-header">
        <span className="panel-kicker">KNOWLEDGE EXPLORATION</span>
        <h2>知识探索</h2>
      </header>
      <div className="exploration-sidebar-footer">
        <p>让 Agent 从已有报表、代码、数据和已验证结论中查证，而不是从零开始。</p>
        <button className="exploration-create" type="button" onClick={createExploration}>
          <span aria-hidden="true">+</span> 新建探索
        </button>
      </div>
      <nav className="exploration-nav" aria-label="知识探索导航" data-active={tab === "explorations" ? "0" : tab === "resources" ? "1" : "2"}>
        <span className="exploration-nav-indicator" aria-hidden="true" />
        <button className={tab === "explorations" ? "active" : ""} type="button" onClick={() => setTab("explorations")}>
          我的探索
        </button>
        <button className={tab === "resources" ? "active" : ""} type="button" onClick={() => setTab("resources")}>
          资源库
        </button>
        <button className={tab === "knowledge" ? "active" : ""} type="button" onClick={() => setTab("knowledge")}>
          知识沉淀
        </button>
      </nav>
      <div className="exploration-sidebar-content">
        {tab === "explorations" && (
          <section aria-label="探索任务列表">
            <div className="section-caption">
              <span>探索任务</span>
              <span className="exploration-list-actions">
                <small>{explorations.length} 项</small>
                <button type="button" onClick={managingExplorations ? exitExplorationManageMode : () => setManagingExplorations(true)}>
                  {managingExplorations ? "完成" : "管理"}
                </button>
              </span>
            </div>
            {orderedExplorations.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`exploration-item ${selectedExplorationId === item.id ? "active" : ""} ${managingExplorations ? "is-managing" : ""}`}
                onClick={() => (managingExplorations ? toggleExplorationDelete(item.id) : setSelectedExplorationId(item.id))}
              >
                {managingExplorations && (
                  <span className={`exploration-checkbox ${selectedDeleteIds.has(item.id) ? "checked" : ""}`} aria-hidden="true">
                    {selectedDeleteIds.has(item.id) ? "✓" : ""}
                  </span>
                )}
                <span className="exploration-item-top">
                  <strong>{item.title}</strong>
                  <em className={item.status}>{item.status}</em>
                </span>
                <small>{formatExplorationTime(item.lastMessageAt ?? item.updatedAt)}</small>
              </button>
            ))}
            {managingExplorations && (
              <div className={`exploration-bulk-actions ${confirmingDelete ? "is-confirming" : ""}`}>
                <span>{confirmingDelete ? `确认删除 ${selectedDeleteIds.size} 项？` : `已选 ${selectedDeleteIds.size} 项`}</span>
                <div>
                  {confirmingDelete && (
                    <button className="secondary" type="button" onClick={() => setConfirmingDelete(false)}>
                      取消
                    </button>
                  )}
                  <button type="button" onClick={deleteSelectedExplorations} disabled={selectedDeleteIds.size === 0}>
                    {confirmingDelete ? "确认删除" : "删除所选"}
                  </button>
                </div>
              </div>
            )}
          </section>
        )}

        {tab === "resources" && (
          <section aria-label="资源库列表">
            <label className="resource-search">
              <span aria-hidden="true">S</span>
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索报表、ETL、SQL 或数据表"
              />
            </label>
            <div className="resource-filter-bar" aria-label="资源筛选">
              {(["全部", "报表", "ETL", "SQL", "数据表"] as const).map((type) => (
                <button
                  key={type}
                  className={resourceTypeFilter === type ? "active" : ""}
                  type="button"
                  onClick={() => setResourceTypeFilter(type)}
                >
                  {type}
                </button>
              ))}
              <button type="button" onClick={searchResourceLibrary} disabled={resourceSearching}>
                {resourceSearching ? "搜索中" : "搜索"}
              </button>
            </div>
            <div className="section-caption">
              <span>资源库</span>
              <small>{filteredResources.length} 项</small>
            </div>
            {filteredResources.length > 0 ? (
              filteredResources.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`resource-item ${selectedResourceId === item.id ? "active" : ""}`}
                  onClick={() => setSelectedResourceId(item.id)}
                >
                  <span>{item.type}</span>
                  <strong>{item.name}</strong>
                  <small>{item.location}</small>
                </button>
              ))
            ) : (
              <p className="resource-empty">没有命中的资源。可以换一个关键词，或先刷新本地索引。</p>
            )}
          </section>
        )}

        {tab === "knowledge" && (
          <section aria-label="知识沉淀列表">
            <div className="section-caption">
              <span>已验证知识</span>
              <small>{knowledge.length} 项</small>
            </div>
            {knowledge.map((item) => (
              <button
                key={item.id}
                type="button"
                className={`knowledge-item ${selectedKnowledgeId === item.id ? "active" : ""}`}
                onClick={() => setSelectedKnowledgeId(item.id)}
              >
                <strong>{item.title}</strong>
                <span>{item.scope}</span>
                <small>最后验证 {item.verified}</small>
              </button>
            ))}
          </section>
        )}

      </div>
    </div>
  );
}

export function KnowledgeExploration() {
  const {
    explorations,
    tab,
    setTab,
    selectedExplorationId,
    setSelectedExplorationId,
    selectedExploration,
    selectedResource,
    resourceDetail,
    resourceDetailLoading,
    loadSelectedResourceDetail,
    resourceExcerpt,
    resourceExcerptLoading,
    loadSelectedResourceExcerpt,
    selectedKnowledge,
    deleteSelectedKnowledge,
    saveExplorationKnowledge,
    openEvidenceResource,
    selectedRunTrace,
    runTraceLoading,
    runTraceMissing,
    loadSelectedKnowledgeRunTrace,
    knowledgeDeleting,
    knowledgeSavingId,
    createExploration,
    runExploration,
    resourceStatus,
    runtimeStatus,
    refreshResourceIndex,
    resourceRefreshing,
  } = useExploration();
  const [draft, setDraft] = useState("");
  const activeStopTokenRef = useRef<{ stopped: boolean } | null>(null);
  const messagesRef = useRef<HTMLOListElement | null>(null);
  const visibleMessages = useMemo(() => {
    if (!selectedExploration) return [];
    return selectedExploration.messages.filter(shouldShowExplorationMessage);
  }, [selectedExploration]);
  const displayedExplorations = useMemo(() => {
    if (selectedExplorationId !== draftExplorationId) return explorations;
    if (explorations.some((item) => item.id === draftExplorationId)) return explorations;
    return [draftExploration, ...explorations];
  }, [explorations, selectedExplorationId]);
  const [visualSelectedExplorationId, setVisualSelectedExplorationId] = useState(selectedExplorationId);
  const visualSelectedExplorationIndex = Math.max(
    0,
    displayedExplorations.findIndex((item) => item.id === visualSelectedExplorationId),
  );
  const targetExplorationIndex = Math.max(
    0,
    displayedExplorations.findIndex((item) => item.id === selectedExplorationId),
  );
  const isCardTransitioning = tab === "explorations" && visualSelectedExplorationId !== selectedExplorationId;
  const cardTransitionDirection = targetExplorationIndex >= visualSelectedExplorationIndex ? "forward" : "backward";
  const [submitting, setSubmitting] = useState(false);
  const [submittingExplorationId, setSubmittingExplorationId] = useState<string | null>(null);
  const showExplorationWaiting =
    visualSelectedExplorationId === selectedExplorationId &&
    shouldShowExplorationWaiting(submitting, submittingExplorationId, selectedExploration.id);
  const waitingContext = useMemo(() => {
    const userMessageCount = visibleMessages.filter((message) => message.role === "user").length;
    return userMessageCount > 1 ? "已收到你的追问，会基于当前探索继续处理。" : "问题已发送，正在等待第一段结果。";
  }, [visibleMessages]);

  useEffect(() => {
    if (tab !== "explorations") return;
    if (isCardTransitioning) return;
    const node = messagesRef.current;
    if (!node) return;
    requestAnimationFrame(() => {
      node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
    });
  }, [isCardTransitioning, tab, selectedExploration.id, selectedExploration.status, visibleMessages.length, submittingExplorationId]);

  useEffect(() => {
    if (tab !== "explorations") return;
    if (isCardTransitioning) return;
    const node = messagesRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        node.scrollTo({ top: node.scrollHeight, behavior: "smooth" });
      });
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [isCardTransitioning, tab, selectedExploration.id]);

  useEffect(() => {
    if (tab !== "explorations") {
      setVisualSelectedExplorationId(selectedExplorationId);
      return;
    }
    if (visualSelectedExplorationId === selectedExplorationId) return;
    const currentIndex = displayedExplorations.findIndex((item) => item.id === visualSelectedExplorationId);
    const targetIndex = displayedExplorations.findIndex((item) => item.id === selectedExplorationId);
    if (currentIndex === -1 || targetIndex === -1) {
      setVisualSelectedExplorationId(selectedExplorationId);
      return;
    }
    const direction = targetIndex > currentIndex ? 1 : -1;
    const nextId = displayedExplorations[currentIndex + direction]?.id ?? selectedExplorationId;
    const remainingSteps = Math.abs(targetIndex - currentIndex);
    const timer = window.setTimeout(() => {
      setVisualSelectedExplorationId(nextId);
    }, remainingSteps > 1 ? 130 : 210);
    return () => window.clearTimeout(timer);
  }, [displayedExplorations, selectedExplorationId, tab, visualSelectedExplorationId]);

  async function submitExploration(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || submitting) return;
    const stopToken = { stopped: false };
    activeStopTokenRef.current = stopToken;
    setSubmittingExplorationId(selectedExploration.id);
    setDraft("");
    setSubmitting(true);
    try {
      await runExploration(question, () => stopToken.stopped, setSubmittingExplorationId);
    } finally {
      if (activeStopTokenRef.current === stopToken) {
        setSubmitting(false);
        setSubmittingExplorationId(null);
        activeStopTokenRef.current = null;
      }
    }
  }

  function submitExplorationFromKeyboard(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (getComposerKeyIntent(event) !== "submit") return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function stopExploration() {
    if (!submitting) return;
    if (activeStopTokenRef.current) {
      activeStopTokenRef.current.stopped = true;
    }
    setSubmitting(false);
  }

  function bringResourceIntoExploration() {
    if (selectedResource.id === emptyResource.id) return;
    setDraft(buildResourceExplorationPrompt(selectedResource));
    setTab("explorations");
  }

  return (
    <section className="knowledge-exploration-page" aria-label="知识探索">
      {tab === "explorations" && (
        <div className="disc-stage">
          <div className={`disc-deck ${isCardTransitioning ? "is-moving" : ""} is-${cardTransitionDirection}`} aria-label="探索会话卡片堆">
            {displayedExplorations.map((item, index) => {
              const isActive = item.id === visualSelectedExplorationId;
              const isTarget = item.id === selectedExplorationId;
              const itemMessages = item.messages.filter(shouldShowExplorationMessage);
              const shouldRenderConversation = isActive && isTarget && !isCardTransitioning;
              const offset = index - visualSelectedExplorationIndex;
              const distance = Math.min(Math.abs(offset), 4);
              const direction = offset === 0 ? 0 : offset > 0 ? 1 : -1;
              const isInStack = Math.abs(offset) <= 4;
              const cardStyle = {
                "--card-x": `${direction * distance * 78}px`,
                "--card-y": `${distance * 26}px`,
                "--card-scale": `${1 - distance * 0.062}`,
                "--card-opacity": `${isActive ? 1 : Math.max(0.2, 0.66 - distance * 0.11)}`,
                "--card-z": `${40 - distance}`,
              } as CSSProperties;
              return (
                <article
                  key={item.id}
                  className={`disc-card ${isActive ? "active" : ""} ${isTarget ? "is-target" : ""} ${isCardTransitioning && isActive && !isTarget ? "is-exiting" : ""} ${offset < 0 ? "is-before" : offset > 0 ? "is-after" : ""} ${isInStack ? "" : "is-hidden"}`}
                  data-exploration-id={item.id}
                  style={cardStyle}
                  onClick={() => !isActive && setSelectedExplorationId(item.id)}
                  aria-label={item.title}
                  aria-hidden={!isInStack}
                >
                  <div>
                    <span className="disc-kicker">{item.id === draftExplorationId ? "草稿" : item.id}</span>
                    <h2 className="disc-title">{item.title}</h2>
                  </div>
                  <div className="disc-meta">
                    <span className={`disc-badge ${item.status}`}>{item.status}</span>
                    <span>创建 {formatExplorationTime(item.createdAt ?? item.updatedAt)}</span>
                  </div>
                  {!shouldRenderConversation && (
                    <div className="disc-card-preview" aria-hidden="true">
                      <strong>{item.id === draftExplorationId ? "等待你的问题" : item.summary}</strong>
                      <span>{item.id === draftExplorationId ? "这是一张新的探索会话卡片，输入问题后会开始真实探索。" : `${item.messages.length} 条会话记录`}</span>
                    </div>
                  )}
                  {shouldRenderConversation && (
                    <>
                      <ol className="disc-messages" ref={isActive ? messagesRef : null}>
                        {itemMessages.map((message) => (
                          <li key={message.id} className={`exploration-message ${message.role}`}>
                            <span className={`message-avatar ${message.role === "user" ? "user-avatar" : ""}`} aria-hidden="true">
                              {message.role === "user" ? (
                                "J"
                              ) : (
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                  <rect x="4" y="7" width="16" height="12" rx="2" />
                                  <path d="M12 3v4" />
                                  <circle cx="9" cy="13" r="0.6" fill="currentColor" />
                                  <circle cx="15" cy="13" r="0.6" fill="currentColor" />
                                  <path d="M2 12v3" />
                                  <path d="M22 12v3" />
                                </svg>
                              )}
                            </span>
                            <div className={`message-bubble ${message.title ? messageTitleClass(message.title) : ""}`}>
                              {message.title && <strong className={`message-title ${messageTitleClass(message.title)}`}>{message.title}</strong>}
                              <div className="message-body-markdown">
                                <MarkdownContent>{message.body}</MarkdownContent>
                              </div>
                              {message.details?.map((group) => (
                                <details key={group.label} className="message-details">
                                  <summary>{group.label}</summary>
                                  <ul>
                                    {group.items.map((detailItem) => (
                                      <li key={detailItem}>{detailItem}</li>
                                    ))}
                                  </ul>
                                </details>
                              ))}
                              {message.action && (
                                <button
                                  className="knowledge-save"
                                  type="button"
                                  onClick={() => saveExplorationKnowledge(message)}
                                  disabled={knowledgeSavingId === message.id}
                                >
                                  {knowledgeSavingId === message.id ? "保存中" : message.action}
                                </button>
                              )}
                            </div>
                          </li>
                        ))}
                        {showExplorationWaiting && (
                          <li className="exploration-message agent exploration-thinking" aria-live="polite">
                            <span className="message-avatar" aria-hidden="true">
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                <rect x="4" y="7" width="16" height="12" rx="2" />
                                <path d="M12 3v4" />
                                <circle cx="9" cy="13" r="0.6" fill="currentColor" />
                                <circle cx="15" cy="13" r="0.6" fill="currentColor" />
                                <path d="M2 12v3" />
                                <path d="M22 12v3" />
                              </svg>
                            </span>
                            <div className="message-bubble">
                              <strong className="message-title is-progress">等待 Agent 返回</strong>
                              <div className="message-body-markdown">
                                <p>Agent 正在调用工具或等待模型输出。</p>
                                <p className="thinking-note">{waitingContext}</p>
                              </div>
                              <span className="thinking-status-line" aria-hidden="true" />
                            </div>
                          </li>
                        )}
                      </ol>

                      <form className="exploration-composer" onSubmit={submitExploration}>
                        <textarea
                          value={draft}
                          onChange={(event) => setDraft(event.target.value)}
                          onKeyDown={submitExplorationFromKeyboard}
                          placeholder="输入探索问题，或补充 Agent 需要确认的口径"
                          rows={2}
                        />
                        <button
                          type={submitting ? "button" : "submit"}
                          className={submitting ? "is-stopping" : ""}
                          aria-label={submitting ? "停止对话" : "发送"}
                          title={submitting ? "停止对话" : "发送"}
                          disabled={!submitting && !draft.trim()}
                          onClick={submitting ? stopExploration : undefined}
                        >
                          {submitting ? (
                            <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
                              <rect x="5.5" y="5.5" width="13" height="13" rx="2" />
                            </svg>
                          ) : (
                            <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M12 19V5" />
                              <path d="m5 12 7-7 7 7" />
                            </svg>
                          )}
                        </button>
                      </form>
                    </>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      )}

      {tab === "resources" && (
        <article className="exploration-detail resource-detail">
          <span className="exploration-kicker">{selectedResource.type.toUpperCase()}</span>
          <h2>{selectedResource.name}</h2>
          <p>{selectedResource.description}</p>
          <dl>
            <div>
              <dt>索引状态</dt>
              <dd>{resourceStatus?.indexed ? `${resourceStatus.resourceCount} 项资源` : "本地演示数据"}</dd>
            </div>
            <div>
              <dt>来源</dt>
              <dd>{selectedResource.location}</dd>
            </div>
            <div>
              <dt>适用动作</dt>
              <dd>查看、引用到探索、作为验证依据</dd>
            </div>
            <div>
              <dt>更新时间</dt>
              <dd>{resourceStatus?.summaryModifiedAt?.slice(0, 10) ?? "未连接"}</dd>
            </div>
          </dl>
          <div className="exploration-actions">
            <button className="exploration-open" type="button" onClick={bringResourceIntoExploration} disabled={selectedResource.id === emptyResource.id}>
              带入新的探索
            </button>
            <button className="exploration-open secondary" type="button" onClick={refreshResourceIndex} disabled={resourceRefreshing}>
              {resourceRefreshing ? "刷新中" : "刷新索引"}
            </button>
            <button className="exploration-open secondary" type="button" onClick={loadSelectedResourceDetail} disabled={resourceDetailLoading}>
              {resourceDetailLoading ? "读取中" : "查看结构摘要"}
            </button>
            <button className="exploration-open secondary" type="button" onClick={loadSelectedResourceExcerpt} disabled={resourceExcerptLoading}>
              {resourceExcerptLoading ? "读取中" : "查看证据片段"}
            </button>
          </div>
          <div className="resource-signals" aria-label="资源结构摘要">
            <div>
              <strong>结构摘要</strong>
              <small>
                {resourceDetail
                  ? `${resourceDetail.status}${resourceDetail.truncatedSummary ? " · 已截断" : ""}`
                  : "待读取"}
              </small>
            </div>
            {resourceDetail?.profileItems.length ? (
              <div className="resource-profile" aria-label="资源画像">
                {resourceDetail.profileItems.map((item) => (
                  <section key={item.label}>
                    <span>{item.label}</span>
                    <strong>{item.value}</strong>
                  </section>
                ))}
              </div>
            ) : (
              <p>点击“查看结构摘要”后，这里会显示文件大小、更新时间、摘要范围和读取告警。</p>
            )}
            {resourceDetail?.signalGroups.length ? (
              <div className="signal-grid">
                {resourceDetail.signalGroups.map((group) => (
                  <section key={group.label}>
                    <h3>{group.label}</h3>
                    <ul>
                      {group.items.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            ) : (
              <p>点击“查看结构摘要”后，这里会显示数据集候选、表引用、参数候选等结构信号。</p>
            )}
            {resourceDetail?.warnings.length ? <small>{resourceDetail.warnings.join("；")}</small> : null}
          </div>
          <div className="resource-excerpt" aria-label="资源证据片段">
            <div>
              <strong>证据片段</strong>
              <small>
                {resourceExcerpt
                  ? `${resourceExcerpt.relativePath} · ${resourceExcerpt.startLine}-${resourceExcerpt.endLine}`
                  : "待读取"}
              </small>
            </div>
            <pre>
              {resourceExcerpt?.text ||
                "连接探索后端并点击“查看证据片段”后，这里会显示受控行数内的资源内容。"}
            </pre>
            {resourceExcerpt?.truncated && <small>该片段已按服务端限制截断。</small>}
          </div>
        </article>
      )}

      {tab === "knowledge" && (
        <article className="exploration-detail knowledge-detail">
          <span className="exploration-kicker">VERIFIED KNOWLEDGE</span>
          <h2>{selectedKnowledge.title}</h2>
          <dl>
            {selectedKnowledge.question && (
              <div>
                <dt>来源问题</dt>
                <dd>{selectedKnowledge.question}</dd>
              </div>
            )}
            <div>
              <dt>适用范围</dt>
              <dd>{selectedKnowledge.scope}</dd>
            </div>
            <div>
              <dt>最后验证</dt>
              <dd>{selectedKnowledge.verified}</dd>
            </div>
            {selectedKnowledge.verification && (
              <div>
                <dt>验证方式</dt>
                <dd>{selectedKnowledge.verification}</dd>
              </div>
            )}
            {selectedKnowledge.runId && (
              <div>
                <dt>来源探索</dt>
                <dd>{selectedKnowledge.runId}</dd>
              </div>
            )}
          </dl>
          <p>{selectedKnowledge.note}</p>
          <section className="knowledge-evidence" aria-label="知识证据引用">
            <div>
              <strong>证据引用</strong>
              <small>{selectedKnowledge.evidenceRefs?.length ? `${selectedKnowledge.evidenceRefs.length} 项` : "暂无"}</small>
            </div>
            {selectedKnowledge.evidenceRefs?.length ? (
              <ul>
                {selectedKnowledge.evidenceRefs.map((item) => (
                  <li key={item}>
                    <button type="button" onClick={() => openEvidenceResource(item)}>
                      {item}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p>这条知识暂未记录证据引用。后续从探索过程沉淀时会自动带入资源和证据。</p>
            )}
          </section>
          <div className="exploration-actions">
            <button className="exploration-open" type="button" onClick={() => setTab("resources")}>
              查看参考资源
            </button>
            <button
              className="exploration-open secondary"
              type="button"
              onClick={loadSelectedKnowledgeRunTrace}
              disabled={runTraceLoading || !selectedKnowledge.runId}
            >
              {runTraceLoading ? "读取中" : "查看执行追踪"}
            </button>
            <button
              className="exploration-open danger"
              type="button"
              onClick={deleteSelectedKnowledge}
              disabled={knowledgeDeleting || selectedKnowledge.id === emptyKnowledge.id}
            >
              {knowledgeDeleting ? "删除中" : "删除知识"}
            </button>
          </div>
          {(selectedRunTrace || runTraceMissing) && (
            <section className="run-trace-panel" aria-label="来源执行追踪">
              <div>
                <strong>来源执行追踪</strong>
                <small>{selectedRunTrace ? selectedRunTrace.status : "未找到"}</small>
              </div>
              {selectedRunTrace ? (
                <>
                  <p>{selectedRunTrace.question}</p>
                  <div className="run-trace-metrics">
                    {selectedRunTrace.metrics.map((metric) => (
                      <section key={metric.label}>
                        <span>{metric.label}</span>
                        <strong>{metric.value}</strong>
                      </section>
                    ))}
                  </div>
                  {selectedRunTrace.error && <small>错误：{selectedRunTrace.error}</small>}
                </>
              ) : (
                <p>当前后端没有这次来源 Run 的追踪记录，可能是本地 demo 知识或 trace 文件尚未生成。</p>
              )}
            </section>
          )}
        </article>
      )}

    </section>
  );
}
