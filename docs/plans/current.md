# 当前任务

更新时间：2026-07-31（Asia/Shanghai）

## 当前分支

- 仓库：`E:\my_repo\agentic genbi`
- 分支：`feature/analysis-task-next`
- 当前切片：文档收敛 + 前端 IA/mock 改造后的架构方向整理。

## 当前产品方向

```text
用户在分析工作台提出业务问题。
openai-codex Python SDK / Codex 负责编排：规划、执行、反思、工具调度、上下文和事件流。
业务语义库让 Agent 看懂数据和业务。
分析资产库让报告、图表、SQL、数据快照、分析路径、SKILL.md 可复用。
安全、权限、SQL、数据访问和审计必须在服务端。
```

原则：能用 Codex 的，绝不自研；本项目只做业务语义、数据安全、分析资产治理、前端体验和 Codex 适配层。

不再把“分析任务”和“知识探索”做成两个并列入口；知识探索能力应收敛成 Harness 背后的语义查证工具。

## 当前工作区改动

文档：

- `AGENTS.md`：已收敛为协作卡片。
- `README.md`：已收敛为项目一页总览。
- `docs/product/product-scope.md`：已收敛为产品边界，核心对象统一为产品层“分析任务 / 分析会话 / 分析资产”和系统层 `Thread / Turn / Item`。
- `docs/architecture/overview.md`：已收敛为架构边界，把 API/SSE 口径调整为 Thread/Turn/Item 事件边界，并写入 Codex 优先原则。
- `docs/plans/current.md`：已收敛为当前快照。

前端：

- `AnalysisWorkspace.tsx`：一级导航改为工作台、分析工作台、分析资产库、业务语义库、系统。
- `AnalysisAssetLibrary.tsx`：右侧只保留当前任务资产。
- `AnalysisAssetLibraryPage.tsx`：新增独立分析资产库 mock。
- `BusinessSemanticLibrary.tsx`：新增业务语义库 mock。
- mock Agent 文案已改为检索业务语义库、语义查证、读取报表语义/字段/血缘/SQL 示例。
- `analysis/types/analysis.ts`：新增系统层 `AnalysisSystemThread`、`AnalysisSystemTurn`、`AnalysisSystemRun`、`AnalysisSystemItem` 类型。
- `agentClients/types.ts` 和 `backendClient.ts`：前端 Agent 事件可携带 `threadId`、`turnId`、`runId`、`itemId`，兼容现有 UI。

后端：

- `backend/analysis/run_service.py`：分析事件 payload 开始补齐 `thread_id`、`turn_id`、`run_id`、`item_id`、`item_kind`，旧 `conversation_id` 继续兼容。
- `backend/harness/thread_store.py`：新增 Thread/Turn/Run/Item JSONL 保存层。
- `backend/persistence/postgres_stores.py`：新增 `PostgresThreadStore`，默认建 `analysis_threads`、`analysis_turns`、`analysis_runs`、`analysis_items`。
- `AnalysisRunService`：分析任务不再默认写旧 trace/event store，改为写新 ThreadStore；旧参数保留用于兼容测试和过渡。
- `backend/api/exploration_api.py`：新增 `GET /api/analysis/threads` 和 `GET /api/analysis/threads/{thread_id}`，`GET /api/analysis/tasks/runs/{run_id}` 会返回 `systemRun`；默认配置 Postgres 时使用 `PostgresThreadStore`，否则回退 JSONL。
- `backend/harness/codex_sdk_runner.py`：新增 openai-codex Python SDK 最小 runner，支持启动/恢复 Codex thread、消费 stream、映射消息事件，并默认使用只读 sandbox 和拒绝权限升级。
- `backend/api/exploration_api.py`：`GENBI_ANALYSIS_RUNTIME=codex` 时注入 `CodexSdkAnalysisRunner`；`llm/openai` 仍回退旧 `OpenAIAnalysisAgentRunner`。
- `backend/analysis/run_service.py`：向 runner 传递 `thread_id`、`turn_id`、`run_id` 和可选 `codex_thread_id`，并保持旧 runner 签名兼容。

## 已验证

