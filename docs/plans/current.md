# 当前任务

更新时间：2026-08-02（Asia/Shanghai）

> 本页只记录当前可验证状态；实现过程和历史细节交给 Git。

## 当前状态

- 分支：`Agentic-GenBI`。
- 当前产品形态：用户在分析工作台对话；右侧展示、编辑和保存当前分析结果；“我的分析”查看已保存结果和历史版本。
- 最终职责边界已写入 `README.md`、`docs/product/product-scope.md` 和 `docs/architecture/overview.md`：
  - Codex 负责 Agent Loop、Thread、Turn、Item、上下文、上下文压缩、工具调度、流式执行事件、中断和追加指令、Sandbox / Approval 基础能力。
  - GenBI 负责用户和租户、数据权限、数据源、FineReport 语义案例、指标与关联规则、受控 SQL 工具、Artifact、Artifact 版本和血缘、分享、发布和治理。
- 分析工作台外部主线已收敛为 Thread / Turn / Item：
  - 新建首轮：`POST /api/analysis/threads/turns` 和 `/stream`。
  - 追加上下文：`POST /api/analysis/threads/{thread_id}/turns` 和 `/stream`。
  - 读取单轮：`GET /api/analysis/threads/{thread_id}/turns/{turn_id}`。
  - 旧 `/api/analysis/tasks/runs*` 外部入口已移除。
- 分析 SSE 不再发 `run.created` / `run.completed` 作为生命周期事件；前端只从 `turn/started`、`turn/completed`、`item/*`、`genbi/artifact/*` 映射会话、调试和结果。
- `run_id` / `runId` 仍保留为内部 execution attempt 和旧存储兼容镜像；新的外部响应以 `thread_id`、`turn_id`、`execution_attempt_id`、`latest_execution_attempt_id` 为主。
- 探索模块 `/api/explorations/runs/*` 仍是历史探索能力，不属于本轮分析工作台边界迁移范围。

## 已完成

- 移除了分析工作台旧 Run HTTP 入口和相关响应里的 `run_id` / `latest_run_id` 主字段。
- 将分析 HTTP body/helper 命名从 Run 语义改为 Turn 语义。
- 删除分析服务额外生成的 `run.created` / `run.completed` 兼容生命周期事件。
- 前端 backend client 删除旧 `run.created` / `run.completed` 映射分支；测试夹具迁到 `turn/started` / `turn/completed`。
- Artifact source、lineage、Codex Item projection、Thread/Turn 映射继续保留上一轮已完成状态。

## 已验证

- `python -m unittest backend.tests.test_analysis_api backend.tests.test_analysis_run_service -v`：20 项通过。
- `npm.cmd test -- tests/analysis-backend-client.test.ts`：15 项通过。
- `python -m unittest discover backend\tests -v`：129 项通过。
- `npm.cmd test`（frontend）：13 个测试文件 / 89 项通过。
- `npm.cmd run build`（frontend）：通过。
- `docker compose config`：成功输出配置；Docker 同时提示读取 `C:\Users\Jason\.docker\config.json` 被拒绝。

## 当前限制

- `AnalysisRunService` 类名、`AnalysisRunRequest` 类型名、`run_id` 字段和部分存储表述仍作为 execution attempt 兼容层存在，尚未完全重命名。
- Artifact 和报告响应仍会镜像旧 `runId/sourceRunId`，用于兼容旧前端和历史数据。
- 用户、租户、RLS、分享、发布、治理和生产级权限绑定仍未完成。

## 下一步

1. 将内部 `AnalysisRunService` / `AnalysisRunRequest` 命名继续迁移到 Thread / Turn / ExecutionAttempt 语义。
2. 让 Artifact lineage 优先依赖 `codex_thread_id / codex_turn_id / codex_item_id`，进一步弱化 `sourceRunId`。
3. 把资源库、数据库和业务语义库作为受控 Codex tools / MCP 接入。
