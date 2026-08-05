"use client";

import { useState } from "react";
import type { SavedReport, SharedReport } from "../types/report";
import { ReportPanel } from "./ReportPanel";

type Props = {
  reports: SavedReport[];
  sharedReports: SharedReport[];
  onOpenReport: (saved: SavedReport) => void | Promise<void>;
  onCreateAnalysis: (saved: SavedReport) => void | Promise<void>;
};

export function MyAnalysisPage({ reports, sharedReports, onOpenReport, onCreateAnalysis }: Props) {
  const [previewReport, setPreviewReport] = useState<SavedReport | null>(null);

  return (
    <section className="my-analysis-page" aria-label="报表中心">
      <header>
        <span>REPORT CENTER</span>
        <h1>报表中心</h1>
        <p>这里保存用户确认保留的报表快照。打开报表不会自动重新查询，刷新数据只产生运行时结果。</p>
      </header>

      <section className="my-analysis-section" aria-label="我的报表">
        <div className="my-analysis-section-head">
          <div>
            <span>MY REPORTS</span>
            <h2>我的报表</h2>
          </div>
          <small>{reports.length} 份已保存</small>
        </div>
        {reports.length === 0 ? (
          <p className="my-analysis-empty">尚未保存报表。回到分析工作台完成一轮分析后，选择“保存”。</p>
        ) : (
          <div className="my-analysis-cards">
            {reports.map((saved) => (
              <ReportCard
                key={saved.report.id}
                saved={saved}
                onPreview={setPreviewReport}
                onOpenReport={onOpenReport}
                onCreateAnalysis={onCreateAnalysis}
              />
            ))}
          </div>
        )}
      </section>

      <section className="my-analysis-section" aria-label="分享给我">
        <div className="my-analysis-section-head">
          <div>
            <span>SHARED WITH ME</span>
            <h2>分享给我</h2>
          </div>
          <small>{sharedReports.length} 份可查看</small>
        </div>
        {sharedReports.length === 0 ? (
          <p className="my-analysis-empty">暂无别人分享给你的报表。</p>
        ) : (
          <div className="my-analysis-cards">
            {sharedReports.map((shared) => (
              <ReportCard
                key={`${shared.report.id}:${shared.permission}`}
                saved={shared}
                onPreview={setPreviewReport}
                onOpenReport={onOpenReport}
                onCreateAnalysis={shared.permission === "view_and_reuse" ? onCreateAnalysis : undefined}
              />
            ))}
          </div>
        )}
      </section>

      {previewReport ? <ReportPreviewDialog saved={previewReport} onClose={() => setPreviewReport(null)} /> : null}
    </section>
  );
}

function ReportCard({
  saved,
  onPreview,
  onOpenReport,
  onCreateAnalysis,
}: {
  saved: SavedReport;
  onPreview: (saved: SavedReport) => void;
  onOpenReport: (saved: SavedReport) => void | Promise<void>;
  onCreateAnalysis?: (saved: SavedReport) => void | Promise<void>;
}) {
  return (
    <article className="report-center-card">
      <h3>{saved.report.title}</h3>
      <footer>
        <div className="report-card-actions">
          <button type="button" onClick={() => onPreview(saved)}>预览</button>
          <button type="button" onClick={() => window.alert("删除功能待接入后端。")}>删除</button>
          {saved.report.sourceSessionId ? (
            <button type="button" onClick={() => onOpenReport(saved)}>回到会话</button>
          ) : null}
          <button type="button" disabled={!onCreateAnalysis} onClick={() => onCreateAnalysis?.(saved)}>新建会话</button>
        </div>
      </footer>
    </article>
  );
}

function ReportPreviewDialog({ saved, onClose }: { saved: SavedReport; onClose: () => void }) {
  return (
    <div className="report-preview-backdrop" role="dialog" aria-modal="true" aria-label="报表预览">
      <section className="report-preview-dialog">
        <header>
          <h2>{saved.report.title}</h2>
          <button type="button" onClick={onClose} aria-label="关闭预览">×</button>
        </header>
        <div className="report-preview-body">
          <ReportPanel
            taskTitle={saved.report.title}
            running={false}
            initialReport={saved.report}
          />
        </div>
      </section>
    </div>
  );
}
