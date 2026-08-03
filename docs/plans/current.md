# 当前任务

更新时间：2026-08-03 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 当前分支

- 分支：`Agentic-GenBI`。
- 工作区：有未提交改动，集中在分析工作台前端交互、后端 Thread/Turn 列表、Codex MCP 工具事件、`interactive_report` artifact、MCP 系统管理页和对应测试。

## 本轮完成

- 左侧分析列表读取真实 `/api/analysis/threads`，不再使用硬编码示例任务。
- 左侧任务列表支持独立滚动、多选删除和二次确认删除；后端支持删除真实 analysis thread。
- 新建分析或点击建议问题后，前端会立刻展示用户问题和“正在思考...”，不再在第一条 SSE 回来前闪回建议页。
- 线程标题左上角保留珊瑚色短 ID，便于调试定位具体任务；用户问题气泡不再显示额外短 ID。
- 输入框交互改为 Enter 提交、Shift+Enter 换行。
- 工具调用活动移除状态点；连续相同工具调用会合并展示。
- 非 SQL MCP 工具调用也会显示可展开详情。
- Agent 回复正文不再使用内嵌滚动条，统一跟随线程主滚动区域。
- 流式文本显示层会清理 Unicode replacement character，减少乱码直接出现在 Markdown 表格和正文中。
- 右侧 interactive report 图表渲染支持从 rows 自动推断类目列和数值列，并将金额/百分比字符串转成数值，避免字段名不完全一致时柱状图空白。
- 新增 `GenBI_report` MCP server，当前先暴露 `create_interactive_report`。
- `create_interactive_report` 不再默认或强制绑定 `dm.dm_channel_mtsg_sale_total`；`sourceTable` 仅作为可选证据来源说明，另支持 `sourceDescription`。
- `create_interactive_report` 会将已查证 rows 编译成最小 `interactive_report` artifact。
- Codex MCP tool call 完成事件会保留 `mcp_result`；后端识别 `GenBI_report / create_interactive_report` 后保存报告版本，并追加 `genbi/artifact/updated` SSE 事件。
- interactive report 版本存储新增 `datasets`；右侧 Puck 渲染时 ECharts / AG Grid 从 `report.datasets[datasetId].rows` 读取真实行数据。
- 当 Codex 流正常结束但没有发出 `turn/completed` 时，后端会追加 `turn/completed(status=failed)`，避免任务永久停留在 running。
- 新增系统 MCP 管理页：点击左侧“系统”后可查看 MCP server 列表、展开工具、查看状态、权限、approval 标记、配置环境变量名，并触发连接测试。
- 新增 `/api/system/mcp/servers` 和 `/api/system/mcp/servers/{server_name}/test`，用于前端读取 MCP 配置状态和测试可用性。
- `GenBI_report` 在 GenBI MCP 配置状态中标记为内部受信任工具：`permission=artifact.write`、`approval=trusted`、`trusted=true`。
- MiniMax Codex adapter 已给 `codex-auto-review` 配置模型别名：审核请求里的 `model=codex-auto-review` 会改写为 `GENBI_CODEX_AUTO_REVIEW_MODEL`，未配置时回落到 `GENBI_ANALYSIS_MODEL` / `MINIMAX_MODEL` / `MiniMax-M3`。
- MiniMax Codex adapter 已支持把模型返回的唯一裸工具名映射回 MCP namespace。例如 `create_interactive_report` 会映射为 `mcp__GenBI_report__ / create_interactive_report`，避免 Codex 报 `unsupported call`。
- Codex 分析系统提示已恢复为中文，并明确要求：真实业务数据先查证，需要右侧报告时先查数据再调用 `GenBI_report.create_interactive_report`。
- 修复旧 Run 字段残留导致的报告保存失败：旧库中的 `analysis_reports.source_run_id` 和 `analysis_report_versions.source_run_id` 会自动改为 nullable，避免新架构保存 `interactive_report` 时触发 NOT NULL 异常。
- 修复 `interactive_report` artifact 事件识别过窄的问题：当 Codex 的 `mcpToolCall` item 已包含 `interactive_report` payload，但没有填充 `mcp_server/mcp_tool` 字段时，后端也会追加 `genbi/artifact/updated` SSE 事件。
- 报告列表接口支持按 `source_thread_id` 查询；前端点击历史任务时会自动加载该 thread 绑定的 report 到右侧面板。
- 新建 analysis thread 使用 `analysis_thread_*`；旧 `conv_analysis_*` 作为历史 thread ID 继续可读，但前端 UI 和新 API 响应不再使用旧命名。
- 已将历史报告 `report_ec4ec8ff3226` 绑定回历史 thread `conv_analysis_74a99bb7d7c5` / turn `analysis_turn_7b09a80f037f`，owner 调整为 `local-user`。

