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
- **删除 GenBI 自研 Item**（用户规范）：会话恢复只依赖 Turn + Codex Item Projection，实时流与历史恢复用同一种标准化投影结构。
  - ThreadStore 删除 `ItemRecord`、`state["items"]` 读写、`_items_from_events()`、`_item_params` / `_item_record_from_row`。
  - TurnRecord 增加 `inputText` / `startedAt` / `completedAt` 字段；`question` 字段保留以兼容旧数据。
  - CodexItemProjectionRecord 增加 `sequence` 字段（realtime 顺序保持 + 历史 replay 时按 `createdAt`/`codexItemId` 重排成密集索引）。
  - `get_thread` / `get_turn` 不再返回 `items` 字段；`get_turn_events` 改为从 `codex_item_projections` 重建统一 shape（type/turn_id/payload/created_at + sequence + codex_* + item_type + status），与实时 SSE 流形状一致。
  - 用户输入存于 `analysis_turns.input_text`；不再从 Codex 事件伪造 GenBI User Item。
  - postgres_stores 删除 `POSTGRES_ITEM_TABLE` 与对应 `_item_*` helper；`analysis_turns` 表加 `input_text` / `started_at` / `completed_at` 列；`analysis_codex_item_projections` 加 `sequence` 列。
  - 验收：
    - `test_thread_and_turn_detail_drop_legacy_items_field`：`get_thread` / `get_turn` 不带 `items` 字段，仅 `codexItemProjections`；turn 行的 `inputText` / `startedAt` / `completedAt` 已落库。
    - `test_get_turn_events_returns_normalised_projection_shape`：replay 返回的 events 含 `codex_item_id` / `item_type` / `status` / `sequence`，与 live stream 形状对齐。
    - `test_no_fake_user_item_is_constructed_for_turn`：Codex 没发 item 时 `codexItemProjections` 为空，但 `turn.inputText` 仍存在。
    - `test_projection_sequence_renumbers_after_save`：replay 时 sequence 重新按 createdAt 顺序编号为 0/1。
  - 测试：后端 `NoGenBIItemTest` 4 个用例；前端 `analysis-backend-client.test.ts` 新增 `replay is projection-only (no GenBI Item rows required)`。
  - 后端 119/119、前端 95/95、tsc 全过。
- **旧数据兼容读取**（用户规范）：旧 `analysis_threads` 行里
  `id != codex_session_id`（一行同时带 GenBI id + Codex-issued id）。
  新 contract 永远是 `id == codex_session_id`。先做兼容读取，等
  旧使用量确认后再决定永久保留或一次迁移。
  - 兼容点：
    * `SessionCatalog.resolve_session_id(raw_id) -> str | None`：
      用 raw id **或** `codexSessionId` 都能查到同一行；返回
      canonical row id（catalog 的真 row id），下游只面对 row，
      不面对 alias。
    * `get_view` 内部统一走 `resolve_session_id`。
    * `register_session` 继续强制 `id == codex_session_id`（新
      record 永远是新 shape）。
  - API 落地：
    * `GET / PATCH / DELETE /api/analysis/sessions/{session_id}` 全部
      走 `resolve_session_id` 拿 canonical id；找不到才 404。
    * `POST /api/analysis/sessions/{session_id}/turns`：URL 拿到 raw
      id 后 resolve；如果 row 存在，runtime 看到
      `view.session.codexSessionId`（真 codex id），projections 落
      canonical row；不存在时按 raw id 走 lazy register。
    * `POST /api/analysis/sessions/{session_id}/cancel`：archive
      canonical row，response `session.id` 是 canonical id，前端
      拿到后 replace URL。
  - 数据形态（不为了数据库形式完美改坏历史）：
    * 旧 row：保留 `id != codex_session_id` 形态，继续可读。
    * 新 row：`id == codex_session_id`，`metadata.codex_session_id`
      也对齐。
    * `SessionCatalog._read_state` 已有从 JSONL 读 `codexSessionId`
      的兜底（兼容老字段名 `codexThreadId`）。
  - 测试：
    * `SessionCatalogPurityTest.test_resolve_session_id_accepts_legacy_codex_session_id_alias`
      锁住"任一 id 都能查到同一行，row id 是 canonical"。
    * `LegacySessionIdCompatibilityTest`（2 例）锁住 API 层
      `GET / PATCH / DELETE / cancel / continuation` 全部用
      GenBI alias 也 200，且 `session_id` response 是 canonical。
  - 验收：后端 129/129、前端 93/93、tsc 全过。
