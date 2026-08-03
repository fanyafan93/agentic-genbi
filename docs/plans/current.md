# 当前任务

更新时间：2026-08-03 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 当前分支

- 分支：`Agentic-GenBI`。
- 工作区：有未提交改动，集中在分析工作台前端交互、Codex MCP 工具事件、interactive_report artifact、MCP 系统管理页、报告渲染和对应测试。

## 本轮完成

- 分析 Codex runtime 启动时改用 `load_runtime_codex_mcp_servers_from_env()`，只注册 enabled 且在 `GENBI_CODEX_ALLOWED_MCP_SERVERS` 里的 MCP server。
- 新增 `GENBI_CODEX_DEFAULT_TOOLS_ENABLED=false` 配置，并同时写入 Codex `thread_start(config=...)`、`config_overrides` 和 runtime `CODEX_HOME/config.toml`，用于关闭默认/内置工具入口。
- `.env.example` 增加分析 runtime 工具收紧配置说明；本地 `.env` 增加 `GENBI_CODEX_ALLOWED_MCP_SERVERS=BI_doris GenBI_report` 和 `GENBI_CODEX_DEFAULT_TOOLS_ENABLED=false`。
- MCP 管理页的 Doris 已知工具列表收敛为 GenBI 允许的 `mysql_query`，不再把 resource 类能力作为 GenBI 认可工具展示。
- 定位任务 `analysis_thread_8e9dd9a8a78a`：后端已创建 thread/turn，但没有保存 item 或 report，状态停在 `running`。
- 修复 SSE 被前端停止、切换任务或连接断开打断时的持久化问题：如果还没有 `turn/completed`，后端会补 `turn/completed(status=interrupted, error=client_disconnected)` 再保存。
- 已给历史任务 `analysis_thread_8e9dd9a8a78a` 补写 `interrupted` 终态事件，避免继续显示为运行中。
- 定位任务 `analysis_thread_422345f87652`：新建任务从 `draft_*` 收到真实 `analysis_thread_*` 后，前端把 `currentAnalysisTaskId` 改成真实 thread id，导致 `useFlow(threadKey)` 重新初始化并触发 `agent.cancel()`，SSE 被前端自己中止。
- 修复新建任务的 draft id 到真实 thread id 同步逻辑：真实 thread id 只用于更新左侧任务列表，不再切换当前 `useFlow` 的 key，避免 in-flight turn 被前端重挂载取消。
- 定位任务 `analysis_thread_f24cdc662d89`：Doris 工具已多次成功返回真实聚合数据，但最终停在 Codex `reasoning` 后没有收到最终回复或 report 工具调用，前端显示 `Analysis backend request timed out. Please retry.`。
- 前端新增 Codex `reasoning` 可见状态：收到 reasoning item 时在当前 assistant 节点显示 `思考中...`，避免长时间无正文时看起来像卡死。
- 分析 SSE 前端空闲超时默认从 95 秒调整为 300 秒；收到任意 SSE 事件仍会刷新计时。
- 使用 Chrome DevTools MCP 从上往下点击左侧任务，定位到历史任务点击会错误刷新 `updatedAt` 并把任务移动到列表顶部；旧 `running` 残留任务也会触发同样问题。
- 修复左侧任务列表同步条件：只有本页面正在执行或刚执行过的 flow、以及新建 `draft_*` 落地为真实 thread 时，才更新任务时间和排序；普通打开历史任务不再改写列表顺序。
- 定位任务 `analysis_thread_c033299e5733`：该任务绑定两个 interactive_report，点击历史任务时右侧先清空为无报告状态，再异步加载最新 report，造成柱/折线图看起来刷新两次。
- 修复右侧报告面板的任务绑定：只展示属于当前 thread 的 `flow.reportArtifact` 或 `openedReport`，历史任务加载 report 时显示稳定的“报告加载中”，并用请求序号避免快速切换任务后旧请求回写。
- 修复 `InteractiveReportPanel` 中 Puck document `content/zones` 的类型收窄，避免 `next build` 把稳定 ID 处理后的数组推断为 `unknown[]`。