## 已运行验证

- `python -m unittest backend.tests.test_minimax_codex_adapter backend.tests.test_codex_sdk_runner backend.tests.test_genbi_report_mcp_server -v`：21 个测试通过。
- `python -m unittest backend.tests.test_interactive_report_api backend.tests.test_analysis_api -v`：18 个测试通过。
- `python -m unittest backend.tests.test_analysis_api -v`：16 个测试通过。
- `npm.cmd test -- analysis-backend-client.test.ts interactive-report-api-client.test.ts`：2 个测试文件、23 个测试通过。
- `npm.cmd test -- analysis-backend-client.test.ts analysis-task-copy.test.ts`：2 个测试文件、35 个测试通过。
- `npm.cmd test -- chart-adapter.test.ts interactive-report-api-client.test.ts`：2 个测试文件、5 个测试通过。
- `rg -n "历史会话|来源 Conversation|删除选中的 .*会话|暂无历史会话|正在加载历史会话|conversation-init|conversationId\\?:" frontend/src/modules/analysis frontend/tests docs/plans/current.md docs/product docs/architecture`：仅剩测试中的反向断言。
- `GET http://127.0.0.1:8000/health`：返回 `{"status":"ok"}`。
- `GET http://127.0.0.1:8000/api/system/mcp/servers`：返回 `BI_doris` 为 `ready`，`GenBI_report` 为 `trusted`。
- `GET http://127.0.0.1:8000/api/analysis/reports?source_thread_id=conv_analysis_74a99bb7d7c5`：返回 `report_ec4ec8ff3226`。
- `docker compose restart backend`：backend 已重启，adapter 修复已生效。
- `docker compose restart backend frontend`：backend 和 frontend 已重启，历史任务加载 report 的逻辑已生效。
- `docker compose restart frontend`：frontend 已重启，图表渲染修复已生效。
- 容器内查询 `information_schema.columns` 确认 `analysis_reports.source_run_id` 和 `analysis_report_versions.source_run_id` 的 `is_nullable=YES`。

## 风险或未完成

- `GenBI_report.update_interactive_report` 和 `GenBI_report.get_interactive_report` 尚未实现。
- 系统 MCP 管理页的打开/关闭开关当前是前端本地状态，不会改写 `.env` 或重启 Codex / backend。
- 任务 `b4694b03` 中 `BI_doris / mysql_query` 已成功调用过；失败点是 `GenBI_report.create_interactive_report` 曾以裸工具名触发 `unsupported call`，本轮已补 adapter 映射，但该历史任务不会自动重跑。
- 任务 `f3b7044a` 中 `GenBI_report` 已走到报告保存阶段；前端显示 network error 的直接原因是旧数据库字段 `analysis_reports.source_run_id` 仍为 NOT NULL，本轮已修复 schema，但该历史任务不会自动重跑。
- 任务 `bee2fa08` 中 `GenBI_report` 已走到报告版本保存阶段；前端显示 network error 的直接原因是旧数据库字段 `analysis_report_versions.source_run_id` 仍为 NOT NULL，本轮已修复 schema，但该历史任务不会自动重跑。
- 任务 `74a99bb7` 已完成，且 projection 中已经包含 `interactive_report` payload；右侧未渲染的原因是该 `mcpToolCall` 没有 `mcp_server/mcp_tool` 字段，旧逻辑没有发出 `genbi/artifact/updated`。本轮已修复新任务的事件识别，并将该历史报告绑定回 thread，点击该任务时应能从后端加载右侧报告。
- 尚未用浏览器发起新问题验证完整链路：`BI_doris.mysql_query -> GenBI_report.create_interactive_report -> genbi/artifact/updated -> 右侧 Puck 渲染`。

## 下一步

1. 用一个新任务验证完整报告生成链路。
2. 若新任务仍失败，抓取 adapter 入站/出站工具事件，确认模型实际 emit 的 function call 格式。
3. 跑通 create 链路后，再做 `update_interactive_report` 和 `get_interactive_report`。
