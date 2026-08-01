"use client";

import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Puck, Render, type Config, type Data } from "@puckeditor/core";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef } from "ag-grid-community";
import { EChartRenderer } from "@/shared/charts/EChartRenderer";
import { channelSalesReportQueryRef, createDefaultReportFilters, mockInteractiveReport, queryMockDataset } from "../mocks/interactive-report";
import { fetchInteractiveReportQuery, shouldUseBackendReportQueries } from "../api/interactive-report-query-service";
import type { SavedInteractiveReport } from "../mocks/interactive-report-storage";
import type { InteractiveReportVersionSummary } from "../api/interactive-report-service";
import type { InteractiveReport, ReportDatasetRow, ReportRuntimeFilters } from "../types/interactive-report";

ModuleRegistry.registerModules([AllCommunityModule]);

type ReportRuntime = {
  report: InteractiveReport;
  filters: ReportRuntimeFilters;
  getRows: (queryRef: string) => ReportDatasetRow[];
};

const RuntimeContext = createContext<ReportRuntime | null>(null);

function useReportRuntime() {
  const runtime = useContext(RuntimeContext);
  if (!runtime) throw new Error("Interactive report blocks must render inside ReportRuntimeContext.");
  return runtime;
}

function formatValue(value: string | number, format?: "currency" | "percent" | "number") {
  if (typeof value !== "number") return value;
  if (format === "currency") return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value) + " 元";
  if (format === "percent") return `${(value * 100).toFixed(1)}%`;
  return value.toLocaleString("zh-CN");
}

function SectionBlock({ title, tone }: { title: string; tone?: "coral" | "navy" }) {
  return <section className={`report-section-title ${tone === "coral" ? "coral" : ""}`}><span>{tone === "coral" ? "ANALYST NOTE" : "ANALYSIS VIEW"}</span><h3>{title}</h3></section>;
}

function MarkdownBlock({ content }: { content: string }) {
  return <div className="report-markdown">{content}</div>;
}

function KpiBlock({ metric }: { metric: "sales" | "share" | "growth" }) {
  const { getRows, report } = useReportRuntime();
  const rows = getRows(Object.keys(report.queries)[0] ?? channelSalesReportQueryRef);
  const total = rows.reduce((sum, row) => sum + Number(row.salesAmount), 0);
  const lead = rows[0];
  const growthValues = rows.map((row) => Number(row.growth)).filter((value) => Number.isFinite(value));
  const values = {
    sales: { label: "销售额", value: formatValue(total, "currency"), meta: "当前筛选范围" },
    share: { label: "主渠道占比", value: lead ? formatValue(Number(lead.salesShare), "percent") : "-", meta: String(lead?.channel ?? "暂无数据") },
    growth: { label: "增长表现", value: growthValues.length ? formatValue(Math.max(...growthValues), "percent") : "-", meta: growthValues.length ? "同比增长" : "待接入环比/同比查询" },
  }[metric];
  return <article className="report-kpi"><span>{values.label}</span><strong>{values.value}</strong><small>{values.meta}</small></article>;
}

function ChartBlock({ chartSpecRef, queryRef }: { chartSpecRef: string; queryRef: string }) {
  const { report, getRows } = useReportRuntime();
  const spec = report.chartSpecs[chartSpecRef];
  const rows = getRows(queryRef);
  if (!spec) return null;
  return <article className="report-chart-block"><EChartRenderer spec={{ type: spec.type, title: spec.title, categoryField: spec.xField, series: spec.series.map((item) => ({ field: item.field, name: item.label, format: item.format })) }} rows={rows} /></article>;
}

function GridBlock({ gridSpecRef, queryRef }: { gridSpecRef: string; queryRef: string }) {
  const { report, getRows } = useReportRuntime();
  const spec = report.gridSpecs[gridSpecRef];
  const rows = getRows(queryRef);
  if (!spec) return null;
  const columnDefs: ColDef<ReportDatasetRow>[] = spec.columns.map((column) => ({
    field: column.field,
    headerName: column.label,
    sortable: true,
    filter: true,
    minWidth: column.field === "channel" ? 150 : 120,
    flex: column.field === "channel" ? 1.25 : 1,
    valueFormatter: (params) => formatValue(params.value, column.format),
    cellClass: column.field === "status" ? "analysis-status-cell" : undefined,
  }));
  return <article className="report-grid-block"><AgGridReact<ReportDatasetRow> rowData={rows} columnDefs={columnDefs} theme={themeQuartz.withParams({ accentColor: "#e8685a", borderColor: "#e5e8eb", headerBackgroundColor: "#f7f8fa", headerTextColor: "#667085", foregroundColor: "#182230", spacing: 6 })} pagination paginationPageSize={spec.pageSize} domLayout="autoHeight" /></article>;
}

