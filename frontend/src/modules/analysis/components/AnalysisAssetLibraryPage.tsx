"use client";

import { useState } from "react";
import { SharedAnalysisAssetLibrary } from "./SharedAnalysisAssetLibrary";
import type { AnalysisAssetLibraryEntry } from "./analysis-asset-contracts";
import type { AnalysisAssetCard } from "./analysis-assets";

type Props = {
  onContinueFromAsset: (asset: AnalysisAssetCard) => void;
};

const sharedAnalysisAssets: AnalysisAssetLibraryEntry[] = [
  {
    assetId: "asset_shared_rebuy_report",
    artifactVersionId: "artifact_version_rebuy_report_v3",
    sourceTaskId: "analysis_task_rebuy_30d",
    sourceTaskTitle: "首购后 30 天复购率",
    sourceConversationId: "conv_analysis_rebuy_30d",
    assetType: "报告",
    title: "首购后 30 天复购率分析报告",
    label: "报告",
    description: "已确认退款排除规则，可复用到复购经营复盘。",
    visibility: "team",
    status: "saved",
    latestVersion: "v3-approved",
    fileId: "reports-rebuy-30d-html",
    reopenContext: {
      sourceTaskId: "analysis_task_rebuy_30d",
      sourceConversationId: "conv_analysis_rebuy_30d",
      continuationPrompt: "基于首购后 30 天复购率分析报告继续分析，并沿用已确认退款排除规则。",
      targetFileId: "reports-rebuy-30d-html",
    },
  },
  {
    assetId: "asset_shared_channel_sql",
    artifactVersionId: "artifact_version_channel_sql_v2",
    sourceTaskId: "analysis_task_channel_share",
    sourceTaskTitle: "渠道销售占比分析",
    sourceConversationId: "conv_analysis_channel_share",
    assetType: "SQL",
    title: "渠道销售占比只读 SQL",
    label: "SQL",
    description: "包含渠道归因字段、订单状态过滤和默认 limit。",
    visibility: "org",
    status: "reusable",
    latestVersion: "v2-reusable",
    fileId: "queries-channel-share-sql",
    reopenContext: {
      sourceTaskId: "analysis_task_channel_share",
      sourceConversationId: "conv_analysis_channel_share",
      continuationPrompt: "基于渠道销售占比 SQL 继续分析，优先检查渠道结构和时间范围。",
      targetFileId: "queries-channel-share-sql",
    },
  },
  {
    assetId: "asset_shared_gmv_rule",
    artifactVersionId: "artifact_version_gmv_rule_v1",
    sourceTaskId: "analysis_task_east_gmv",
    sourceTaskTitle: "华东 GMV 下滑原因",
    sourceConversationId: "conv_analysis_east_gmv",
    assetType: "业务规则",
    title: "华东 GMV 下滑排查规则",
    label: "规则",
    description: "先看渠道结构、活动节奏和大客户订单波动。",
    visibility: "team",
    status: "saved",
    latestVersion: "v1-draft",
    fileId: "rules-east-gmv-md",
    reopenContext: {
      sourceTaskId: "analysis_task_east_gmv",
      sourceConversationId: "conv_analysis_east_gmv",
      continuationPrompt: "基于华东 GMV 下滑排查规则继续分析，并补充最新渠道结构证据。",
      targetFileId: "rules-east-gmv-md",
    },
  },
  {
    assetId: "asset_shared_filereport_path",
    artifactVersionId: "artifact_version_filereport_path_v1",
    sourceTaskId: "analysis_task_report_parser",
    sourceTaskTitle: "FineReport 报表语义解析",
    sourceConversationId: "conv_analysis_report_parser",
    assetType: "分析路径",
    title: "报表级语义模型解析路径",
    label: "路径",
    description: "从报表信息、数据集、指标、维度和交互规则抽象语义模型。",
    visibility: "private",
    status: "reusable",
    latestVersion: "v0.2-reusable",
    fileId: "paths-filereport-semantic-md",
    reopenContext: {
      sourceTaskId: "analysis_task_report_parser",
      sourceConversationId: "conv_analysis_report_parser",
      continuationPrompt: "基于报表级语义模型解析路径继续完善解析器输出结构。",
      targetFileId: "paths-filereport-semantic-md",
    },
  },
  {
    assetId: "asset_shared_metric_skill",
    artifactVersionId: "artifact_version_metric_skill_v01",
    sourceTaskId: "analysis_task_metric_diagnostics",
    sourceTaskTitle: "指标异动诊断方法",
    sourceConversationId: "conv_analysis_metric_diagnostics",
    assetType: "SKILL.md",
    title: "指标异动诊断 Skill.md",
    label: "Skill",
    description: "可复用分析方法：确认口径、定位维度、生成诊断报告。",
    visibility: "team",
    status: "published_mock",
    latestVersion: "v0.1-draft",
    fileId: "skills-metric-diagnostics-md",
    reopenContext: {
      sourceTaskId: "analysis_task_metric_diagnostics",
      sourceConversationId: "conv_analysis_metric_diagnostics",
      continuationPrompt: "继续编辑指标异动诊断 Skill.md，确认适用场景、业务口径和复用权限。",
      targetFileId: "skills-metric-diagnostics-md",
    },
  },
];

