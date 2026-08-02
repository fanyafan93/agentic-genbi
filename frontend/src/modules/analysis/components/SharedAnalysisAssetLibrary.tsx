"use client";

import type { AnalysisAssetLibraryEntry } from "./analysis-asset-contracts";

type Props = {
  entries: AnalysisAssetLibraryEntry[];
  onOpenEntry: (entry: AnalysisAssetLibraryEntry) => void;
  onReopenEntry: (entry: AnalysisAssetLibraryEntry) => void;
};

function getStatusLabel(entry: AnalysisAssetLibraryEntry) {
  if (entry.status === "published_mock") return "已发布 / mock";
  if (entry.status === "saved") return "已保存";
  if (entry.status === "reusable") return "可复用";
  return "草稿";
}

export function SharedAnalysisAssetLibrary({
  entries,
  onOpenEntry,
  onReopenEntry,
}: Props) {
  return (
    <section className="shared-asset-library" aria-label="共享分析资产库">
      <div className="shared-asset-library-header">
        <div>
          <strong>共享分析资产库</strong>
          <small>已保存、已共享或可复用的资产，可从这里回到分析工作台继续</small>
        </div>
        <span>{entries.length} 项</span>
      </div>
      {entries.length === 0 ? (
        <p className="shared-asset-empty">保存资产或发布 Skill 后会出现在这里</p>
      ) : (
        <div className="shared-asset-grid">
          {entries.map((entry) => (
            <article className="shared-asset-card" key={entry.assetId}>
              <div className="shared-asset-card-main">
                <span>{entry.label}</span>
                <strong>{entry.title}</strong>
                <small>{entry.description}</small>
              </div>
              <dl className="shared-asset-meta">
                <div><dt>来源任务</dt><dd>{entry.sourceTaskTitle}</dd></div>
                <div><dt>最新版本</dt><dd>{entry.latestVersion}</dd></div>
                <div><dt>可见范围</dt><dd>{entry.visibility}</dd></div>
                <div><dt>状态</dt><dd>{getStatusLabel(entry)}</dd></div>
                <div><dt>资产 ID</dt><dd>{entry.assetId}</dd></div>
                <div><dt>来源执行</dt><dd>{entry.sourceExecutionAttemptId}</dd></div>
              </dl>
              <div className="shared-asset-actions">
                <button type="button" onClick={() => onOpenEntry(entry)}>打开资产</button>
                <button type="button" onClick={() => onReopenEntry(entry)}>回到分析工作台继续</button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