- **PostgreSQL P0 修复**（用户规范）：旧 `analysis_threads` /
  `analysis_turns` / `analysis_codex_item_projections` 的 schema
  跟新代码 contract 不对齐，三个 P0 bug 必须第一批修：
  1. `build_postgres_session_catalog()` 调了不存在的方法
     `SessionCatalog.from_backend(backend)`。
  2. Postgres backend 实现的是 `_read_state` / `_write_state`，
     catalog / projection store 调的是 `read_state` / `write_state`。
  3. 旧 DB 缺 `session_id` / `codex_session_id` 列，新 INSERT
     会失败。
  修复：
  * `SessionCatalog.from_backend(backend)` → `SessionCatalog(backend=backend)`
    （catalog 自己的构造函数支持 `backend=`）。
  * Postgres backend 公开 `read_state` / `write_state`（public
    名字）；underscored 名字不再被使用。
  * `ensure_schema` 加 idempotent 迁移：
    - `analysis_threads`：加 `codex_session_id`，backfill
      `codex_session_id = codex_thread_id`。
    - `analysis_turns`：加 `session_id` 与 `codex_session_id`，
      backfill `session_id = thread_id` /
      `codex_session_id = codex_thread_id`。
    - `analysis_codex_item_projections`：加 `codex_session_id`
      与 `genbi_session_id`，backfill
      `codex_session_id = codex_thread_id` /
      `genbi_session_id = genbi_thread_id`。
  * 新 INSERT 不会因为旧 schema 缺列而失败；旧 row 仍然可读
    （含 `id != codex_session_id` 的 legacy 形态，跟
    `SessionCatalog.resolve_session_id` 配合）。
  验证（真实 docker postgres，134 sessions / 166 turns / 905 projections）：
  * `ALTER` + `UPDATE` 全部成功（166 turns 全部 backfill）。
  * 重建 backend image 后 `GET /api/analysis/sessions/{id}` 用
    GenBI id 跟 Codex id 都能 resolve 到同一行；2 turns 跟 6
    codex item projections 完整 round-trip。
  测试（新增 `test_postgres_p0_compat.py`，6 用例）：
  * `build_postgres_session_catalog` 走 public 构造函数，不再调
    不存在的 `from_backend`。
  * Postgres backend 暴露 public `read_state` / `write_state`。
  * `codex_thread_id` → `codex_session_id` backfill。
  * `thread_id` → `session_id` backfill，且新 write path 走
    canonical `session_id` 列。
  * `build_postgres_codex_projection_store` 走 public 构造函数。
  * Turn / projection round-trip 走 fake connection。
 - 验收：后端 135/135、前端 93/93、tsc 全过；docker compose up 后
  legacy session 双 id 都能 round-trip。
