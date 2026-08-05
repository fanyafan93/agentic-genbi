# 当前任务

更新时间：2026-08-05 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 全局数据契约（新会话必读）

**适用于所有新写入的数据。**

- `analysis_threads.id` == `analysis_threads.codex_thread_id`（同一值）
  - 旧字段 `codex_thread_id` 保留以兼容旧代码读取，**值与 `id` 相同**，不再单独生成。
- `analysis_turns.id` == `analysis_turns.codex_turn_id`（同一值）
- `analysis_codex_item_projections.codex_item_id` == Codex 原始 Item ID

**不做的范围（本切片明确不做）：**

- 不生成 `analysis_thread_xxx` / `analysis_turn_xxx` / `genbi_item_xxx` 形式的新 ID。
- 不改任何表名。
- 不删除旧字段。
- 不迁移旧历史数据。
- 不改前端页面。
- 不接 ChatKit。

**验收**（创建一条新分析后，数据库必须满足）：

- `thread.id == thread.codex_thread_id`
- `turn.id == turn.codex_turn_id`

**实现要点（已落地）：**

- `CodexSdkAnalysisRuntime._iter_streamed` 在拿到 Codex thread 之后立即 yield `genbi/thread/provisioned`（payload 含 `codex_thread_id`），收到 turn 之后立即 yield `genbi/turn/provisioned`（payload 含 `codex_turn_id`）。两条事件的 `eventSource=genbi`，前置出现于任何 Codex 业务事件之前。
- `ThreadStore.create_thread(thread_id, codex_thread_id=…)` 强制要求 `thread_id == codex_thread_id`，违反时抛 `ValueError(thread_id must equal codex_thread_id)`。
- `ThreadStore.create_turn_only(thread_id, turn_id, codex_turn_id=…)` 同样强制 `turn_id == codex_turn_id`，并要求 thread 行已存在。
- `ThreadStore.save_turn` 增加防御性契约 guard：若事件流中出现与 `turn_id` 不一致的 `codex_turn_id` 直接抛错。
- `analysis_api._astream_runtime_events` 捕获 `genbi/thread/provisioned` / `genbi/turn/provisioned`：
  - thread 事件 → 直接 `ThreadStore.create_thread(thread_id=codex_thread_id, ...)`。
  - turn 事件 → `ThreadStore.create_turn_only(turn_id=codex_turn_id, ...)`。
  - 末尾 `save_turn` 时 `turn_id` 已是 Codex 原始 id，保证 `analysis_turns.id == analysis_turns.codex_turn_id`。
- 同步端点 `POST /api/analysis/threads` 与 `POST /api/analysis/reports/{id}/analysis-thread` 通过 `_provision_codex_thread_id` 在 FastAPI event loop 中驱动一次 `async_stream("")`，遇到 `genbi/thread/provisioned` 即返回 `codex_thread_id`；调用方立刻用该 id 落库。
- `disabled` 运行时若未在 metadata 中预置 `codex_thread_id`，同步端点返回 `503 codex_runtime_not_configured`（绝不擅自生成本地 id）。

## 当前分支

- 分支：`feature/session-management`（新增会话入口切片）
- 工作区：本轮含 backend 新增 `POST /api/analysis/sessions/turns[ /stream]`、前端取消 waiting_for_question 预创建。

## 本轮完成