## 已运行验证

- `npm.cmd test`：15 个前端测试文件、72 个测试通过。
- `python -m unittest backend.tests.test_codex_mcp_config backend.tests.test_codex_sdk_runner -v`：30 个后端测试通过。
- `python -m unittest backend.tests.test_analysis_api -v`：17 个后端测试通过。
- `npm.cmd test -- analysis-flow-streaming.test.ts analysis-backend-client.test.ts analysis-task-copy.test.ts`：3 个前端测试文件、45 个测试通过。
- `npm.cmd test -- analysis-backend-client.test.ts analysis-flow-streaming.test.ts`：2 个前端测试文件、31 个测试通过。
- `npm.cmd test -- analysis-task-copy.test.ts analysis-flow-streaming.test.ts analysis-backend-client.test.ts`：3 个前端测试文件、47 个测试通过。
- `npm.cmd test -- analysis-task-copy.test.ts interactive-report-empty-state.test.ts interactive-report-puck-ids.test.ts`：3 个前端测试文件、18 个测试通过。
- `npm.cmd run build`：前端生产构建通过。
- `docker compose up -d --force-recreate --no-deps backend`：后端容器已重建并启动。
- `GET http://127.0.0.1:8000/health`：返回 `{"status":"ok"}`。
- 容器内确认 `GENBI_CODEX_DEFAULT_TOOLS_ENABLED=false`，`GENBI_CODEX_ALLOWED_MCP_SERVERS=BI_doris GenBI_report`，runtime MCP server 解析结果为 `["BI_doris", "GenBI_report"]`。
- `GET http://127.0.0.1:8000/api/analysis/threads/analysis_thread_8e9dd9a8a78a`：确认 thread 和 turn 状态均为 `interrupted`。
- `docker compose up -d --force-recreate --no-deps frontend`：前端容器已重建并启动，Next.js 日志显示 `Ready`。
- `docker compose ps frontend`：确认 `agentic-genbi-frontend-1` 运行中并监听 `3000`。
- Chrome DevTools MCP 自动点击左侧前 12 个任务：修复前多个任务时间被刷新到当前时间并重排；修复后 `initialLabels` 与 `finalLabels` 一致，点击过程未再重排。
- Chrome DevTools MCP 复测任务 `c033299e`（页面显示 23:03）：右侧从“报告加载中”进入 `各渠道销售趋势折线图`，canvas 数量从 0 到 1 后保持稳定。

## 风险或未完成

- `openai-codex` 当前 Python SDK 暴露的是原生 config 透传，不提供已验证的按 MCP tool 粒度 allowlist 参数；本轮先做到分析 runtime 只注册允许的 MCP server，并关闭默认工具。
- 若直连的 `@benborla29/mcp-server-mysql` 自身仍向 Codex 暴露 resource/resource_template 能力，是否能被 Codex 原生配置逐项隐藏仍是待验证假设；本轮未新增 MCP 代理或自研工具调度层。
- 历史任务 `analysis_thread_422345f87652` 已经被旧前端状态切换中止，不会自动恢复；需要用新任务验证修复后的链路。
- 历史任务 `analysis_thread_f24cdc662d89` 已经因前端超时断流被标记为 `interrupted`，不会自动恢复；新超时配置只影响后续任务。
- 工作区存在本轮之前的未提交改动，本轮未回滚。

## 下一步

1. 用一个新分析 turn 验证 `draft_* -> analysis_thread_*` 不再触发前端自中止，且长 reasoning 时会显示 `思考中...`。
2. 验证 Codex 是否只看到 BI_doris 与 GenBI_report 两个 server，并观察 `commandExecution` / `collabAgentToolCall` 是否消失。
3. 再回到右侧 ReportArtifact 通用协议和 GenBI_report 工具完善。
