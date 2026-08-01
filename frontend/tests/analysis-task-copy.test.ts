import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";

const workspaceSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/AnalysisWorkspace.tsx"),
  "utf8",
);

const suggestionsSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/Suggestions.tsx"),
  "utf8",
);

const agentTypesSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/agentClients/types.ts"),
  "utf8",
);

const mockClientSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/agentClients/mockClient.ts"),
  "utf8",
);

const backendClientSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/agentClients/backendClient.ts"),
  "utf8",
);

const agentClientIndexSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/agentClients/index.ts"),
  "utf8",
);

const assetsSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/analysis-assets.ts"),
  "utf8",
);

const assetContractsSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/analysis-asset-contracts.ts"),
  "utf8",
);

const assetLibrarySource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/AnalysisAssetLibrary.tsx"),
  "utf8",
);

const assetLibraryPageSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/AnalysisAssetLibraryPage.tsx"),
  "utf8",
);

const businessSemanticLibrarySource = readFileSync(
  resolve(process.cwd(), "src/modules/business-semantics/components/BusinessSemanticLibrary.tsx"),
  "utf8",
);

const analysisTaskThreadSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/AnalysisTaskThread.tsx"),
  "utf8",
);

const flowNodeViewSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/FlowNodeView.tsx"),
  "utf8",
);

const globalStylesSource = readFileSync(resolve(process.cwd(), "src/app/globals.css"), "utf8");

const sharedAssetLibrarySource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/SharedAnalysisAssetLibrary.tsx"),
  "utf8",
);

const assetLibraryServiceSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/api/analysis-asset-library-service.ts"),
  "utf8",
);

const modeToggleSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/AnalysisModeToggle.tsx"),
  "utf8",
);