- `cmd /c npm run test`：9 个前端测试文件 / 68 个测试通过。
- `cmd /c npm run build`：Next.js build 通过。
- `python -m unittest backend.tests.test_analysis_run_service -v`：3 个后端测试通过。
- `cmd /c npm run test -- tests/analysis-task-copy.test.ts tests/analysis-asset-library-interactions.test.tsx`：2 个前端测试文件 / 14 个测试通过。
- `python -m unittest backend.tests.test_thread_store backend.tests.test_analysis_run_service backend.tests.test_analysis_api -v`：10 个后端测试通过。
- `python -m py_compile backend\harness\thread_store.py backend\persistence\postgres_stores.py backend\analysis\run_service.py backend\api\exploration_api.py`：通过。
- `python -m unittest backend.tests.test_codex_sdk_runner backend.tests.test_analysis_agent_runner backend.tests.test_analysis_run_service backend.tests.test_analysis_api -v`：20 个后端测试通过。
- `python -m py_compile backend\harness\codex_sdk_runner.py backend\analysis\run_service.py backend\api\exploration_api.py`：通过。
- openai-codex Python SDK 安装验证通过：`openai-codex==0.144.4`、`openai-codex-cli-bin==0.144.4`。
- Codex SDK runner 真实 smoke 通过：`CodexSdkAnalysisRunner.stream(...)` 返回 13 个 item，最终文本为 `Codex SDK smoke ok。`。
- AnalysisRunService + CodexSdkAnalysisRunner + ThreadStore 真实 smoke 通过：64 个事件，`run.completed=True`，包含 `runtime=openai-codex`，保存 12 个 ThreadStore item。
- Docker backend 重建通过：backend 镜像已安装 `openai-codex==0.144.4`，容器内 `GENBI_ANALYSIS_RUNTIME=codex`，`openai_codex` 可导入。
- Codex SDK runner 已支持 MiniMax provider：当 `GENBI_LLM_PROVIDER=minimax` 或 `GENBI_CODEX_PROVIDER=minimax` 时，会配置 `model_providers.minimax`、`wire_api=responses`、`base_url=https://api.minimaxi.com/v1`，并复用 `MINIMAX_API_KEY`。
- Docker HTTP smoke 通过：`thread_codex_minimax_http_smoke_4` / `run_analysis_a4d02e297cee` 返回 `run.completed`，包含 `runtime=openai-codex`、Codex MiniMax delta、message、artifact 事件。
- Docker SSE smoke 通过：`POST /api/analysis/tasks/runs/stream` 返回 200，包含 `event: agent.message.delta`、`openai-codex` 和 `event: run.completed`。
- ThreadStore / Postgres 回读通过：`GET /api/analysis/threads/thread_codex_minimax_http_smoke_4` 返回 completed thread、1 个 run、12 个 item；Postgres `analysis_runs` 有 1 条对应 run，`analysis_items` 有 12 条对应 item。
- Docker Postgres 冒烟通过：后端重启后 `GET /api/analysis/threads` 返回 200；`PostgresThreadStore` 创建 `analysis_threads`、`analysis_turns`、`analysis_runs`、`analysis_items`。
- Docker Postgres 写入验证通过：`thread_codex_pg_smoke` 写入 1 个 thread、1 个 turn、1 个 run、11 个 item，并可通过 `GET /api/analysis/threads/thread_codex_pg_smoke` 回读。
- 旧表验证通过：`run_analysis_3753e21b770f` 在 `exploration_run_traces` 和 `exploration_run_events` 中均为 0 条，分析任务没有再写旧 run trace/event 表。
- MiniMax 新 key 已通过 backend 容器最小请求验证：`status=200`，当前 key 指纹为 `sk-c...uLQU`。
- backend 健康检查通过：`GET /health` 返回 200。
- frontend 曾因 `.next` dev/prod 目录冲突返回 500；已清理 `frontend/.next` 并重启 frontend，页面恢复 200。

## 当前风险

- 后端仍有历史 runner 代码：`backend/analysis/agent_runner.py`、`backend/exploration/agent_runner.py`、`backend/resource_library/exploration_agent.py`。分析任务已有 openai-codex SDK runner；探索和工具侧仍需迁移，不自研替代 runtime。
- MiniMax 目前通过 Codex 自定义 model provider 接入，已通过最小 HTTP/SSE smoke；后续接工具时仍需验证工具调用、结构化输出、长上下文和错误恢复兼容性。
- ThreadStore 已有 Postgres 实现；迁移脚本、真实库集成冒烟和探索会话接入仍未完成。
- 独立分析资产库目前仍是静态 mock，未接真实 `GET /api/analysis/assets`。
- 业务语义库目前是前端 mock，未有真实持久化模型。
- `docker compose restart` 不会重新注入 `.env` 变更；改 key 后需要 `docker compose up -d --force-recreate --no-deps backend`。
- 文档已收敛，历史细节需要从 Git diff / commit 查，不再写在 `current.md`。

