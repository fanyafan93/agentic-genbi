# 当前任务

更新时间：2026-08-04 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 当前分支

- 分支：`feature/report-artifact-design`
- 工作区：有未提交改动，包含 FineReport 报表画像切片、报告产物协议、多用户身份隔离改造及相关验证。

## 本轮完成

- 报表中心入口已从“我的分析”收敛为“报表中心”，只展示“我的报表”和“分享给我”。
- 报表中心卡片保留主标题和四个操作：`预览`、`删除`、`回到原任务`、`新建分析`。
- `预览` 使用真实 `InteractiveReportPanel` 只读渲染，不再用伪缩略图。
- 右侧 Report 面板保存成功后显示“已保存到报表中心”。
- 后端新增 `POST /api/analysis/threads`，用于创建真实空分析 Thread，状态为 `waiting_for_question`。
- 后端新增 `POST /api/analysis/reports/{report_id}/analysis-thread`，用于从已保存报表创建新的真实分析 Thread。
- 从报表创建的新 Thread 会在 metadata 中记录 `source_report_id`、`initial_report_version` 和 `initial_report_artifact`，用于恢复右侧报表快照。
- 前端移除分析工作台主路径里的 `draft_*` / `draft_report_*` 特判；未提问任务也是真实 `analysis_thread_*`。
- 报表中心点击“新建分析”后，已验证会创建真实 Thread，左侧显示“待提问”，中间只显示等待提问空态，右侧带入原报表。
- 分析工作台点击“新建分析”创建真实空 Thread 后，中间面板继续显示建议问题页；用户输入首问或点击建议后，才在该 Thread 内开始分析并更新任务标题。
- 修复空 Thread 首问错误创建第二个 Thread 的问题：前端 backend client 现在只要有 `threadId` 就调用 `/api/analysis/threads/{thread_id}/turns/stream`，不再因 `turn_kind=start` 走新建 Thread 入口。
- 报表中心点击“回到原任务”现在会加载来源 Thread 的历史 turns/items，恢复原分析过程；不再只切换 thread id 后显示“等待提问”空态。
- 回到原任务加载 Thread 详情时只原地替换左侧列表中的对应任务，不再把旧时间任务强行移动到顶部。
- `useFlow` 重置逻辑改为跟随 `threadKey`，避免因为空数组引用变化导致反复重置或闪烁。
- 后端创建空分析 Thread 时会复用同用户、同标题、同来源报表且尚未提问的 `waiting_for_question` Thread，避免重复点击或验证脚本堆出一批“等待提问”任务。
- 已清理本轮验证产生的 3 条空 `waiting_for_question` Thread；接口检查确认当前列表没有无问题的空等待任务残留。
- 修复 `backend/tests/test_analysis_api.py` 的编码问题，并补充空 Thread 复用测试。
- 修复历史任务点击后中间面板显示“等待提问”的问题：`useFlow` 现在会在非运行状态下接收异步加载回来的历史节点。
- 分析任务列表过滤旧 `draft_*` 任务，避免 legacy 草稿继续混入真实 Thread 列表。
- 诊断 `analysis_thread_c41e0fb05b8c`：数据查询已执行，但 `GenBI_report` 多次收到被 Codex/MCP 适配层包成 `{item: ...}` 或 PowerShell 对象字符串的 rows/specs，导致校验认为数据集为空，最终没有 report artifact 入库。
- `GenBI_report` 工具入口增加参数归一化：递归展开单字段 `item` 包装，解析 `@{field=value; ...}` 形态的行数据，恢复被包装的 `rows`、`series`、`columns`、`content`、`filterBindings`，再进入 `create_interactive_report` / `validate_interactive_report` 校验。
- `MiniMax Codex Adapter` 的上游 SSE 读取超时不再抛出 ASGI 异常，改为返回 `response.failed` 事件，避免后端日志刷 traceback 且前端长期卡住。
- FineReport 结构化知识入口从“报表解析”改名为“报表画像”。
- FineReport 默认资源路径改为 `资源库/finereport/报表画像`。
- Docker Compose 中 backend 的 `GENBI_FINEREPORT_ROOT` 默认值同步改为 `/app/资源库/finereport/报表画像`，避免容器仍读取旧 `/app/资源库/finereport/解析`。
- FineReport 后端仓库支持递归读取无“解析”字样的画像 JSON 文件，并继续兼容旧 `.原始解析.json` 和三段分片文件。
- FineReport 画像详情新增 `reportUsage`，列表 counts 新增 `usageUsers` 和 `totalUsageCount`。
- 前端 FineReport 画像页面新增“使用情况”页签，渲染 `report_usage.users` 和总使用次数。
- FineReport 使用统计合并脚本已过滤用户名原文或规范化用户名中包含 `超管`、`admin` 的记录，避免系统账号污染画像使用情况。
- 已使用 `资源库/finereport/finereport近90天执行记录汇总.xlsx` 重新生成并覆盖 `资源库/finereport/报表画像` 下 692 份画像 JSON。
- **多用户身份隔离（核心 P0）**：以 Auth.js session cookie 为后端唯一身份来源，前端不再发送 `ownerId` / `user_id`。
  - 新增 `backend/api/principal.py`：从 `next-auth.session-token` cookie 解析 Postgres `Session` 表，构造 `Principal(user_id, tenant_id, role, session_id)`，未登录返回 401。
  - 所有 Thread / Turn / Asset / InteractiveReport 接口接 `Depends(require_principal)`；删除、重命名、分享、保存前自动按 `principal.user_id` 校验所有权；他用户资源 404（不泄露存在性）。
  - `InteractiveReportBody` / `InteractiveReportRenameBody` / `ReportShareBody` 上的 `ownerId`、`userId` 字段已标注后端覆盖；前端不再发送。
  - `ThreadStore` 与 Postgres 链路上写入 `tenant_id`，列表接口按 tenant + user 过滤。
  - 新增 `backend/tests/test_principal_isolation.py`：覆盖未登录 401、跨用户读/删/分享 404、伪造 `ownerId` 被覆盖、`role=admin` 不可由前端声称、跨租户不可读。
  - 前端 `AnalysisWorkspace.tsx` 删除 `const isAdmin = true`，改读 `session.user.role`；不再发送 `ownerId`；fetch 默认 `credentials: 'include'` 以带上 session cookie。
  - 单元测试通过 `backend/tests/auth_test_client.py` 的 `X-Genbi-Test-Principal` 旁路头走 dev-only 注入；生产构建默认拒绝该头。
