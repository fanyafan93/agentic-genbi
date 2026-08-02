"use client";

import { useState } from "react";
import { EChartRenderer } from "@/shared/charts/EChartRenderer";
import { mockArtifact } from "./artifact-mock";
import { buildAnalysisAssetCards, describeArtifact, getJsonPreview, getMarkdownPreview, getSqlPreview, pythonCode } from "./analysis-assets";
import type { AnalysisAssetSaveRequest, AnalysisAssetSourceContext } from "./analysis-asset-contracts";
import type { AnalysisAssetCard } from "./analysis-assets";
import type { AnalysisRow } from "../types/analysis";
import type { ArtifactFile, ArtifactFolder } from "../types/artifact";

type Props = {
  taskTitle: string;
  sourceContext: AnalysisAssetSourceContext;
  folders: ArtifactFolder[];
  files: ArtifactFile[];
  activeFile?: ArtifactFile;
  openFileIds: string[];
  expandedFolders: Record<string, boolean>;
  savedAssetIds: string[];
  explorerCollapsed: boolean;
  mobileHidden: boolean;
  lastSaveRequest?: AnalysisAssetSaveRequest;
  onToggleExplorer: () => void;
  onToggleFolder: (folderId: string) => void;
  onOpenFile: (file: ArtifactFile) => void;
  onActivateFile: (fileId: string) => void;
  onCloseFile: (fileId: string) => void;
  onSaveAsset: (asset: AnalysisAssetCard) => void;
  onContinueFromAsset: (asset: AnalysisAssetCard) => void;
};

function formatCell(value: AnalysisRow[string]) {
  if (typeof value !== "number") return value;
  if (Math.abs(value) < 1) return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString("zh-CN");
}

function FileKind({ file }: { file: ArtifactFile }) {
  return <span className={`file-kind ${file.kind}`}>{file.kind === "python" ? "PY" : file.kind.slice(0, 3).toUpperCase()}</span>;
}

function isSkillFile(file: ArtifactFile) {
  return file.name.toLowerCase().includes("skill");
}