function EvidenceBlock({ label, content }: { label: string; content: string }) {
  return <aside className="report-evidence"><strong>{label}</strong><p>{content}</p></aside>;
}

export const interactiveReportPuckConfig: Config = {
  components: {
    SectionBlock: { fields: { title: { type: "text" }, tone: { type: "select", options: [{ label: "珊瑚", value: "coral" }, { label: "深蓝", value: "navy" }] } }, defaultProps: { title: "新章节", tone: "navy" }, render: (props) => <SectionBlock title={String(props.title)} tone={props.tone === "coral" ? "coral" : "navy"} /> },
    MarkdownBlock: { fields: { content: { type: "textarea" } }, defaultProps: { content: "输入分析说明" }, render: (props) => <MarkdownBlock content={String(props.content)} /> },
    KpiBlock: { fields: { metric: { type: "select", options: [{ label: "销售额", value: "sales" }, { label: "主渠道占比", value: "share" }, { label: "最快增长", value: "growth" }] } }, defaultProps: { metric: "sales" }, render: (props) => <KpiBlock metric={props.metric === "share" || props.metric === "growth" ? props.metric : "sales"} /> },
    ChartBlock: { fields: { chartSpecRef: { type: "text" }, queryRef: { type: "text" } }, defaultProps: { chartSpecRef: "channel-sales-chart", queryRef: channelSalesReportQueryRef }, render: (props) => <ChartBlock chartSpecRef={String(props.chartSpecRef)} queryRef={String(props.queryRef)} /> },
    GridBlock: { fields: { gridSpecRef: { type: "text" }, queryRef: { type: "text" } }, defaultProps: { gridSpecRef: "channel-sales-grid", queryRef: channelSalesReportQueryRef }, render: (props) => <GridBlock gridSpecRef={String(props.gridSpecRef)} queryRef={String(props.queryRef)} /> },
    EvidenceBlock: { fields: { label: { type: "text" }, content: { type: "textarea" } }, defaultProps: { label: "证据与假设", content: "说明数据来源、口径与需要确认的内容。" }, render: (props) => <EvidenceBlock label={String(props.label)} content={String(props.content)} /> },
  },
};

function ReportRuntimeProvider({ report, filters, children }: { report: InteractiveReport; filters: ReportRuntimeFilters; children: ReactNode }) {
  const [backendRows, setBackendRows] = useState<Record<string, ReportDatasetRow[]>>({});

  useEffect(() => {
    let cancelled = false;
    if (!shouldUseBackendReportQueries()) {
      setBackendRows({});
      return () => { cancelled = true; };
    }
    const queryRefs = Object.keys(report.queries);
    void Promise.all(queryRefs.map(async (queryRef) => {
      try {
        const result = await fetchInteractiveReportQuery(queryRef, filters);
        return [queryRef, result.rows] as const;
      } catch {
        return [queryRef, []] as const;
      }
    })).then((entries) => {
      if (!cancelled) setBackendRows(Object.fromEntries(entries));
    });
    return () => { cancelled = true; };
  }, [filters, report]);

  const runtime = useMemo<ReportRuntime>(() => ({
    report,
    filters,
    getRows: (queryRef) => {
      const query = report.queries[queryRef];
      if (!query) return [];
      if (shouldUseBackendReportQueries()) return backendRows[queryRef] ?? [];
      return queryMockDataset(query.datasetId, filters);
    },
  }), [backendRows, filters, report]);
  return <RuntimeContext.Provider value={runtime}>{children}</RuntimeContext.Provider>;
}

type Props = {
  taskTitle: string;
  running: boolean;
  initialReport?: InteractiveReport;
  initialVersion?: number;
  onSaveReport?: (saved: SavedInteractiveReport) => Promise<SavedInteractiveReport>;
  onListVersions?: (reportId: string) => Promise<InteractiveReportVersionSummary[]>;
  onLoadVersion?: (reportId: string, version: number) => Promise<SavedInteractiveReport>;
};

