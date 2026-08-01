"use client";

import { useState, useMemo, useEffect, type PointerEvent as ReactPointerEvent } from "react";
import { useSession } from "next-auth/react";
import { UserChip } from "@/modules/auth/components/UserChip";
import {
  BusinessSemanticLibrary,
  type BusinessSemanticSection,
  type StructuredKnowledgeSource,
} from "@/modules/business-semantics/components/BusinessSemanticLibrary";
import { useFlow } from "../hooks/use-flow";
import { AnalysisTaskThread } from "./AnalysisTaskThread";
import { InteractiveReportPanel } from "./InteractiveReportPanel";
import { MyAnalysisPage } from "./MyAnalysisPage";
import { findAnalysisTaskByTitle } from "../agentClients/scripts/analysis-tasks";
import type { AnalysisMode } from "../agentClients";
import { shouldUseBackendAnalysisClient } from "../agentClients/backendClient";
import { loadSavedInteractiveReports, saveInteractiveReport, type SavedInteractiveReport } from "../mocks/interactive-report-storage";
import {
  getInteractiveReportFromBackend,
  listInteractiveReportsFromBackend,
  listInteractiveReportVersionsFromBackend,
  saveInteractiveReportToBackend,
  shouldUseBackendInteractiveReports,
} from "../api/interactive-report-service";

const navItems = [
  { id: "workspace", label: "工作台", icon: "dashboard" },
  { id: "analysis-workspace", label: "分析工作台", icon: "analysisTask" },
  { id: "analysis-assets", label: "我的分析", icon: "assetLibrary" },
  { id: "business-semantics", label: "业务语义库", icon: "businessSemantics" },
] as const;

const adminNavItem = { id: "system", label: "系统", icon: "system" } as const;
type ActiveTool = (typeof navItems)[number]["id"] | typeof adminNavItem["id"];
const structuredKnowledgeNav: Array<{
  id: StructuredKnowledgeSource;
  label: string;
  description: string;
}> = [
  { id: "finereport", label: "FineReport", description: "报表解析" },
  { id: "hop", label: "Apache Hop", description: "ETL 血缘解析" },
  { id: "database", label: "数据库", description: "MySQL / Doris 元数据" },
  { id: "kingdee", label: "金蝶", description: "业务数据字典" },
];
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
    assetLibrary: <><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h5l2 2h6A1.5 1.5 0 0 1 20 7.5v11A1.5 1.5 0 0 1 18.5 20h-13A1.5 1.5 0 0 1 4 18.5v-13Z" /><path d="M8 15h8M8 11h5" /></>,
    businessSemantics: <><ellipse cx="12" cy="5.5" rx="6.5" ry="2.5" /><path d="M5.5 5.5v6c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5v-6" /><path d="M5.5 9c0 1.4 2.9 2.5 6.5 2.5s6.5-1.1 6.5-2.5" /><path d="M8 18h8M12 14v4" /></>,
    system: <><path d="M12 3.5 19 6v5.4c0 4.2-2.8 7.6-7 9.1-4.2-1.5-7-4.9-7-9.1V6l7-2.5Z" /><path d="m9 12 2 2 4-4" /></>,
  };

  return <svg data-icon={name} aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

