# Agentic GenBI

Agentic GenBI 是面向数据分析师和运营人员的 AI Agent BI 工作台。用户在分析任务中与 Agent 协作解决业务问题，持续生成、更新和复用可核对的分析资产（Artifact）；资产可以自动刷新，并可进一步提炼和发布为可复用 Agent。

当前仓库是 **前端优先、mock-first** 演进中的产品原型：用可交互的界面和虚拟后端厘清系统边界，并逐步替换为真实 API、数据源、Agent Runtime 与持久化。

## 文档入口

1. [AGENTS.md](AGENTS.md)：协作、验证与 Git 规则。
2. [产品边界](docs/product/product-scope.md)：用户、信息架构、核心对象与产品原则。
3. [架构边界](docs/architecture/overview.md)：当前实现、前端目标架构与真实后端演进方向。
4. [当前任务](docs/plans/current.md)：当前工作区、验证、风险与下一步。

## 当前能力

- Next.js + TypeScript 分析工作台。
- 分析任务左中右布局：分析任务列表、对话/真实后端 Run 事件、分析资产库预览区；分析资产保存已具备最小后端 JSONL API，但共享库视图、跨用户权限和完整 Artifact 持久化仍在演进中。
- 分析任务后端已提供首个真实 Run API / SSE 纵切，可按快速分析/深度分析产生问题分类、语义模型检索计划、Agent 消息、追问和资产事件；前端可通过环境变量切换到该后端客户端。后端已预留 OpenAI Agents SDK 分析 Runner，配置后可由真实 Runner 生成分析回复。
- 本地 mock Agent 事件流、追问和基础图表渲染。
- 知识探索页面已按探索会话事件契约接入真实探索 API；不可用时明确失败，不再回退本地模拟事件。
- 飞书单点登录已按 Auth.js v5 接入前端，使用 Prisma + Docker Postgres 保存 DB session；知识探索列表会按登录用户隔离。
- Docker Compose 启动前端、知识探索后端和 Postgres：前端 `http://localhost:3000`，后端 `http://localhost:8000`，Postgres `localhost:5432`。
- Docker 真实后端默认把知识探索 Run trace、Run events 和知识沉淀保存到 Postgres；本地 JSONL store 仅保留为测试与离线开发存储。

调度、完整权限体系和完整 Agent Runtime 治理仍未实现。

## 本地启动

```bash
cd frontend
npm install
npm run dev
```

Docker Compose：

```bash
docker compose up --build
```

飞书登录需要在 `.env` 中配置：

```bash
AUTH_URL=http://localhost:3000
AUTH_SECRET=replace-with-a-long-random-secret
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
AUTH_DATABASE_URL=postgresql://agentic_genbi:agentic_genbi_dev_password@localhost:5432/agentic_genbi?schema=public
```

飞书开放平台回调地址配置为：

```text
http://localhost:3000/api/auth/callback/feishu
```

无网络或 Docker Hub 拉取失败时，可以先复用本地镜像启动：

```bash
docker compose up -d --no-build
```

前端接探索后端时配置：

```bash
set NEXT_PUBLIC_GENBI_API_BASE_URL=http://localhost:8000
```

前端分析任务接真实后端时额外配置：

```bash
set NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME=backend
set NEXT_PUBLIC_GENBI_API_BASE_URL=http://localhost:8000
```

分析任务后端启用 OpenAI Agents SDK Runner：

```bash
set GENBI_ANALYSIS_RUNTIME=openai
set GENBI_ANALYSIS_MODEL=gpt-4.1-mini
set GENBI_ANALYSIS_MAX_TURNS=30
set OPENAI_API_KEY=...
```

检查本地真实运行环境：

```bash
.venv\Scripts\python -m backend.config.env doctor
.venv\Scripts\python -m backend.config.env doctor --json --no-fail
```

`doctor` 会加载项目 `.env` 或 `GENBI_ENV_FILE` 指向的文件，并检查 LLM Runner、MySQL 只读连接、资源库、前端 API 地址和成本估算配置。默认缺少关键项时返回非零退出码；`--no-fail` 只打印报告。

后端也提供同一检查结果：

```bash
GET /api/runtime/status
```

前端知识探索页会读取该接口，并在标题区显示后端未连接、后端已连接但配置待补，还是关键配置已就绪。

## 验证

```bash
cd frontend
cmd /c npm run test
cmd /c npm run build
docker compose config
python -m unittest discover -s backend\tests
```

在 Windows PowerShell 中，如 `npm.ps1` 被执行策略拦截，使用 `cmd /c npm ...`。

## 资源库索引

本地真实资源放在 `资源库/`，该目录已被 Git 忽略。生成本地索引：

```bash
python -m backend.resource_library.indexer --root "E:\my_repo\agentic genbi\资源库" --output ".resource-index\resources.json"
```

索引输出 `.resource-index/` 也被 Git 忽略；当前只记录文件元信息、类型、大小、修改时间和 hash。

生成结构摘要：

```bash
python -m backend.resource_library.inspector --index ".resource-index\resources.json" --output ".resource-index\resource-summaries.json"
```

摘要只保留结构信号，如 XML 标签计数、候选参数、候选数据集、SQL 读写表、输出字段、FineReport 表达式候选和文件是否截断；不保存完整业务文件正文。

搜索、查看摘要和读取受控片段：

```bash
python -m backend.resource_library.tools search "复购率" --limit 5
python -m backend.resource_library.tools inspect res_xxx
python -m backend.resource_library.tools excerpt res_xxx --section match --query "dm_sale" --max-lines 80
```

`search` 和 `inspect` 不返回完整文件正文；`excerpt` 仅在明确指定资源时返回有限行数和字节数的片段。

