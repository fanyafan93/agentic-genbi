"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getFineReportReport,
  listFineReportReports,
  type FineReportDataset,
  type FineReportReportDetail,
  type FineReportReportSummary,
} from "../api/finereport-reports";
import { FineReportSheetGrid } from "./FineReportSheetGrid";

type DetailTab = "preview" | "overview" | "datasets" | "interactions" | "structure" | "usage";

const detailTabs: Array<{ id: DetailTab; label: string }> = [
  { id: "preview", label: "报表预览" },
  { id: "overview", label: "概览" },
  { id: "datasets", label: "数据集与 SQL" },
  { id: "interactions", label: "参数与交互" },
  { id: "structure", label: "结构详情" },
  { id: "usage", label: "使用情况" },
];

export function FineReportReportBrowser() {
  const [reports, setReports] = useState<FineReportReportSummary[]>([]);
  const [selectedReportId, setSelectedReportId] = useState("");
  const [detail, setDetail] = useState<FineReportReportDetail | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>("preview");
  const [activeSheetName, setActiveSheetName] = useState("");
  const [activeDatasetName, setActiveDatasetName] = useState("");
  const [zoom, setZoom] = useState(100);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [structureQuery, setStructureQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    listFineReportReports()
      .then((items) => {
        if (!active) return;
        setReports(items);
        setSelectedReportId((current) => current || items[0]?.id || "");
        setError("");
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "无法读取 FineReport 报表画像");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedReportId) return;
    let active = true;
    setLoading(true);
    getFineReportReport(selectedReportId)
      .then((payload) => {
        if (!active) return;
        setDetail(payload);
        setActiveSheetName(payload.sheets[0]?.name ?? "");
        setActiveDatasetName(payload.datasets[0]?.name ?? "");
        setActiveTab("preview");
        setStructureQuery("");
        setError("");
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setDetail(null);
        setError(reason instanceof Error ? reason.message : "无法读取报表详情");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [selectedReportId]);

  const activeSheet = detail?.sheets.find((sheet) => sheet.name === activeSheetName) ?? detail?.sheets[0];
  const activeDataset = detail?.datasets.find((dataset) => dataset.name === activeDatasetName) ?? detail?.datasets[0];
  const filteredReports = useMemo(() => {
    const query = catalogQuery.trim().toLowerCase();
    if (!query) return reports;
    return reports.filter((report) => {
      const haystack = [report.name, report.sourceCptPath, ...report.sheetNames].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }, [catalogQuery, reports]);
  const filteredCells = useMemo(() => {
    if (!activeSheet) return [];
    const query = structureQuery.trim().toLowerCase();
    if (!query) return activeSheet.cells;
    return activeSheet.cells.filter((cell) => JSON.stringify(cell).toLowerCase().includes(query));
  }, [activeSheet, structureQuery]);

  return (
    <section className="finereport-browser" aria-label="FineReport 报表画像">
      <header className="finereport-browser-header">
        <div>
          <span>FINEREPORT REPORT PROFILE</span>
          <h1>报表画像</h1>
          <p>浏览报表画像中的结构、数据集、参数、交互规则、字段绑定和使用情况。</p>
        </div>
        <strong>{reports.length} 张报表</strong>
      </header>

      <div className="finereport-browser-layout">
        <aside className="finereport-report-catalog" aria-label="FineReport 报表目录">
          <span>报表目录</span>
          <label className="finereport-catalog-search">
            <input
              type="search"
              value={catalogQuery}
              placeholder="搜索报表、路径或 Sheet"
              aria-label="搜索报表"
              onChange={(event) => setCatalogQuery(event.target.value)}
            />
          </label>
          <div>
            {filteredReports.map((report) => (
              <button
                key={report.id}
                type="button"
                className={selectedReportId === report.id ? "active" : ""}
                aria-current={selectedReportId === report.id ? "page" : undefined}
                aria-label={`${report.name} ${report.counts.sheets} 个 Sheet`}
                onClick={() => setSelectedReportId(report.id)}
              >
                <strong>{report.name}</strong>
                <small>{report.counts.sheets} Sheet · {report.counts.datasets} 数据集 · {report.counts.cells} 单元格</small>
                {report.status === "incomplete" && <em>画像不完整</em>}
              </button>
            ))}
            {filteredReports.length === 0 && <p className="finereport-catalog-empty">没有匹配的报表。</p>}
          </div>
        </aside>

        <section className="finereport-report-detail" aria-label="FineReport 报表详情">
          {loading && !detail ? (
            <div className="finereport-state">正在读取报表画像...</div>
          ) : error ? (
            <div className="finereport-state error">{error}</div>
          ) : detail ? (
            <>
              <header className="finereport-detail-header">
                <div>
                  <span>{detail.report.status === "complete" ? "画像完整" : "画像不完整"}</span>
                  <h2>{detail.report.name}</h2>
                  <p>{detail.report.sourceCptPath || "未记录 CPT 来源路径"}</p>
                </div>
                <dl>
                  <div><dt>Sheet</dt><dd>{detail.report.counts.sheets}</dd></div>
                  <div><dt>数据集</dt><dd>{detail.report.counts.datasets}</dd></div>
                  <div><dt>公式</dt><dd>{detail.report.counts.formulas}</dd></div>
                  <div><dt>绑定</dt><dd>{detail.report.counts.bindings}</dd></div>
                </dl>
              </header>

              <nav className="finereport-detail-tabs" aria-label="报表详情视图">
                {detailTabs.map((tab) => (
                  <button key={tab.id} type="button" className={activeTab === tab.id ? "active" : ""} onClick={() => setActiveTab(tab.id)}>
                    {tab.label}
                  </button>
                ))}
              </nav>

              <div className="finereport-detail-body">
                {activeTab === "preview" && activeSheet && (
                  <ReportPreview
                    detail={detail}
                    activeSheetName={activeSheet.name}
                    zoom={zoom}
                    onSheetChange={setActiveSheetName}
                    onZoomChange={setZoom}
                  />
                )}
                {activeTab === "overview" && <ReportOverview report={detail.report} />}
                {activeTab === "datasets" && (
                  <DatasetPanel
                    datasets={detail.datasets}
                    activeDataset={activeDataset}
                    onDatasetChange={setActiveDatasetName}
                  />
                )}
                {activeTab === "interactions" && <InteractionPanel detail={detail} />}
                {activeTab === "structure" && activeSheet && (
                  <StructurePanel
                    detail={detail}
                    activeSheetName={activeSheet.name}
                    query={structureQuery}
                    cells={filteredCells}
                    onSheetChange={setActiveSheetName}
                    onQueryChange={setStructureQuery}
                  />
                )}
                {activeTab === "usage" && <UsagePanel usage={detail.reportUsage} />}
              </div>
            </>
          ) : (
            <div className="finereport-state">报表画像目录中还没有报表。</div>
          )}
        </section>
      </div>
    </section>
  );
}

function ReportPreview({
  detail,
  activeSheetName,
  zoom,
  onSheetChange,
  onZoomChange,
}: {
  detail: FineReportReportDetail;
  activeSheetName: string;
  zoom: number;
  onSheetChange: (name: string) => void;
  onZoomChange: (zoom: number) => void;
}) {
  const sheet = detail.sheets.find((item) => item.name === activeSheetName) ?? detail.sheets[0];
  return (
    <div className="finereport-preview-panel">
      <div className="finereport-preview-toolbar">
        <div className="finereport-sheet-tabs" aria-label="报表 Sheet">
          {detail.sheets.map((item) => (
            <button key={item.name} type="button" className={item.name === sheet.name ? "active" : ""} onClick={() => onSheetChange(item.name)}>
              {item.name}
            </button>
          ))}
        </div>
        <div className="finereport-zoom" aria-label="报表缩放">
          <button type="button" title="缩小" aria-label="缩小" onClick={() => onZoomChange(Math.max(60, zoom - 10))}>−</button>
          <button type="button" title="恢复 100%" onClick={() => onZoomChange(100)}>{zoom}%</button>
          <button type="button" title="放大" aria-label="放大" onClick={() => onZoomChange(Math.min(160, zoom + 10))}>+</button>
        </div>
      </div>
      <FineReportSheetGrid key={`${detail.report.id}-${sheet.name}`} sheet={sheet} zoom={zoom} />
    </div>
  );
}

function ReportOverview({ report }: { report: FineReportReportSummary }) {
  const metrics = [
    ["Sheet", report.counts.sheets],
    ["数据集", report.counts.datasets],
    ["SQL 数据集", report.counts.sqlDatasets],
    ["参数控件", report.counts.parameterWidgets],
    ["交互规则", report.counts.conditionalRules],
    ["单元格", report.counts.cells],
    ["公式", report.counts.formulas],
    ["字段绑定", report.counts.bindings],
    ["使用人数", report.counts.usageUsers],
    ["使用次数", report.counts.totalUsageCount],
  ];
  return (
    <div className="finereport-overview-grid">
      {metrics.map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}
    </div>
  );
}

function UsagePanel({ usage }: { usage: FineReportReportDetail["reportUsage"] }) {
  return (
    <div className="finereport-interaction-grid">
      <section>
        <header><h3>使用概况</h3><span>{usage.totalUsageCount}</span></header>
        <div className="finereport-record-list">
          {usage.users.map((user, index) => (
            <article key={`${user.userName}-${index}`}>
              <strong>{user.userName || "未知用户"}</strong>
              <p>{[user.position, user.department].filter(Boolean).join(" / ") || "未记录岗位与部门"}</p>
              <code>{user.usageCount} 次</code>
            </article>
          ))}
          {usage.users.length === 0 && <p>该报表画像尚未记录使用情况。</p>}
        </div>
      </section>
    </div>
  );
}

function DatasetPanel({
  datasets,
  activeDataset,
  onDatasetChange,
}: {
  datasets: FineReportDataset[];
  activeDataset?: FineReportDataset;
  onDatasetChange: (name: string) => void;
}) {
  return (
    <div className="finereport-dataset-panel">
      <nav aria-label="报表数据集">
        {datasets.map((dataset) => (
          <button key={dataset.name} type="button" className={activeDataset?.name === dataset.name ? "active" : ""} onClick={() => onDatasetChange(dataset.name)}>
            <strong>{dataset.name}</strong>
            <small>{dataset.connection_name || dataset.type || "内嵌数据"}</small>
          </button>
        ))}
      </nav>
      <section>
        {activeDataset ? (
          <>
            <header><span>{activeDataset.type || "dataset"}</span><h3>{activeDataset.name}</h3><p>{activeDataset.connection_name || "未配置数据库连接"}</p></header>
            <pre><code>{activeDataset.raw_sql || "该数据集没有 SQL 文本。"}</code></pre>
          </>
        ) : <p>该报表没有数据集。</p>}
      </section>
    </div>
  );
}

function InteractionPanel({ detail }: { detail: FineReportReportDetail }) {
  return (
    <div className="finereport-interaction-grid">
      <section>
        <header><h3>参数控件</h3><span>{detail.parameterWidgets.length}</span></header>
        <div className="finereport-record-list">
          {detail.parameterWidgets.map((item, index) => (
            <article key={`${String(item.parameter)}-${index}`}><strong>{String(item.label || item.parameter || "未命名控件")}</strong><code>{String(item.widget_class || "widget")}</code></article>
          ))}
        </div>
      </section>
      <section>
        <header><h3>条件与交互规则</h3><span>{detail.conditionalRules.length}</span></header>
        <div className="finereport-record-list">
          {detail.conditionalRules.map((item, index) => (
            <article key={`${String(item.cell)}-${index}`}><strong>{String(item.cell || "report")}</strong><p>{String(item.condition || "无条件")}</p><code>{String(item.action || item.action_class || "action")}</code></article>
          ))}
        </div>
      </section>
    </div>
  );
}

function StructurePanel({
  detail,
  activeSheetName,
  query,
  cells,
  onSheetChange,
  onQueryChange,
}: {
  detail: FineReportReportDetail;
  activeSheetName: string;
  query: string;
  cells: FineReportReportDetail["sheets"][number]["cells"];
  onSheetChange: (name: string) => void;
  onQueryChange: (value: string) => void;
}) {
  return (
    <div className="finereport-structure-panel">
      <div className="finereport-structure-toolbar">
        <select value={activeSheetName} aria-label="选择 Sheet" onChange={(event) => onSheetChange(event.target.value)}>
          {detail.sheets.map((sheet) => <option key={sheet.name} value={sheet.name}>{sheet.name}</option>)}
        </select>
        <input type="search" value={query} placeholder="搜索单元格、值、公式或绑定字段" onChange={(event) => onQueryChange(event.target.value)} />
        <span>{cells.length} 个结果</span>
      </div>
      <div className="finereport-cell-table" role="table" aria-label="报表单元格结构">
        <div className="finereport-cell-table-row head" role="row"><strong>单元格</strong><strong>值</strong><strong>公式</strong><strong>绑定</strong></div>
        {cells.slice(0, 300).map((cell) => (
          <div className="finereport-cell-table-row" role="row" key={cell.cell}>
            <strong>{cell.cell}</strong>
            <span>{cell.value === undefined || cell.value === null ? "" : String(cell.value)}</span>
            <code>{cell.formula || ""}</code>
            <code>{cell.binding ? `${cell.binding.dataset || ""}.${cell.binding.field || ""}` : ""}</code>
          </div>
        ))}
      </div>
    </div>
  );
}