function SkillDraftPreview() {
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [scenarioReady, setScenarioReady] = useState(false);
  const [metricReady, setMetricReady] = useState(false);
  const [permissionReady, setPermissionReady] = useState(false);
  const [published, setPublished] = useState(false);
  const [scenario, setScenario] = useState("当用户询问渠道销售占比、渠道增长来源或渠道结构变化时使用。");
  const [confirmations, setConfirmations] = useState("销售额口径\n时间范围\n退款/取消/测试订单排除\n复用权限");
  const [steps, setSteps] = useState("确认业务口径和分析范围\n检索语义模型与历史 SQL\n生成并校验只读 SQL\n产出图表、报告和风险提示\n沉淀为可复用 Skill");
  const confirmationList = confirmations.split("\n").map((item) => item.trim()).filter(Boolean);
  const stepList = steps.split("\n").map((item) => item.trim()).filter(Boolean);
  const references = ["candidate.sql", "channel_share.chart.json", "analysis_report.html"];
  const referencesReady = references.length >= 3;
  const publishReady = saved && scenarioReady && metricReady && permissionReady && referencesReady;
  const publicationMetadata = {
    methodId: "method_channel_sales_skill",
    version: "v0.1-draft",
    visibility: "team",
    sourceTask: "渠道销售占比分析",
    sourceTurn: "turn_mock_skill_publish",
    sourceAssets: ["analysis_skill.md", ...references],
    confirmations: ["适用场景", "销售额口径", "复用权限"],
  };
  const saveDraft = () => {
    setEditing(false);
    setSaved(true);
    setPublished(false);
  };
  const updateScenario = (value: string) => {
    setScenario(value);
    setScenarioReady(false);
    setPublished(false);
  };
  const updateConfirmations = (value: string) => {
    setConfirmations(value);
    setMetricReady(false);
    setPermissionReady(false);
    setPublished(false);
  };

  return (
    <article className="skill-draft-preview" aria-label="Skill 草稿编辑预览">
      <header>
        <span>SKILL DRAFT</span>
        <h2>渠道销售占比分析 Skill</h2>
        <p>把这次成功分析沉淀为下次 Agent 可复用的工作方法。</p>
        <div className="skill-draft-actions">
          <button type="button" onClick={() => setEditing((value) => !value)}>{editing ? "退出编辑" : "编辑草稿"}</button>
          <button type="button" onClick={saveDraft}>保存草稿</button>
          {saved && <em role="status">草稿已保存，等待发布配置</em>}
        </div>
      </header>
      <section>
        <h3>适用场景</h3>
        {editing ? <textarea aria-label="编辑 Skill 适用场景" value={scenario} onChange={(event) => updateScenario(event.target.value)} /> : <p>{scenario}</p>}
      </section>
      <section>
        <h3>需要确认</h3>
        {editing ? (
          <textarea aria-label="编辑 Skill 需要确认" value={confirmations} onChange={(event) => updateConfirmations(event.target.value)} />
        ) : (
          <div className="skill-confirmation-grid">
            {confirmationList.map((item) => <span key={item}>{item}</span>)}
          </div>
        )}
      </section>
      <section>
        <h3>推荐步骤</h3>
        {editing ? <textarea aria-label="编辑 Skill 推荐步骤" value={steps} onChange={(event) => setSteps(event.target.value)} /> : <ol>{stepList.map((step) => <li key={step}>{step}</li>)}</ol>}
      </section>
      <section>
        <h3>引用资产</h3>
        <div className="skill-reference-list">
          {references.map((item) => <span key={item}>{item}</span>)}
        </div>
      </section>
      <section className="skill-readiness" aria-label="Skill 发布准备">
        <div className="skill-readiness-header">
          <h3>复用准备</h3>
          <span className={`skill-readiness-status ${publishReady ? "ready" : "blocked"}`}>
            {publishReady ? "可作为分析资产复用" : "还需补齐确认"}
          </span>
        </div>
        <div className="skill-readiness-list">
          <label>
            <input type="checkbox" checked={scenarioReady} onChange={(event) => { setScenarioReady(event.target.checked); setPublished(false); }} />
            已确认适用场景
          </label>
          <label>
            <input type="checkbox" checked={metricReady} onChange={(event) => { setMetricReady(event.target.checked); setPublished(false); }} />
            已确认销售额口径
          </label>
          <label>
            <input type="checkbox" checked={permissionReady} onChange={(event) => { setPermissionReady(event.target.checked); setPublished(false); }} />
            已确认复用权限
          </label>
          <label className="readonly">
            <input type="checkbox" checked={saved} readOnly />
            草稿已保存
          </label>
          <label className="readonly">
            <input type="checkbox" checked={referencesReady} readOnly />
            引用资产齐全
          </label>
        </div>
        <div className="skill-readiness-actions">
          <button type="button" disabled={!publishReady} onClick={() => setPublished(true)}>模拟入库</button>
          <small>当前只检查复用条件，不写入真实审批或权限系统。</small>
          {published && <em role="status">已模拟作为可复用分析方法入库</em>}
        </div>
      </section>
      {published && (
        <section className="skill-publication" aria-label="Skill 复用元数据预览">
          <div className="skill-publication-header">
            <span>REUSABLE METHOD PREVIEW</span>
            <h3>复用元数据预览</h3>
            <p>真实后端需要把这些字段持久化，才能让别人复用 Skill 时追溯来源、版本、权限和确认记录。</p>
          </div>
          <dl className="skill-metadata-grid">
            <div><dt>方法 ID</dt><dd>{publicationMetadata.methodId}</dd></div>
            <div><dt>版本</dt><dd>{publicationMetadata.version}</dd></div>
            <div><dt>可见范围</dt><dd>{publicationMetadata.visibility}</dd></div>
            <div><dt>来源分析任务</dt><dd>{publicationMetadata.sourceTask}</dd></div>
            <div><dt>Codex Turn</dt><dd>{publicationMetadata.sourceTurn}</dd></div>
            <div><dt>入库状态</dt><dd>等待审批 / mock</dd></div>
          </dl>
          <div className="skill-lineage">
            <h3>资产血缘</h3>
            <ol>
              {publicationMetadata.sourceAssets.map((asset) => <li key={asset}>{asset}</li>)}
            </ol>
          </div>
          <div className="skill-approval-record">
            <h3>确认记录</h3>
            <div>
              {publicationMetadata.confirmations.map((item) => <span key={item}>{item}</span>)}
            </div>
          </div>
        </section>
      )}
    </article>
  );
}