function assetFromEntry(entry: AnalysisAssetLibraryEntry): AnalysisAssetCard {
  return {
    id: entry.assetId,
    title: entry.title,
    label: entry.label,
    description: entry.description,
    status: entry.status === "draft" ? "draft" : "reusable",
    intent: entry.assetType.toLowerCase().includes("skill") ? "edit-skill" : "continue",
    fileId: entry.fileId,
  };
}

export function AnalysisAssetLibraryPage({ onContinueFromAsset }: Props) {
  const [selectedEntry, setSelectedEntry] = useState(sharedAnalysisAssets[0]);

  return (
    <section className="analysis-asset-library-page" aria-label="分析资产库">
      <header className="library-page-hero">
        <span>ANALYSIS ASSET LIBRARY</span>
        <h1>分析资产库</h1>
        <p>团队共享、已保存和可复用的分析资产集中在这里；从资产可以回到来源分析任务继续追问、修改或派生新版本。</p>
      </header>

      <div className="library-page-grid">
        <div className="library-page-main">
          <div className="library-page-toolbar" aria-label="分析资产库筛选">
            <button type="button" className="active">全部资产</button>
            <button type="button">报告</button>
            <button type="button">图表</button>
            <button type="button">SQL</button>
            <button type="button">业务规则</button>
            <button type="button">分析路径</button>
            <button type="button">SKILL.md</button>
          </div>
          <SharedAnalysisAssetLibrary
            entries={sharedAnalysisAssets}
            onOpenEntry={setSelectedEntry}
            onReopenEntry={(entry) => onContinueFromAsset(assetFromEntry(entry))}
          />
        </div>

        <aside className="library-page-detail" aria-label="分析资产详情">
          <span>{selectedEntry.label}</span>
          <h2>{selectedEntry.title}</h2>
          <p>{selectedEntry.description}</p>
          <dl>
            <div><dt>来源任务</dt><dd>{selectedEntry.sourceTaskTitle}</dd></div>
            <div><dt>来源 Conversation</dt><dd>{selectedEntry.sourceConversationId}</dd></div>
            <div><dt>版本</dt><dd>{selectedEntry.latestVersion}</dd></div>
            <div><dt>状态</dt><dd>{selectedEntry.status}</dd></div>
            <div><dt>可见范围</dt><dd>{selectedEntry.visibility}</dd></div>
          </dl>
          <div className="library-page-detail-actions">
            <button type="button">打开资产</button>
            <button type="button" onClick={() => onContinueFromAsset(assetFromEntry(selectedEntry))}>回到分析工作台继续</button>
          </div>
        </aside>
      </div>
    </section>
  );
}
