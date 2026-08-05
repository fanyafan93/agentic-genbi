# 当前可验证状态

更新时间：2026-08-05 Asia/Shanghai

本页只记录当前状态。历史过程交给 Git。

## 一、当前最终契约

### 1.1 ID 统一契约（新写入的数据）
- Session：`analysis_threads.id == analysis_threads.codex_session_id`，由 Codex runtime 提供。
- Turn：`analysis_turns.id == analysis_turns.codex_turn_id`，由 Codex runtime 提供。
- Projection：`analysis_codex_item_projections.codex_item_id` == Codex 原始 Item ID。
- **不为新写入的数据生成** `analysis_thread_xxx` / `analysis_turn_xxx` / `genbi_item_xxx` 形式的 id。
- 旧历史行（`id != codex_session_id`）可读，不迁移；`SessionCatalog.resolve_session_id(raw_id)` 接受任一 alias 并返回 canonical row id。

### 1.2 会话入口（Sessionless Start）
- 点击"新建"不预分配 Session 行；第一句话触发 `POST /api/analysis/sessions/turns` 或 `/turns/stream` 时 Codex runtime 分配 session id。
- `metadata.codex_session_id` 作为 preflight id 仅在 runtime disabled / offline 时生效；runtime enabled 时 Codex 分配值永远覆盖 preflight。
- `message == ""` 时两端点均 422，不写任何空行。

### 1.3 Session / Turn 状态机
- Session 仅两态：`active` / `archived`；catalog 拒绝其余值。
- Turn：`running` / `completed` / `failed` / `cancelled` / `needs_input`。
- `latestTurnId` / `latestTurnStatus` 从 projections 派生，前端不自行推断。
- Turn failed → session.status 仍为 active，允许同一会话继续下一题。

### 1.4 HTTP 路由与 Body 契约（单一 id 来源）
- 保留 7 条 canonical + 2 条 stream + 1 条 per-turn cancel + legacy `/cancel`：
  - `GET    /api/analysis/sessions`（`?status=active|archived`，非法值 400）
  - `POST   /api/analysis/sessions/turns`（首轮 JSON）
  - `POST   /api/analysis/sessions/turns/stream`（首轮 SSE）
  - `GET    /api/analysis/sessions/{session_id}`
  - `PATCH  /api/analysis/sessions/{session_id}`（`title` / `status: active|archived`）
  - `DELETE /api/analysis/sessions/{session_id}` → **soft archive**（v1 不物理删除）
  - `POST   /api/analysis/sessions/{session_id}/turns`（续轮 JSON）
  - `POST   /api/analysis/sessions/{session_id}/turns/stream`（续轮 SSE）
  - `POST   /api/analysis/sessions/{session_id}/turns/{turn_id}/cancel`（中断 Codex + 写 cancelled）
  - `POST   /api/analysis/sessions/{session_id}/cancel`（仅 archive session，旧行为保留）
  - `POST   /api/analysis/reports/{id}/sessions`（canonical `/analysis-thread` 重命名）
- Body 永不携带 session id：`extra="forbid"`；`sessionId` / `session_id` / `task_id` / `conversation_id` 出现即 422。
- URL `{session_id}` 是唯一可信 id；stream 路由收到 body 内 sessionId 与 URL 不一致 → 400 `session_id_mismatch`。
- Continuation 用 **不存在** 的 id → 404 `analysis_session_not_found`；不 lazy register、不造 orphan turn。
- `archived` 状态续传（JSON/stream）→ 409 `analysis_session_archived`；但 `GET /sessions/{id}` 仍 200（历史回放）。
- runtime disabled 时 stream 路由 503 `codex_runtime_not_configured`，强制走 JSON fallback。

### 1.5 所有权与数据完整性
- `CodexProjectionStore.upsert_item(session_id, turn_id, …)`：若 `turn.sessionId != session_id` → `ValueError`，拒绝跨 Session 污染。
- `CodexProjectionStore.save_turn(session_id, turn_id, …)`：同 id 已存在则必须属于同一 session，否则拒绝"重挂父"。
- DELETE 软归档：默认列表仅 `status=active`，`?status=archived` 可回查；DELETE 幂等（再 DELETE 同 row 仍是 200 + archived，非 404）。

