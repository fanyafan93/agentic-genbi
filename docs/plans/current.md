# 当前分支状态

更新时间：2026-08-05 Asia/Shanghai

## 分支

- 当前分支：`feature/session-management`
- 基线：`Agentic-GenBI`
- 本轮目标：只处理 PostgreSQL 行级 CRUD，不改权限、UI 或 Session/Turn/Item 模型。

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

## 已验证

- `python -m pytest backend\tests\test_postgres_p0_compat.py -q`
  - 9 passed
- `python -m pytest backend\tests\test_session_catalog_purity.py backend\tests\test_codex_projection_store_purity.py -q`
  - 19 passed
- `python -m pytest backend\tests\test_analysis_api.py -q`
  - 65 passed
- `python -m pytest backend\tests\test_postgres_p0_compat.py backend\tests\test_session_catalog_purity.py backend\tests\test_codex_projection_store_purity.py backend\tests\test_analysis_api.py -q`
  - 93 passed
- `git diff --check`
  - passed
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
   - 本轮按范围约束未处理权限。

2. 单 worker 强制限制
   - `_active_turns` 仍是进程内字典。
   - V1 仍需启动时限制 backend 单 worker，后续再做跨进程 turn registry。

3. 小 P1 收尾
   - 前端处理 `genbi/artifact/failed`。
   - `session/created` 时更早记录 `codexTurnId`。
   - 删除默认示例问题。
   - `_active_turns` 在 interrupt 成功后再 `pop`。
   - 报表创建 Session 时禁止客户端伪造 Codex ID。

## 下一步

1. Principal 多用户隔离。
2. 强制单 worker。
3. 小 P1 收尾。
