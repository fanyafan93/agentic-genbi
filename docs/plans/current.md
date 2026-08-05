# 当前分支状态

更新时间：2026-08-05 Asia/Shanghai

## 分支

- 当前分支：`feature/session-management`
- 基线：`Agentic-GenBI`
- 本轮目标：在 PostgreSQL 行级 CRUD 之后，收掉小 P1 和单 worker 强制限制；Principal 多用户隔离仍单独处理。

## 本轮已处理

1. PostgreSQL SessionCatalogBackend 改为行级 CRUD
   - 新增 `get_session`、`resolve_session_id`、`list_sessions`、`insert_session`、`update_session`、`archive_session`、`touch_session`、`delete_session`。
   - `SessionCatalog` 在 backend 具备 row-level 方法时不再走 `_read_state()` / `_write_state()`。
   - `touch_session` 是单行 `UPDATE analysis_threads ... WHERE id = ...`。

2. PostgreSQL CodexProjectionBackend 改为行级 CRUD
   - 新增 `get_turn`、`list_turns`、`latest_turn`、`upsert_turn`、`upsert_item`、`list_items`。
   - `CodexProjectionStore` 在 backend 具备 row-level 方法时不再走 `_read_state()` / `_write_state()`。
   - Postgres projection backend 不再暴露通用 `read_state()` / `write_state()`。
   - Item 写入只对当前 item 执行 `INSERT ... ON CONFLICT DO UPDATE`。

3. PostgreSQL migration / index
   - 新增索引：
     - `analysis_threads (tenant_id, user_id, updated_at DESC)`
     - `analysis_turns (session_id, updated_at DESC)`
     - `analysis_codex_item_projections (genbi_session_id, genbi_turn_id, sequence)`
   - 历史 item replay 按 `sequence` 排序。
   - legacy projection 迁移补齐 `genbi_turn_id = codex_turn_id`，避免旧 item 无法按 turn 恢复。

4. 并发不覆盖测试
   - 覆盖不同 Session 写 item 不互相覆盖。
   - 覆盖一个 Session 的 Turn 从 `running` 到 `completed`，同时另一个 Session 写新 Turn，不会把 completed 覆盖回 running。
   - 覆盖两个 Session 分别 touch `updatedAt`，两个时间都保留。

5. 小 P1 收尾
   - 前端 `mapBackendEvents()` 已将 `genbi/artifact/failed` 映射为可见 `error` 事件。
   - 前端 start 请求不再把空问题替换为“渠道销售占比”默认示例；空输入直接 `done`，不发请求。
   - `_active_turns` 在 Codex SDK interrupt 成功后才 `pop`；interrupt 抛错时保留 handle，允许重试。
   - 报表创建 Session 调用 `_provision_codex_thread_id(..., allow_client_preflight=False)`，不再接受客户端 metadata 中伪造的 `codex_session_id` / `codex_thread_id`。

6. 单 worker 强制限制
   - `create_app()` 启动时检查 `GENBI_BACKEND_WORKERS`、`WEB_CONCURRENCY`、`UVICORN_WORKERS`。
   - 任一配置大于 1 时抛出 `backend_single_worker_required`，避免 V1 多 worker 下 cancel 请求进入没有 live Turn handle 的进程。

7. Turn / Item 全局 ID 完整性
   - `CodexProjectionStore.save_turn()` 写入前按全局 `turn_id` 查 owner，拒绝同一 Turn ID 写入不同 Session。
   - `CodexProjectionStore.upsert_item()` 写入前按全局 `codex_item_id` 查 owner，拒绝同一 Item ID 移动到另一个 Session/Turn。
   - Postgres backend 新增 `get_turn_by_id()` / `get_item()`。
   - Postgres `ON CONFLICT` 增加 owner 条件保护，避免绕过 Store 层时污染其他 Session。
   - Item 写入不再通过 `list_items(session_id, turn_id)` 扫描整个 Turn items 来查 existing item。

## 已验证

- `python -m pytest backend\tests\test_postgres_p0_compat.py -q`
  - 9 passed
- `python -m pytest backend\tests\test_session_catalog_purity.py backend\tests\test_codex_projection_store_purity.py -q`
  - 19 passed
- `python -m pytest backend\tests\test_analysis_api.py -q`
  - 65 passed
- `python -m pytest backend\tests\test_postgres_p0_compat.py backend\tests\test_session_catalog_purity.py backend\tests\test_codex_projection_store_purity.py backend\tests\test_analysis_api.py -q`
  - 93 passed
- `python -m pytest backend\tests\test_codex_sdk_runner.py backend\tests\test_analysis_api.py -q`
  - 79 passed
- `npm.cmd test -- analysis-backend-client.test.ts`
  - 29 passed
- `python -m pytest backend\tests\test_codex_projection_store_purity.py backend\tests\test_postgres_p0_compat.py -q`
  - 23 passed
- `git diff --check`
  - passed
- 真实 Docker PostgreSQL integrity smoke
  - 使用 backend 容器和临时真实 PostgreSQL 数据库验证：
    - Store 层拒绝跨 Session Turn ID 冲突。
    - Store 层拒绝跨 Session/Turn Item ID 冲突。
    - 直接绕过 Store 调用 Postgres backend upsert 时，`ON CONFLICT ... WHERE owner matches` 不覆盖原 owner 行。
  - 输出：`REAL_POSTGRES_INTEGRITY_OK`
- 真实 Docker PostgreSQL smoke
  - 使用 backend 容器和两个临时真实 PostgreSQL 数据库验证：
    - 全新数据库启动
    - 重复 `ensure_schema()` 幂等
    - Session/Turn/Item 行级写入
    - 两个 Session 写 item 不丢数据
    - Turn completed 不被另一个 Session 写入覆盖
    - 两个 Session touch `updatedAt` 不互相覆盖
    - 旧 schema + 旧数据迁移
  - 输出：`REAL_POSTGRES_SMOKE_OK`

测试警告：本机 pytest cache 目录无写权限；不影响测试结果。

## 尚未处理

1. Principal 多用户隔离
   - `GET/PATCH/DELETE/continue/cancel` 仍需接入 `tenant_id/user_id/workspace_id/roles` 校验。
   - 本轮按范围约束未处理权限，不可信任请求体里的 `user_id` / `userId`。

2. 跨进程 turn registry
   - V1 已通过单 worker guard 阻断多 worker。
   - 后续如果要支持多 worker，需要 Redis/数据库级 live turn registry 或 reconciliation。

## 下一步

1. Principal 多用户隔离。
2. 合入前全量前端、后端和 `docker compose config`。
3. 后续评估跨进程 turn registry。