- **`useFlow` 拆分 + 等待创建（核心 P0）**：把"加载历史"和"控制当前执行"两件事从一个 hook 中拆开。
  - 新增 `useTaskList()`：左栏任务列表，只读、独立于当前活动 task。
  - 新增 `useTaskDetail(taskId)`：读取 task 历史 turns + items，用于水合渲染，**不会取消** in-flight 流。
  - 新增 `useTaskReport(taskId)`：读取 task 下的 saved reports，独立 hook。
  - 新增 `useTurnExecution()`：唯一持有 SSE AbortController 的 hook；`start`/`send`/`reply`/`stop` 显式接收 `taskId`，并发取消只影响匹配 taskId 的流。
  - 新增 `useTaskCreation()`：等待创建状态，POST `/api/analysis/tasks` 期间 `creating=true`，返回服务端真实 taskId。
  - `useFlow(threadKey, initial)` 保留为薄 facade，仅做历史水合；它的 reset 路径不再"模块级"取消任何请求。
  - 工作区从"`useFlow` 一把抓"改为组合这四个 hook，删除 `hadLocalRunningFlowRef` 这种把列表和执行耦在一起的 ref；`createWaitingThread` 内部调用改为 `useTaskCreation.createTask`。
  - 旧全局 `let client: AgentClient | null` 单例和模块级 `cancelled` 变量经核查已经不存在（getAgentClient() 每次返回新实例，组件 unmount 的 `cancelled` 标志仅用于 effect race）。
  - **draft_*** 假 ID 经核查也未在主路径出现：所有创建都走后端 `POST /api/analysis/threads` 或新的 `POST /api/analysis/tasks`，服务端返回真实 `analysis_thread_*` ID。点击"新建分析"期间 `disabled={taskCreation.creating}`，按钮文案切到"正在创建…"，**不暴露任何本地 taskId**。
  - 后端新增 `POST /api/analysis/tasks` 端点（语义"任务"），与 `/api/analysis/threads` 等价行为但路径表达更明确；返回 `{ "task": { id, title, status: "waiting_for_question", ... } }`。