describe("analysis task product language", () => {
  test("frames the primary workspace as a unified analysis workspace", () => {
    expect(workspaceSource).toContain('label: "分析工作台"');
    expect(workspaceSource).toContain('label: "分析资产库"');
    expect(workspaceSource).toContain('label: "业务语义库"');
    expect(workspaceSource).toContain("ANALYSIS WORKSPACE");
    expect(workspaceSource).toContain("<h2>分析工作台</h2>");
    expect(workspaceSource).toContain('placeholder="搜索分析任务"');
    expect(workspaceSource).toContain("+ 新建分析");
    expect(workspaceSource).toContain('aria-label="分析任务工作区"');
    expect(workspaceSource).toContain(">分析工作台</button>");
    expect(workspaceSource).toContain("新分析");

    expect(workspaceSource).not.toContain('label: "会话"');
    expect(workspaceSource).not.toContain('label: "知识探索"');
    expect(workspaceSource).not.toContain('label: "Agent 中心"');
    expect(workspaceSource).not.toContain("KnowledgeExploration");
    expect(workspaceSource).not.toContain("CONVERSATIONS");
    expect(workspaceSource).not.toContain("+ 新建会话");
    expect(suggestionsSource).not.toContain("开始一个会话");
  });

  test("keeps current task assets in the analysis workspace and moves shared assets to the standalone library", () => {
    expect(workspaceSource).toContain("AnalysisAssetLibrary");
    expect(workspaceSource).toContain("AnalysisAssetLibraryPage");
    expect(assetLibrarySource).toContain("当前任务资产");
    expect(assetLibrarySource).toContain("可复用");
    expect(assetLibrarySource).toContain('aria-label="当前任务资产视图"');
    expect(assetLibrarySource).not.toContain("SharedAnalysisAssetLibrary");
    expect(assetLibrarySource).not.toContain("共享资产库");
    expect(assetLibrarySource).not.toContain("libraryView");
    expect(assetLibrarySource).not.toContain('aria-label="切换分析资产库视图"');
    expect(assetLibraryPageSource).toContain("SharedAnalysisAssetLibrary");
    expect(assetLibraryPageSource).toContain("共享、已保存和可复用的分析资产");
    expect(assetLibraryPageSource).toContain("打开资产");
    expect(assetLibraryPageSource).toContain("回到分析工作台继续");
    expect(assetLibraryPageSource).toContain("来源任务");
    expect(assetLibraryPageSource).toContain("latestVersion");
    expect(assetLibraryPageSource).toContain("visibility");
    expect(sharedAssetLibrarySource).toContain("共享分析资产库");
    expect(sharedAssetLibrarySource).toContain("已保存、已共享或可复用的资产");
    expect(sharedAssetLibrarySource).toContain("回到分析工作台继续");
  });

  test("adds a business semantic library for structured knowledge and semantics", () => {
    expect(workspaceSource).toContain("BusinessSemanticLibrary");
    expect(workspaceSource).toContain("结构化知识");
    expect(workspaceSource).toContain("系统里实际存在什么");
    expect(workspaceSource).toContain("语义");
    expect(workspaceSource).toContain("业务解释和使用规则");
    expect(workspaceSource).toContain("FineReport");
    expect(workspaceSource).toContain("报表解析");
    expect(workspaceSource).toContain("Apache Hop");
    expect(workspaceSource).toContain("ETL 血缘解析");
    expect(workspaceSource).toContain("MySQL / Doris 元数据");
    expect(workspaceSource).toContain("金蝶");
    expect(workspaceSource).toContain("业务数据字典");
    expect(businessSemanticLibrarySource).toContain("business-semantic-page-empty");
    expect(businessSemanticLibrarySource).not.toContain("structured-knowledge-card");
    expect(businessSemanticLibrarySource).not.toContain("semantic-flow-strip");
  });

  test("keeps the desktop page structure at every viewport width", () => {
    expect(globalStylesSource).toContain("--app-canvas-min-width: 1180px");
    expect(globalStylesSource).toContain(
      "html { min-width: var(--app-canvas-min-width); overflow-x: auto; overflow-y: hidden; }",
    );
    expect(globalStylesSource).toContain(
      "body { min-width: var(--app-canvas-min-width); overflow: hidden; }",
    );
    expect(globalStylesSource).toContain(
      ".topbar, .shell { min-width: var(--app-canvas-min-width); }",
    );
    expect(globalStylesSource).not.toContain("@media (max-width: 900px)");
    expect(globalStylesSource).not.toContain("@media (max-width: 620px)");
    expect(globalStylesSource).not.toContain("@media (max-width: 520px)");
  });

  test("uses a fixed report catalog and scrollable FineReport grid", () => {
    expect(globalStylesSource).toContain(
      ".finereport-browser-layout { display: grid; grid-template-columns: 220px minmax(0, 1fr);",
    );
    expect(globalStylesSource).toContain(
      ".finereport-grid-scroll { min-width: 0; min-height: 0; overflow: auto;",
    );
    expect(globalStylesSource).toContain(".finereport-grid { position: relative; display: grid;");
  });

  test("keeps the lower-level interaction event generic for shared conversations", () => {
    expect(agentTypesSource).toContain('"conversation-init"');
    expect(agentTypesSource).toContain("conversationId?: string");
    expect(agentTypesSource).toContain('"run-init"');
    expect(agentTypesSource).not.toContain('"analysis-task-init"');
  });

  test("supports quick and deep analysis modes as agent behavior inputs", () => {
    expect(agentTypesSource).toContain('export type AnalysisMode = "quick" | "deep"');
    expect(agentTypesSource).toContain("analysisMode?: AnalysisMode");
    expect(agentTypesSource).toContain('{ kind: "reply"; optionId: string; analysisMode?: AnalysisMode }');
    expect(modeToggleSource).toContain("快速分析");
    expect(modeToggleSource).toContain("深度分析");
    expect(workspaceSource).toContain("AnalysisTaskThread");
    expect(analysisTaskThreadSource).toContain("AnalysisModeToggle");
    expect(mockClientSource).toContain('this.state.analysisMode === "deep"');
    expect(mockClientSource).toContain("quick_report.html");
    expect(mockClientSource).toContain("检索业务语义库");
    expect(mockClientSource).toContain("语义查证");
    expect(mockClientSource).toContain("读取报表语义 / 字段 / 血缘 / SQL 示例");
  });

  test("can switch analysis tasks from mock client to the real backend run API", () => {
    expect(agentClientIndexSource).toContain("BackendAnalysisAgentClient");
    expect(agentClientIndexSource).toContain("shouldUseBackendAnalysisClient");
    expect(backendClientSource).toContain("NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME");
    expect(backendClientSource).toContain("NEXT_PUBLIC_GENBI_API_BASE_URL");
    expect(backendClientSource).toContain("/api/analysis/tasks/runs/stream");
    expect(backendClientSource).toContain("analysis.problem.classified");
    expect(backendClientSource).toContain("analysis.retrieval.plan");
    expect(backendClientSource).toContain("artifact.created");
    expect(backendClientSource).toContain("artifact.updated");
    expect(backendClientSource).toContain("mapBackendEvents");
    expect(backendClientSource).toContain("event.payload.conversation_id");
  });

  test("keeps the analysis task thread presentation in its own component", () => {
    expect(workspaceSource).toContain("AnalysisTaskThread");
    expect(analysisTaskThreadSource).toContain("FlowNodeView");
    expect(analysisTaskThreadSource).toContain("Suggestions");
    expect(analysisTaskThreadSource).toContain("FlowComposer");
    expect(analysisTaskThreadSource).toContain("threadScrollRef");
    expect(analysisTaskThreadSource).toContain("输入待解决的业务问题，按回车发送");
    expect(analysisTaskThreadSource).toContain("有什么问题，或想继续分析什么？");
    expect(workspaceSource).not.toContain("threadScrollRef");
    expect(workspaceSource).not.toContain("lastNodeCountRef");
  });

  test("renders long agent analysis answers as bounded markdown", () => {
    expect(flowNodeViewSource).toContain('import ReactMarkdown from "react-markdown"');
    expect(flowNodeViewSource).toContain('import remarkGfm from "remark-gfm"');
    expect(flowNodeViewSource).toContain('className="message-body-markdown flow-content"');
    expect(globalStylesSource).toContain(".flow-agent .flow-content");
    expect(globalStylesSource).toContain("max-height: min(54vh, 680px)");
  });

  test("treats generated files and Skill markdown as analysis assets", () => {
    expect(workspaceSource).toContain("mergeArtifactFolders");
    expect(assetLibrarySource).toContain("describeArtifact");
    expect(assetLibrarySource).toContain("buildAnalysisAssetCards");
    expect(assetLibrarySource).toContain("可沉淀资产");
    expect(assetLibrarySource).toContain("保存后可从分析资产库回到本任务继续");
    expect(assetLibrarySource).toContain("onSaveAsset");
    expect(assetLibrarySource).toContain("onContinueFromAsset");
    expect(assetLibrarySource).toContain("已保存到分析资产库");
    expect(assetsSource).toContain("渠道销售占比分析 Skill");
    expect(assetsSource).toContain("可复用分析方法");
    expect(assetsSource).toContain("待确认业务口径");
    expect(assetsSource).toContain('intent: "edit-skill"');
    expect(assetsSource).toContain("复用权限");
    expect(assetsSource).toContain("指标口径");
    expect(assetsSource).toContain("业务规则");
    expect(assetsSource).toContain("分析路径");
    expect(assetsSource).toContain("Dashboard 片段");
    expect(mockClientSource).toContain("skills/analysis_skill.md");
    expect(mockClientSource).toContain("scripts/analysis_notebook.py");
    expect(mockClientSource).toContain("definitions/channel_sales_metric.md");
    expect(mockClientSource).toContain("rules/order_scope_rule.md");
    expect(mockClientSource).toContain("paths/channel_analysis_path.md");
    expect(mockClientSource).toContain("dashboards/channel_overview.dashboard.json");
  });

  test("lets saved analysis assets reopen the current analysis task context", () => {
    expect(workspaceSource).toContain("savedAssetIds");
    expect(workspaceSource).toContain("handleSaveAsset");
    expect(workspaceSource).toContain("handleContinueFromAsset");
    expect(workspaceSource).toContain("基于分析资产");
    expect(workspaceSource).toContain("继续当前分析任务");
    expect(workspaceSource).toContain("可从资产回到本任务继续");
  });

  test("shows a shared asset library entry that can reopen source task context", () => {
    expect(assetContractsSource).toContain("AnalysisAssetLibraryEntry");
    expect(assetContractsSource).toContain("AnalysisAssetReopenContext");
    expect(assetContractsSource).toContain("AnalysisAssetSaveRequest");
    expect(assetContractsSource).toContain("AnalysisAssetSaveResult");
    expect(assetContractsSource).toContain("assetId");
    expect(assetContractsSource).toContain("artifactVersionId");
    expect(assetContractsSource).toContain("sourceTaskId");
    expect(assetContractsSource).toContain("sourceConversationId");
    expect(assetContractsSource).toContain("sourceRunId");
    expect(assetContractsSource).toContain("AnalysisAssetSourceContext");
    expect(assetContractsSource).toContain("sourceContext: AnalysisAssetSourceContext");
    expect(assetContractsSource).toContain("visibility");
    expect(assetContractsSource).toContain("latestVersion");
    expect(assetContractsSource).toContain("reopenContext");
    expect(assetContractsSource).toContain("continuationPrompt");
    expect(assetContractsSource).toContain("saveReason");
    expect(assetContractsSource).toContain("saveAnalysisAssetMock");
    expect(assetContractsSource).toContain("buildMockAnalysisAssetLibraryEntries");
    expect(assetLibraryServiceSource).toContain("AnalysisAssetLibraryService");
    expect(assetLibraryServiceSource).toContain("AnalysisAssetLibraryListRequest");
    expect(assetLibraryServiceSource).toContain("AnalysisAssetReopenResult");
    expect(assetLibraryServiceSource).toContain("mockAnalysisAssetLibraryService");
    expect(assetLibraryServiceSource).toContain("listEntries");
    expect(assetLibraryServiceSource).toContain("saveAsset");
    expect(assetLibraryServiceSource).toContain("reopenEntry");
    expect(sharedAssetLibrarySource).toContain("来源任务");
    expect(sharedAssetLibrarySource).toContain("最新版本");
    expect(sharedAssetLibrarySource).toContain("可见范围");
    expect(sharedAssetLibrarySource).toContain("资产 ID");
    expect(sharedAssetLibrarySource).toContain("来源 Run");
    expect(sharedAssetLibrarySource).toContain("打开资产");
    expect(sharedAssetLibrarySource).toContain("回到分析工作台继续");
    expect(sharedAssetLibrarySource).toContain("保存资产或发布 Skill 后会出现在这里");
    expect(assetContractsSource).toContain("v0.1-draft");
    expect(assetLibraryPageSource).toContain("sharedAnalysisAssets");
    expect(workspaceSource).toContain("mockAnalysisAssetLibraryService.saveAsset");
    expect(workspaceSource).toContain("assetSourceContext");
    expect(workspaceSource).toContain("flow.conversationId");
    expect(assetLibraryPageSource).toContain("reopenContext");
    expect(workspaceSource).toContain("lastSaveRequest");
    expect(assetLibrarySource).toContain("MOCK SAVE PAYLOAD");
    expect(assetContractsSource).not.toContain("analysis_task_channel_sales_share");
    expect(assetContractsSource).not.toContain("conv_analysis_channel_sales");
    expect(assetLibrarySource).toContain("保存请求预览");
  });

  test("treats Skill.md as an editable reusable method, not a normal report", () => {
    expect(assetLibrarySource).toContain("编辑 Skill");
    expect(assetLibrarySource).toContain("待确认");
    expect(assetLibrarySource).toContain("SkillDraftPreview");
    expect(assetLibrarySource).toContain("Skill 草稿编辑预览");
    expect(assetLibrarySource).toContain("引用资产");
    expect(assetLibrarySource).toContain("quick_candidate.sql");
    expect(assetLibrarySource).toContain("编辑草稿");
    expect(assetLibrarySource).toContain("保存草稿");
    expect(assetLibrarySource).toContain("草稿已保存，等待发布配置");
    expect(assetLibrarySource).toContain("复用准备");
    expect(assetLibrarySource).toContain("还需补齐确认");
    expect(assetLibrarySource).toContain("可作为分析资产复用");
    expect(assetLibrarySource).toContain("已确认适用场景");
    expect(assetLibrarySource).toContain("已确认销售额口径");
    expect(assetLibrarySource).toContain("已确认复用权限");
    expect(assetLibrarySource).toContain("引用资产齐全");
    expect(assetLibrarySource).toContain("模拟入库");
    expect(assetLibrarySource).toContain("已模拟作为可复用分析方法入库");
    expect(assetLibrarySource).toContain("复用元数据预览");
    expect(assetLibrarySource).toContain("REUSABLE METHOD PREVIEW");
    expect(assetLibrarySource).toContain("method_channel_sales_skill");
    expect(assetLibrarySource).toContain("run_mock_skill_publish");
    expect(assetLibrarySource).toContain("来源分析任务");
    expect(assetLibrarySource).toContain("来源 Run");
    expect(assetLibrarySource).toContain("等待审批 / mock");
    expect(assetLibrarySource).toContain("资产血缘");
    expect(assetLibrarySource).toContain("确认记录");
    expect(assetLibrarySource).toContain('aria-label="编辑 Skill 适用场景"');
    expect(assetLibrarySource).toContain('aria-label="编辑 Skill 需要确认"');
    expect(assetLibrarySource).toContain('aria-label="编辑 Skill 推荐步骤"');
    expect(workspaceSource).toContain("继续编辑 Skill.md");
    expect(workspaceSource).toContain("适用场景、口径和复用权限");
    expect(mockClientSource).toContain("整理适用场景");
    expect(mockClientSource).toContain("提取需要确认的业务口径");
    expect(mockClientSource).toContain("标注复用权限");
  });
});