- **取消空白任务**（用户规范）：前端"点击新建"不再调用 `POST /api/analysis/threads` 或 `POST /api/analysis/tasks`，不写数据库；后端接口暂时保留以兼容。
  - 新增唯一首轮入口：`POST /api/analysis/sessions/turns`（以及流式变体 `POST /api/analysis/sessions/turns/stream`）。请求体 `{ "message": "..." }`；后端 lazy 调用 Codex `thread_start`，首个 SSE 业务事件为：
    ```json
    { "type": "session/created", "payload": { "sessionId": "<codex_thread_id>", "codexThreadId": "<codex_thread_id>", "codexTurnId": "<turn_id>" } }
    ```
    客户端收到 `session/created` 后用 `window.history.pushState` 把 URL 从 `/analysis/new` 切换到 `/analysis/{codex_thread_id}`。
  - 后端实现要点：`CodexSdkAnalysisRuntime` 已在拿到 Codex thread 后 yield `genbi/thread/provisioned`、拿到 turn 后 yield `genbi/turn/provisioned`；新端点捕获这两个事件，从 `genbi/thread/provisioned.payload.codex_thread_id` 抽出 `sessionId`，在首个业务事件前插入 `session/created`；internal markers（`genbi/thread/provisioned`、`genbi/turn/provisioned`）不外发到客户端。
  - 前端实现要点：`BackendAnalysisAgentClient.send` 检测到 `input.kind === "start" && !input.threadId` 时改走 `/api/analysis/sessions/turns/stream`，请求体改为 `{ message, metadata }`；流到 `session/created` 时把它翻译为 `AgentEvent`；`AnalysisWorkspace` 维护 `localNewSession` 状态，记录"页面处于 new 模式"，待 `flow.threadId` 拿到后 `setCurrentAnalysisTaskId(flow.threadId)` 并切路由。
  - 验收：
    - 点击"新建"后数据库行数不变。
    - 输入第一句话后才出现 Session。
    - 不再产生空会话。
    - 不再需要 `waiting_for_question`。
  - 测试：`backend/tests/test_analysis_api.py` 新增 `SessionlessStartTest`（3 个用例）锁住契约；`backend/tests/test_analysis_api.py` / `frontend/tests/analysis-task-copy.test.ts` / `frontend/tests/analysis-backend-client.test.ts` 各自更新断言以匹配新会话入口与 URL 切换。
- **前端只认一个 Session ID**（用户规范）：client 内部状态收敛成 `sessionId` + `currentTurnId`，不再保留 `threadId` 字段。
  - `useFlow(sessionId, initial, { onSessionCreated })` 仅保存 `currentTurnId` / `running` / `nodes` / `artifacts` / `reportArtifact` / `codexLineage`。`currentTurnId` 只在 `user` 事件（来自 `turn/started`）里写入。
  - `BackendAnalysisAgentClient` 删除 `private threadId` 字段；每次 `send` 必须显式传入 `sessionId`（`null` 走 `/api/analysis/sessions/turns/stream`，否则走 `/api/analysis/sessions/{sessionId}/turns/stream`）。
  - 不允许 client 跨调用"记住上一次 thread"——切到 B 时 A 的 ID 不得出现在 B 的请求 URL 或 body。
  - 路由层接 `onSessionCreated` 回调，从 sessionless 流拿到 `sessionId` 后 `setCurrentAnalysisTaskId` + `pushState('/analysis/{sessionId}')`。
  - 后端新增 `POST /api/analysis/sessions/{sessionId}/turns/stream` 端点：URL 的 `session_id` 是唯一可信 id，body 的 `sessionId` 与 URL 不一致返回 `400 session_id_mismatch`。
  - 测试：
    - `frontend/tests/analysis-backend-client.test.ts` 新增 `never leaks the previous session id into the next request (A → B → send)`：开 A → 开 B → 给 B 续传时 URL 与 body 都不出现 A 的 id；session/created 事件不携带 A 的 threadId。
    - `backend/tests/test_analysis_api.py` 新增 `SessionScopedContinuationTest`（3 个用例）：续传 turn 落到 `codex_thread_created` 行、`session_id_mismatch` 返回 400、URL 单独作为可信 id。