前端资源详情页会把 `inspect` 返回的结构信号整理为表引用、读表、写表、数据集候选、参数候选、Hop 节点、输出字段、字段候选、表达式候选和命名节点等分组；点击“查看证据片段”时才读取受控 excerpt。

## 数据库只读工具

数据库连接通过 `.env` 或本机环境变量配置，密码不要提交 Git。后端启动和 CLI 会自动读取项目根目录 `.env`；也可以用 `GENBI_ENV_FILE` 指向其他 env 文件：

```bash
DATABASE_URL=mysql+pymysql://readonly_user:password@127.0.0.1:3306/dm
# 或使用 GenBI 专用字段覆盖 DATABASE_URL
NEXT_PUBLIC_GENBI_API_BASE_URL=http://localhost:8000
GENBI_RESOURCE_LIBRARY_ROOT=资源库
GENBI_DB_HOST=127.0.0.1
GENBI_DB_PORT=3306
GENBI_DB_USER=readonly_user
GENBI_DB_PASSWORD=...
GENBI_DB_DATABASE=dm
GENBI_BUSINESS_QUERY_ENABLED=true
GENBI_DB_MAX_ROWS=1000
```

校验 SQL：

```bash
python -m backend.resource_library.database_tools validate "select order_id from dm.sales"
```

工具默认只允许单条只读查询，禁止写操作、多语句和 `select *`，并会自动补默认 `limit`。

## 知识探索 Agent 后端

当前已提供 OpenAI Agents SDK 适配层、知识探索 Agent 提示词和工具注册。后端依赖建议安装在项目虚拟环境中：

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
```

已注册工具包括资源库搜索、资源结构查看、受控片段读取、数据库表搜索、表结构查询、业务只读 SQL 和知识沉淀。Docker 真实后端默认把知识沉淀写入 Postgres；本地 JSONL store 会写入被 Git 忽略的 `.resource-index/knowledge.jsonl`，仅作为测试与离线开发存储。

```bash
.venv\Scripts\python -m backend.resource_library.knowledge_store list
```

Docker 真实后端默认把探索 Run 追踪记录和事件流写入 Postgres，记录 Run 状态、耗时、事件数、工具调用数、消息数、token usage 和按配置估算的成本。本地 JSONL store 会写入 `.resource-index/run-traces.jsonl` 和 `.resource-index/run-events.jsonl`，仅作为测试与离线开发存储。配置模型价格后可计算成本：

```bash
set GENBI_MODEL_INPUT_USD_PER_1M=0.4
set GENBI_MODEL_OUTPUT_USD_PER_1M=1.6
.venv\Scripts\python -m backend.exploration.run_trace_store list
```

把现有本地 JSONL 迁入 Postgres：

```bash
python -m backend.scripts.migrate_file_stores_to_postgres
```

探索会话 API / SSE 已提供后端入口；前端知识探索已按同一事件契约接入，配置 `NEXT_PUBLIC_GENBI_API_BASE_URL` 后会优先调用 SSE stream 并增量更新探索过程，失败时回退一次性 conversation API，再失败则显示后端不可用，不再回退本地事件。SSE 端点会通过 async streaming 实时转发真实 Runner 的工具调用、工具输出和中间消息事件；一次性接口仍返回完整事件列表。探索过程里的“沉淀为知识”会调用 `POST /api/knowledge` 保存结论；未配置后端时保存失败，不更新本地 demo 列表。

知识探索 API 需要真实 Agent Runner。切换到真实 LLM Runner（默认 OpenAI）：

```bash
set GENBI_EXPLORATION_RUNTIME=openai
set GENBI_LLM_PROVIDER=openai
set GENBI_EXPLORATION_MODEL=gpt-4.1-mini
set GENBI_EXPLORATION_MAX_TURNS=30
set OPENAI_API_KEY=...
```

也可以用 `GENBI_EXPLORATION_RUNTIME=llm` 显式表示模型 Runner。MiniMax 先按 OpenAI-compatible endpoint 接入：

```bash
set GENBI_EXPLORATION_RUNTIME=llm
set GENBI_LLM_PROVIDER=minimax
set GENBI_EXPLORATION_MODEL=你的 MiniMax 模型名
set MINIMAX_API_KEY=...
set MINIMAX_BASE_URL=...
```

开启 LLM Runner 但缺少对应 provider 的 API key、模型名或 MiniMax base URL 时，Run 会返回 `agent.runner.failed` 和 `run.failed` 事件，不会伪装为成功。MiniMax 是否完整支持工具调用和 streaming 取决于其 OpenAI-compatible 接口能力；不兼容时会在真实 Run 中暴露错误。

Run 事件服务和 FastAPI 入口代码已存在：

```bash
.venv\Scripts\python -m backend.api.exploration_api
.venv\Scripts\python -m uvicorn backend.api.exploration_api:create_app --factory --host 0.0.0.0 --port 8000
```

启动 API 前需要先安装 `backend/requirements.txt`。当前本机已验证接口包括：

- `GET /health`
- `GET /api/runtime/status`
- `POST /api/explorations/runs`
- `GET /api/explorations/runs/{run_id}/events`
- `POST /api/explorations/runs/stream`
- `GET /api/explorations/run-traces`
- `GET /api/explorations/run-traces/{run_id}`
- `GET /api/resources/status`
- `GET /api/resources/search`
- `GET /api/resources/{resource_id}`
- `GET /api/resources/{resource_id}/excerpt`
- `POST /api/resources/reindex`
- `GET /api/knowledge`
- `POST /api/knowledge`
- `DELETE /api/knowledge/{record_id}`
- `DELETE /api/knowledge`