## 下一步

1. 把业务语义库、资源库和只读数据库访问包装成 Codex tool / MCP / Skill adapters。
2. 验证 Codex tool / MCP / Skill adapters 与 MiniMax provider 的兼容性，重点看工具调用、结构化输出、长上下文和错误恢复。

## 2026-07-31 追加切片：Codex thread 持久化恢复

- 本轮只做 `codex_thread_id` 持久化恢复，不接业务语义库、只读数据库和 Artifact tools。
- `ThreadStore` 新增 `get_thread_metadata()` 和 `get_runtime_thread_id()`，用于从 GenBI `thread_id` 读取运行时 thread 映射。
- `AnalysisRunService` 在调用 runner 前会从 `analysis_threads.metadata.codex_thread_id` / `runtime_threads.openai-codex` 自动恢复 Codex thread；在 run 完成保存时，会从事件 payload 中提取最新 `codex_thread_id` 写回 Thread metadata。
- 前端仍只需要传 GenBI `conversation_id`；不需要知道 Codex 内部 thread id。
- 已验证：`python -m unittest backend.tests.test_thread_store backend.tests.test_analysis_run_service backend.tests.test_codex_sdk_runner backend.tests.test_analysis_api -v`，17 个测试通过。
- 已验证：`python -m py_compile backend\harness\thread_store.py backend\analysis\run_service.py backend\tests\test_thread_store.py backend\tests\test_analysis_run_service.py` 通过。
- 已重启 Docker backend，`GET /health` 返回 200。
- 已验证 Docker HTTP smoke：`thread_codex_resume_smoke_150823` 第一轮 `resumed=false`，第二轮 `resumed=true`，两轮 `codex_thread_id` 相同，ThreadStore 回读 2 个 run / 20 个 item。
- 已验证 Docker SSE smoke：`POST /api/analysis/tasks/runs/stream` 返回 200，包含 `agent.message.delta`、`run.completed` 和 `openai-codex`。
- 下一步：先让前端正常使用当前后端问答；业务语义库、只读数据库和 Artifact tools 后续单独设计 Codex tool / MCP / Skill adapters。

## 2026-07-31 追加切片：收敛 Codex 回复重复落库

- Codex SDK 的 `item/completed` agent message 不再映射为 `agent.message.created`，避免和 `AnalysisRunService` 包装的最终“分析结果”重复入库。
- 当前保留 `agent.message.delta` 用于流式显示；最终可查询的 assistant 回复只保留 `AnalysisRunService` 生成的 `agent.message.created`。
- 已验证：`python -m unittest backend.tests.test_codex_sdk_runner backend.tests.test_analysis_run_service backend.tests.test_analysis_api -v`，15 个测试通过。
- 已验证：`python -m py_compile backend\harness\codex_sdk_runner.py backend\tests\test_codex_sdk_runner.py` 通过。
- 已重启 Docker backend。
- 已验证 Docker HTTP smoke：`thread_codex_single_message_152159` / `run_analysis_8438c7ce8e77` 的 `analysis_items` 中 `agent.message.created` 只有 1 条，title 为“分析结果”，并已写入 `codex_thread_id`。

## 2026-07-31 追加切片：前端流式回复渲染

- `BackendAnalysisAgentClient` 现在会把后端 `agent.message.delta` 映射成前端 `tokens` 事件，节点 ID 使用稳定的 `agent-{run_id}`。
- `useFlow` 的 `tokens` 分支现在在 agent 节点不存在时也会创建一个临时流式气泡，然后持续追加 delta 文本；最终 `agent.message.created` 会用完整内容 replace 同一个气泡。
- 已验证：`cmd /c npm run test -- tests/analysis-backend-client.test.ts tests/analysis-task-copy.test.ts`，2 个测试文件 / 20 个测试通过。
- 已验证：`cmd /c npm run build` 通过。
- 已重启 Docker frontend；首次探测在 Next dev 启动中连接关闭，重试 `GET http://192.168.101.12:3000/` 返回 200。
