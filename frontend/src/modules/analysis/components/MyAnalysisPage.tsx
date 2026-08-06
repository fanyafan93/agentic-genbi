"use client";

import { useState, type KeyboardEvent, type MouseEvent } from "react";
import type { SavedReport, SharedReport } from "../types/report";
import { ReportCover } from "./ReportCover";
import { ReportPanel } from "./ReportPanel";

type Props = {
  reports: SavedReport[];
  sharedReports: SharedReport[];
  exampleReports: SavedReport[];
  onOpenReport: (saved: SavedReport) => boolean | Promise<boolean>;
  onCreateAnalysis: (saved: SavedReport) => void | Promise<void>;
  onDeleteReport: (saved: SavedReport) => Promise<void>;
};

type Notice = { kind: "status" | "error"; text: string } | null;

export function MyAnalysisPage({ reports, sharedReports, exampleReports = [], onOpenReport, onCreateAnalysis, onDeleteReport }: Props) {
  const [previewReport, setPreviewReport] = useState<SavedReport | null>(null);
  const [pendingDeleteReport, setPendingDeleteReport] = useState<SavedReport | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [deletingReportId, setDeletingReportId] = useState<string | null>(null);

  return (
    <section className="my-analysis-page" aria-label="报表中心">
      <header>
        <span>REPORT CENTER</span>
        <h1>报表中心</h1>
        <p>封面只展示报表结构，不查询数据；打开完整 Report 时再加载最新数据。</p>
      </header>

      {notice ? (
        <p className={`report-center-notice is-${notice.kind}`} role={notice.kind === "error" ? "alert" : "status"}>
          {notice.text}
        </p>
      ) : null}

      <ReportSection title="我的报表" kicker="MY REPORTS" count={`${reports.length} 份已保存`} empty="尚未保存报表。回到分析工作台完成一轮分析后，选择“保存”。">
        {reports.map((saved) => (
          <ReportCard
            key={saved.report.id}
            saved={saved}
            owned
            showReturn
            deleting={deletingReportId === saved.report.id}
            onPreview={setPreviewReport}
            onReturn={handleReturn}
            onDelete={handleDelete}
            onCreateAnalysis={onCreateAnalysis}
          />
        ))}
      </ReportSection>

      <ReportSection title="分享给我" kicker="SHARED WITH ME" count={`${sharedReports.length} 份可查看`} empty="暂无别人分享给你的报表。">
        {sharedReports.map((shared) => (
          <ReportCard
            key={`${shared.report.id}:${shared.permission}`}
            saved={shared}
            owned={false}
            showReturn
            deleting={false}
            onPreview={setPreviewReport}
            onReturn={handleReturn}
            onCreateAnalysis={shared.permission === "view_and_reuse" ? onCreateAnalysis : undefined}
          />
        ))}
      </ReportSection>

      <ReportSection title="示例报表" kicker="EXAMPLE REPORTS" count={`${exampleReports.length} 份公开示例`} empty="暂无公开示例报表。">
        {exampleReports.map((saved) => (
          <ReportCard
            key={saved.report.id}
            saved={saved}
            owned={false}
            showReturn={false}
            deleting={false}
            onPreview={setPreviewReport}
            onReturn={handleReturn}
            onCreateAnalysis={onCreateAnalysis}
          />
        ))}
      </ReportSection>

      {pendingDeleteReport ? (
        <ReportDeleteDialog
          saved={pendingDeleteReport}
          deleting={deletingReportId === pendingDeleteReport.report.id}
          onCancel={() => setPendingDeleteReport(null)}
          onConfirm={() => void confirmDelete(pendingDeleteReport)}
        />
      ) : null}
      {previewReport ? <ReportPreviewDialog saved={previewReport} onClose={() => setPreviewReport(null)} /> : null}
    </section>
  );

  async function handleReturn(saved: SavedReport) {
    setNotice(null);
    if (!saved.report.sourceSessionId) {
      setNotice({ kind: "status", text: "无关联会话或会话已经删除" });
      return;
    }
    try {
      const opened = await onOpenReport(saved);
      if (!opened) setNotice({ kind: "status", text: "无关联会话或会话已经删除" });
    } catch {
      setNotice({ kind: "status", text: "无关联会话或会话已经删除" });
    }
  }

  function handleDelete(saved: SavedReport) {
    setPendingDeleteReport(saved);
  }

  async function confirmDelete(saved: SavedReport) {
    setNotice(null);
    setDeletingReportId(saved.report.id);
    try {
      await onDeleteReport(saved);
      setPendingDeleteReport(null);
    } catch {
      setNotice({ kind: "error", text: "删除失败，请稍后重试" });
    } finally {
      setDeletingReportId(null);
    }
  }
}