### 1.6 前端 useFlow 单 id 入口
- `const flow = useFlow(sessionId)`；`sessionId` 为 null 表示新会话。
- `flow.start(question)` / `flow.send(content)` / `flow.reply(optionId)` **不再接受** `sessionId` 参数。
- 内部 `sessionIdRef = useRef(sessionId)` + `useEffect` sync；所有请求的 `AgentInput.sessionId` 都从该 ref 取，调用方无法绕过把 A 实例消息发到 B 的 session。

### 1.7 前端 cancelled 实例隔离
- `use-flow.ts` 取消模块级 `let cancelled=false`；替换为 `const cancelledRef = useRef(false)`，与 `runningRef` 均为实例级。
- 实例 mount 时 `cancelledRef.current=false` 重置；cleanup 置 true；A 卸载 / 切换 tab 不会影响 B 的流消费。

### 1.8 严格 UTF-8 契约
- 不做运行时 mojibake 修复：已删除 `_repair_text_encoding` / `_is_unreadable_legacy_text` / `cleanDisplayText` 的 `\uFFFD` 剥离。
- � 出现即数据在存储层已损坏，直接原样暴露，禁止 render-time 掩盖。

### 1.9 严格 Artifact 契约（Report）
- `ArtifactProjector.project_interactive_report` **仅接受** `item/completed + mcpToolCall` 且 payload 已带 `mcp_result.interactive_report`（完整预序列化报告）。
- 严格禁止"服务器根据 mcp_arguments 现场 `compile_interactive_report` 补齐缺失字段"；Agent 必须自己发出合法结构。
- `validate_report_artifact` 失败 → 返回 `None`（无 artifact 事件、无 silent patch、无字段删改）；Agent 下一轮自行重发 corrected payload。
- `source.threadId` / `source.turnId` 只从 Runner 的参数注入，不从 payload 的 caller 值读取。
- `compile_interactive_report` 现为 test fixture 专用，生产代码不导入不调用。

---

## 二、当前最终架构（职责边界）

```
┌──────────────────────────────────────────────────────────┐
│                  analysis_api.py  (HTTP 薄封装)          │
│  • DI 构造 3 个 services  • 参数+权限校验                 │
│  • XxxNotFoundError→404 / Conflict→409 / 422 from model │
│  • SSE streaming response wrapper & genbi/* event filter│
│  • 返回 envelope 兼容：snake/camel 双别名 + thread 字段  │
└────────────┬─────────────────────────────────────────────┘
             │  delegate
      ┌──────┴──────────────────────────────────────────────┐
      │   backend/services/ (业务 service 层，新拆分 P2-3)   │
      │                                                     │
      │ ┌──────────────────────┐  ┌──────────────────────┐  │
      │ │ SessionService       │  │ CodexTurnRunner      │  │
      │ │  • list_sessions     │  │  • AnalysisTurnReq   │  │
      │ │  • get_session_detail│  │  • run_turn_buffered │  │
      │ │    (turns+timeline+  │  │  • stream_first_turn │  │
      │ │     codexItemProj)   │  │  • stream_cont_turn  │  │
      │ │  • rename_session    │  │  • interrupt_turn    │  │
      │ │  • archive_session   │  │  • stream_runtime_   │  │
      │ │  • reactivate_session│  │    events(3-tuple)   │  │
      │ │  • delete_session    │  │  • _enrich + terminal │ │
      │ │  • resolve_session_id│  │    compensation       │ │
      │ └──────────┬───────────┘  └────────────┬─────────┘  │
      │            │                            │            │
      │            │               ┌────────────┴───────┐    │
      │            │               │ ArtifactProjector  │    │
      │            │               │  project_inter-    │    │
      │            │               │  active_report     │    │
      │            │               └──────┬─────────────┘    │
      └────────────┼──────────────────────┼──────────────────┘
                   │  persistence         │
      ┌────────────┴──────────┐    ┌──────┴─────────────┐
      │ SessionCatalog        │    │ CodexProjection    │
      │ (harness/session_     │    │ Store              │
      │  catalog.py)          │    │ (harness/codex_    │
      │  session rows only    │    │  projection_store) │
      │  active/archived FSM  │    │  turns + item projs│
      └───────────────────────┘    │  sequence + latest_│
                                   │  turn_{id,status}  │
                                   └────────────────────┘
```