export function AnalysisAssetLibrary({
  taskTitle,
  folders,
  files,
  activeFile,
  openFileIds,
  expandedFolders,
  savedAssetIds,
  explorerCollapsed,
  mobileHidden,
  lastSaveRequest,
  onToggleExplorer,
  onToggleFolder,
  onOpenFile,
  onActivateFile,
  onCloseFile,
  onSaveAsset,
  onContinueFromAsset,
}: Props) {
  const assetCards = buildAnalysisAssetCards(files);
  const openCardFile = (fileId?: string) => {
    const file = files.find((item) => item.id === fileId);
    if (file) onOpenFile(file);
  };
  const savedAssets = assetCards.filter((asset) => savedAssetIds.includes(asset.id));
  const getActionLabel = (asset: AnalysisAssetCard) => {
    if (asset.intent === "edit-skill") return "编辑 Skill";
    if (savedAssetIds.includes(asset.id) || asset.status === "reusable") return "继续分析";
    return "保存";
  };

  return (
    <div className={`artifact-workspace ${mobileHidden ? "mobile-hidden" : ""} ${explorerCollapsed ? "explorer-collapsed" : ""}`}>
      <aside className={`artifact-explorer ${explorerCollapsed ? "is-collapsed" : ""}`} aria-label="分析资产库目录">
        <header>
          <div className="explorer-title"><span>CURRENT ASSETS</span><h2>当前任务资产</h2><small>本次分析生成、引用和正在编辑的资产</small></div>
          <button
            type="button"
            className="explorer-toggle"
            title={explorerCollapsed ? "展开目录" : "收起目录"}
            aria-label={explorerCollapsed ? "展开资产目录" : "收起资产目录"}
            aria-expanded={!explorerCollapsed}
            onClick={onToggleExplorer}
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m9 6-6 6 6 6" /><path d="M15 6v12" /></svg>
          </button>
        </header>
        <div className="explorer-stage" aria-hidden={explorerCollapsed}>
          <div className="explorer-view explorer-view-expanded">
            {folders.length === 0 ? (
              <div className="explorer-empty">
                <span aria-hidden="true">◇</span>
                <strong>暂无分析资产</strong>
                <small>开始分析任务后将自动产生报告 / SQL / 脚本 / 数据文件</small>
              </div>
            ) : (
              <section className="asset-task-view" aria-label="当前任务资产视图">
                <div className="artifact-root"><strong>{taskTitle}</strong><small>{files.length} 个资产</small></div>
                {assetCards.length > 0 && (
                  <section className="asset-card-list" aria-label="分析资产摘要">
                    <div className="asset-card-list-title">
                      <strong>可沉淀资产</strong>
                      <small>保存后可从分析资产库回到本任务继续</small>
                    </div>
                    {assetCards.map((asset) => (
                      <article
                        key={asset.id}
                        className={`asset-card ${savedAssetIds.includes(asset.id) ? "confirmed" : asset.status}`}
                      >
                        <button type="button" className="asset-card-main" onClick={() => openCardFile(asset.fileId)}>
                          <span className="asset-card-label">{asset.label}</span>
                          <span className="asset-card-body">
                            <strong>{asset.title}</strong>
                            <small>{asset.description}</small>
                            {asset.intent === "edit-skill" && asset.confirmations && (
                              <em>待确认：{asset.confirmations.join(" / ")}</em>
                            )}
                          </span>
                        </button>
                        <button
                          type="button"
                          className="asset-card-action"
                          onClick={() => asset.intent === "edit-skill" || savedAssetIds.includes(asset.id) || asset.status === "reusable" ? onContinueFromAsset(asset) : onSaveAsset(asset)}
                        >
                          {getActionLabel(asset)}
                        </button>
                      </article>
                    ))}
                    {savedAssets.length > 0 && (
                      <div className="saved-asset-summary" aria-live="polite">
                        <span>已保存到分析资产库</span>
                        {savedAssets.map((asset) => (
                          <button type="button" key={asset.id} onClick={() => onContinueFromAsset(asset)}>
                            <span>{asset.label}</span>
                            <strong>{asset.title}</strong>
                          </button>
                        ))}
                      </div>
                    )}
                    {lastSaveRequest && (
                      <section className="asset-save-preview" aria-label="分析资产保存请求预览">
                        <div>
                          <span>MOCK SAVE PAYLOAD</span>
                          <strong>保存请求预览</strong>
                          <small>未来后端 API 会按这个形状持久化资产和重开上下文。</small>
                        </div>
                        <pre>{JSON.stringify(lastSaveRequest, null, 2)}</pre>
                      </section>
                    )}
                  </section>
                )}
                <div className="artifact-tree">
                  {folders.map((folder) => (
                    <div className="artifact-folder" key={folder.id}>
                      <button type="button" className="folder-row" onClick={() => onToggleFolder(folder.id)}>
                        <span className="folder-toggle" aria-hidden="true">{expandedFolders[folder.id] ? "▾" : "▸"}</span>
                        <strong>{folder.name}</strong>
                        <small>{folder.children.length}</small>
                      </button>
                      {expandedFolders[folder.id] && (
                        <div className="artifact-files">
                          {folder.children.map((file) => {
                            const asset = describeArtifact(file);
                            return (
                              <button type="button" key={file.id} className={activeFile?.id === file.id ? "active" : ""} onClick={() => onOpenFile(file)}>
                                <FileKind file={file} />
                                <span className="artifact-file-text">
                                  <span>{file.name}</span>
                                  <small>{asset.label} · {asset.description}</small>
                                </span>
                              </button>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
          <div className="explorer-view explorer-view-collapsed" aria-hidden={!explorerCollapsed}>
            <div className="artifact-collapsed-meta">
              <span>AR</span>
              <small>{files.length}</small>
            </div>
            <div className="artifact-collapsed-tree">
              {files.map((file) => (
                <button type="button" key={file.id} className={`file-chip ${activeFile?.id === file.id ? "active" : ""}`} title={file.name} aria-label={`打开 ${file.name}`} onClick={() => onOpenFile(file)}>
                  <FileKind file={file} />
                </button>
              ))}
            </div>
          </div>
        </div>
      </aside>

      <section className="artifact-viewer">
        {openFileIds.length > 0 && (
          <div className="artifact-tabs" role="tablist" aria-label="已打开的分析资产库文件">
            {openFileIds.map((fileId) => {
              const file = files.find((item) => item.id === fileId);
              return file ? (
                <div className={`artifact-tab ${activeFile?.id === file.id ? "active" : ""}`} key={file.id}>
                  <button type="button" onClick={() => onActivateFile(file.id)}><FileKind file={file} />{file.name}</button>
                  <button type="button" aria-label={`关闭 ${file.name}`} onClick={() => onCloseFile(file.id)}>×</button>
                </div>
              ) : null;
            })}
          </div>
        )}
        <div className={`artifact-content ${openFileIds.length === 0 ? "is-empty" : ""}`}>
          {openFileIds.length === 0 ? (
            <div className="artifact-empty">
              <span aria-hidden="true">◇</span>
              <strong>未打开任何分析资产</strong>
              <p>请在左侧文件目录中选择一个文件开始预览。</p>
              <button type="button" onClick={() => files[0] && onOpenFile(files[0])} disabled={files.length === 0}>打开 Report.html</button>
            </div>
          ) : activeFile ? (
            <>
              {activeFile.kind === "html" && <div className="report-preview"><div className="metric-row">{mockArtifact.metrics.map((metric) => <div className="metric-card" key={metric.label}><span>{metric.label}</span><strong>{metric.value}</strong><em>{metric.delta}</em></div>)}</div><div className="chart-picker"><button className="active">Bar Chart</button><button>Line Chart</button><button>Pie Chart</button><button>Table</button></div><div className="output-body"><aside className="insight"><h3>关键洞察</h3><ul>{mockArtifact.insights.map((item) => <li key={item}>{item}</li>)}</ul></aside><div className="chart-area"><EChartRenderer spec={mockArtifact.chart} rows={mockArtifact.table} /></div></div></div>}
              {activeFile.kind === "sql" && <pre className="artifact-code sql">{getSqlPreview(activeFile)}</pre>}
              {activeFile.kind === "python" && <pre className="artifact-code python">{pythonCode}</pre>}
              {activeFile.kind === "markdown" && (isSkillFile(activeFile) ? <SkillDraftPreview /> : <article className="markdown-preview"><pre>{getMarkdownPreview(activeFile)}</pre></article>)}
              {activeFile.kind === "json" && <pre className="artifact-code json">{getJsonPreview(activeFile)}</pre>}
              {activeFile.kind === "csv" && <table className="data-table artifact-table"><thead><tr>{Object.keys(mockArtifact.table[0]).map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{mockArtifact.table.map((row) => <tr key={String(row.channel)}>{Object.values(row).map((value, index) => <td key={index}>{formatCell(value)}</td>)}</tr>)}</tbody></table>}
            </>
          ) : null}
        </div>
      </section>
    </div>
  );
}