- **把状态拆开**（用户规范）：会话与 turn 拥有独立状态机。
  - Session 状态机：仅 `active` / `archived`；`create_thread` 拒绝 `running` / `completed` / `waiting_for_question` / `failed` / `needs_input` 等历史值。
  - Turn 状态机：`running` / `completed` / `failed` / `cancelled` / `needs_input`。`_turn_status` 把 `turn/completed.status` 严格映射（`complete`/`succeeded` → `completed`；`failed` / 未知 → `failed`；`cancelled` / `interrupted` → `cancelled`），`needs_input` 留给 ask 事件。
  - ThreadStore 取消 `save_turn` 时复制 turn 状态到 session 的旧逻辑；session.status 始终保持 `active`，除非用户显式 `archive_thread` / `reactivate_thread`。
  - API 表面把 `latestTurnStatus` 与 `latestTurnId` 暴露给前端（snake + camelCase 双键），不再让前端从 session 推断 turn 结果。
  - 前端：`analysisThreadStatus` / `analysisThreadStatusLabel` 改用 `latestTurnStatus`；`isWaitingForFirstQuestion` 在 session 还没 turn 时为真；`markCurrentThreadAsStarted` 不再写 session.status = "running"，只写 `latestTurnStatus = "running"`。
  - 验收：
    - `test_turn_failure_keeps_session_active_and_allows_continuation`：开 A → 强制把 turn 1 标为 `failed` → GET 看到 `session.status=active`、`latestTurnStatus=failed`；再发 turn 2 走 `/api/analysis/sessions/{id}/turns/stream`，写入新 turn；`session.status` 仍为 `active`，`latestTurnStatus` 切到 `completed`。
    - `test_list_threads_returns_latest_turn_status_per_session`：列表里每个 session 都带 `latestTurnStatus`，session.status 永远 `active`。
  - 测试：
    - 后端 `SessionTurnStateDecouplingTest` 5 个用例（fresh session active、拒绝 legacy session 状态、turn status 终态化、turn failed 后 session 仍 active 可续传、列表带 latestTurnStatus、archive/reactivate）。
    - 前端 `analysis-backend-client.test.ts` 新增 `forwards the latestTurnStatus signal from the backend sidebar` 与 `keeps sending new questions after a failed turn on the same session`。
  - 后端 115/115、前端 94/94、tsc 全过。
- 恢复主开发分支到 `29c0e0f merge: feature/report-artifact-design → Agentic-GenBI`。
- 确认 `119e4c5 fix(frontend): align flow.start/send/reply signature with AgentInput threadId` 内容已包含在恢复点中，cherry-pick 为空补丁。
- 修复 FineReport 报表画像加载：
  - 默认目录从 `资源库/finereport/解析` 改为 `资源库/finereport/报表画像`。
  - Docker 后端环境变量同步改为 `/app/资源库/finereport/报表画像`。
  - 后端 repository 支持递归读取报表画像目录下普通单文件 `*.json`，不再只依赖旧的 `*.原始解析.json` 或 `01/02/03` 分片命名。
  - 后端读取并返回 `report_usage`，统一为 `reportUsage`。
  - 前端“报表解析”恢复为“报表画像”，并新增“使用情况”页签。
- 修复新建分析任务 404：
  - 当前运行前端仍可能调用旧入口 `POST /api/analysis/tasks`。
  - 后端新增兼容入口 `POST /api/analysis/tasks`，内部复用 canonical `POST /api/analysis/threads` 创建逻辑，并返回 `{ task }` envelope。

## 已运行验证

- `python -m pytest backend/tests/test_finereport_reports.py -q`：2 passed。
- `npm.cmd test -- tests/finereport-report-browser.test.tsx`：2 passed。
- `python -m pytest backend/tests/test_analysis_api.py backend/tests/test_finereport_reports.py -q`：26 passed。
- 后端本地 repository 验证：`资源库/finereport/报表画像` 可读出 692 个报表画像。
- 真实接口验证：`GET http://127.0.0.1:8000/api/business-semantics/finereport/reports` 返回 692 条。
- 真实接口验证：`POST http://127.0.0.1:8000/api/analysis/tasks` 从 404 修复为 200。
- 服务重启验证：backend health ready，frontend ready。
- **新会话 ID 契约（本轮）：**
  - `python -m unittest discover -s backend/tests -v`：**103 个后端测试全部通过**（含 `test_analysis_api`、`test_thread_store`、`test_codex_sdk_runner`、`test_principal_isolation`、`test_genbi_report_mcp_server`、`test_minimax_codex_adapter`、`test_thread_store`、`test_finereport_reports`、`test_env_config`、`test_analysis_task_endpoint`、`test_artifact_strict_save_contract`、`test_health_endpoint`、`test_text_encoding_contract`）。
  - 契约断言示例（`backend/tests/test_analysis_api.py::test_analysis_thread_turn_api_streams_codex_events_and_persists_thread`）：
    - `payload["thread_id"]` 以 `codex_thread_` 开头
    - `payload["turn_id"]` 以 `codex_turn_` 开头
    - 事件序列前置 `genbi/thread/provisioned` 与 `genbi/turn/provisioned`
    - `GET /api/analysis/threads/{id}` 返回的 `thread.codexThreadId == thread.id`、`turns[0].codexTurnId == turns[0].id`
  - `disabled` 运行时端点契约：`POST /api/analysis/threads/turns` 未传 `metadata.codex_thread_id` 时返回 `503 codex_runtime_not_configured`（不再偷偷生成本地 `analysis_thread_xxx`）。
  - `python -m py_compile backend/api/analysis_api.py backend/harness/codex_sdk_runner.py backend/harness/thread_store.py`：语法检查通过。