- **删除业务兜底（核心 P0）**：7 项自动修正、隐形降级、伪造数据全部下架。
  - **1. 删默认业务问题**：`getInputQuestion` 移除 `"分析一下渠道销售占比"` 兜底；`send` 路径遇到空 `question` 立即 `yield { type: "error", message: "问题不能为空…" }` 后 `done`，**不**调用 fetch、不进入 SSE 循环。`AnalysisWorkspace.handleSendMessage` 在工作台入口也加 `if (!trimmed)` 短路并显示 `请输入业务问题后再开始分析`。新测试 `analysis-empty-input.test.ts` 锁住"空问题 = 错误事件 + fetch 不被调用"契约。
  - **2. 删 Report Compiler 兜底**：删除 `backend/analysis/report_compiler.py`（`compile_interactive_report` 全文件下线）。生产链 `_interactive_report_artifact_event` 不再调用 compile：当 agent 没在 `mcp_result` 返回 artifact 时，**显式发 `genbi/artifact/failed`**（`status=missing_artifact`），不再偷偷造一份 channel-sales 报告。
  - **3. 拒绝预修复**：`normalize_report_artifact` 退化为 `return dict(artifact)`（仅复制、不改字段），删除所有 `_best_dimension_field` / `_best_measure_field` / 自动填空 column 的代码路径。**校验失败**直接走 `genbi/artifact/failed`，**不**改写后再存入；`validate_report_artifact` 之前调用在 `normalize` 之前；模型错了就是错了，让模型重做。新测试 `test_artifact_strict_save_contract.py` 锁住"invalid → failed + 存盘未发生"。
  - **4. 删 pending 来源 ID + 改 MCP Schema**：`genbi_report_server` 的 `create_interactive_report` / `validate_interactive_report` schema 现在只接受 `artifact` 字段，**强制拒绝** agent 写入 `threadId / turnId / codex_thread_id / codex_turn_id / codex_item_id / source`（返回 `forbidden_field`）。GenBI Runtime 在 `_interactive_report_artifact_event` 中**唯一**负责注入 `source.threadId/turnId`，agent 再也碰不到 `codex_*_pending`。
  - **5. 删本地 Store 降级**：`create_app` 启动时**总是**走 `PostgresKnowledgeStore / PostgresThreadStore / PostgresAnalysisAssetStore / PostgresInteractiveReportStore`；`InteractiveReportStore` (in-memory) 只在测试中通过 `build_test_app(thread_store="auto")` 显式注入。`/health` 端点主动探测每个 Store 的 `list_*`，任一失败返回 `503 unhealthy` 并按 store 名报告。`test_health_endpoint.py` 锁住"任一 store 不可用 = 503 unhealthy"。
  - **6. 删乱码运行时修复**：删除 `_repair_text_encoding` / `_is_unreadable_legacy_text` / `_looks_more_readable` / `_cjk_count` / `_mojibake_marker_count` 全部函数。`_with_latest_thread_question` / `_repair_thread_detail_text` 不再做 latin1-redecode / 问号比例猜测，文本按存储原样返回。前端 `cleanDisplayText` 改为**不** strip `\uFFFD`、**只** `console.warn` 提示编码异常；UI 原样显示替代字符，让操作员能在 UI 里看到问题。`test_text_encoding_contract.py` 锁住 "mangled bytes round-trip verbatim"。
  - **7. 禁止吞掉报表保存失败**：`_interactive_report_artifact_event` 现在按以下契约：
    - 校验失败 → `genbi/artifact/failed` `status=validation_failed`，含 `errors[]`。
    - Store 不可用 (`interactive_report_store is None`) → `genbi/artifact/failed` `status=save_unavailable`。
    - `InteractiveReportVersionConflict` → `genbi/artifact/failed` `status=version_conflict`。
    - `ValueError` → `genbi/artifact/failed` `status=save_failed`，`detail` 带原始错误。
    - 保存成功 → `genbi/artifact/created`（不再是 `updated`），payload 包含 server-injected `source.threadId/turnId` 和 `version`。
    前端 `backendClient.ts` 把 `genbi/artifact/created` 视为有效 artifact，把 `genbi/artifact/failed` 映射为带 `errors[]` 的 `error` 事件；不再吞掉 version 为 None 的成功事件。
  - **测试夹具入口**：`backend/tests/auth_test_client.build_test_app` 自动注入所有 in-memory stores（`"auto"` sentinel），测试代码仍可单点显式覆盖；新增 `backend/tests/test_artifact_strict_save_contract.py` / `test_health_endpoint.py` / `test_text_encoding_contract.py` 锁住 3、5、6、7 契约。前端 `frontend/tests/analysis-empty-input.test.ts` 锁住 1 契约。

