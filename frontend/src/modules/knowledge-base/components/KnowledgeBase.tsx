"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";

import { createKnowledgeBaseItem, listKnowledgeBaseItems, listKnowledgeBaseTags, updateKnowledgeBaseItem } from "../api";
import { deriveKnowledgeTags, filterKnowledgeItems } from "../logic";
import {
  knowledgeSourceLabels,
  knowledgeStatusLabels,
  knowledgeTypeLabels,
  knowledgeVisibilityLabels,
  semanticTypes,
} from "../mock";
import type { ApprovalRole, KnowledgeApproval, KnowledgeBaseItem, KnowledgeBaseTab, KnowledgeFilterState, KnowledgeItemType, KnowledgeSaveInput, KnowledgeStatus, KnowledgeTag, KnowledgeVisibility } from "../types";

const tabs: Array<{ id: KnowledgeBaseTab; label: string; hint: string }> = [
  { id: "all", label: "全部知识", hint: "统一检索指标、字段、表、报表和口径" },
  { id: "semantic", label: "语义层", hint: "业务语言到数据实现的映射" },
  { id: "exploration", label: "探索沉淀", hint: "从探索会话保存的验证结论" },
  { id: "certification", label: "认证中心", hint: "处理待确认、冲突和过期知识" },
  { id: "tags", label: "标签体系", hint: "维护业务域、场景和治理标签" },
];

const initialFilters: KnowledgeFilterState = {
  tab: "all",
  query: "",
  type: "all",
  status: "all",
  tag: "all",
  owner: "all",
};

const emptyInput: KnowledgeSaveInput = {
  title: "",
  type: "metric_definition",
  content: "",
  businessDefinition: "",
  technicalDefinition: "",
  formula: "",
  scope: "",
  excludedScope: "",
  owner: "未分配",
  visibility: "team",
  status: "draft",
  tags: [],
  relatedTables: [],
  relatedFields: [],
  relatedResources: [],
  agentVisible: true,
};

