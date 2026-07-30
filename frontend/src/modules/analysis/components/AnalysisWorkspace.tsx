"use client";

import { useState, useMemo, useEffect, type PointerEvent as ReactPointerEvent } from "react";
import { UserChip } from "@/modules/auth/components/UserChip";
import { KnowledgeExploration, KnowledgeExplorationProvider, KnowledgeExplorationSidebar } from "@/modules/investigation/components/DataInvestigation";
import { useFlow } from "../hooks/use-flow";
import { AnalysisTaskThread } from "./AnalysisTaskThread";
import { AnalysisAssetLibrary } from "./AnalysisAssetLibrary";
import { mergeArtifactFolders } from "./analysis-assets";
import {
  mockAnalysisAssetLibraryService,
  saveAnalysisAssetToBackend,
  shouldUseBackendAnalysisAssetLibrary,
} from "../api/analysis-asset-library-service";
import type { AnalysisAssetSaveRequest, AnalysisAssetSourceContext } from "./analysis-asset-contracts";
import type { AnalysisAssetCard } from "./analysis-assets";
import { findAnalysisTaskByTitle } from "../agentClients/scripts/analysis-tasks";
import type { AnalysisMode } from "../agentClients";
import type { ArtifactFile } from "../types/artifact";

const navItems = [
  { id: "workspace", label: "工作台", icon: "dashboard" },
  { id: "analysis-tasks", label: "分析任务", icon: "analysisTask" },
  { id: "investigation", label: "知识探索", icon: "investigation" },
  { id: "agent-center", label: "Agent 中心", icon: "agent" },
] as const;

const adminNavItem = { id: "system", label: "系统", icon: "system" } as const;
const analysisTaskGroups = [
  {
    label: "今天",
    items: [
      { title: "渠道销售占比分析", time: "14:32", status: "saved", statusLabel: "已保存" },
      { title: "库存周转异常排查", time: "10:18", status: "running", statusLabel: "运行中" },
    ],
  },
  {
    label: "更早",
    items: [
      { title: "华东区域 GMV 趋势", time: "昨天", status: "readonly", statusLabel: "只读" },
      { title: "月度经营复盘", time: "7月21日", status: "readonly", statusLabel: "只读" },
    ],
  },
] as const;
type NavIconName = (typeof navItems)[number]["icon"] | typeof adminNavItem["icon"];