- **`analysis_api.py`**：只保留 HTTP + DI + 薄错误映射；helper 从本文件删除。
- **`SessionService`**（新）：对 catalog + projections + artifact store 做读组装（session detail = session + turns + per-turn timeline + codexItemProjections 列表）与 CRUD。
- **`CodexTurnRunner`**（新）：start / resume / stream / interrupt；内部封装 provisioned 事件捕获、预创建 session/turn、每事件 fold projection、调 ArtifactProjector、终态补偿（`_interrupted_terminal_event` / `_missing_terminal_event`）。`interrupt_turn` 写 projection `status="cancelled"` + `mark_updated(session_id)`。
- **`ArtifactProjector`**（新）：严格 Artifact 契约（见 1.9）。
- **`SessionCatalog`** / **`CodexProjectionStore`**：两薄组件（PurityTest 锁边界）；不导入对方领域类型。
- **`create_app(thread_store=)` legacy shim**：仍保留以兼容老测试；长期目标删除，显式传 `session_catalog=` / `codex_projection_store=`。

---

## 三、最新一次验证（2026-08-05 本轮 P2 全通过）

### 后端 pytest
- `backend/tests/test_analysis_api.py`：**64 / 64 passed**。
- `backend/tests/test_codex_projection_store_purity.py`：**10 / 10 passed**。
- `py_compile`：`session_service.py` / `codex_turn_runner.py` / `artifact_projector.py` / `analysis_api.py` / `test_analysis_api.py` 全部 0 syntax error。
- （历史遗留 collection error 1 个：`test_codex_mcp_config.py::test_codex_mcp_server` 顶层 fixture 命名问题，与本轮无关，不阻塞。）

### 前端
- `npx tsc --noEmit`：**0 errors**。
- `npx vitest run`：**Test Files 18 passed / 18**；**Tests 95 passed / 95**。
  - `analysis-backend-client.test.ts`：含 never-leaks-session-id（A→B 不泄漏）、forwards latestTurnStatus、failed turn 后仍能续发、projection-only replay。
  - `analysis-flow-streaming.test.ts`：13 条 streaming。
  - `analysis-task-copy.test.ts`：契约断言"start 签名不含 `(content, currentAnalysisTaskId)`"，只允许单 id 入口。

### 行为关键断言（均 200 / passed）
1. `SessionOwnershipTest`：首轮 forged `metadata.codex_session_id` 永不生效；disabled runtime 两端点 503 不造行；未知 id continuation 两端点 404。
2. `TurnCancellationTest`：per-turn cancel 写 `status="cancelled"` 且 session 仍 active；legacy `/cancel` 只 archive。
3. `StreamingResolvedTurnIdTest`：`CodexTurnRunner.stream_runtime_events` 三元组解包；`resolved_turn_id` 到达 enrichment 与 artifact lineage；preflight id 不会泄漏到下游。
4. `SessionTurnStateDecouplingTest`：turn failed → session 仍 active；列表带 `latestTurnStatus`。
5. `SessionContinuationBodyContractTest`：body 含 `sessionId/session_id/task_id/conversation_id` / `turn_kind=start` → 422；`turn_kind in {message,reply}` → 200。
6. `test_*_soft_archives_instead_of_orphan_deletion`：DELETE 后 200+archived；默认列表空；`?status=archived` 回查；续传 409；无孤儿 turn/projection。
7. `test_upsert_item_rejects_turn_belonging_to_another_session` + `test_save_turn_rejects_moving_existing_turn_across_sessions`：跨 Session 挂 item / move turn 均 ValueError。
8. `test_report_payload_mcp_item_emits_artifact_without_server_tool_fields`：`ArtifactProjector(store).project_interactive_report` 返回 `genbi/artifact/updated`；只有 `mcp_result.interactive_report` 的完整 payload 能成功。
9. 严格 UTF-8：`test_returns_text_verbatim_no_runtime_encoding_repair` + `test_does_not_mask_mojibake_at_read_time`。

---

## 四、仍存在的风险