export function InteractiveReportPanel({ taskTitle, running, initialReport = mockInteractiveReport, initialVersion = 1, onSaveReport, onListVersions, onLoadVersion }: Props) {
  const [report, setReport] = useState(initialReport);
  const [filters, setFilters] = useState(() => createDefaultReportFilters(initialReport));
  const [editorOpen, setEditorOpen] = useState(false);
  const [notice, setNotice] = useState("Agent 已生成一份可继续编辑的分析结果。");
  const [version, setVersion] = useState(initialVersion);
  const [versionHistory, setVersionHistory] = useState<InteractiveReportVersionSummary[] | null>(null);

  useEffect(() => {
    setReport(initialReport);
    setVersion(initialVersion);
    setFilters(createDefaultReportFilters(initialReport));
    setVersionHistory(null);
    setNotice("已加载本轮分析结果；当前筛选是新的运行时视图。");
  }, [initialReport, initialVersion]);

  const changeFilter = (id: keyof ReportRuntimeFilters, value: string) => setFilters((current) => ({ ...current, [id]: value }));
  const persist = async (nextReport: InteractiveReport) => {
    const fallback: SavedInteractiveReport = { report: nextReport, version, savedAt: new Date().toISOString() };
    const saved = onSaveReport ? await onSaveReport(fallback) : { ...fallback, version: version + 1 };
    setReport(saved.report);
    setVersion(saved.version);
    return saved;
  };
  const publish = async (document: Data) => {
    const nextReport = { ...report, document };
    try {
      await persist(nextReport);
      setEditorOpen(false);
      setNotice("已保存新的报告版本。筛选状态保持为本次运行时视图。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "分析结果保存失败。");
    }
  };
  const save = async () => {
    try {
      await persist(report);
      setNotice("已保存到“我的结果”。筛选状态没有写入报告版本。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "分析结果保存失败。");
    }
  };
  const toggleVersionHistory = async () => {
    if (!onListVersions) return;
    if (versionHistory) {
      setVersionHistory(null);
      return;
    }
    try {
      setVersionHistory(await onListVersions(report.id));
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "历史版本读取失败。");
    }
  };
  const loadVersion = async (targetVersion: number) => {
    if (!onLoadVersion || targetVersion === version) return;
    try {
      const saved = await onLoadVersion(report.id, targetVersion);
      setReport(saved.report);
      setVersion(saved.version);
      setFilters(createDefaultReportFilters(saved.report));
      setNotice(`已打开 v${saved.version} 历史版本；编辑或保存会创建新版本。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "历史版本读取失败。");
    }
  };

  return (
    <section className="interactive-report-panel" aria-label="分析结果">
      <header className="result-panel-header">
        <div>
          <span className="result-kicker">INTERACTIVE RESULT · v{version}</span>
          <h2>{report.title}</h2>
          <p>{taskTitle} · {report.subtitle}</p>
        </div>
        <div className="result-actions">
          <button type="button" onClick={save}>保存</button>
          {onListVersions && onLoadVersion ? <button type="button" onClick={toggleVersionHistory}>历史版本</button> : null}
          <button type="button" onClick={() => setNotice("已创建团队内只读分享链接（Mock）。")}>分享</button>
          <button type="button" onClick={() => setNotice("已从本次对话、查询和结果提炼出分析模板草稿（Mock）。")}>提炼为模板</button>
          <button type="button" onClick={() => setNotice("导出队列已创建：交互式报告 PDF 与渠道明细 XLSX（Mock）。")}>导出</button>
          <button className="primary" type="button" onClick={() => setEditorOpen(true)}>编辑结果</button>
        </div>
      </header>
      <div className="report-filter-row" aria-label="报告筛选条件">
        {report.filters.map((filter) => <label key={filter.id}><span>{filter.label}</span><select aria-label={filter.label} value={filters[filter.id]} onChange={(event) => changeFilter(filter.id, event.target.value)}>{filter.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>)}
        <span className={`report-runtime-status ${running ? "running" : ""}`}>{running ? "Agent 正在更新结果" : "运行时筛选不会创建版本"}</span>
      </div>
      <p className="report-notice" role="status">{notice}</p>
      {versionHistory ? <section className="report-version-history" aria-label="报告历史版本">
        <strong>历史版本</strong>
        <div>{versionHistory.map((item) => <button key={item.version} type="button" className={item.version === version ? "active" : ""} onClick={() => void loadVersion(item.version)}>v{item.version} · {new Date(item.createdAt).toLocaleString("zh-CN")}</button>)}</div>
      </section> : null}
      <div className="report-canvas">
        <ReportRuntimeProvider report={report} filters={filters}><Render config={interactiveReportPuckConfig} data={report.document} /></ReportRuntimeProvider>
      </div>
      {editorOpen && (
        <div className="report-editor-backdrop" role="dialog" aria-modal="true" aria-label="编辑分析结果">
          <div className="report-editor-shell">
            <header><div><span>PUCK REPORT EDITOR</span><h2>编辑分析结果</h2></div><button type="button" onClick={() => setEditorOpen(false)} aria-label="关闭编辑器">×</button></header>
            <ReportRuntimeProvider report={report} filters={filters}><Puck config={interactiveReportPuckConfig} data={report.document} onPublish={publish} headerTitle="分析结果编排" /></ReportRuntimeProvider>
          </div>
        </div>
      )}
    </section>
  );
}