export function KnowledgeBase() {
  const [items, setItems] = useState<KnowledgeBaseItem[]>([]);
  const [backendTags, setBackendTags] = useState<KnowledgeTag[]>([]);
  const [filters, setFilters] = useState<KnowledgeFilterState>(initialFilters);
  const [selectedId, setSelectedId] = useState<string>("");
  const [mode, setMode] = useState<"view" | "edit" | "create">("view");
  const [draft, setDraft] = useState<KnowledgeSaveInput>(emptyInput);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("正在载入知识库");

  useEffect(() => {
    let alive = true;
    Promise.all([listKnowledgeBaseItems(), listKnowledgeBaseTags()]).then(([nextItems, nextTags]) => {
      if (!alive) return;
      setItems(nextItems);
      setBackendTags(nextTags);
      setSelectedId(nextItems[0]?.id ?? "");
      setNotice(nextItems.length ? "知识库已就绪" : "暂无知识");
    });
    return () => {
      alive = false;
    };
  }, []);

  const tags = useMemo(() => deriveKnowledgeTags(items, backendTags), [backendTags, items]);
  const owners = useMemo(() => Array.from(new Set(items.map((item) => item.owner))).filter(Boolean), [items]);
  const filteredItems = useMemo(() => filterKnowledgeItems(items, filters), [filters, items]);
  const selected = items.find((item) => item.id === selectedId) ?? filteredItems[0] ?? items[0];

  useEffect(() => {
    if (selected && !items.some((item) => item.id === selectedId)) setSelectedId(selected.id);
  }, [items, selected, selectedId]);

  function switchTab(tab: KnowledgeBaseTab) {
    setFilters((current) => ({ ...current, tab, type: "all", status: "all", tag: "all" }));
    setMode("view");
  }

  function startCreate(type: KnowledgeItemType = "metric_definition") {
    setDraft({ ...emptyInput, type });
    setMode("create");
  }

  function startEdit(item: KnowledgeBaseItem) {
    setDraft(toInput(item));
    setMode("edit");
  }

  async function saveDraft() {
    if (!draft.title.trim() || saving) return;
    setSaving(true);
    try {
      if (mode === "create") {
        const saved = await createKnowledgeBaseItem(draft);
        const next = saved ?? localItemFromInput(draft);
        setItems((current) => [next, ...current]);
        setSelectedId(next.id);
        setNotice(saved ? "已保存到后端知识库" : "后端不可用，已在当前页面创建演示知识");
      } else if (mode === "edit" && selected) {
        const saved = await updateKnowledgeBaseItem(selected.id, draft);
        const next = saved ?? { ...selected, ...itemFieldsFromInput(draft), updatedAt: today() };
        setItems((current) => current.map((item) => (item.id === selected.id ? next : item)));
        setNotice(saved ? "已更新后端知识库" : "后端不可用，已在当前页面更新演示知识");
      }
      setMode("view");
    } finally {
      setSaving(false);
    }
  }

  function toggleApproval(role: string) {
    if (!selected) return;
    const approvals = selected.approvals.some((item) => item.role === role)
      ? selected.approvals.map((item) => {
          const nextStatus: KnowledgeApproval["status"] = item.status === "approved" ? "pending" : "approved";
          return item.role === role ? { ...item, status: nextStatus, approvedAt: today() } : item;
        })
      : [...selected.approvals, { role: role as ApprovalRole, approver: "当前用户", status: "approved" as const, approvedAt: today() }];
    setItems((current) => current.map((item) => (item.id === selected.id ? { ...item, approvals, status: approvals.some((approval) => approval.status === "pending") ? "pending" : item.status } : item)));
  }

  return (
    <article className="knowledge-base-workspace" aria-label="知识库">
      <header className="knowledge-base-topbar">
        <div>
          <span className="exploration-kicker">KNOWLEDGE BASE</span>
          <h2>知识库</h2>
          <p>管理可复用、可治理、可被 Agent 调用的业务语义与验证结论。</p>
        </div>
        <div className="knowledge-base-actions">
          <button type="button" className="secondary">导入</button>
          <button type="button" className="secondary">批量打标</button>
          <button type="button" className="secondary" onClick={() => switchTab("certification")}>待认证 {items.filter((item) => item.status === "pending").length}</button>
          <button type="button" onClick={() => startCreate()}>新建知识</button>
        </div>
      </header>

      <nav className="knowledge-base-tabs" aria-label="知识库导航">
        {tabs.map((tab) => (
          <button key={tab.id} type="button" className={filters.tab === tab.id ? "active" : ""} onClick={() => switchTab(tab.id)}>
            <strong>{tab.label}</strong>
            <span>{tab.hint}</span>
          </button>
        ))}
      </nav>

      <section className="knowledge-base-grid">
        <aside className="knowledge-base-filters" aria-label="知识筛选">
          <label className="knowledge-search">
            <span>搜索</span>
            <input value={filters.query} onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))} placeholder="搜指标、字段、表、报表、口径" />
          </label>
          <FilterBlock title="知识分类">
            <button type="button" className={filters.type === "all" ? "active" : ""} onClick={() => setFilters((current) => ({ ...current, type: "all" }))}>全部类型</button>
            {Object.entries(knowledgeTypeLabels).map(([type, label]) => (
              <button key={type} type="button" className={filters.type === type ? "active" : ""} onClick={() => setFilters((current) => ({ ...current, type: type as KnowledgeItemType }))}>
                {label}
              </button>
            ))}
          </FilterBlock>
          <FilterBlock title="语义层">
            {semanticTypes.map((type) => (
              <button key={type} type="button" onClick={() => setFilters((current) => ({ ...current, tab: "semantic", type }))}>
                {knowledgeTypeLabels[type]}
              </button>
            ))}
          </FilterBlock>
          <FilterBlock title="治理状态">
            {(["all", "approved", "pending", "conflicted", "expired", "draft"] as const).map((status) => (
              <button key={status} type="button" className={filters.status === status ? "active" : ""} onClick={() => setFilters((current) => ({ ...current, status }))}>
                {status === "all" ? "全部状态" : knowledgeStatusLabels[status]}
              </button>
            ))}
          </FilterBlock>
          <FilterBlock title="负责人">
            <button type="button" className={filters.owner === "all" ? "active" : ""} onClick={() => setFilters((current) => ({ ...current, owner: "all" }))}>全部负责人</button>
            {owners.map((owner) => (
              <button key={owner} type="button" className={filters.owner === owner ? "active" : ""} onClick={() => setFilters((current) => ({ ...current, owner }))}>{owner}</button>
            ))}
          </FilterBlock>
          <FilterBlock title="标签">
            {tags.slice(0, 12).map((tag) => (
              <button key={tag.name} type="button" className={filters.tag === tag.name ? "active" : ""} onClick={() => setFilters((current) => ({ ...current, tag: current.tag === tag.name ? "all" : tag.name }))}>
                {tag.name} <small>{tag.count}</small>
              </button>
            ))}
          </FilterBlock>
        </aside>

        <section className="knowledge-base-list" aria-label="知识列表">
          <div className="knowledge-list-head">
            <div>
              <strong>{tabs.find((tab) => tab.id === filters.tab)?.label}</strong>
              <span>{filteredItems.length} 条知识 · {notice}</span>
            </div>
            <button type="button" className="secondary" onClick={() => startCreate(filters.type === "all" ? "metric_definition" : filters.type)}>按当前分类新建</button>
          </div>

          {filters.tab === "tags" ? (
            <TagSystemView tags={tags} onSelect={(tag) => setFilters((current) => ({ ...current, tab: "all", tag }))} />
          ) : (
            <div className="knowledge-cards">
              {filteredItems.map((item) => (
                <button key={item.id} type="button" className={`knowledge-card ${selected?.id === item.id ? "active" : ""}`} onClick={() => { setSelectedId(item.id); setMode("view"); }}>
                  <span className={`knowledge-status ${item.status}`}>{knowledgeStatusLabels[item.status]}</span>
                  <strong>{item.title}</strong>
                  <p>{item.businessDefinition || item.content}</p>
                  <div>
                    <small>{knowledgeTypeLabels[item.type]}</small>
                    <small>{knowledgeSourceLabels[item.source]}</small>
                    <small>{item.owner}</small>
                  </div>
                  <span className="knowledge-card-tags">{item.tags.slice(0, 3).join(" / ")}</span>
                </button>
              ))}
              {filteredItems.length === 0 && <p className="knowledge-empty">没有命中的知识。可以调整筛选，或新建一条语义定义。</p>}
            </div>
          )}
        </section>

        <section className="knowledge-base-detail" aria-label="知识详情">
          {mode === "create" || mode === "edit" ? (
            <KnowledgeEditor
              draft={draft}
              mode={mode}
              saving={saving}
              onChange={setDraft}
              onCancel={() => setMode("view")}
              onSave={saveDraft}
            />
          ) : selected ? (
            <KnowledgeDetail item={selected} onEdit={() => startEdit(selected)} onToggleApproval={toggleApproval} />
          ) : (
            <div className="knowledge-empty-detail">选择一条知识查看详情。</div>
          )}
        </section>
      </section>
    </article>
  );
}

function FilterBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="knowledge-filter-block">
      <h3>{title}</h3>
      <div>{children}</div>
    </section>
  );
}

function TagSystemView({ tags, onSelect }: { tags: KnowledgeTag[]; onSelect: (tag: string) => void }) {
  const groups = Array.from(new Set(tags.map((tag) => tag.group)));
  return (
    <div className="knowledge-tag-system">
      {groups.map((group) => (
        <section key={group}>
          <header>
            <strong>{group}</strong>
            <small>{tags.filter((tag) => tag.group === group).length} 个标签</small>
          </header>
          <div>
            {tags.filter((tag) => tag.group === group).map((tag) => (
              <button key={tag.name} type="button" onClick={() => onSelect(tag.name)}>
                <span>{tag.name}</span>
                <small>{tag.count}</small>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function KnowledgeDetail({ item, onEdit, onToggleApproval }: { item: KnowledgeBaseItem; onEdit: () => void; onToggleApproval: (role: string) => void }) {
  return (
    <div className="knowledge-detail-panel">
      <header>
        <div>
          <span className={`knowledge-status ${item.status}`}>{knowledgeStatusLabels[item.status]}</span>
          <h3>{item.title}</h3>
          <p>{knowledgeTypeLabels[item.type]} · {knowledgeSourceLabels[item.source]} · {knowledgeVisibilityLabels[item.visibility]}</p>
        </div>
        <button type="button" onClick={onEdit}>编辑</button>
      </header>

      <DetailSection title="概览">
        <InfoGrid items={[
          ["创建人", item.createdBy],
          ["负责人", item.owner],
          ["版本", item.version],
          ["更新时间", item.updatedAt],
          ["有效期", item.expiresAt ?? "长期有效"],
          ["Agent 可见", item.agentVisible ? "可检索" : "暂不开放"],
        ]} />
        <p>{item.content}</p>
      </DetailSection>

      <DetailSection title="语义定义">
        <Definition label="业务解释" value={item.businessDefinition} />
        <Definition label="技术定义" value={item.technicalDefinition} />
        {item.formula && <pre>{item.formula}</pre>}
        <InfoGrid items={[["适用范围", item.scope], ["不适用范围", item.excludedScope || "未记录"]]} />
      </DetailSection>

      <DetailSection title="证据与来源">
        <ChipGroup label="关联表" values={item.relatedTables} />
        <ChipGroup label="关联字段" values={item.relatedFields} />
        <ChipGroup label="关联资源" values={[...item.relatedResources, ...item.evidenceRefs]} />
        {item.sourceQuestion && <Definition label="来源问题" value={item.sourceQuestion} />}
        {item.sourceExplorationId && <Definition label="来源探索" value={item.sourceExplorationId} />}
      </DetailSection>

      <DetailSection title="认证记录">
        <div className="approval-grid">
          {["BI 工程师", "财务", "运营", "数据负责人", "管理层"].map((role) => {
            const approval = item.approvals.find((entry) => entry.role === role);
            return (
              <button key={role} type="button" className={approval?.status === "approved" ? "approved" : ""} onClick={() => onToggleApproval(role)}>
                <strong>{role}</strong>
                <span>{approval?.status === "approved" ? `${approval.approver} 已认可` : "待认可"}</span>
              </button>
            );
          })}
        </div>
      </DetailSection>

      <DetailSection title="关联对象">
        <ChipGroup label="标签" values={item.tags} />
        <ChipGroup label="冲突关系" values={item.conflicts.length ? item.conflicts : ["暂无冲突"]} />
      </DetailSection>

      <DetailSection title="版本历史">
        <Timeline items={item.versionHistory.map((version) => `${version.changedAt} · ${version.version} · ${version.author}：${version.note}`)} />
      </DetailSection>

      <DetailSection title="Agent 使用记录">
        <Timeline items={item.usageRecords.length ? item.usageRecords.map((usage) => `${usage.usedAt} · ${usage.agent}：${usage.context}`) : ["暂未被 Agent 引用"]} />
      </DetailSection>
    </div>
  );
}

function KnowledgeEditor({ draft, mode, saving, onChange, onCancel, onSave }: {
  draft: KnowledgeSaveInput;
  mode: "create" | "edit";
  saving: boolean;
  onChange: (draft: KnowledgeSaveInput) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <div className="knowledge-editor">
      <header>
        <div>
          <span className="exploration-kicker">{mode === "create" ? "CREATE KNOWLEDGE" : "EDIT KNOWLEDGE"}</span>
          <h3>{mode === "create" ? "新建知识" : "编辑知识"}</h3>
        </div>
        <div>
          <button type="button" className="secondary" onClick={onCancel}>取消</button>
          <button type="button" onClick={onSave} disabled={saving || !draft.title.trim()}>{saving ? "保存中" : "保存"}</button>
        </div>
      </header>
      <label>
        <span>标题</span>
        <input value={draft.title} onChange={(event) => onChange({ ...draft, title: event.target.value })} placeholder="例如：毛利率" />
      </label>
      <div className="editor-row">
        <SelectField label="类型" value={draft.type} options={knowledgeTypeLabels} onChange={(value) => onChange({ ...draft, type: value as KnowledgeItemType })} />
        <SelectField label="状态" value={draft.status} options={knowledgeStatusLabels} onChange={(value) => onChange({ ...draft, status: value as KnowledgeStatus })} />
        <SelectField label="可见范围" value={draft.visibility} options={knowledgeVisibilityLabels} onChange={(value) => onChange({ ...draft, visibility: value as KnowledgeVisibility })} />
      </div>
      <label>
        <span>正文</span>
        <textarea value={draft.content} onChange={(event) => onChange({ ...draft, content: event.target.value })} rows={4} />
      </label>
      <label>
        <span>业务解释</span>
        <textarea value={draft.businessDefinition} onChange={(event) => onChange({ ...draft, businessDefinition: event.target.value })} rows={3} />
      </label>
      <label>
        <span>技术定义</span>
        <textarea value={draft.technicalDefinition} onChange={(event) => onChange({ ...draft, technicalDefinition: event.target.value })} rows={3} />
      </label>
      <label>
        <span>公式</span>
        <input value={draft.formula} onChange={(event) => onChange({ ...draft, formula: event.target.value })} placeholder="例如：(收入 - 成本) / 收入" />
      </label>
      <div className="editor-row">
        <TextListField label="标签" value={draft.tags} onChange={(tags) => onChange({ ...draft, tags })} />
        <TextListField label="关联表" value={draft.relatedTables} onChange={(relatedTables) => onChange({ ...draft, relatedTables })} />
      </div>
      <div className="editor-row">
        <TextListField label="关联字段" value={draft.relatedFields} onChange={(relatedFields) => onChange({ ...draft, relatedFields })} />
        <TextListField label="关联资源" value={draft.relatedResources} onChange={(relatedResources) => onChange({ ...draft, relatedResources })} />
      </div>
      <div className="editor-row">
        <label>
          <span>适用范围</span>
          <input value={draft.scope} onChange={(event) => onChange({ ...draft, scope: event.target.value })} />
        </label>
        <label>
          <span>不适用范围</span>
          <input value={draft.excludedScope} onChange={(event) => onChange({ ...draft, excludedScope: event.target.value })} />
        </label>
      </div>
      <div className="editor-row">
        <label>
          <span>负责人</span>
          <input value={draft.owner} onChange={(event) => onChange({ ...draft, owner: event.target.value })} />
        </label>
        <label className="knowledge-toggle">
          <input type="checkbox" checked={draft.agentVisible} onChange={(event) => onChange({ ...draft, agentVisible: event.target.checked })} />
          <span>允许 Agent 检索</span>
        </label>
      </div>
    </div>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: Record<string, string>; onChange: (value: string) => void }) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {Object.entries(options).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
    </label>
  );
}

function TextListField({ label, value, onChange }: { label: string; value: string[]; onChange: (value: string[]) => void }) {
  return (
    <label>
      <span>{label}</span>
      <input value={value.join("，")} onChange={(event) => onChange(splitList(event.target.value))} placeholder="用逗号分隔" />
    </label>
  );
}

function DetailSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="knowledge-detail-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function Definition({ label, value }: { label: string; value: string }) {
  return (
    <div className="knowledge-definition">
      <strong>{label}</strong>
      <p>{value || "未记录"}</p>
    </div>
  );
}

function InfoGrid({ items }: { items: Array<[string, string]> }) {
  return (
    <dl className="knowledge-info-grid">
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ChipGroup({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="knowledge-chip-group">
      <strong>{label}</strong>
      <div>{values.length ? values.map((value) => <span key={value}>{value}</span>) : <span>未记录</span>}</div>
    </div>
  );
}

function Timeline({ items }: { items: string[] }) {
  return <ol className="knowledge-timeline">{items.map((item) => <li key={item}>{item}</li>)}</ol>;
}

function toInput(item: KnowledgeBaseItem): KnowledgeSaveInput {
  return {
    title: item.title,
    type: item.type,
    content: item.content,
    businessDefinition: item.businessDefinition,
    technicalDefinition: item.technicalDefinition,
    formula: item.formula,
    scope: item.scope,
    excludedScope: item.excludedScope,
    owner: item.owner,
    visibility: item.visibility,
    status: item.status,
    tags: item.tags,
    relatedTables: item.relatedTables,
    relatedFields: item.relatedFields,
    relatedResources: item.relatedResources,
    agentVisible: item.agentVisible,
  };
}

function itemFieldsFromInput(input: KnowledgeSaveInput) {
  return {
    title: input.title,
    type: input.type,
    content: input.content,
    businessDefinition: input.businessDefinition,
    technicalDefinition: input.technicalDefinition,
    formula: input.formula,
    scope: input.scope,
    excludedScope: input.excludedScope,
    owner: input.owner,
    visibility: input.visibility,
    status: input.status,
    tags: input.tags,
    relatedTables: input.relatedTables,
    relatedFields: input.relatedFields,
    relatedResources: input.relatedResources,
    agentVisible: input.agentVisible,
  };
}

function localItemFromInput(input: KnowledgeSaveInput): KnowledgeBaseItem {
  const now = today();
  return {
    id: `kn_local_${Date.now()}`,
    ...itemFieldsFromInput(input),
    source: "manual",
    evidenceRefs: input.relatedResources,
    createdBy: "当前用户",
    approvals: [],
    version: "v1.0",
    updatedAt: now,
    conflicts: [],
    usageRecords: [],
    versionHistory: [{ version: "v1.0", author: "当前用户", changedAt: now, note: "手动创建" }],
  };
}

function splitList(value: string) {
  return value.split(/[，,\n]/).map((item) => item.trim()).filter(Boolean);
}

function today() {
  return new Date().toISOString().slice(0, 10);
}
