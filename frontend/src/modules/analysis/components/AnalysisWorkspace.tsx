"use client";

import { useState, useMemo, useEffect, useRef, type PointerEvent as ReactPointerEvent } from "react";
import { useSession } from "next-auth/react";
import { UserChip } from "@/modules/auth/components/UserChip";
import {
  BusinessSemanticLibrary,
  type BusinessSemanticSection,
  type StructuredKnowledgeSource,
} from "@/modules/business-semantics/components/BusinessSemanticLibrary";
import { useTaskCreation } from "../hooks/use-task-creation";
import { useTaskDetail } from "../hooks/use-task-detail";
import { useTaskList } from "../hooks/use-task-list";
import { useTaskReport } from "../hooks/use-task-report";
import { useTurnExecution } from "../hooks/use-turn-execution";
import { AnalysisTaskThread } from "./AnalysisTaskThread";
import { InteractiveReportPanel } from "./InteractiveReportPanel";
import { MyAnalysisPage } from "./MyAnalysisPage";
import { SystemMcpPage } from "./SystemMcpPage";
import {
  createAnalysisThreadFromReportBackend,
  listInteractiveReportsByThreadFromBackend,
  listReportCenterFromBackend,
  saveInteractiveReportToBackend,
  shouldUseBackendInteractiveReports,
  type SavedInteractiveReport,
  type SharedInteractiveReport,
} from "../api/interactive-report-service";
import {
  deleteBackendAnalysisThread,
  getBackendAnalysisThread,
  type BackendAnalysisThreadSummary,
} from "../agentClients/backendClient";

const navItems = [
  { id: "workspace", label: "工作台", icon: "dashboard" },
  { id: "analysis-workspace", label: "分析工作台", icon: "analysisTask" },
  { id: "analysis-assets", label: "报表中心", icon: "assetLibrary" },
  { id: "business-semantics", label: "业务语义库", icon: "businessSemantics" },
] as const;

const adminNavItem = { id: "system", label: "系统", icon: "system" } as const;
type ActiveTool = (typeof navItems)[number]["id"] | typeof adminNavItem["id"];
const structuredKnowledgeNav: Array<{
  id: StructuredKnowledgeSource;
  label: string;
  description: string;
}> = [
  { id: "finereport", label: "FineReport", description: "报表画像" },
  { id: "hop", label: "Apache Hop", description: "ETL 血缘解析" },
  { id: "database", label: "数据库", description: "MySQL / Doris 元数据" },
  { id: "kingdee", label: "金蝶", description: "业务数据字典" },
];
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

type AnalysisThreadGroup = {
  label: string;
  items: BackendAnalysisThreadSummary[];
};

function groupAnalysisThreads(threads: BackendAnalysisThreadSummary[]): AnalysisThreadGroup[] {
  const today = new Date().toDateString();
  const todayItems = threads.filter((thread) => threadDate(thread).toDateString() === today);
  const earlierItems = threads.filter((thread) => threadDate(thread).toDateString() !== today);
  return [
    ...(todayItems.length > 0 ? [{ label: "今天", items: todayItems }] : []),
    ...(earlierItems.length > 0 ? [{ label: "更早", items: earlierItems }] : []),
  ];
}

function analysisThreadTitle(thread: BackendAnalysisThreadSummary): string {
  return usefulThreadTitle(thread.title) || usefulThreadTitle(thread.latestQuestion) || "历史任务";
}

function usefulThreadTitle(value: string | null | undefined): string {
  const text = String(value ?? "").trim();
  return text && text !== "未命名分析任务" ? text : "";
}

function taskTitleFromQuestion(question: string): string {
  const text = question.trim().replace(/\s+/g, " ");
  return text.slice(0, 32) || "未命名分析任务";
}

