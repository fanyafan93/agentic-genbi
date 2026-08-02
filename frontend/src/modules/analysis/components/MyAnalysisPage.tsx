"use client";

import type { SavedInteractiveReport } from "../api/interactive-report-service";

type Props = {
  reports: SavedInteractiveReport[];
  onOpenReport: (saved: SavedInteractiveReport) => void;
};

export function MyAnalysisPage({ reports, onOpenReport }: Props) {
  return (
    <section className="my-analysis-page" aria-label="我的分析">
      <header>
        <span>MY ANALYSIS</span>
        <h1>我的分析</h1>
        <p>这里保存你确认要保留的结果和可复用的分析模板。临时筛选不产生新版本。</p>
      </header>
      <section className="my-analysis-section" aria-label="我的结果">
        <div className="my-analysis-section-head"><div><span>INTERACTIVE RESULTS</span><h2>我的结果</h2></div><small>{reports.length} 份已保存</small></div>
        {reports.length === 0 ? <p className="my-analysis-empty">尚未保存分析结果。回到分析工作台完成一轮分析后，选择“保存”。</p> : <div className="my-analysis-cards">
          {reports.map((saved) => <article key={saved.report.id}>
            <span>交互式报告 · v{saved.version}</span>
            <h3>{saved.report.title}</h3>
            <p>{saved.report.subtitle}</p>
            <footer><time>{new Date(saved.savedAt).toLocaleString("zh-CN")}</time><button type="button" onClick={() => onOpenReport(saved)}>打开结果</button></footer>
          </article>)}
        </div>}
      </section>
      <section className="my-analysis-section template-placeholder" aria-label="分析模板">
        <div className="my-analysis-section-head"><div><span>ANALYSIS TEMPLATES</span><h2>分析模板</h2></div><small>下一阶段</small></div>
        <p>用户可从当前对话、查询步骤和最终结果中提炼模板，再用新参数发起下一次分析。</p>
      </section>
    </section>
  );
}