- **Streaming Turn ID 必须实时落 streaming accumulator**（用户规范
  P0）：`_astream_runtime_events` 之前只更新
  `effective_thread_id`，`turn_id` 参数保持 preflight 空值。
  后果：
  * `_accumulate_projection(turn_id="")` → 首轮 Item Projection
    不会落 canonical turn row。
  * `_enrich_analysis_event(turn_id="")` → 事件 envelope
    `turnId` 为空。
  * `_interactive_report_artifact_event(turn_id="")` →
    `source.turnId` 为空，首轮报告血缘错。
  * `_missing_terminal_event(turn_id="")` → 中途中断时无法
    准确关闭 Turn。
  * 只有 `_save_analysis_turn()` 批量重建时才部分恢复，
    中断场景下整个 turn 处于悬挂态。
  修复：
  * `_astream_runtime_events` 内部维护 `resolved_turn_id`，在
    `genbi/turn/provisioned` 第一次出现时立即更新。
  * 后续所有事件（fold / enrich / artifact / 缺失终态事件）
    都用 `resolved_turn_id`。
  * `turn_id` 形参仍然保留（preflight id / 调用方 hint），
    但首轮 provisioning 之前的事件不会 fold（这些事件没真实
    turn id，fold 会落到不存在的行上）。
  * `pre-create turn row` 的逻辑也用 `resolved_turn_id` 写
    canonical `running` 行（避免 race）。
  测试（新增 `StreamingResolvedTurnIdTest`，2 例）：
  * `test_resolved_turn_id_reaches_enrichment_and_artifact_lineage`：
    驱动 `_astream_runtime_events` 整路径，断言所有
    `item/agentMessage/delta` 事件 `turn_id == "codex_turn_1"`,
    `codex_projection_store.list_turns` 包含 canonical 行。
  * `test_preflight_turn_id_is_overridden_by_runtime`：
    验证 preflight `turn_id` 不会泄漏到下游；runtime-issued
    id 才是唯一权威。
  * 修复前两个测试都失败（`'' != 'codex_turn_1'`），
    修复后通过。
 - 验收：后端 137/137、前端 93/93、tsc 全过。
- **Streaming turn endpoints（P1 关键回归修复）**：上一轮把
  `/turns` 端点从 SSE 改成 JSON 等全部完成后再发，丢了流式
  体验。Session Manager 收缩**不应该**以删除流式能力为代价。
  修复：
  * 新增 `POST /api/analysis/sessions/turns/stream`（首轮）
    跟 `POST /api/analysis/sessions/{session_id}/turns/stream`
    （续轮）两条 SSE 路由，返回
    `StreamingResponse(..., media_type="text/event-stream")`。
  * 这两条路由**共享**同一个 Session / Turn / Projection
    内核（`_astream_runtime_events`，上一轮已经修了
    `resolved_turn_id` accumulator）：`_stream_session_first_turn_response`
    走 sessionless 首轮，`_stream_analysis_turn_response`
    走续轮。两端点内部事件流、projection fold、artifact
    lineage 都用同一个 kernel。
  * 现有 `/turns` JSON 路由**保留**——disabled runtime / 测试
    / non-streaming client 用。streaming 路径**专属** runtime
    enabled 场景，`/turns/stream` 在 runtime disabled 时返
    503 强制走 JSON fallback。
  * `_stream_analysis_turn_response` 加 `genbi/*` 内部事件过
    滤——首轮 helper 之前已有过滤，续轮 helper 漏了；现在两
    边对齐，下游 SSE 看不到内部 marker。
  * Frontend `BackendAnalysisAgentClient` 改用 SSE parser
    (`readAnalysisSse`)：response body 拉流 → 解析
    `data:` 行 → 转发 AgentEvent → 必要时 `session/created`
    触发 URL navigation。**不再** `await response.json()`
    等完整返回。
  * URL path 跟 body 不携带 session id 的规则不变；
    `codex_session_id` resolve 走 `SessionCatalog.resolve_session_id`
    跟上一轮一样。
  测试：
  * 后端 `StreamingEndpointContractTest`（3 例）：
    - `test_first_turn_stream_endpoint_returns_event_stream`：
      `/turns/stream` 返回 `text/event-stream`，第一个事件是
      `session/created` 且带 `codexTurnId`。
    - `test_continuation_turn_stream_endpoint_returns_event_stream`：
      `/{id}/turns/stream` 返回 SSE，第一个事件不是
      `session/created`（session 已存在），是 `turn/started`
      或 `item/agentMessage/delta`。
    - `test_first_turn_stream_endpoint_rejects_disabled_runtime`：
      runtime disabled 时 `/turns/stream` 返 503，强制走
      JSON fallback。
  * 前端 `sseResponse(events)` helper + URL 期望改成
    `/turns/stream`（4 个受影响的 route 测试）。
  * 前端 `streams backend events as soon as the runtime emits them`
    验证 streaming：ReadableStream 每 10 ms push 一个 chunk，
    第一个 event 延迟 < 50 ms，第二个 event 晚于第一个，
    总时间 bounded by chunk schedule。**修复前**这个测试
    失败（前端 `await response.json()` 等完整 JSON）——
    证明它真的锁住"等全部完成才播放"的 P1 回归。
  验收：后端 140/140、前端 94/94、tsc 全过；docker backend
  rebuild 后 `/api/analysis/sessions/turns/stream` 返回
  `text/event-stream`（用容器内 python urllib 实测）。