## 已运行验证

- `python -m unittest backend.tests.test_principal_isolation -v`：6 个拒绝用例全部通过，覆盖未登录 401、跨用户隔离、伪造 ownerId/admin role。
- `python -m unittest backend.tests.test_analysis_api -v`：24 个 API 测试通过（已切换到 `auth_test_client`，每个调用自动带 dev principal）。
- `python -m unittest backend.tests.test_interactive_report_api -v`：3 个测试通过。
- `python -m unittest discover backend/tests -v`：所有 110 个后端测试通过。
- `npx.cmd vitest run`：前端 18 个测试文件、93 个测试全部通过，包括修改后的 `interactive-report-api-client.test.ts` 与 `analysis-backend-client.test.ts`。
- `npx.cmd tsc --noEmit`：前端 TypeScript 校验通过。
- `python -m unittest backend.tests.test_analysis_api -v`：23 个后端 API 测试通过。
- `python -m unittest backend.tests.test_analysis_api -v`：24 个后端 API 测试通过。
- `python -m unittest backend.tests.test_genbi_report_mcp_server -v`：9 个 GenBI_report MCP 测试通过。
- `python -m unittest backend.tests.test_minimax_codex_adapter -v`：10 个 MiniMax Codex Adapter 测试通过。
- `python -m unittest backend.tests.test_analysis_api -v`：24 个后端 API 测试通过。
- `python -m unittest backend.tests.test_thread_store -v`：6 个 ThreadStore 测试通过。
- `python -m unittest backend.tests.test_finereport_reports backend.tests.test_env_config -v`：9 个后端 FineReport/env 测试通过。
- `npm.cmd test -- interactive-report-api-client.test.ts analysis-task-copy.test.ts report-center-card-actions.test.tsx`：25 个前端测试通过。
- `npm.cmd test -- analysis-flow-streaming.test.ts`：13 个前端 flow 测试通过。
- `npm.cmd test -- analysis-task-copy.test.ts analysis-flow-streaming.test.ts`：30 个前端测试通过。
- `npm.cmd test -- analysis-task-copy.test.ts report-center-card-actions.test.tsx`：19 个前端测试通过。
- `npm.cmd test -- analysis-backend-client.test.ts analysis-task-copy.test.ts`：39 个前端测试通过。
- `npm.cmd test -- finereport-report-browser.test.tsx analysis-task-copy.test.ts`：19 个前端测试通过。
- `npx.cmd tsc --noEmit`：前端 TypeScript 校验通过。
- `FineReportReportRepository()` 默认目录实测读取 `692` 张报表画像，并抽查到 `report_usage` 非空画像可返回 `usageUsers=10`、`totalUsageCount=35`。
- backend 容器内实测 `GENBI_FINEREPORT_ROOT=/app/资源库/finereport/报表画像`，目录存在，`FineReportReportRepository().list_reports()` 返回 `692` 张。
- `GET /api/business-semantics/finereport/reports`：返回 `692` 张报表画像。
- `docker compose up -d --build --force-recreate frontend`：frontend/backend 镜像重建并启动成功。
- `docker compose up -d --build --force-recreate backend`：backend 镜像重建并启动成功。
- `docker compose up -d --build --force-recreate backend frontend`：backend/frontend 镜像重建并启动成功。
- `GET http://127.0.0.1:3000`：返回 200。
- `curl.exe -I http://127.0.0.1:3000`：返回 200，frontend 容器内进程为 `next-server (v16.2.10)`。
- Chrome DevTools MCP 验证 `http://192.168.101.12:3000/`：报表中心“新建分析”创建 `analysis_thread_d776e1cab5a7`，状态 `waiting_for_question`，页面显示任务号 `d776e1ca`、等待提问空态，并在右侧渲染报表。
- Chrome DevTools MCP 复测 `analysis_thread_c033299e5733`：刷新页面后点击已完成历史任务，中间面板恢复用户消息、工具调用和 agent 回复，不再显示“等待提问”空态。
- `GET /api/analysis/threads`：确认返回列表 `draftCount=0`。
- `GET http://127.0.0.1:8000/health`：返回 `{"status":"ok"}`。
- `python -m py_compile scripts\finereport\extract_report_and_datasets.py scripts\finereport\extract_parameters_and_interactions.py scripts\finereport\extract_report_structure.py scripts\finereport\merge_usage_statistics.py scripts\finereport\build_report_profiles.py scripts\finereport\download_usage_excel.py`：脚本语法校验通过。
- `python scripts\finereport\build_report_profiles.py 资源库/finereport/LR 资源库/finereport/报表画像 --usage-file 资源库/finereport/finereport近90天执行记录汇总.xlsx`：692 个 CPT 画像全部生成成功，失败数 0。
- 报表画像巡检：`json_files=692`，`matched_reports=399`，`total_usage_count_sum=88264`，`bad_user_samples=[]`，确认画像使用人员中无 `超管/admin` 残留。
- 修复空 Thread 首次提问创建第二个 Thread：新建任务后输入问题或点击建议问题时，前端会把新建的 `thread.id` 明确传给首个 Turn。
- 修复首次提问流式执行被误中断：`useFlow` 已移除跨实例共享的取消标记，改为按当前执行序号和活动 Thread 管理取消状态；同一 Thread 从等待态切换为选中态时不会终止正在读取的 SSE。
- 浏览器复测 `analysis_thread_3c7234dd3f97`：点击“渠道销售占比分析”后始终使用同一个 Thread，完成 1 个 Turn、归档 41 个 Item，最终状态为 `completed`，未产生第二个 Thread。
- `python -m pytest backend/tests/test_analysis_task_endpoint.py -v`：2 个新增任务创建端点测试通过；`POST /api/analysis/tasks` 返回 `analysis_thread_*` ID，draft_ 不会被任何标题字串冒充。
- `python -m pytest backend/tests/test_artifact_strict_save_contract.py -v`：7 个严格保存契约测试通过，覆盖 valid → created-with-version / invalid → failed-no-save / version-conflict → failed / value-error → failed / store-missing → failed / no-rewrite。
- `python -m pytest backend/tests/test_health_endpoint.py -v`：2 个健康检查测试通过（200 ok / 503 unhealthy per store）。
- `python -m pytest backend/tests/test_text_encoding_contract.py -v`：2 个编码直传测试通过（`??` 串与 `Ã©` 串不再被改写）。
- `python -m pytest backend/tests`：106 个后端测试全部通过。
- `npx.cmd vitest run`：前端 21 个测试文件、103 个测试全部通过，包含新加的 `analysis-empty-input.test.ts`（锁住"空问题 = 错误事件 + fetch 不被调用"契约）。
- `npx.cmd tsc --noEmit`：前端 TypeScript 校验通过。