function analysisThreadTime(thread: BackendAnalysisThreadSummary): string {
  const date = threadDate(thread);
  if (Number.isNaN(date.getTime())) return "";
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "昨天";
  return date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

function analysisThreadStatus(thread: BackendAnalysisThreadSummary): "running" | "saved" | "readonly" {
  return thread.status === "running" ? "running" : thread.status === "completed" ? "saved" : "readonly";
}

function analysisThreadStatusLabel(thread: BackendAnalysisThreadSummary): string {
  if (thread.status === "waiting_for_question") return "待提问";
  return thread.status === "running" ? "运行中" : thread.status === "completed" ? "已完成" : "已保存";
}

function threadDate(thread: BackendAnalysisThreadSummary): Date {
  return new Date(thread.updatedAt || thread.createdAt || 0);
}

function savedReportFromThreadMetadata(metadata: Record<string, unknown> | null | undefined): SavedInteractiveReport | null {
  const report = metadata?.initial_report_artifact;
  if (!report || typeof report !== "object") return null;
  const version = Number(metadata?.initial_report_version ?? 1);
  return {
    report: report as SavedInteractiveReport["report"],
    version: Number.isFinite(version) && version > 0 ? version : 1,
    savedAt: String(metadata?.initial_report_saved_at ?? metadata?.created_at ?? new Date().toISOString()),
  };
}

export function AnalysisWorkspace() {
  const { data: session } = useSession();
  const [activeTool, setActiveTool] = useState<ActiveTool>("analysis-workspace");
  const [collapsed, setCollapsed] = useState(false);
  const [selectedAnalysisTask, setSelectedAnalysisTask] = useState<string | null>(null);
  const [splitPercent, setSplitPercent] = useState(40);
  const [mobilePane, setMobilePane] = useState<"analysisTask" | "assetLibrary">("analysisTask");
  const [currentAnalysisTaskId, setCurrentAnalysisTaskId] = useState<string | null>(null);
  const [businessSemanticSection, setBusinessSemanticSection] = useState<BusinessSemanticSection>("structured");
  const [structuredKnowledgeSource, setStructuredKnowledgeSource] = useState<StructuredKnowledgeSource>("finereport");
  const [savedReports, setSavedReports] = useState<SavedInteractiveReport[]>([]);
  const [sharedReports, setSharedReports] = useState<SharedInteractiveReport[]>([]);
  const [selectingAnalysisThreads, setSelectingAnalysisThreads] = useState(false);
  const [selectedThreadIds, setSelectedThreadIds] = useState<string[]>([]);
  const [openedReportId, setOpenedReportId] = useState<string | null>(null);
  const [openedReportThreadId, setOpenedReportThreadId] = useState<string | null>(null);
  const [openedReportLoadingThreadId, setOpenedReportLoadingThreadId] = useState<string | null>(null);
  const [analysisTaskNotice, setAnalysisTaskNotice] = useState("");
  const reportLoadRequestRef = useRef(0);
  // The backend derives identity from the active session cookie; this
  // component no longer carries an "owner id" of its own. Re-renders when
  // the session changes so a logout/login swap refreshes the user's data.
  const sessionRefreshKey = session?.user?.id ?? "";

  // Each hook owns exactly one concern. The workspace composes them
  // instead of holding their state inline; the contract is documented
  // in each hook.
  const taskList = useTaskList();
  const taskDetail = useTaskDetail(currentAnalysisTaskId);
  const taskReport = useTaskReport(currentAnalysisTaskId);
  const turn = useTurnExecution();
  const taskCreation = useTaskCreation();

  // Hydrate the live turn renderer from the historical detail fetch.
  // We only do this when there's no in-flight stream so we never clobber
  // tokens that are mid-render.
  useEffect(() => {
    if (!currentAnalysisTaskId) return;
    if (turn.running) return;
    if (taskDetail.nodes.length === 0) return;
    turn.replaceNodes(taskDetail.nodes);
  }, [currentAnalysisTaskId, taskDetail.nodes, taskDetail.requestId, turn.running, turn]);

  const analysisThreads = taskList.threads;
  const analysisThreadsLoading = taskList.loading;
  const analysisTaskGroups = useMemo(() => groupAnalysisThreads(analysisThreads), [analysisThreads]);
  const selectedThreadCount = selectedThreadIds.length;
  const currentAnalysisThread = currentAnalysisTaskId
    ? analysisThreads.find((thread) => thread.id === currentAnalysisTaskId)
    : undefined;
  const isNewAnalysisTask = selectedAnalysisTask === null && !taskCreation.creating;

  useEffect(() => {
    let cancelled = false;
    if (!shouldUseBackendInteractiveReports()) {
      setSavedReports([]);
      return () => { cancelled = true; };
    }
    void listReportCenterFromBackend()
      .then((center) => {
        if (cancelled) return;
        setSavedReports(center.mine);
        setSharedReports(center.sharedWithMe);
      })
      .catch(() => {
        if (cancelled) return;
        setSavedReports([]);
        setSharedReports([]);
      });
    return () => { cancelled = true; };
  }, [sessionRefreshKey]);
  useEffect(() => {
    if (activeTool === "business-semantics") setCollapsed(false);
  }, [activeTool]);
  // Admin powers (see ``share with team``, etc.) are evaluated server-side.
  // The UI mirrors the role from the active session; ``true`` is no longer
  // burned into the bundle.
  const sessionRole = (session?.user as { role?: string } | undefined)?.role ?? "user";
  const isAdmin = sessionRole === "admin" || sessionRole === "platform_admin";
  const openedReport = savedReports.find((saved) => saved.report.id === openedReportId);
  const openedReportBelongsToCurrentTask = openedReport?.report.source.threadId === currentAnalysisTaskId
    || (currentAnalysisTaskId ? openedReportThreadId === currentAnalysisTaskId : false);
  const flowReportBelongsToCurrentTask = Boolean(
    turn.reportArtifact
    && turn.reportArtifact.source.threadId === currentAnalysisTaskId,
  );
  const currentPanelReport = flowReportBelongsToCurrentTask ? turn.reportArtifact : openedReportBelongsToCurrentTask && openedReport ? openedReport.report : undefined;
  const currentPanelVersion = openedReportBelongsToCurrentTask && openedReport ? openedReport.version : undefined;
  const currentPanelReportLoading = openedReportLoadingThreadId === currentAnalysisTaskId || taskReport.loading;
  const isWaitingForFirstQuestion = Boolean(
    !turn.running
    && taskDetail.nodes.length === 0
    && !taskCreation.creating
    && (
      isNewAnalysisTask
      || (
        currentAnalysisThread?.status === "waiting_for_question"
        && !usefulThreadTitle(currentAnalysisThread.latestQuestion)
      )
    ),
  );
  const displayedAnalysisTitle = taskCreation.creating
    ? "正在创建…"
    : isWaitingForFirstQuestion
    ? "新分析"
    : isNewAnalysisTask
    ? "新分析"
    : (selectedAnalysisTask ?? "分析工作台");

  function markCurrentThreadAsStarted(content: string) {
    if (!currentAnalysisTaskId) return;
    const title = taskTitleFromQuestion(content);
    const now = new Date().toISOString();
    setSelectedAnalysisTask(title);
    const updatedThread: BackendAnalysisThreadSummary = {
      id: currentAnalysisTaskId,
      title,
      latestQuestion: content,
      updatedAt: now,
      status: "running",
    };
    taskList.upsert(updatedThread);
  }

  async function selectExistingAnalysisTask(thread: BackendAnalysisThreadSummary) {
    if (selectingAnalysisThreads) {
      toggleSelectedThread(thread.id);
      return;
    }
    if (turn.running && thread.id !== currentAnalysisTaskId) {
      setAnalysisTaskNotice("当前任务正在分析，停止回答后再切换任务。");
      return;
    }
    setAnalysisTaskNotice("");
    setSelectedAnalysisTask(analysisThreadTitle(thread));
    setCurrentAnalysisTaskId(thread.id);
    setOpenedReportId(null);
    setOpenedReportThreadId(null);
    const reportLoadRequestId = ++reportLoadRequestRef.current;
    let restoredInitialReport = false;
    if (shouldUseBackendInteractiveReports()) setOpenedReportLoadingThreadId(thread.id);
    try {
      const detail = await getBackendAnalysisThread(thread.id);
      if (reportLoadRequestId !== reportLoadRequestRef.current) return;
      const initialReport = savedReportFromThreadMetadata(detail.thread.metadata);
      if (initialReport) {
        restoredInitialReport = true;
        setOpenedReportId(initialReport.report.id);
        setOpenedReportThreadId(thread.id);
        setSavedReports((items) => [initialReport, ...items.filter((item) => item.report.id !== initialReport.report.id)]);
      }
    } catch {
      if (reportLoadRequestId !== reportLoadRequestRef.current) return;
    }
    if (shouldUseBackendInteractiveReports()) {
      try {
        const reports = await listInteractiveReportsByThreadFromBackend(thread.id);
        const latest = reports[0];
        if (reportLoadRequestId !== reportLoadRequestRef.current) return;
        if (latest || !restoredInitialReport) setOpenedReportId(latest?.report.id ?? null);
        if (latest) {
          setOpenedReportThreadId(null);
          setSavedReports((items) => [latest, ...items.filter((item) => item.report.id !== latest.report.id)]);
        }
      } catch {
        if (reportLoadRequestId !== reportLoadRequestRef.current) return;
        setOpenedReportId(null);
      } finally {
        if (reportLoadRequestId === reportLoadRequestRef.current) setOpenedReportLoadingThreadId(null);
      }
    }
  }

  function toggleSelectedThread(threadId: string) {
    setSelectedThreadIds((ids) => (
      ids.includes(threadId)
        ? ids.filter((id) => id !== threadId)
        : [...ids, threadId]
    ));
  }

  function startThreadSelection() {
    setSelectingAnalysisThreads(true);
    setSelectedThreadIds([]);
  }

  function cancelThreadSelection() {
    setSelectingAnalysisThreads(false);
    setSelectedThreadIds([]);
  }

  async function deleteSelectedThreads() {
    if (selectedThreadIds.length === 0) return;
    const confirmed = window.confirm(`确认删除选中的 ${selectedThreadIds.length} 个任务？删除后不可恢复。`);
    if (!confirmed) return;
    const idsToDelete = [...selectedThreadIds];
    await Promise.all(idsToDelete.map((threadId) => deleteBackendAnalysisThread(threadId)));
    await taskList.refresh();
    if (currentAnalysisTaskId && idsToDelete.includes(currentAnalysisTaskId)) {
      setSelectedAnalysisTask(null);
      setCurrentAnalysisTaskId(null);
      setOpenedReportId(null);
      setOpenedReportThreadId(null);
    }
    setSelectingAnalysisThreads(false);
    setSelectedThreadIds([]);
  }

  /**
   * Create a new analysis task. The backend returns the canonical
   * ``thread.id``; the UI only flips to that task once the promise
   * resolves. While we wait, ``useTaskCreation.creating`` is ``true``
   * and the renderer shows a "正在创建" placeholder instead of any
   * client-side taskId.
   */
  async function handleCreateBlankAnalysis() {
    if (turn.running) {
      setAnalysisTaskNotice("当前任务正在分析，停止回答后再新建分析。");
      return;
    }
    setAnalysisTaskNotice("");
    const task = await taskCreation.createTask("新分析");
    if (!task) {
      setAnalysisTaskNotice(taskCreation.error ?? "创建分析任务失败，请重试。");
      return;
    }
    taskList.upsert(task);
    setSelectedAnalysisTask(analysisThreadTitle(task));
    setCurrentAnalysisTaskId(task.id);
    setOpenedReportId(null);
    setOpenedReportThreadId(null);
    setActiveTool("analysis-workspace");
    setMobilePane("analysisTask");
  }

  async function handleSendMessage(content: string) {
    const trimmed = content.trim();
    if (!trimmed) {
      setAnalysisTaskNotice("请输入业务问题后再开始分析。");
      return;
    }
    if (isNewAnalysisTask) {
      // First turn on a brand new analysis task: create the task on the
      // server, then dispatch the first turn. The renderer shows
      // "正在创建" while the POST is in flight.
      const task = await taskCreation.createTask(taskTitleFromQuestion(trimmed));
      if (!task) {
        setAnalysisTaskNotice(taskCreation.error ?? "创建分析任务失败，请重试。");
        return;
      }
      taskList.upsert(task);
      const newTaskId = task.id;
      setSelectedAnalysisTask(analysisThreadTitle(task));
      setCurrentAnalysisTaskId(newTaskId);
      setOpenedReportId(null);
      setOpenedReportThreadId(null);
      setMobilePane("analysisTask");
      await turn.start(trimmed, newTaskId, newTaskId);
    } else if (currentAnalysisTaskId) {
      if (isWaitingForFirstQuestion) {
        markCurrentThreadAsStarted(trimmed);
        await turn.start(trimmed, currentAnalysisTaskId, currentAnalysisTaskId);
      } else {
        await turn.send(trimmed, currentAnalysisTaskId, currentAnalysisTaskId);
      }
    }
  }

  async function handleStartFromSuggestion(_id: string, title: string) {
    const question = `${title}。请基于当前数据展开分析。`;
    if (!isNewAnalysisTask && isWaitingForFirstQuestion && currentAnalysisTaskId) {
      markCurrentThreadAsStarted(question);
      setOpenedReportId(null);
      setOpenedReportThreadId(null);
      setMobilePane("analysisTask");
      await turn.start(question, currentAnalysisTaskId, currentAnalysisTaskId);
      return;
    }
    const task = await taskCreation.createTask(taskTitleFromQuestion(title));
    if (!task) {
      setAnalysisTaskNotice(taskCreation.error ?? "创建分析任务失败，请重试。");
      return;
    }
    taskList.upsert(task);
    const newTaskId = task.id;
    setSelectedAnalysisTask(analysisThreadTitle(task));
    setCurrentAnalysisTaskId(newTaskId);
    setOpenedReportId(null);
    setOpenedReportThreadId(null);
    setMobilePane("analysisTask");
    await turn.start(question, newTaskId, newTaskId);
  }

  async function handleSaveReport(saved: SavedInteractiveReport): Promise<SavedInteractiveReport> {
    const previous = savedReports.find((item) => item.report.id === saved.report.id);
    if (!shouldUseBackendInteractiveReports()) throw new Error("分析结果存储不可用。");
    const persisted = await saveInteractiveReportToBackend(saved.report, previous?.version);
    setSavedReports((reports) => [persisted, ...reports.filter((item) => item.report.id !== persisted.report.id)]);
    return persisted;
  }

  async function handleOpenReport(saved: SavedInteractiveReport) {
    if (turn.running) {
      setAnalysisTaskNotice("当前任务正在分析，停止回答后再切换报表。");
      return;
    }
    setAnalysisTaskNotice("");
    const sourceThreadId = saved.report.source.threadId;
    setOpenedReportId(saved.report.id);
    setOpenedReportThreadId(null);
    setSelectedAnalysisTask(saved.report.title);
    setCurrentAnalysisTaskId(sourceThreadId);
    setActiveTool("analysis-workspace");
    setMobilePane("analysisTask");
    const reportLoadRequestId = ++reportLoadRequestRef.current;
    if (shouldUseBackendInteractiveReports()) setOpenedReportLoadingThreadId(sourceThreadId);
    try {
      const detail = await getBackendAnalysisThread(sourceThreadId);
      if (reportLoadRequestId !== reportLoadRequestRef.current) return;
      setSelectedAnalysisTask(analysisThreadTitle(detail.thread) || saved.report.title);
      const refreshed: BackendAnalysisThreadSummary = {
        id: detail.thread.id,
        title: detail.thread.title ?? saved.report.title,
        latestQuestion: detail.thread.latestQuestion,
        updatedAt: detail.thread.updatedAt,
        status: detail.thread.status,
      };
      taskList.upsert(refreshed);
    } catch {
      if (reportLoadRequestId !== reportLoadRequestRef.current) return;
    } finally {
      if (reportLoadRequestId === reportLoadRequestRef.current) setOpenedReportLoadingThreadId(null);
    }
  }

  async function handleCreateAnalysisFromReport(saved: SavedInteractiveReport) {
    if (turn.running) {
      setAnalysisTaskNotice("当前任务正在分析，停止回答后再新建分析。");
      return;
    }
    setAnalysisTaskNotice("");
    if (!shouldUseBackendInteractiveReports()) return;
    const title = `${saved.report.title} 新分析`;
    const created = await createAnalysisThreadFromReportBackend(saved.report.id, title);
    taskList.upsert(created.thread);
    setSelectedAnalysisTask(analysisThreadTitle(created.thread));
    setCurrentAnalysisTaskId(created.thread.id);
    setOpenedReportId(created.saved.report.id);
    setOpenedReportThreadId(created.thread.id);
    setSavedReports((reports) => [created.saved, ...reports.filter((item) => item.report.id !== created.saved.report.id)]);
    setActiveTool("analysis-workspace");
    setMobilePane("analysisTask");
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
              key={adminNavItem.id}
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
              <button
                className="analysis-task-new"
                type="button"
                disabled={taskCreation.creating}
                onClick={() => { void handleCreateBlankAnalysis(); }}
              >
                <span>{taskCreation.creating ? "正在创建…" : "+ 新建分析"}</span>
              </button>
              <div className="analysis-task-bulk-actions" data-selecting={selectingAnalysisThreads}>
                {selectingAnalysisThreads ? (
                  <>
                    <button type="button" onClick={cancelThreadSelection}>取消</button>
                    <button className="danger" type="button" disabled={selectedThreadCount === 0} onClick={() => { void deleteSelectedThreads(); }}>删除{selectedThreadCount > 0 ? ` ${selectedThreadCount}` : ""}</button>
                  </>
                ) : (
                  <button type="button" disabled={analysisThreads.length === 0} onClick={startThreadSelection}>多选删除</button>
                )}
              </div>
              <div className="analysis-task-groups">
                {analysisThreadsLoading && analysisTaskGroups.length === 0 && <p className="analysis-task-empty">正在加载历史任务...</p>}
                {!analysisThreadsLoading && analysisTaskGroups.length === 0 && <p className="analysis-task-empty">暂无历史任务</p>}
                {analysisTaskGroups.map((group) => (
                  <section className="analysis-task-group" key={group.label}>
                    <h3>{group.label}</h3>
                    <div className="analysis-task-list">
                      {group.items.map((item) => (
                        <button key={item.id} className={`analysis-task-item ${currentAnalysisTaskId === item.id ? "active" : ""} ${selectedThreadIds.includes(item.id) ? "selected" : ""}`} type="button" onClick={() => { void selectExistingAnalysisTask(item); }}>
                          {selectingAnalysisThreads && <span className="analysis-task-check" aria-hidden="true">{selectedThreadIds.includes(item.id) ? "✓" : ""}</span>}
                          <span className="analysis-task-item-main">
                            <strong>{analysisThreadTitle(item)}</strong>
                          </span>
                          <span className="analysis-task-item-meta"><time>{analysisThreadTime(item)}</time><span className={`status-dot ${analysisThreadStatus(item)}`} title={analysisThreadStatusLabel(item)} aria-label={analysisThreadStatusLabel(item)} /></span>
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </div>
          ) : activeTool === "analysis-assets" ? (
             <div className="workbench-panel">
               <header className="panel-header"><span className="panel-kicker">REPORT CENTER</span><h2>报表中心</h2></header>
               <div className="panel-brief-list">
                 <span>我的报表</span>
                 <span>分享给我</span>
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
          {activeTool === "system" ? (
            <SystemMcpPage />
          ) : activeTool === "analysis-assets" ? (
             <MyAnalysisPage reports={savedReports} sharedReports={sharedReports} onOpenReport={handleOpenReport} onCreateAnalysis={handleCreateAnalysisFromReport} />
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
          ) : <div key={currentAnalysisTaskId ?? (taskCreation.creating ? "creating" : "new")} className="workbench-frame" style={{ height: "100%" }}>
              <div className="mobile-pane-switch" role="tablist" aria-label="分析任务工作区">
                <button className={mobilePane === "analysisTask" ? "active" : ""} type="button" onClick={() => setMobilePane("analysisTask")}>分析工作台</button>
                <button className={mobilePane === "assetLibrary" ? "active" : ""} type="button" onClick={() => setMobilePane("assetLibrary")}>分析结果</button>
              </div>
              <section className="workspace" style={{ gridTemplateColumns: `${splitPercent}% 7px minmax(0, 1fr)`, height: "100%" }}>
                <AnalysisTaskThread
                  title={displayedAnalysisTitle}
                  isNewTask={isWaitingForFirstQuestion}
                  running={turn.running}
                  nodes={turn.nodes}
                  assetNotice={analysisTaskNotice}
                  mobileHidden={mobilePane !== "analysisTask"}
                  taskKey={currentAnalysisTaskId}
                  onReply={(optionId) => {
                    if (currentAnalysisTaskId) {
                      void turn.reply(optionId, currentAnalysisTaskId, currentAnalysisTaskId);
                    }
                  }}
                  onStartFromSuggestion={handleStartFromSuggestion}
                  onSendMessage={handleSendMessage}
                  onStop={() => {
                    if (currentAnalysisTaskId) {
                      turn.stop(currentAnalysisTaskId);
                    }
                  }}
                />

                <div className="workspace-resizer" role="separator" aria-label="调整分析工作台和当前任务资产宽度" aria-orientation="vertical" onPointerDown={startResize} onDoubleClick={() => setSplitPercent(40)}><span /></div>

                <div className={`analysis-result-pane ${mobilePane !== "assetLibrary" ? "mobile-hidden" : ""}`}>
                  <InteractiveReportPanel taskTitle={selectedAnalysisTask ?? "当前分析任务"} running={turn.running} loading={currentPanelReportLoading} initialReport={currentPanelReport ?? undefined} initialVersion={currentPanelVersion} onSaveReport={handleSaveReport} />
                </div>
              </section>
          </div>
          }
        </main>
      </div>
    </div>
  );
}
