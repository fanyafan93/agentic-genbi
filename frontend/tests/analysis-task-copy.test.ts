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

const interactiveReportSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/InteractiveReportPanel.tsx"),
  "utf8",
);

const systemMcpPageSource = readFileSync(
  resolve(process.cwd(), "src/modules/analysis/components/SystemMcpPage.tsx"),
  "utf8",
);

describe("analysis task product language", () => {
  test("frames the primary workspace as a unified analysis workspace", () => {
    expect(workspaceSource).toContain('label: "分析工作台"');
    expect(workspaceSource).toContain('label: "报表中心"');
    expect(workspaceSource).toContain('label: "业务语义库"');
    expect(workspaceSource).toContain("ANALYSIS WORKSPACE");
    expect(workspaceSource).toContain("<h2>分析工作台</h2>");
    expect(workspaceSource).toContain('placeholder="搜索分析任务"');
    expect(workspaceSource).toContain("+ 新建分析");
    expect(workspaceSource).toContain('aria-label="分析任务工作区"');
    expect(workspaceSource).toContain(">分析工作台</button>");
    expect(workspaceSource).toContain(">分析结果</button>");
    expect(workspaceSource).toContain("新分析");
    expect(workspaceSource).toContain("InteractiveReportPanel");
    expect(workspaceSource).toContain("SystemMcpPage");

    expect(workspaceSource).not.toContain('label: "会话"');
    expect(workspaceSource).not.toContain('label: "KnowledgeBaseLegacy"');
    expect(workspaceSource).not.toContain('label: "Agent 中心"');
    expect(workspaceSource).not.toContain("KnowledgeBaseLegacy");
    expect(workspaceSource).not.toContain("CONVERSATIONS");
    expect(workspaceSource).not.toContain("+ 新建会话");
    expect(suggestionsSource).not.toContain("开始一个会话");
  });

  test("keeps the current interactive result in the analysis workspace and moves reusable items to my analysis", () => {
    expect(workspaceSource).toContain("InteractiveReportPanel");
    expect(workspaceSource).toContain("MyAnalysisPage");
    expect(workspaceSource).not.toContain("AnalysisAssetLibraryPage");
    expect(interactiveReportSource).toContain('aria-label="分析结果"');
    expect(interactiveReportSource).toContain("@puckeditor/core");
    expect(interactiveReportSource).toContain("AgGridReact");
    expect(interactiveReportSource).toContain("EChartRenderer");
    expect(workspaceSource).not.toContain("loadSavedInteractiveReports");
    expect(workspaceSource).not.toContain("saveInteractiveReport(");
    expect(workspaceSource).toContain("saveInteractiveReportToBackend");
  });

  test("adds a business semantic library for structured knowledge and semantics", () => {
    expect(workspaceSource).toContain("BusinessSemanticLibrary");
    expect(workspaceSource).toContain("结构化知识");
    expect(workspaceSource).toContain("系统里实际存在什么");
    expect(workspaceSource).toContain("语义");
    expect(workspaceSource).toContain("业务解释和使用规则");
    expect(workspaceSource).toContain("FineReport");
    expect(workspaceSource).toContain("报表画像");
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

  test("keeps the lower-level interaction event generic for shared threads", () => {
    expect(agentTypesSource).not.toContain('"conversation-init"');
    expect(agentTypesSource).toContain("threadId?: string | null");
    expect(agentTypesSource).not.toContain("conversationId?: string | null");
    expect(agentTypesSource).toContain("turnId?: string");
    expect(agentTypesSource).not.toContain('"analysis-task-init"');
  });

  test("adds a system MCP server management page", () => {
    expect(systemMcpPageSource).toContain("MCP Servers 管理");
    expect(systemMcpPageSource).toContain("listBackendMcpServers");
    expect(systemMcpPageSource).toContain("testBackendMcpServer");
    expect(systemMcpPageSource).toContain("测试连接");
    expect(systemMcpPageSource).toContain("server.approval");
    expect(globalStylesSource).toContain(".system-mcp-page");
    expect(globalStylesSource).toContain(".mcp-tool-table");
  });

  test("keeps analysis task inputs free of removed mode and data-egress controls", () => {
    expect(agentTypesSource).not.toContain("AnalysisMode");
    expect(agentTypesSource).not.toContain("analysisMode");
    expect(agentTypesSource).not.toContain("dataEgressAuthorized");
    expect(workspaceSource).toContain("AnalysisTaskThread");
    expect(analysisTaskThreadSource).not.toContain("AnalysisModeToggle");
    expect(analysisTaskThreadSource).not.toContain("data-egress-toggle");
    expect(agentClientIndexSource).not.toContain("MockAgentClient");
  });

  test("can switch analysis tasks from mock client to the real backend turn API", () => {
    expect(agentClientIndexSource).toContain("BackendAnalysisAgentClient");
    expect(agentClientIndexSource).toContain("shouldUseBackendAnalysisClient");
    expect(backendClientSource).toContain("NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME");
    expect(backendClientSource).toContain("NEXT_PUBLIC_GENBI_API_BASE_URL");
    expect(backendClientSource).toContain("createBackendAnalysisThread");
    expect(backendClientSource).toContain("/api/analysis/threads");
    expect(backendClientSource).toContain("/api/analysis/threads/turns/stream");
    expect(backendClientSource).toContain("/turns/stream");
    expect(backendClientSource).toContain("item/completed");
    expect(backendClientSource).toContain("item/agentMessage/delta");
    expect(backendClientSource).toContain("genbi/artifact/created");
    expect(backendClientSource).toContain("genbi/artifact/updated");
    expect(backendClientSource).toContain("mapBackendEvents");
    expect(backendClientSource).toContain("event.payload.thread_id");
    expect(backendClientSource).toContain("listBackendAnalysisThreads");
    expect(backendClientSource).toContain("deleteBackendAnalysisThread");
    expect(workspaceSource).toContain("flow.start(content, thread.id)");
    expect(workspaceSource).toContain("flow.start(question, thread.id)");
    expect(workspaceSource).toContain("createWaitingThread");
    expect(workspaceSource).toContain("const isWaitingForFirstQuestion = Boolean(");
    expect(workspaceSource).toContain('currentAnalysisThread?.status === "waiting_for_question"');
    expect(workspaceSource).toContain("markCurrentThreadAsStarted");
    expect(workspaceSource).toContain("isNewTask={isWaitingForFirstQuestion}");
    expect(workspaceSource).not.toContain("draft_");
    expect(workspaceSource).not.toContain("const analysisTaskGroups = [");
    expect(workspaceSource).toContain("暂无历史任务");
    expect(workspaceSource).toContain("多选删除");
    expect(workspaceSource).toContain("确认删除选中的");
  });

  test("keeps the analysis task thread presentation in its own component", () => {
    expect(workspaceSource).toContain("AnalysisTaskThread");
    expect(analysisTaskThreadSource).toContain("FlowNodeView");
    expect(analysisTaskThreadSource).toContain("Suggestions");
    expect(analysisTaskThreadSource).toContain("FlowComposer");
    expect(analysisTaskThreadSource).toContain("threadScrollRef");
    expect(analysisTaskThreadSource).toContain("输入待解决的业务问题，按回车发送");
    expect(analysisTaskThreadSource).toContain("有什么问题，或想继续分析什么？");
    expect(analysisTaskThreadSource).not.toContain("draft_");
    expect(workspaceSource).not.toContain("threadScrollRef");
    expect(workspaceSource).not.toContain("lastNodeCountRef");
  });

  test("renders long agent analysis answers with thread-level scrolling", () => {
    expect(flowNodeViewSource).toContain('import ReactMarkdown from "react-markdown"');
    expect(flowNodeViewSource).toContain('import remarkGfm from "remark-gfm"');
    expect(flowNodeViewSource).toContain('className="message-body-markdown flow-content"');
    expect(globalStylesSource).toContain(".flow-agent .flow-content");
    expect(globalStylesSource).toContain(".flow-agent .flow-content { overflow: visible; padding-right: 0; }");
    expect(globalStylesSource).not.toContain("max-height: min(54vh, 680px)");
  });

  test("keeps generated files and Skill markdown as reusable analysis materials", () => {
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
  });

  test("lets saved interactive results reopen the analysis workspace", () => {
    expect(workspaceSource).toContain("handleOpenReport");
    expect(workspaceSource).toContain("openedReportId");
    expect(workspaceSource).toContain("openedReportBelongsToCurrentTask");
    expect(workspaceSource).toContain("currentPanelReport");
    expect(workspaceSource).toContain("const detail = await getBackendAnalysisThread(sourceThreadId)");
    expect(workspaceSource).toContain("setInitialFlowMessages(flowNodesFromBackendThread(detail))");
    expect(workspaceSource).toContain("threads.map((thread) => (thread.id === detail.thread.id ? detail.thread : thread))");
    expect(workspaceSource).toContain("orderAnalysisThreads([detail.thread, ...threads])");
    expect(workspaceSource).toContain("loading={currentPanelReportLoading}");
    expect(workspaceSource).not.toContain("onListVersions=");
    expect(workspaceSource).not.toContain("onLoadVersion=");
    expect(interactiveReportSource).toContain("onSaveReport");
    expect(interactiveReportSource).not.toContain("历史版本");
    expect(interactiveReportSource).not.toContain("新的报告版本");
    expect(interactiveReportSource).not.toContain("INTERACTIVE RESULT · v");
  });

  test("creates a real backend analysis thread from a saved report and carries its report snapshot", () => {
    expect(workspaceSource).toContain("handleCreateAnalysisFromReport");
    expect(workspaceSource).toContain("createAnalysisThreadFromReportBackend");
    expect(workspaceSource).toContain("setCurrentAnalysisTaskId(created.thread.id)");
    expect(workspaceSource).toContain("setOpenedReportThreadId(created.thread.id)");
    expect(workspaceSource).toContain("savedReportFromThreadMetadata");
    expect(workspaceSource).not.toContain("draftReportIds");
    expect(workspaceSource).not.toContain("draft_report_");
    expect(workspaceSource).not.toContain("reportDraftNodes");
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
    expect(assetContractsSource).toContain("sourceCodexTurnId");
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
    expect(sharedAssetLibrarySource).toContain("Codex Turn");
    expect(sharedAssetLibrarySource).toContain("打开资产");
    expect(sharedAssetLibrarySource).toContain("回到分析工作台继续");
    expect(sharedAssetLibrarySource).toContain("保存资产或发布 Skill 后会出现在这里");
    expect(assetContractsSource).toContain("v0.1-draft");
    expect(assetLibraryPageSource).toContain("sharedAnalysisAssets");
    expect(assetLibraryPageSource).toContain("reopenContext");
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
    expect(assetLibrarySource).toContain("candidate.sql");
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
    expect(assetLibrarySource).toContain("turn_mock_skill_publish");
    expect(assetLibrarySource).toContain("来源分析任务");
    expect(assetLibrarySource).toContain("Codex Turn");
    expect(assetLibrarySource).toContain("等待审批 / mock");
    expect(assetLibrarySource).toContain("资产血缘");
    expect(assetLibrarySource).toContain("确认记录");
    expect(assetLibrarySource).toContain('aria-label="编辑 Skill 适用场景"');
    expect(assetLibrarySource).toContain('aria-label="编辑 Skill 需要确认"');
    expect(assetLibrarySource).toContain('aria-label="编辑 Skill 推荐步骤"');
  });

  test("keeps the history list stable when opening an existing task", () => {
    expect(workspaceSource).toContain("}, []);");
    expect(workspaceSource).toContain("if (!flow.threadId || !selectedAnalysisTask) return;");
    expect(workspaceSource).toContain("threadId !== currentAnalysisTaskId");
    expect(workspaceSource).toContain("当前任务正在分析，停止回答后再切换任务。");
    expect(workspaceSource).toContain("const shouldSyncThread = flow.running || hadLocalRunningFlow;");
    expect(workspaceSource).toContain("if (!shouldSyncThread) return threads;");
    expect(workspaceSource).not.toContain("setCurrentAnalysisTaskId(threadId);");
    expect(workspaceSource).not.toContain("}, [flow.threadId]);");
  });
});