## 风险或未完成

- 报表中心“删除”按钮仍是前端提示，尚未接后端删除动作。
- “刷新数据”“修改报表”“另存为新报表”的完整产品链路尚未实现。
- 当前 `ReportArtifact` 协议仍需继续通用化，查询、数据集、组件、布局、筛选、交互和血缘需要进一步收敛。
- 历史任务 `c41e0fb0` 后续重试被上游 MiniMax 流读取超时中断；修复只保证后续同类工具参数更稳、超时可控失败，不会自动补写该历史任务的 artifact。
- 本机直接运行 `npm.cmd run build` 曾遇到 `.next/node_modules/@prisma/client-*` unlink `EPERM`，当前以 Docker 容器内 build/start 和 `tsc --noEmit` 作为验证口径。
- 历史故障 Thread `analysis_thread_18518278c22c` 和 `analysis_thread_602d91330827` 未删除；前者为空等待任务，后者是修复前被中断的 Turn，仅用于保留故障事实。
- 本轮浏览器复测中 `GenBI_report` 仍被既有 approval 配置拦截并回退为聊天结果；该问题与 Thread 重复创建、SSE 被误中断无关，尚未在本切片处理。
- 删除兜底后，**已存在的历史数据库**里可能仍存有：旧 `codex_thread_pending` 占位的 Thread / Turn 血缘、latin1-mojibake 文本、broken 字段的 Artifact 记录。一次性数据迁移不在本切片内。生产环境需要后续跑一次清理脚本（基于 `docs/plans/current.md` 的"待验证假设"列），把损坏数据从生产库迁移或删除，否则健康检查可以一路绿，但 `turns[0].question` 仍可能显示 `?? GMV ???????????????`。

## 下一步

1. 继续设计并收敛通用 `ReportArtifact` JSON 协议。
2. 继续完善 `GenBI_report` 工具契约和后端校验路径，减少模型反复试错。
3. 实现报表中心删除、刷新数据、修改报表和另存为新报表的最小闭环。
