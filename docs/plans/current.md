# 当前任务

更新时间：2026-07-29（Asia/Shanghai）

## 当前状态

- 仓库：`E:\my_repo\agentic genbi`
- 分支：`feature/data-investigation-frontend`
- 当前切片：把知识探索的用户侧命名收口为“探索任务/探索过程”，底层 `Conversation` 只作为通用多轮交互能力，`run_*` 只保留为内部审计执行记录。
- 工作区注意：当前工作区已有大量历史未跟踪/已修改文件，本轮只处理知识探索继续追问链路、相关测试和文档，不回退无关改动。

## 本轮变更

- 新增 PostgreSQL 持久化实现：
  - `exploration_run_traces`：保存探索 Run 汇总。
  - `exploration_run_events`：保存探索 Run 完整事件流。
  - `verified_knowledge`：保存知识沉淀记录。
- 保留原 JSONL store 作为测试与离线开发存储，不作为知识探索运行时降级路径。
- `docker-compose.yml` 中 backend 默认启用 `GENBI_PERSISTENCE=postgres`，并通过 `GENBI_DATABASE_URL` 连接同一个 Postgres。
- 新增迁移脚本：`python -m backend.scripts.migrate_file_stores_to_postgres`，用于把 `.resource-index/*.jsonl` 迁入 Postgres。
- API 默认服务现在把同一个 knowledge store 注入给 Agent 工具和 `/api/knowledge`，避免写入和读取不一致。
- 新增后端依赖：`psycopg[binary]`。
- 知识探索继续追问不再由前端构造“这是同一个知识探索会话...”的合成问题；前端只发送用户本轮真实输入。
- 后端 `RunTraceStore`/Postgres trace store 新增按 `conversation_id` 查找最近关联 Run 的能力。
- 真实 Agent Runner 调用前，后端会读取同一探索会话的历史事件，整理为受控上下文，再附加本轮追问。
- 后端新增探索会话 API：`POST/GET/DELETE /api/explorations/conversations` 和 `POST /api/explorations/conversations/stream`；旧 `/api/explorations/runs/*` 保留兼容。
- 新建探索任务现在生成独立 `conv_*`，每次提问/追问生成单独 `run_*`；一个 `conv_*` 下可聚合多个 `run_*`。
- 前端知识探索改为调用 conversation API；恢复会话详情时会聚合同一 `conversation_id` 下的多轮用户消息和 Agent 输出。
- 前端探索页标题区小标签展示当前探索 ID；知识探索左侧仍是“探索任务”，内部 `run_*` 改为用户可见的“执行追踪”。
- 架构文档补充命名边界：底层 `Conversation` 可复用于分析、知识探索、Agent 调试等模块，但知识探索 UI 不泛称“会话”。
- 去掉“你好/你能干什么”等固定短路回复；有真实 Agent Runner 时统一进入 Agent 链路。
- 去掉知识探索本地模拟降级：未配置真实 Agent Runtime 或后端不可用时明确失败，不再生成本地模拟搜索、证据或追问。
- 前端会自动过滤旧浏览器缓存中的 `local-*` 探索任务，避免历史本地占位继续出现在探索列表。
- SDK `message_output_created` 流事件不再额外渲染为“探索进展”，避免最终回答同时显示成进展和结论。
- 资源库索引已用当前本机 `E:\my_repo\agentic genbi\资源库` 重建，当前索引包含 3450 个资源。
- `ResourceLibrary` 读取资源原文片段时会优先使用索引 root；如果索引 root 在当前运行环境不可用，则回退到 `GENBI_RESOURCE_LIBRARY_ROOT` 或项目下 `资源库`，避免本机路径与 Docker 容器路径互相影响。

## 已验证

- `python -m unittest backend.tests.test_exploration_api -v`：11 个探索 API 测试通过，包含会话 API 聚合多轮执行记录。
- `python -m unittest discover -s backend\tests -v`：71 个后端测试通过。
- `python -m compileall -q backend`：通过。
- `cmd /c npm run test -- investigation-events`：33 个前端事件映射测试通过。
- `cmd /c npm run build`：Next.js 构建通过。
- `docker compose config --quiet`：Compose 配置可解析。
- `docker compose up -d --build backend frontend`：backend、frontend、postgres 均已启动。
- 最后一次 `docker compose ps` 确认 `agentic-genbi-backend-1`、`agentic-genbi-frontend-1` 和 `agentic-genbi-postgres-1` 均在运行。
- 已通过 `POST /api/explorations/conversations` 直接验证新建探索返回 `conv_*`，连续两轮消息会在同一个 `conv_*` 下产生多个 `run_*` 并聚合；临时验证记录已删除。
- 已执行迁移脚本，迁移结果：
  - `run_traces`: 72
  - `run_events`: 20814
  - `knowledge_records`: 4
- 已直接查询 Postgres，三张表计数与迁移结果一致。
- `GET http://192.168.101.12:8000/api/explorations/runs?limit=3` 可从后端返回已迁移 Run。
- `GET http://192.168.101.12:8000/api/knowledge?limit=3` 可从后端返回已迁移知识。
- 已通过 `/api/knowledge` 创建并删除临时记录 `kn_7645534f8a45`，验证新写入路径也走 Postgres。
- 后端容器中已确认 `GENBI_PERSISTENCE=postgres`，且 `GENBI_DATABASE_URL` 已配置（未输出连接串）。
- `python -m unittest backend.tests.test_resource_tools -v`：5 个资源库工具测试通过，包含索引 root 不可用时回退到运行环境资源目录的用例。
- `python -m backend.resource_library.tools search "推广总览明细表" --limit 3`：命中 `res_1c3d8e6e772a0f52`。
- `python -m backend.resource_library.tools excerpt res_1c3d8e6e772a0f52 --section match --query dm_adv_tm_total --max-lines 40`：可读取 `推广总览明细表.cpt` 中受控 SQL 片段。

## 边界与风险

- 资源库原文件、结构摘要和搜索索引本轮不迁入数据库；它们仍是可重建的本地文件索引与受控片段读取能力。
- 当前 PostgreSQL 表由后端启动时 `CREATE TABLE IF NOT EXISTS` 创建，尚未接入正式 Alembic/Prisma 迁移治理。
- 当前已提供用户侧 `conv_*`，但数据库仍沿用 run trace/event 聚合同一 `conversation_id`；尚未建立正式 `Conversation` / `Message` 表。
- 完整会话、Artifact、Agent、Automation、权限、审计和对象存储仍未迁移。
- `GET /api/runtime/status` 仍提示缺少模型成本估算价格；Run trace 会保留 token，但成本字段可能为空。

## 下一步

1. 后续把探索会话的用户权限校验下沉到后端，而不是只依赖前端传 `user_id`。
2. 为知识探索补正式 `Conversation` / `Message` 模型，替代当前基于 Run trace 的聚合实现。
3. 为 PostgreSQL 持久化补正式迁移体系和最小集成测试。