- **统一 API**（用户规范）：保留 7 个 `/api/analysis/sessions/*`
  路由，body 永不携带 session id。
  - `GET    /api/analysis/sessions`
  - `POST   /api/analysis/sessions/turns` （首 turn，body 含
    `message` / `user_id` / `metadata`，`metadata.codex_session_id`
    作为 preflight id）
  - `GET    /api/analysis/sessions/{session_id}`
  - `PATCH  /api/analysis/sessions/{session_id}` （`title` /
    `status: active|archived`）
  - `DELETE /api/analysis/sessions/{session_id}`
  - `POST   /api/analysis/sessions/{session_id}/turns` （续 turn，
    非流；body 含 `message` / `turn_kind` / `user_id` / `metadata`）
  - `POST   /api/analysis/sessions/{session_id}/cancel`
  - 删除：`/api/analysis/tasks`、`/api/analysis/threads` 及全部
    `/threads/{id}/*` 端点。
  - 取消请求体别名：`thread_id` / `conversation_id` / `task_id` 不再被
    服务端读取（URL 是 session id 的唯一来源）。
  - 同时把 `/api/analysis/reports/{id}/analysis-thread` 重命名为
    `/api/analysis/reports/{id}/sessions`，response `thread` envelope
    改为 `session`。
  - 实现要点：
    * `create_app` 接受 `session_catalog=` / `codex_projection_store=`，
      保留 `thread_store=` shim 兼容老测试。
    * `start_session_first_turn` 支持 `metadata.codex_session_id`
      preflight id；runtime 关闭时短路到 `InMemoryCodexAnalysisRuntime`
      写 1 row。
    * `_astream_runtime_events` 中 runtime-yield 的 `codex_thread_id`
      永远覆盖 preflight（runtime 是 session id 的唯一权威）。
    * `_build_thread_detail` 返回
      `{ "session": ..., "thread": ..., ... }` 兼容老客户端。
    * helper kwarg 重命名：`_create_analysis_turn_payload(session_id=)`、
      `_astream_runtime_events(session_id=)`、`_save_analysis_turn(session_id=)`。
    * `_analysis_request_from_body` 从 `message` 字段读 question；
      `body.thread_id` / `body.conversation_id` / `body.task_id`
      不再被读取。
    * 删除 `_with_latest_thread_question` /
      `_find_waiting_analysis_thread` / `_build_default_thread_store` 旧名字。
  - 前端：
    * `BackendAnalysisAgentClient.send` 改为 JSON 请求（不再 SSE）；
      body 只含 `message` / `turn_kind` / `user_id` / `metadata`。
    * `listBackendAnalysisSessions` / `getBackendAnalysisSession` /
      `deleteBackendAnalysisSession` 取代旧 `*Threads`。
    * `flowNodesFromBackendSession` 取代 `flowNodesFromBackendThread`。
    * `createAnalysisThreadFromReportBackend` 调
      `/reports/{id}/sessions`。
  - 验收：
    * 后端 126/126、前端 93/93、tsc 全过。
    * `analysis-task-copy.test.ts` 字符串契约测试从
      `/api/analysis/threads` / `getBackendAnalysisThread` /
      `flowNodesFromBackendThread` 改为 `/api/analysis/sessions` /
      `getBackendAnalysisSession` / `flowNodesFromBackendSession`。
    * `SessionCatalogPurityTest` / `CodexProjectionStorePurityTest`
      锁住"两薄组件不偷对方职责"的边界。
    * `SessionlessStartTest` 验证 `metadata.codex_session_id` preflight id
      是 runtime offline 时唯一能让 endpoint 落 session row 的入口。