function ReportDeleteDialog({ saved, deleting, onCancel, onConfirm }: {
  saved: SavedReport;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="report-delete-backdrop" role="dialog" aria-modal="true" aria-label="确认删除 Report">
      <section className="report-delete-dialog">
        <span>DELETE REPORT</span>
        <h2>删除“{saved.report.title}”？</h2>
        <p>删除后，该 Report 将不再显示在报表中心。</p>
        <footer>
          <button type="button" onClick={onCancel} disabled={deleting}>取消</button>
          <button type="button" className="is-danger" onClick={onConfirm} disabled={deleting}>
            {deleting ? "删除中…" : "确认删除"}
          </button>
        </footer>
      </section>
    </div>
  );
}

function ReportSection({ title, kicker, count, empty, children }: { title: string; kicker: string; count: string; empty: string; children: React.ReactNode }) {
  const hasReports = Array.isArray(children) ? children.length > 0 : Boolean(children);
  return (
    <section className="my-analysis-section" aria-label={title}>
      <div className="my-analysis-section-head">
        <div><span>{kicker}</span><h2>{title}</h2></div>
        <small>{count}</small>
      </div>
      {hasReports ? <div className="my-analysis-cards">{children}</div> : <p className="my-analysis-empty">{empty}</p>}
    </section>
  );
}

function ReportCard({ saved, owned, showReturn, deleting, onPreview, onReturn, onDelete, onCreateAnalysis }: {
  saved: SavedReport;
  owned: boolean;
  showReturn: boolean;
  deleting: boolean;
  onPreview: (saved: SavedReport) => void;
  onReturn: (saved: SavedReport) => void | Promise<void>;
  onDelete?: (saved: SavedReport) => void | Promise<void>;
  onCreateAnalysis?: (saved: SavedReport) => void | Promise<void>;
}) {
  const updatedAt = formatReportDate(saved.report.updatedAt ?? saved.report.createdAt);
  const openPreview = () => onPreview(saved);
  return (
    <article
      className="report-center-card"
      role="button"
      tabIndex={0}
      aria-label={`打开${saved.report.title}`}
      onClick={openPreview}
      onKeyDown={(event: KeyboardEvent<HTMLElement>) => {
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openPreview();
        }
      }}
    >
      <div className="report-card-paper">
        <span className="report-card-fold" aria-hidden="true" />
        <ReportCover report={saved.report} />
      </div>
      <div className="report-card-caption">
        <h3>{saved.report.title}</h3>
        <p>{saved.report.subtitle || "Report"}</p>
        <time>{updatedAt}</time>
        <code className="report-card-id">ID: {saved.report.id}</code>
      </div>
      <footer className="report-card-actions" onClick={stopCardOpen} onKeyDown={stopCardKey}>
        {owned ? <button type="button" disabled={deleting} onClick={() => void onDelete?.(saved)}>{deleting ? "删除中…" : "删除"}</button> : null}
        {showReturn ? <button type="button" onClick={() => void onReturn(saved)}>回到会话</button> : null}
        <button type="button" disabled={!onCreateAnalysis} onClick={() => void onCreateAnalysis?.(saved)}>新建会话</button>
      </footer>
    </article>
  );
}

function ReportPreviewDialog({ saved, onClose }: { saved: SavedReport; onClose: () => void }) {
  return (
    <div className="report-preview-backdrop" role="dialog" aria-modal="true" aria-label="报表预览">
      <section className="report-preview-dialog">
        <header><h2>{saved.report.title}</h2><button type="button" onClick={onClose} aria-label="关闭预览">×</button></header>
        <div className="report-preview-body"><ReportPanel taskTitle={saved.report.title} running={false} initialReport={saved.report} /></div>
      </section>
    </div>
  );
}

function stopCardOpen(event: MouseEvent<HTMLElement>) {
  event.stopPropagation();
}

function stopCardKey(event: KeyboardEvent<HTMLElement>) {
  event.stopPropagation();
}

function formatReportDate(value?: string): string {
  if (!value) return "刚刚更新";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "刚刚更新";
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}
