import type { AnalysisReport } from "../../types/analysis";

import { ReportChart } from "./ReportChart";
import { ReportTable } from "./ReportTable";

export function ReportView({ report }: { report: AnalysisReport }) {
  return (
    <article className="report-view">
      <div className="report-heading">
        <div><span className="section-kicker">RESULT / 01</span><h2>{report.title}</h2></div>
        <span className="duration">{report.query_duration_ms} ms · {report.sql_attempts} 次 SQL 尝试</span>
      </div>
      <div className="summary-list">
        {report.summary.map((item) => <p key={item}>{item}</p>)}
      </div>
      <div className="report-grid">
        <section className="sql-panel"><span className="section-kicker">QUERY</span><pre>{report.sql}</pre></section>
        <ReportChart report={report} />
      </div>
      <section className="table-panel"><div className="panel-heading"><span className="section-kicker">ROWS</span><h3>查询结果</h3></div><ReportTable table={report.table} /></section>
      {(report.assumptions.length > 0 || report.warnings.length > 0) && (
        <div className="notes-grid">
          {report.assumptions.length > 0 && <NoteList title="假设" items={report.assumptions} />}
          {report.warnings.length > 0 && <NoteList title="提醒" items={report.warnings} warning />}
        </div>
      )}
    </article>
  );
}

function NoteList({ title, items, warning = false }: { title: string; items: string[]; warning?: boolean }) {
  return <section className={warning ? "note note-warning" : "note"}><h3>{title}</h3>{items.map((item) => <p key={item}>{item}</p>)}</section>;
}