- **拆掉万能ThreadStore**（用户规范）：会话/turn/codex projection 各归其位。
  - `SessionCatalog`（`backend/harness/session_catalog.py`）只管 session 行 + 状态机（`active`/`archived`），API 严格按规范：
    - `list_sessions` / `get_session` / `register_session` / `rename_session` / `archive_session`（外加 `reactivate_session` / `delete_session` / `mark_updated` / `bind_latest_turn_provider` / `get_view` / `list_views`）。
    - 通过 `LatestTurnProvider` 协议从 `CodexProjectionStore` 读 `latest_turn_status` / `latest_turn_id`，**不直接**访问 projection 表。
    - 拒绝 `running` / `completed` / `failed` / `needs_input` / `waiting_for_question` 等历史 session 状态。
  - `CodexProjectionStore`（`backend/harness/codex_projection_store.py`）只管 `analysis_turns` + `analysis_codex_item_projections`，API 严格按规范：
    - `save_turn` / `complete_turn` / `upsert_item` / `list_turns` / `list_items`（外加 `get_turn` / `get_turn_events` / `latest_turn_status` / `latest_turn_id` / `bind_session_touch`）。
    - 输入为**已构造**的标准化字段；不接收 `events` / `agent_events` / Codex item payload 译码。
    - 不接收 session-level 状态（`active`/`archived` 走 catalog）、不接受 user 权限、收藏、分享、Artifact 业务规则。
  - `CodexAnalysisRuntime`（`backend/harness/analysis_runtime.py`）承担 Codex Runtime 责任：
    - `thread_start` / `thread_resume` / `turn.stream` / `interrupt`。
    - 状态机（`turn_status_from_events`）只在这里。
    - 投影 accumulator 顺序化 + 重排 `sequence`。
    - 不落盘；落盘全交给两个薄 store。
  - `analysis_api.py` 重写：组合 `SessionCatalog` + `CodexProjectionStore` + `CodexAnalysisRuntime`，`create_app` 接受 `session_catalog=` / `codex_projection_store=`，保留 `thread_store=` legacy kwarg 作为 shim。
  - `postgres_stores.py` 拆成 `PostgresSessionCatalogBackend` + `PostgresCodexProjectionBackend`，分别建 `analysis_threads` 与 `analysis_turns` + `analysis_codex_item_projections` schema；`analysis_items` 表删除。
  - `backend/harness/thread_store.py` 删除。`ItemRecord` / `_items_from_events` / `state["items"]` / `create_turn_only` / `save_turn` / `archive_thread` / `get_runtime_thread_id` / `get_thread_metadata` 一并删除。
  - 验收（后端 `SessionCatalogPurityTest` + `CodexProjectionStorePurityTest`）：
    - SessionCatalog 公共方法签名只暴露 session 操作；`save_turn` / `upsert_item` / `get_turn_events` / `list_turns` / `list_items` 一律不出现。
    - SessionCatalog 模块不导入 `AgentEvent` / `ToolCall` / `CodexItemProjectionRecord` / `TurnRecord`。
    - CodexProjectionStore 公共方法不含 `archive_session` / `save_artifact` / `share_artifact` 等。
    - CodexProjectionStore.save_turn 签名不含 `events` / `agent_events`。
    - CodexProjectionStore.complete_turn 拒绝 `active`（session 状态）。
    - CodexProjectionStore.upsert_item 拒绝不存在的 turn。
    - CodexProjectionStore 模块不导出 `user_id` / `tenant_id` / `permission` / `share_token`。
  - 测试：后端 126/126、前端 95/95、tsc 全过。
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