1. **`create_app(thread_store=)` legacy shim 残留**：P2-3 拆分后 API 仍暴露该兼容入口；仍允许调用方绕开"两薄组件"边界注入老的万能 ThreadStore。下一切片删除，显式只接受 `session_catalog=` / `codex_projection_store=`。
2. **严格 Artifact 静默 None 无 audit trail**：`project_interactive_report` 校验失败直接 None，无前端提示、无审计事件；如果真实 Codex Agent 仍发出 old-style `mcp_arguments`-only，会出现"点了生成报告但 UI 没反应"的黑盒。下一切片补 `genbi/artifact/validation_failed`。
3. **interrupt 失败场景无 reconciliation**：`Codex runtime.interrupt()` 抛异常时（例如 turn 已结束但 registry 未清），仅 `LOGGER.warning` + 仍然把 projection 写为 `cancelled`。用户看到"已停止"，但 Codex 实际上可能仍在跑工具。下一考虑补 heartbeat / 轮询 reconciliation。
4. **Soft DELETE 语义 vs 前端提示错位**：`DELETE` 实际只 archive（可通过 `?status=archived` 回查 + PATCH 还原）；前端提示"删除后不可恢复"与实际不一致。需要补回收箱 UI（reactivate）或升级为强语义 purge（事务级 cascade 物理删）。
5. **`SessionCatalog.delete_session()` 仍可绕过 API 层删行**：catalog 公开方法仍存在；当前仅 API 不再调用。若内部 CLI / 运维脚本直接用会漏 turn/projection 孤儿。
6. **Git 分支历史分叉未推远端**：当前 feature/session-management 与远端有历史分叉；推送时需非强推方式合并，保证本地代码状态完整。
7. **Codex 真实启动延迟未端到端观测**：mock 测试通过，实际 Codex CLI 首轮冷启动延迟会同步反映到 stream `/turns/stream` 的首字节延迟。环境噪音（.pytest_cache 权限、PowerShell 中文字符显示、starship 未装提示）不影响代码正确性。
8. **历史遗留 UT collection error**：`test_codex_mcp_config.py` 顶层函数名为 `test_codex_mcp_server` 误被 pytest 当 fixture 采集，1 个错误（与本轮无关）。需 rename helper 为 `_codex_mcp_server_spec_helper`。

---

## 五、下一步（按优先级 1–6）

1. **提交本轮 P2 修复**（Conventional Commit，非强推）：
   ```
   refactor(api+frontend+services): P2 session+turn boundary split

   - useFlow(sessionId) closes over its own id; start/send/reply drop
     the redundant sessionId param so A instance cannot address B.
   - module-level cancelled → cancelledRef per hook instance so
     unmount/switch does not kill sibling flows.
   - SessionService / CodexTurnRunner / ArtifactProjector extracted
     from analysis_api.py; HTTP layer now only validates + delegates.
   - Strict UTF-8: no runtime mojibake repair. Strict artifact: no
     silent compile of incomplete report payloads.
   ```
   Files：`backend/api/analysis_api.py`、`backend/services/{session_service,codex_turn_runner,artifact_projector}.py`、`backend/harness/codex_projection_store.py`（metadata= 修正）、`frontend/src/modules/analysis/hooks/use-flow.ts` + `components/AnalysisWorkspace.tsx`、`backend/tests/test_analysis_api.py`、`frontend/tests/analysis-task-copy.test.ts`、`docs/plans/current.md`。
2. **合并远端分叉 + 推送 `feature/session-management`（no force）**。
3. **浏览器 smoke**：
   - 新建 → 第一题 → 停止按钮；SSE abort + `POST /sessions/{id}/turns/{t}/cancel` → turn 立刻 cancelled（session 仍 active）。
   - 两 tab 独立 useFlow；A 卸载/重挂载不影响 B 的 running/cancelled（P2-2 回归）。
   - DevTools 断点尝试改发其它 sessionId；TypeScript 层签名拒绝 + 运行时从 `sessionIdRef.current` 读，无法绕过。
4. **历史遗留清理**：
   - Rename `codex_mcp_config.py` 顶层 `test_codex_mcp_server` → `_codex_mcp_server_spec_helper`，消除 1 个 collection error。
   - 删除 `create_app(thread_store=)` legacy shim。调用方一律显式传 `session_catalog=` / `codex_projection_store=`。
5. **下一 Service 边界切片（Projection Fold 纯状态机）**：从 `CodexTurnRunner.stream_runtime_events` 中再抽出 `TurnProjectionFold`：provisioned→预创建/每事件 fold/projector/终态补偿 抽成纯状态机；`CodexTurnRunner` 仅负责 I/O（runtime stream + SSE yield + store persistence）。目标：Fold 逻辑可纯 UT，不需要启动真实 runtime。
6. **下一严格 Artifact 切片（validation_failed audit event）**：`project_interactive_report` 返回 None 时发 `genbi/artifact/validation_failed`（含 session/turn id + `validate_report_artifact` 错误列表）；前端 toast 展示给用户并提示"Agent 提交的报告数据不完整，已要求修正后重发"，消除静默黑盒。