export function AnalysisWorkspace() {
  const { data: session } = useSession();
  const [activeTool, setActiveTool] = useState<ActiveTool>("analysis-workspace");
  const [collapsed, setCollapsed] = useState(false);
  const [analysisMode, setAnalysisMode] = useState<AnalysisMode>("quick");
  const [selectedAnalysisTask, setSelectedAnalysisTask] = useState<string | null>("渠道销售占比分析");
  const initialScript = findAnalysisTaskByTitle("渠道销售占比分析");
  const initialMessages = initialScript?.messages ?? [];
  const [splitPercent, setSplitPercent] = useState(40);
  const [mobilePane, setMobilePane] = useState<"analysisTask" | "assetLibrary">("analysisTask");
  const [currentAnalysisTaskId, setCurrentAnalysisTaskId] = useState<string | null>("channel");
  const [businessSemanticSection, setBusinessSemanticSection] = useState<BusinessSemanticSection>("structured");
  const [structuredKnowledgeSource, setStructuredKnowledgeSource] = useState<StructuredKnowledgeSource>("finereport");
  const [savedReports, setSavedReports] = useState<SavedInteractiveReport[]>(loadSavedInteractiveReports);
  const [openedReportId, setOpenedReportId] = useState<string | null>(null);
  const [dataEgressAuthorized, setDataEgressAuthorized] = useState(false);
  const reportOwnerId = session?.user?.id ?? "local-user";
  const analysisTaskScriptDef = selectedAnalysisTask ? findAnalysisTaskByTitle(selectedAnalysisTask) : undefined;
  const initialFlowMessages = useMemo(() => {
    if (selectedAnalysisTask === null) return [];
    if (selectedAnalysisTask === "渠道销售占比分析") return initialMessages;
    return analysisTaskScriptDef?.messages ?? [];
  }, [selectedAnalysisTask, analysisTaskScriptDef, initialMessages]);
  const flow = useFlow(currentAnalysisTaskId, initialFlowMessages);
  useEffect(() => {
    let cancelled = false;
    if (!shouldUseBackendInteractiveReports()) {
      setSavedReports(loadSavedInteractiveReports());
      return () => { cancelled = true; };
    }
    void listInteractiveReportsFromBackend(reportOwnerId)
      .then((reports) => { if (!cancelled) setSavedReports(reports); })
      .catch(() => { if (!cancelled) setSavedReports(loadSavedInteractiveReports()); });
    return () => { cancelled = true; };
  }, [reportOwnerId]);
  useEffect(() => {
    if (activeTool === "business-semantics") setCollapsed(false);
  }, [activeTool]);
  const isAdmin = true;
  const isNewAnalysisTask = selectedAnalysisTask === null;
  const openedReport = savedReports.find((saved) => saved.report.id === openedReportId);

  function selectExistingAnalysisTask(title: string) {
    setSelectedAnalysisTask(title);
    const target = findAnalysisTaskByTitle(title);
    if (!target) return;
    setCurrentAnalysisTaskId(target.id);
    setOpenedReportId(null);
  }

  function handleSendMessage(content: string) {
    const authorized = dataEgressAuthorized;
    const interactiveReport = flow.draftReport ?? openedReport?.report ?? undefined;
    if (isNewAnalysisTask) {
      flow.start(content, analysisMode, authorized);
      setSelectedAnalysisTask("未命名分析任务");
    } else {
      flow.send(content, analysisMode, authorized, interactiveReport);
    }
    setDataEgressAuthorized(false);
  }

  function handleStartFromSuggestion(_id: string, title: string) {
    flow.start(`${title}。请基于当前数据展开分析。`, analysisMode, dataEgressAuthorized);
    setSelectedAnalysisTask("未命名分析任务");
    setDataEgressAuthorized(false);
  }

  async function handleSaveReport(saved: SavedInteractiveReport): Promise<SavedInteractiveReport> {
    const previous = savedReports.find((item) => item.report.id === saved.report.id);
    if (shouldUseBackendInteractiveReports()) {
      const persisted = await saveInteractiveReportToBackend(saved.report, previous?.version, reportOwnerId);
      setSavedReports((reports) => [persisted, ...reports.filter((item) => item.report.id !== persisted.report.id)]);
      return persisted;
    }
    const localSaved = { ...saved, version: previous ? previous.version + 1 : 1 };
    setSavedReports(saveInteractiveReport(localSaved));
    return localSaved;
  }

  async function handleLoadReportVersion(reportId: string, version: number): Promise<SavedInteractiveReport> {
    if (!shouldUseBackendInteractiveReports()) throw new Error("历史版本仅在后端存储模式下可用。");
    return await getInteractiveReportFromBackend(reportId, version);
  }

  function handleOpenReport(saved: SavedInteractiveReport) {
    setOpenedReportId(saved.report.id);
    setSelectedAnalysisTask(saved.report.title);
    setCurrentAnalysisTaskId(saved.report.source.threadId);
    setActiveTool("analysis-workspace");
    setMobilePane("assetLibrary");
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

  const mode = activeTool === "analysis-workspace" ? "analysis-task" : "default";

  return (
    <div className="app-shell">
      <header className="topbar">
        <img className="topbar-logo" src="/brand-logo.png" alt="Agentic GenBI" />
        <div className="topbar-slogan" aria-label="Make data sense">
          <span>MAKE</span><span className="connector">DATA</span><span className="emph">SENSE</span>
        </div>
        <UserChip />
      </header>

      <div className={`shell ${collapsed ? "collapsed" : ""}`} data-tool={activeTool}>
        <nav className="icon-toolbar" aria-label="主导航">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`icon-btn ${activeTool === item.id ? "active" : ""}`}
              type="button"
              title={item.label}
              aria-label={item.label}
              aria-current={activeTool === item.id ? "page" : undefined}
              onClick={() => {
                if (item.id === "business-semantics") {
                  setActiveTool(item.id);
                  setCollapsed(false);
                  return;
                }
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
              className={`icon-btn admin-nav ${activeTool === adminNavItem.id ? "active" : ""}`}
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

        <aside className={`panel ${activeTool === "analysis-workspace" ? "analysis-tasks" : ""}`} aria-label="侧栏">
          {activeTool === "analysis-workspace" ? (
            <div className="analysis-task-panel">
              <header className="panel-header"><span className="panel-kicker">ANALYSIS WORKSPACE</span><h2>分析工作台</h2></header>
              <label className="analysis-task-search"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg><input type="search" placeholder="搜索分析任务" /></label>
              <button className="analysis-task-new" type="button" onClick={() => { setSelectedAnalysisTask(null); setCurrentAnalysisTaskId(null); setOpenedReportId(null); }}><span>+ 新建分析</span></button>
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
          ) : activeTool === "analysis-assets" ? (
            <div className="workbench-panel">
              <header className="panel-header"><span className="panel-kicker">MY ANALYSIS</span><h2>我的分析</h2></header>
              <div className="panel-brief-list">
                <span>我的结果</span>
                <span>分析模板</span>
                <span>已分享结果</span>
              </div>
            </div>
          ) : activeTool === "business-semantics" ? (
            <div className="workbench-panel">
              <header className="panel-header"><span className="panel-kicker">BUSINESS SEMANTICS</span><h2>业务语义库</h2></header>
              <nav className="panel-brief-list panel-nav-list" aria-label="业务语义库导航">
                <button
                  type="button"
                  className={businessSemanticSection === "structured" ? "active" : ""}
                  aria-current={businessSemanticSection === "structured" ? "page" : undefined}
                  onClick={() => setBusinessSemanticSection("structured")}
                >
                  <strong>结构化知识</strong>
                  <small>系统里实际存在什么</small>
                </button>
                {businessSemanticSection === "structured" && (
                  <div className="panel-subnav-list" aria-label="结构化知识来源">
                    {structuredKnowledgeNav.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={structuredKnowledgeSource === item.id ? "active" : ""}
                        aria-current={structuredKnowledgeSource === item.id ? "page" : undefined}
                        onClick={() => setStructuredKnowledgeSource(item.id)}
                      >
                        <strong>{item.label}</strong>
                        <small>{item.description}</small>
                      </button>
                    ))}
                  </div>
                )}
                <button
                  type="button"
                  className={businessSemanticSection === "semantic" ? "active" : ""}
                  aria-current={businessSemanticSection === "semantic" ? "page" : undefined}
                  onClick={() => setBusinessSemanticSection("semantic")}
                >
                  <strong>语义</strong>
                  <small>业务解释和使用规则</small>
                </button>
              </nav>
            </div>
          ) : (
            <div className="workbench-panel">
              <header className="panel-header"><span className="panel-kicker">GOVERNANCE</span><h2>系统</h2></header>
              <div className="panel-brief-list">
                <span>数据源连接</span>
                <span>权限与 RLS</span>
                <span>模型与工具配置</span>
              </div>
            </div>
          )}
        </aside>

        <button className="panel-toggle" type="button" aria-label="收起侧栏" onClick={() => setCollapsed(true)}>
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m14 6-6 6 6 6" /></svg>
        </button>

        <main className="main" data-mode={mode} data-tool={activeTool}>
          {activeTool === "analysis-assets" ? (
            <MyAnalysisPage reports={savedReports} onOpenReport={handleOpenReport} />
          ) : activeTool === "business-semantics" ? (
             <BusinessSemanticLibrary section={businessSemanticSection} structuredKnowledgeSource={structuredKnowledgeSource} />
          ) : activeTool === "workspace" ? (
            <section className="overview-workbench" aria-label="工作台">
              <header>
                <span>WORKBENCH</span>
                <h1>工作台</h1>
                <p>这里聚合最近分析、待确认口径、常用资产和运行状态；真正开始分析时进入分析工作台。</p>
              </header>
              <div className="overview-card-grid">
                <article><span>待确认</span><strong>2 个业务口径</strong><small>复购率退款排除、渠道归因优先级</small></article>
                <article><span>最近资产</span><strong>5 个分析资产</strong><small>报告、SQL、业务规则和可复用分析方法</small></article>
                <article><span>语义层</span><strong>6 类语义模型</strong><small>FineReport、MySQL/Doris、ETL、金蝶、SQL 示例、指标维度</small></article>
              </div>
            </section>
          ) : activeTool === "system" ? (
            <section className="overview-workbench" aria-label="系统">
              <header>
                <span>SYSTEM</span>
                <h1>系统</h1>
                <p>治理、安全和配置能力会放在这里，包括 RBAC/RLS、敏感字段、只读数据源、模型工具和审计。</p>
              </header>
            </section>
          ) : <div key={currentAnalysisTaskId ?? "new"} className="workbench-frame" style={{ height: "100%" }}>
              <div className="mobile-pane-switch" role="tablist" aria-label="分析任务工作区">
                <button className={mobilePane === "analysisTask" ? "active" : ""} type="button" onClick={() => setMobilePane("analysisTask")}>分析工作台</button>
                <button className={mobilePane === "assetLibrary" ? "active" : ""} type="button" onClick={() => setMobilePane("assetLibrary")}>分析结果</button>
              </div>
              <section className="workspace" style={{ gridTemplateColumns: `${splitPercent}% 7px minmax(0, 1fr)`, height: "100%" }}>
                <AnalysisTaskThread
                  title={isNewAnalysisTask ? "新分析" : (selectedAnalysisTask ?? "分析工作台")}
                  isNewTask={isNewAnalysisTask}
                  running={flow.running}
                  nodes={flow.nodes}
                  assetNotice=""
                  analysisMode={analysisMode}
                  mobileHidden={mobilePane !== "analysisTask"}
                  taskKey={currentAnalysisTaskId}
                  dataEgressAuthorized={dataEgressAuthorized}
                  canAuthorizeDataEgress={shouldUseBackendAnalysisClient()}
                  onModeChange={setAnalysisMode}
                  onDataEgressAuthorizedChange={setDataEgressAuthorized}
                  onReply={(optionId) => { flow.reply(optionId, analysisMode, dataEgressAuthorized, flow.draftReport ?? openedReport?.report ?? undefined); setDataEgressAuthorized(false); }}
                  onStartFromSuggestion={handleStartFromSuggestion}
                  onSendMessage={handleSendMessage}
                />

                <div className="workspace-resizer" role="separator" aria-label="调整分析工作台和当前任务资产宽度" aria-orientation="vertical" onPointerDown={startResize} onDoubleClick={() => setSplitPercent(40)}><span /></div>

                <div className={`analysis-result-pane ${mobilePane !== "assetLibrary" ? "mobile-hidden" : ""}`}>
                  <InteractiveReportPanel taskTitle={selectedAnalysisTask ?? "当前分析任务"} running={flow.running} initialReport={flow.draftReport ?? openedReport?.report ?? undefined} initialVersion={openedReport?.version} onSaveReport={handleSaveReport} onListVersions={shouldUseBackendInteractiveReports() ? listInteractiveReportVersionsFromBackend : undefined} onLoadVersion={shouldUseBackendInteractiveReports() ? handleLoadReportVersion : undefined} />
                </div>
              </section>
          </div>
          }
        </main>
      </div>
    </div>
  );
}