- **取消空白任务（本轮）：**
  - `python -m unittest discover -s backend/tests -v`：**106 个后端测试全部通过**（在 103 基础上新增 3 个 `SessionlessStartTest`）。
  - `cd frontend && npx.cmd tsc --noEmit`：TypeScript 编译通过。
  - `cd frontend && npx.cmd vitest run`：**91 个前端测试全部通过**（含更新后的 `analysis-task-copy.test.ts` 与 `analysis-backend-client.test.ts`）。
  - 契约断言示例（`backend/tests/test_analysis_api.py::SessionlessStartTest`）：
    - 点击新建前 `thread_store.list_threads(product_kind="analysis_task")` 为空；调 `POST /api/analysis/sessions/turns` 后 `analysis_threads` 才出现一行。
    - 响应 `events` 第一项是 `session/created`，payload 包含 `sessionId == codex_thread_id == thread_id`。
    - 响应 `events` 不包含 `genbi/thread/provisioned` / `genbi/turn/provisioned`（internal markers 已过滤）。
    - `POST /api/analysis/sessions/turns/stream` SSE 同样以 `event: session/created` 开头，body 中不再含 `event: genbi/thread/provisioned`。
    - `message: ""` 端点返回 `422`，`analysis_threads` 仍为空。
  - **前端只认一个 Session ID（本轮）：**
    - `python -m unittest discover -s backend/tests -v`：**109 个后端测试全部通过**（新增 3 个 `SessionScopedContinuationTest`）。
    - `cd frontend && npx.cmd tsc --noEmit`：TypeScript 编译通过。
    - `cd frontend && npx.cmd vitest run`：**92 个前端测试全部通过**（含 `never leaks the previous session id into the next request (A → B → send)`）。
    - 契约断言示例：
      - 前端 `_FakeCodexRuntime` 收到 A→B 切换：A 的 `codex_thread_a` 出现在第一次 SSE response 中，B 的 `codex_thread_b` 出现在第二次，但 B 的续传请求 URL 是 `…/sessions/codex_thread_b/turns/stream`，body 含 `codex_thread_b`，**不含 `codex_thread_a`**。
      - 后端 `/api/analysis/sessions/{sessionId}/turns/stream`：URL 单独是可信 id，body 的 `sessionId` 与 URL 不一致返回 `400 session_id_mismatch`；同一会话的两次 turn 落库到 `turns[0]` 与 `turns[1]` 两条独立行（`codex_turn_1`、`codex_turn_2`），均满足 `id == codex_turn_id`。

## 风险或未完成

- 当前分支与远端存在历史分叉；推送时需要保留本地恢复后的代码状态，同时合并远端历史，避免强推。
- PowerShell 控制台直接显示 API 表格时中文可能乱码；Python 读取同一接口验证中文正常。
- `.pytest_cache` 目录权限警告仍存在，不影响本轮测试结果。
- PowerShell profile 中 `starship` 未安装的提示仍存在，不影响服务。
- 新会话 ID 契约生效后，旧数据库里的 `analysis_thread_xxx` / `analysis_turn_xxx` 行会与新 `codex_thread_xxx` / `codex_turn_xxx` 行并存；旧行**不在本切片迁移**，仅供历史查询与回放。
- 生产 Codex 启动延迟会同步反映到 `POST /api/analysis/threads` 的响应耗时；当前 mock 测试通过，但真实 Codex CLI 的首次启动可能更慢。
- `disabled` runtime 单元测试需要 fixture 在 metadata 里显式预置 `codex_thread_id`；缺少该字段即返回 503，提醒调用方走真实 Codex 路径。

## 下一步

1. 提交本轮恢复修复。
2. 用非强推方式合并远端分叉历史并推送 `Agentic-GenBI`。
3. 推送后在浏览器复测：新建分析任务、报表画像列表、报表画像使用情况页签。
4. （新会话 ID 契约）在真实 Codex 环境下端到端验证 `thread.id == thread.codex_thread_id`、`turn.id == turn.codex_turn_id`。