function NavIcon({ name }: { name: NavIconName }) {
  const paths = {
    dashboard: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    analysisTask: <><path d="M6 3.8h8l4 4V20a1.8 1.8 0 0 1-1.8 1.8H6A1.8 1.8 0 0 1 4.2 20V5.6A1.8 1.8 0 0 1 6 3.8Z" /><path d="M14 4v4h4" /><path className="task-bar task-bar-1" d="M8 17v-3" /><path className="task-bar task-bar-2" d="M11 17v-6" /><path className="task-bar task-bar-3" d="M14 17v-4.5" /></>,
    investigation: <><ellipse cx="10" cy="5.5" rx="5.5" ry="2.5" /><path d="M4.5 5.5v7c0 1.4 2.5 2.5 5.5 2.5.8 0 1.5-.1 2.2-.2" /><path d="M15.5 5.5v3" /><path d="M4.5 9c0 1.4 2.5 2.5 5.5 2.5.8 0 1.5-.1 2.2-.2" /><g className="mag"><circle cx="16.5" cy="15.5" r="3.5" /><path d="m19 18 2 2" /></g></>,
    agent: <><rect x="5" y="7" width="14" height="12" rx="3" /><path d="M12 3v4M9 12h.01M15 12h.01M9 16h6" /><path d="M3 11v4M21 11v4" /></>,
    system: <><path d="M12 3.5 19 6v5.4c0 4.2-2.8 7.6-7 9.1-4.2-1.5-7-4.9-7-9.1V6l7-2.5Z" /><path d="m9 12 2 2 4-4" /></>,
  };

  return <svg data-icon={name} aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

export function AnalysisWorkspace() {
  const [activeTool, setActiveTool] = useState("analysis-tasks");
  const [collapsed, setCollapsed] = useState(false);
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("quick");
  const [selectedAnalysisTask, setSelectedAnalysisTask] = useState<string | null>("渠道销售占比分析");
  const initialScript = findAnalysisTaskByTitle("渠道销售占比分析");
  const initialMessages = initialScript?.messages ?? [];
  const [splitPercent, setSplitPercent] = useState(40);
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({ reports: true, queries: true, scripts: true, data: true });
  const [openFileIds, setOpenFileIds] = useState<string[]>([]);
  const [activeFileId, setActiveFileId] = useState<string>("report");
  const [savedAssetIds, setSavedAssetIds] = useState<string[]>([]);
  const [assetNotice, setAssetNotice] = useState("");
  const [lastSaveRequest, setLastSaveRequest] = useState<AnalysisAssetSaveRequest | undefined>();
  const [mobilePane, setMobilePane] = useState<"analysisTask" | "assetLibrary">("analysisTask");
  const [explorerCollapsed, setExplorerCollapsed] = useState(false);
  const [currentAnalysisTaskId, setCurrentAnalysisTaskId] = useState<string | null>("channel");
  const analysisTaskScriptDef = selectedAnalysisTask ? findAnalysisTaskByTitle(selectedAnalysisTask) : undefined;
  const initialFlowMessages = useMemo(() => {
    if (selectedAnalysisTask === null) return [];
    if (selectedAnalysisTask === "渠道销售占比分析") return initialMessages;
    return analysisTaskScriptDef?.messages ?? [];
  }, [selectedAnalysisTask, analysisTaskScriptDef, initialMessages]);
  const flow = useFlow(currentAnalysisTaskId, initialFlowMessages);
  useEffect(() => {
    if (flow.artifacts.length === 0) return;
    setExpandedFolders((state) => {
      const next = { ...state };
      for (const folder of flow.artifacts) next[folder.id] = true;
      return next;
    });
  }, [flow.artifacts]);
  const isAdmin = true;
  const isNewAnalysisTask = selectedAnalysisTask === null;
  const analysisTaskScript = analysisTaskScriptDef;
  const activeArtifactFolderList = mergeArtifactFolders(analysisTaskScript?.artifacts ?? [], flow.artifacts);
  const artifactFiles = activeArtifactFolderList.flatMap((folder) => folder.children);
  const activeFile = artifactFiles.find((file) => file.id === activeFileId);
  const assetSourceContext: AnalysisAssetSourceContext = {
    sourceTaskId: `analysis_task_${currentAnalysisTaskId ?? flow.runId ?? "current"}`,
    sourceConversationId: flow.conversationId ?? (currentAnalysisTaskId ? `conv_analysis_${currentAnalysisTaskId}` : "conv_analysis_current"),
    sourceRunId: flow.runId ?? "run_mock_asset_save",
  };

  function selectExistingAnalysisTask(title: string) {
    setSelectedAnalysisTask(title);
    const target = findAnalysisTaskByTitle(title);
    if (!target) return;
    setCurrentAnalysisTaskId(target.id);
    setOpenFileIds([]);
    setSavedAssetIds([]);
    setAssetNotice("");
    setLastSaveRequest(undefined);
    setActiveFileId(target.artifacts[0]?.children[0]?.id ?? "report");
  }

  function handleSendMessage(content: string) {
    if (isNewAnalysisTask) {
      flow.start(content, analysisMode);
      setSelectedAnalysisTask("未命名分析任务");
      setSavedAssetIds([]);
      setAssetNotice("");
      setLastSaveRequest(undefined);
    } else {
      flow.send(content, analysisMode);
    }
  }

  function handleStartFromSuggestion(_id: string, title: string) {
    flow.start(`${title}。请基于当前数据展开分析。`, analysisMode);
    setSelectedAnalysisTask("未命名分析任务");
    setSavedAssetIds([]);
    setAssetNotice("");
    setLastSaveRequest(undefined);
  }

  function openArtifact(file: ArtifactFile) {
    setOpenFileIds((ids) => ids.includes(file.id) ? ids : [...ids, file.id]);
    setActiveFileId(file.id);
  }

  function closeArtifact(fileId: string) {
    setOpenFileIds((ids) => {
      const next = ids.filter((id) => id !== fileId);
      if (activeFileId === fileId) setActiveFileId(next.at(-1) ?? "");
      return next;
    });
  }

  function handleSaveAsset(asset: AnalysisAssetCard) {
    const saveResult = mockAnalysisAssetLibraryService.saveAsset(
      asset,
      selectedAnalysisTask ?? "当前分析任务",
      assetSourceContext,
    );
    setSavedAssetIds((ids) => ids.includes(asset.id) ? ids : [...ids, asset.id]);
    setLastSaveRequest(saveResult.request);
    setAssetNotice(`已生成「${asset.title}」保存请求 mock：${saveResult.request.assetId}，可从资产回到本任务继续。`);
    if (!shouldUseBackendAnalysisAssetLibrary()) return;
    void saveAnalysisAssetToBackend(saveResult.request)
      .then((result) => {
        setAssetNotice(`已将「${asset.title}」保存到后端分析资产库：${result.asset.assetId}`);
      })
      .catch((error) => {
        const message = error instanceof Error ? error.message : "后端分析资产保存失败";
        setAssetNotice(`「${asset.title}」已在当前页面标记为已保存，但后端资产库保存失败：${message}`);
      });
  }

  function handleContinueFromAsset(asset: AnalysisAssetCard) {
    setMobilePane("analysisTask");
    if (asset.intent === "edit-skill") {
      setAssetNotice(`正在编辑「${asset.title}」，先确认适用场景、口径和复用权限。`);
      flow.send(`继续编辑 Skill.md：请基于当前分析资产，整理适用场景、需要确认的业务口径、推荐步骤和复用权限。`, analysisMode);
      return;
    }
    setAssetNotice(`正在基于「${asset.title}」继续当前分析任务。`);
    flow.send(`基于分析资产「${asset.title}」继续分析，并在需要时修改相关 SQL、图表、报告或 Skill。`, analysisMode);
  }

  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    const workspace = event.currentTarget.parentElement;
    if (!workspace) return;
    const startX = event.clientX;
    const startPercent = splitPercent;
    const width = workspace.getBoundingClientRect().width;
    const onMove = (moveEvent: PointerEvent) => setSplitPercent(Math.min(62, Math.max(22, startPercent + ((moveEvent.clientX - startX) / width) * 100)));
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  const mode = activeTool === "analysis-tasks" ? "analysis-task" : "default";

  return (
    <KnowledgeExplorationProvider>
    <div className="app-shell">
      <header className="topbar">
        <img className="topbar-logo" src="/brand-logo.png" alt="Agentic GenBI" />
        <div className="topbar-slogan" aria-label="Make data sense">
          <span>MAKE</span><span className="connector">DATA</span><span className="emph">SENSE</span>
        </div>
        <UserChip />
      </header>

      <div className={`shell ${collapsed ? "collapsed" : ""}`}>
        <nav className="icon-toolbar" aria-label="主导航">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`icon-btn ${!collapsed && activeTool === item.id ? "active" : ""}`}
              type="button"
              title={item.label}
              aria-label={item.label}
              aria-current={activeTool === item.id ? "page" : undefined}
              onClick={() => {
                if (activeTool === item.id && !collapsed) {
                  setCollapsed(true);
                  return;
                }
                setActiveTool(item.id);
                setCollapsed(false);
              }}
            >
              <NavIcon name={item.icon} />
            </button>
          ))}
          {isAdmin && (
            <button
              className={`icon-btn admin-nav ${!collapsed && activeTool === adminNavItem.id ? "active" : ""}`}
              type="button"
              title={adminNavItem.label}
              aria-label={adminNavItem.label}
              aria-current={activeTool === adminNavItem.id ? "page" : undefined}
              onClick={() => {
                if (activeTool === adminNavItem.id && !collapsed) {
                  setCollapsed(true);
                  return;
                }
                setActiveTool(adminNavItem.id);
                setCollapsed(false);
              }}
            >
              <NavIcon name={adminNavItem.icon} />
            </button>
          )}
        </nav>

        <aside className={`panel ${activeTool === "analysis-tasks" ? "analysis-tasks" : ""} ${activeTool === "investigation" ? "exploration" : ""}`} aria-label="侧栏">
          {activeTool === "analysis-tasks" ? (
            <div className="analysis-task-panel">
              <header className="panel-header"><span className="panel-kicker">ANALYSIS TASKS</span><h2>分析任务</h2></header>
              <label className="analysis-task-search"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg><input type="search" placeholder="搜索分析任务" /></label>
              <button className="analysis-task-new" type="button" onClick={() => { setSelectedAnalysisTask(null); setCurrentAnalysisTaskId(null); setOpenFileIds([]); setSavedAssetIds([]); setAssetNotice(""); setLastSaveRequest(undefined); setActiveFileId("report"); }}><span>+ 新建分析任务</span></button>
              <div className="analysis-task-groups">
                {analysisTaskGroups.map((group) => (
                  <section className="analysis-task-group" key={group.label}>
                    <h3>{group.label}</h3>
                    <div className="analysis-task-list">
                      {group.items.map((item) => (
                        <button key={item.title} className={`analysis-task-item ${selectedAnalysisTask === item.title ? "active" : ""}`} type="button" onClick={() => selectExistingAnalysisTask(item.title)}>
                          <span className="analysis-task-item-main">
                            <strong>{item.title}</strong>
                          </span>
                          <span className="analysis-task-item-meta"><time>{item.time}</time><span className={`status-dot ${item.status}`} title={item.statusLabel} aria-label={item.statusLabel} /></span>
                          <span className="analysis-task-item-actions" aria-label={`${item.title} 操作`}>
                            <span role="button" tabIndex={0} title="置顶">↑</span><span role="button" tabIndex={0} title="重命名">✎</span><span role="button" tabIndex={0} title="删除">×</span>
                          </span>
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </div>
          ) : activeTool === "investigation" ? (
            <KnowledgeExplorationSidebar />
          ) : (
            <div className="workbench-panel"><div className="placeholder"><span>⌁</span><strong>待开发</strong></div></div>
          )}
        </aside>

        <button className="panel-toggle" type="button" aria-label="收起侧栏" onClick={() => setCollapsed(true)}>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m14 6-6 6 6 6" /></svg>
        </button>

        <main className="main" data-mode={mode} data-tool={activeTool}>
          {activeTool === "investigation" ? <KnowledgeExploration /> : <div key={currentAnalysisTaskId ?? "new"} className="workbench-frame" style={{ height: "100%" }}>
              <div className="mobile-pane-switch" role="tablist" aria-label="分析任务工作区">
                <button className={mobilePane === "analysisTask" ? "active" : ""} type="button" onClick={() => setMobilePane("analysisTask")}>分析任务</button>
                <button className={mobilePane === "assetLibrary" ? "active" : ""} type="button" onClick={() => setMobilePane("assetLibrary")}>分析资产库</button>
              </div>
              <section className="workspace" style={{ gridTemplateColumns: `${splitPercent}% 7px minmax(0, 1fr)`, height: "100%" }}>
                <AnalysisTaskThread
                  title={isNewAnalysisTask ? "新分析任务" : (selectedAnalysisTask ?? "分析任务")}
                  isNewTask={isNewAnalysisTask}
                  running={flow.running}
                  nodes={flow.nodes}
                  assetNotice={assetNotice}
                  analysisMode={analysisMode}
                  mobileHidden={mobilePane !== "analysisTask"}
                  taskKey={currentAnalysisTaskId}
                  onModeChange={setAnalysisMode}
                  onReply={(optionId) => flow.reply(optionId, analysisMode)}
                  onStartFromSuggestion={handleStartFromSuggestion}
                  onSendMessage={handleSendMessage}
                />

                <div className="workspace-resizer" role="separator" aria-label="调整分析任务和分析资产库宽度" aria-orientation="vertical" onPointerDown={startResize} onDoubleClick={() => setSplitPercent(40)}><span /></div>

                <AnalysisAssetLibrary
                  taskTitle={selectedAnalysisTask ?? "当前分析任务"}
                  sourceContext={assetSourceContext}
                  folders={activeArtifactFolderList}
                  files={artifactFiles}
                  activeFile={activeFile}
                  openFileIds={openFileIds}
                  expandedFolders={expandedFolders}
                  savedAssetIds={savedAssetIds}
                  explorerCollapsed={explorerCollapsed}
                  mobileHidden={mobilePane !== "assetLibrary"}
                  lastSaveRequest={lastSaveRequest}
                  onToggleExplorer={() => setExplorerCollapsed((value) => !value)}
                  onToggleFolder={(folderId) => setExpandedFolders((state) => ({ ...state, [folderId]: !state[folderId] }))}
                  onOpenFile={openArtifact}
                  onActivateFile={setActiveFileId}
                  onCloseFile={closeArtifact}
                  onSaveAsset={handleSaveAsset}
                  onContinueFromAsset={handleContinueFromAsset}
                />
              </section>
          </div>
          }
        </main>
      </div>
    </div>
    </KnowledgeExplorationProvider>
  );
}
