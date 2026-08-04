# 当前任务

更新时间：2026-08-04 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 当前分支

- 分支：`feature/report-artifact-design`
- 工作区：有未提交改动，包含报表资产设计切片、报表中心入口、真实 Thread 新建链路和相关验证。

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

## 已运行验证

- `python -m unittest backend.tests.test_thread_store backend.tests.test_analysis_api -v`：27 个后端测试通过。
- `python -m unittest backend.tests.test_analysis_api -v`：23 个后端 API 测试通过。
- `python -m unittest backend.tests.test_analysis_api -v`：24 个后端 API 测试通过。
- `python -m unittest backend.tests.test_genbi_report_mcp_server -v`：9 个 GenBI_report MCP 测试通过。
- `python -m unittest backend.tests.test_minimax_codex_adapter -v`：10 个 MiniMax Codex Adapter 测试通过。
- `python -m unittest backend.tests.test_analysis_api -v`：24 个后端 API 测试通过。
- `python -m unittest backend.tests.test_thread_store -v`：6 个 ThreadStore 测试通过。
- `npm.cmd test -- interactive-report-api-client.test.ts analysis-task-copy.test.ts report-center-card-actions.test.tsx`：25 个前端测试通过。
- `npm.cmd test -- analysis-flow-streaming.test.ts`：13 个前端 flow 测试通过。
- `npm.cmd test -- analysis-task-copy.test.ts analysis-flow-streaming.test.ts`：30 个前端测试通过。
- `npm.cmd test -- analysis-task-copy.test.ts report-center-card-actions.test.tsx`：19 个前端测试通过。
- `npm.cmd test -- analysis-backend-client.test.ts analysis-task-copy.test.ts`：39 个前端测试通过。
- `npx.cmd tsc --noEmit`：前端 TypeScript 校验通过。
- `docker compose up -d --build --force-recreate frontend`：frontend/backend 镜像重建并启动成功。
- `docker compose up -d --build --force-recreate backend`：backend 镜像重建并启动成功。
- `GET http://127.0.0.1:3000`：返回 200。
- Chrome DevTools MCP 验证 `http://192.168.101.12:3000/`：报表中心“新建分析”创建 `analysis_thread_d776e1cab5a7`，状态 `waiting_for_question`，页面显示任务号 `d776e1ca`、等待提问空态，并在右侧渲染报表。
- Chrome DevTools MCP 复测 `analysis_thread_c033299e5733`：刷新页面后点击已完成历史任务，中间面板恢复用户消息、工具调用和 agent 回复，不再显示“等待提问”空态。
- `GET /api/analysis/threads`：确认返回列表 `draftCount=0`。
- `GET http://127.0.0.1:8000/health`：返回 `{"status":"ok"}`。

## 风险或未完成

- 报表中心“删除”按钮仍是前端提示，尚未接后端删除动作。
- “刷新数据”“修改报表”“另存为新报表”的完整产品链路尚未实现。
- 当前 `ReportArtifact` 协议仍需继续通用化，查询、数据集、组件、布局、筛选、交互和血缘需要进一步收敛。
- 历史任务 `c41e0fb0` 后续重试被上游 MiniMax 流读取超时中断；修复只保证后续同类工具参数更稳、超时可控失败，不会自动补写该历史任务的 artifact。
- 本机直接运行 `npm.cmd run build` 曾遇到 `.next/node_modules/@prisma/client-*` unlink `EPERM`，当前以 Docker 容器内 build/start 和 `tsc --noEmit` 作为验证口径。

## 下一步

1. 继续设计并收敛通用 `ReportArtifact` JSON 协议。
2. 继续完善 `GenBI_report` 工具契约和后端校验路径，减少模型反复试错。
3. 实现报表中心删除、刷新数据、修改报表和另存为新报表的最小闭环。
