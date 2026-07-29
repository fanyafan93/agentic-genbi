"use client";

import { useState, useMemo, useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { EChartRenderer } from "@/shared/charts/EChartRenderer";
import { UserChip } from "@/modules/auth/components/UserChip";
import { KnowledgeExploration, KnowledgeExplorationProvider, KnowledgeExplorationSidebar } from "@/modules/investigation/components/DataInvestigation";
import { useFlow } from "../hooks/use-flow";
import { FlowNodeView } from "./FlowNodeView";
import { Suggestions } from "./Suggestions";
import { FlowComposer } from "./FlowComposer";
import { mockArtifact } from "./artifact-mock";
import { findSessionByTitle } from "../agentClients/scripts/sessions";
import type { AnalysisRow } from "../types/analysis";
import type { ArtifactFile, ArtifactFolder } from "../types/artifact";

const navItems = [
  { id: "workspace", label: "工作台", icon: "dashboard" },
  { id: "sessions", label: "会话", icon: "conversation" },
  { id: "investigation", label: "知识探索", icon: "investigation" },
  { id: "agent-center", label: "Agent 中心", icon: "agent" },
] as const;

const adminNavItem = { id: "system", label: "系统", icon: "system" } as const;
const sessionGroups = [
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
const metricCards = [
  { label: "销售额", value: "3,467 万", delta: "+18.6%" },
  { label: "主渠道占比", value: "42.0%", delta: "线上直营" },
  { label: "最快增长", value: "44.7%", delta: "社交电商" },
];

const pythonCode = `import pandas as pd

frame = pd.read_csv("data/result.csv")
channel_summary = frame.sort_values("sales_amount", ascending=False)
fastest_growth = frame.loc[frame["yoy_growth"].idxmax(), "channel"]
print(f"增长最快渠道: {fastest_growth}")`;
const markdownSummary = `# 渠道销售占比分析\n\n线上直营为当前最大渠道，社交电商同比增速最快。`;
const metadataJson = `{"source":"mart_sales","month":"2026-06","rows":5,"validated":true}`;

type NavIconName = (typeof navItems)[number]["icon"] | typeof adminNavItem["icon"];

function NavIcon({ name }: { name: NavIconName }) {
  const paths = {
    dashboard: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    conversation: <><path className="sq-back" d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z" /><path className="sq-front" d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2-2v-1" /></>,
    investigation: <><ellipse cx="10" cy="5.5" rx="5.5" ry="2.5" /><path d="M4.5 5.5v7c0 1.4 2.5 2.5 5.5 2.5.8 0 1.5-.1 2.2-.2" /><path d="M15.5 5.5v3" /><path d="M4.5 9c0 1.4 2.5 2.5 5.5 2.5.8 0 1.5-.1 2.2-.2" /><g className="mag"><circle cx="16.5" cy="15.5" r="3.5" /><path d="m19 18 2 2" /></g></>,
    agent: <><rect x="5" y="7" width="14" height="12" rx="3" /><path d="M12 3v4M9 12h.01M15 12h.01M9 16h6" /><path d="M3 11v4M21 11v4" /></>,
    system: <><path d="M12 3.5 19 6v5.4c0 4.2-2.8 7.6-7 9.1-4.2-1.5-7-4.9-7-9.1V6l7-2.5Z" /><path d="m9 12 2 2 4-4" /></>,
  };

  return <svg data-icon={name} aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function formatCell(value: AnalysisRow[string]) {
  if (typeof value !== "number") return value;
  if (Math.abs(value) < 1) return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString("zh-CN");
}

export function AnalysisWorkspace() {
  const [activeTool, setActiveTool] = useState("sessions");
  const [collapsed, setCollapsed] = useState(false);
  const [selectedSession, setSelectedSession] = useState<string | null>("渠道销售占比分析");
  const initialScript = findSessionByTitle("渠道销售占比分析");
  const initialMessages = initialScript?.messages ?? [];
  const [splitPercent, setSplitPercent] = useState(40);
  const [expandedFolders, setExpandedFolders] = useState<Record<string, boolean>>({ reports: true, queries: true, scripts: true, data: true });
  const [openFileIds, setOpenFileIds] = useState<string[]>([]);
  const [activeFileId, setActiveFileId] = useState<string>("report");
  const [mobilePane, setMobilePane] = useState<"conversation" | "artifacts">("conversation");
  const [explorerCollapsed, setExplorerCollapsed] = useState(false);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>("channel");
  const sessionScriptDef = selectedSession ? findSessionByTitle(selectedSession) : undefined;
  const initialFlowMessages = useMemo(() => {
    if (selectedSession === null) return [];
    if (selectedSession === "渠道销售占比分析") return initialMessages;
    return sessionScriptDef?.messages ?? [];
  }, [selectedSession, sessionScriptDef, initialMessages]);
  const flow = useFlow(currentSessionId, initialFlowMessages);
  const threadScrollRef = useRef<HTMLDivElement>(null);
  const lastNodeCountRef = useRef<number>(-1);
  const streamTailRef = useRef<number>(-1);
  const lastSessionRef = useRef<string | null>(selectedSession);
  const lastSessionIdRef = useRef<string | null>(currentSessionId);

  useEffect(() => {
    const el = threadScrollRef.current;
    if (!el) return;
    const lastAgent = [...flow.nodes].reverse().find((n) => n.role === "agent");
    const tail = lastAgent && lastAgent.role === "agent" ? lastAgent.content.length : -1;
    const nodesChanged = flow.nodes.length !== lastNodeCountRef.current;
    const streamChanged = tail !== streamTailRef.current;
    const sessionChanged = selectedSession !== lastSessionRef.current || currentSessionId !== lastSessionIdRef.current;
    if (nodesChanged || streamChanged || sessionChanged || lastNodeCountRef.current === -1) {
      el.scrollTop = el.scrollHeight;
      lastNodeCountRef.current = flow.nodes.length;
      streamTailRef.current = tail;
      lastSessionRef.current = selectedSession;
      lastSessionIdRef.current = currentSessionId;
    }
  });
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      const el = threadScrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(id);
  }, [flow.nodes.length, currentSessionId, selectedSession]);
  const isAdmin = true;
  const isNewSession = selectedSession === null;
  const sessionScript = sessionScriptDef;
  const activeArtifactFolderList = sessionScript ? sessionScript.artifacts : [];
  const artifactFiles = activeArtifactFolderList.flatMap((folder) => folder.children);
  const activeFile = artifactFiles.find((file) => file.id === activeFileId);

  function selectExistingSession(title: string) {
    setSelectedSession(title);
    const target = findSessionByTitle(title);
    if (!target) return;
    setCurrentSessionId(target.id);
    setOpenFileIds([]);
    setActiveFileId(target.artifacts[0]?.children[0]?.id ?? "report");
  }

  function handleSendMessage(content: string) {
    if (isNewSession) {
      flow.start(content);
      setSelectedSession("未命名会话");
    } else {
      flow.send(content);
    }
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

  const mode = activeTool === "sessions" ? "session" : "default";

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

        <aside className={`panel ${activeTool === "sessions" ? "sessions" : ""} ${activeTool === "investigation" ? "exploration" : ""}`} aria-label="侧栏">
          {activeTool === "sessions" ? (
            <div className="session-panel">
              <header className="panel-header"><span className="panel-kicker">CONVERSATIONS</span><h2>会话</h2></header>
              <label className="session-search"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg><input type="search" placeholder="搜索会话" /></label>
              <button className="session-new" type="button" onClick={() => { setSelectedSession(null); setCurrentSessionId(null); setOpenFileIds([]); setActiveFileId("report"); }}><span>+ 新建会话</span></button>
              <div className="session-groups">
                {sessionGroups.map((group) => (
                  <section className="session-group" key={group.label}>
                    <h3>{group.label}</h3>
                    <div className="session-list">
                      {group.items.map((item) => (
                        <button key={item.title} className={`session-item ${selectedSession === item.title ? "active" : ""}`} type="button" onClick={() => selectExistingSession(item.title)}>
                          <span className="session-item-main">
                            <strong>{item.title}</strong>
                          </span>
                          <span className="session-item-meta"><time>{item.time}</time><span className={`status-dot ${item.status}`} title={item.statusLabel} aria-label={item.statusLabel} /></span>
                          <span className="session-item-actions" aria-label={`${item.title} 操作`}>
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
          {activeTool === "investigation" ? <KnowledgeExploration /> : <div key={currentSessionId ?? "new"} className="workbench-frame" style={{ height: "100%" }}>
              <div className="mobile-pane-switch" role="tablist" aria-label="会话工作区">
                <button className={mobilePane === "conversation" ? "active" : ""} type="button" onClick={() => setMobilePane("conversation")}>会话</button>
                <button className={mobilePane === "artifacts" ? "active" : ""} type="button" onClick={() => setMobilePane("artifacts")}>分析资产</button>
              </div>
              <section className="workspace" style={{ gridTemplateColumns: `${splitPercent}% 7px minmax(0, 1fr)`, height: "100%" }}>
                <div className={`thread ${mobilePane !== "conversation" ? "mobile-hidden" : ""}`}>
                  <header className="thread-header">
                    <h1>{isNewSession ? "新会话" : (selectedSession ?? "会话")}</h1>
                    <em>{flow.running ? "分析中" : isNewSession ? "等待提问" : ""}</em>
                  </header>
                  <div className="thread-scroll" ref={threadScrollRef}>
                    {flow.nodes.length === 0 ? (
                      <Suggestions onSelect={(id, title) => flow.start(`${title}。请基于当前数据展开分析。`)} />
                    ) : (
                      <ol className="flow">
                        {flow.nodes.map((node) => (
                          <FlowNodeView key={node.id} node={node} onReply={flow.reply} />
                        ))}
                      </ol>
                    )}
                  </div>
                  <FlowComposer
                    disabled={flow.running}
                    placeholder={isNewSession ? "输入你的问题，按回车发送" : "有什么问题，或想继续探索什么？"}
                    onSubmit={handleSendMessage}
                  />
                </div>

                <div className="workspace-resizer" role="separator" aria-label="调整会话和分析资产宽度" aria-orientation="vertical" onPointerDown={startResize} onDoubleClick={() => setSplitPercent(40)}><span /></div>

                <div className={`artifact-workspace ${mobilePane !== "artifacts" ? "mobile-hidden" : ""} ${explorerCollapsed ? "explorer-collapsed" : ""}`}>
                  <aside className={`artifact-explorer ${explorerCollapsed ? "is-collapsed" : ""}`} aria-label="分析资产目录">
                    <header>
                      <div className="explorer-title"><span>ARTIFACTS</span><h2>分析资产</h2></div>
                      <button
                        type="button"
                        className="explorer-toggle"
                        title={explorerCollapsed ? "展开目录" : "收起目录"}
                        aria-label={explorerCollapsed ? "展开资产目录" : "收起资产目录"}
                        aria-expanded={!explorerCollapsed}
                        onClick={() => setExplorerCollapsed((value) => !value)}
                      >
                        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m9 6-6 6 6 6" /><path d="M15 6v12" /></svg>
                      </button>
                    </header>
                    <div className="explorer-stage" aria-hidden={explorerCollapsed}>
                      <div className="explorer-view explorer-view-expanded">
                        {activeArtifactFolderList.length === 0 ? (
                          <div className="explorer-empty">
                            <span aria-hidden="true">◇</span>
                            <strong>暂无分析资产</strong>
                            <small>开始对话后将自动产生报告 / SQL / 脚本 / 数据文件</small>
                          </div>
                        ) : (
                          <>
                            <div className="artifact-root"><strong>渠道销售占比分析</strong><small>{artifactFiles.length} 个文件</small></div>
                            <div className="artifact-tree">
                              {activeArtifactFolderList.map((folder) => (
                                <div className="artifact-folder" key={folder.id}>
                                  <button type="button" className="folder-row" onClick={() => setExpandedFolders((state) => ({ ...state, [folder.id]: !state[folder.id] }))}><span className="folder-toggle" aria-hidden="true">{expandedFolders[folder.id] ? "▾" : "▸"}</span><strong>{folder.name}</strong><small>{folder.children.length}</small></button>
                                  {expandedFolders[folder.id] && <div className="artifact-files">{folder.children.map((file) => <button type="button" key={file.id} className={activeFile?.id === file.id ? "active" : ""} onClick={() => openArtifact(file)}><span className={`file-kind ${file.kind}`}>{file.kind === "python" ? "PY" : file.kind.slice(0, 3).toUpperCase()}</span><span>{file.name}</span></button>)}</div>}
                                </div>
                              ))}
                            </div>
                          </>
                        )}
                      </div>
                      <div className="explorer-view explorer-view-collapsed" aria-hidden={!explorerCollapsed}>
                        <div className="artifact-collapsed-meta">
                          <span>AR</span>
                          <small>{artifactFiles.length}</small>
                        </div>
                        <div className="artifact-collapsed-tree">
                          {artifactFiles.map((file) => (
                            <button type="button" key={file.id} className={`file-chip ${activeFile?.id === file.id ? "active" : ""}`} title={file.name} aria-label={`打开 ${file.name}`} onClick={() => openArtifact(file)}>
                              <span className={`file-kind ${file.kind}`}>{file.kind === "python" ? "PY" : file.kind.slice(0, 3).toUpperCase()}</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  </aside>

                  <section className="artifact-viewer">
                    {openFileIds.length > 0 && (
                      <div className="artifact-tabs" role="tablist" aria-label="已打开的分析资产">
                        {openFileIds.map((fileId) => {
                        const file = artifactFiles.find((item) => item.id === fileId);
                        return file ? <div className={`artifact-tab ${activeFile?.id === file.id ? "active" : ""}`} key={file.id}><button type="button" onClick={() => setActiveFileId(file.id)}><span className={`file-kind ${file.kind}`}>{file.kind === "python" ? "PY" : file.kind.slice(0, 3).toUpperCase()}</span>{file.name}</button><button type="button" aria-label={`关闭 ${file.name}`} onClick={() => closeArtifact(file.id)}>×</button></div> : null;
                      })}
                      </div>
                    )}
                    <div className={`artifact-content ${openFileIds.length === 0 ? "is-empty" : ""}`}>
                      {openFileIds.length === 0 ? (
                        <div className="artifact-empty">
                          <span aria-hidden="true">◇</span>
                          <strong>未打开任何分析资产</strong>
                          <p>请在左侧文件目录中选择一个文件开始预览。</p>
                          <button type="button" onClick={() => artifactFiles[0] && openArtifact(artifactFiles[0])} disabled={artifactFiles.length === 0}>打开 Report.html</button>
                        </div>
                      ) : activeFile ? (
                        <>
                          {activeFile.kind === "html" && <div className="report-preview"><div className="metric-row">{mockArtifact.metrics.map((metric) => <div className="metric-card" key={metric.label}><span>{metric.label}</span><strong>{metric.value}</strong><em>{metric.delta}</em></div>)}</div><div className="chart-picker"><button className="active">Bar Chart</button><button>Line Chart</button><button>Pie Chart</button><button>Table</button></div><div className="output-body"><aside className="insight"><h3>关键洞察</h3><ul>{mockArtifact.insights.map((item) => <li key={item}>{item}</li>)}</ul></aside><div className="chart-area"><EChartRenderer spec={mockArtifact.chart} rows={mockArtifact.table} /></div></div></div>}
                          {activeFile.kind === "sql" && <pre className="artifact-code sql">{activeFile.id === "validation" ? `select count(*) as row_count from mart_sales_channel_month where month = '2026-06';` : mockArtifact.sql}</pre>}
                          {activeFile.kind === "python" && <pre className="artifact-code python">{pythonCode}</pre>}
                          {activeFile.kind === "markdown" && <article className="markdown-preview"><h1>渠道销售占比分析</h1><p>{markdownSummary.split("\n\n")[1]}</p></article>}
                          {activeFile.kind === "json" && <pre className="artifact-code json">{metadataJson}</pre>}
                          {activeFile.kind === "csv" && <table className="data-table artifact-table"><thead><tr>{Object.keys(mockArtifact.table[0]).map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{mockArtifact.table.map((row) => <tr key={String(row.channel)}>{Object.values(row).map((value, index) => <td key={index}>{formatCell(value)}</td>)}</tr>)}</tbody></table>}
                        </>
                      ) : null}
                    </div>
                  </section>
                </div>
              </section>
          </div>
          }
        </main>
      </div>
    </div>
    </KnowledgeExplorationProvider>
  );
}
