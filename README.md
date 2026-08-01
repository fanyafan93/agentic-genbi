# Agentic GenBI

## 一句话

用户在分析工作台提出业务问题；openai-codex SDK / Codex 编排业务语义库、数据层和受控工具，产出可验证、可复用的分析资产。

## 当前方向

```text
分析工作台：提出问题、回答追问、查看过程、修改当前资产。
业务语义库：让 Agent 看懂数据和业务，包含语义模型和业务知识。
分析资产库：保存和复用报告、图表、SQL、数据快照、分析路径、SKILL.md。
系统：数据源、权限、安全、模型、工具、审计和成本。
```

不再把“分析”和“知识探索”做成两个并列入口；语义查证是编排层后台能力。

## 目标架构

```text
交互层：统一分析工作台。
编排层：openai-codex Python SDK / Codex，负责规划、执行、反思、工具调度和事件流。
语义层：业务语义库，包含语义模型和业务知识。
数据层：只读、安全、可审计地访问 MySQL、Doris、报表、ETL、金蝶等数据源。
Artifact 层：版本化保存报告、图表、SQL、代码、数据集快照、过程和 SKILL.md。
治理层：RBAC/RLS、敏感字段、审批、发布、审计、成本和运行安全边界。
```

MiniMax、OpenAI-compatible 或其他模型只是 Codex 的 model adapter，不是系统架构本身。能用 Codex 的，绝不自研；本项目只做业务语义、数据安全、分析资产治理、前端体验和 Codex 适配。

## 当前实现快照

- 前端：Next.js + TypeScript，分析工作台 / 分析资产库 / 业务语义库 mock 已有。
- 后端：FastAPI，已提供分析 Run API / SSE、资源库工具、数据库只读工具、知识记录、分析资产最小存储；分析 Thread/Turn/Run/Item 已写入 Postgres；分析 runner 已有 openai-codex Python SDK 最小适配。
- 登录：Auth.js + 飞书 OAuth + PostgreSQL session。
- 运行：Docker Compose 启动 frontend、backend、postgres。
- 仍未完成：Codex 工具/MCP/Skill 接入、完整业务语义库持久化、完整 Artifact 治理、团队权限/RLS、生产数据源治理。

详细状态看 `docs/plans/current.md`，不要从历史段落推断当前完成度。

## 本地运行

```bash
docker compose up -d --build
```

访问：

```text
frontend: http://localhost:3000 或 http://192.168.101.12:3000
backend:  http://localhost:8000 或 http://192.168.101.12:8000
health:   http://192.168.101.12:8000/health
runtime:  http://192.168.101.12:8000/api/runtime/status
```

前端开发：

```bash
cd frontend
npm install
npm run dev
```

## 常用配置

项目根目录 `.env`：

```bash
NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME=backend
GENBI_PUBLIC_API_BASE_URL=http://192.168.101.12:8000

GENBI_ANALYSIS_RUNTIME=codex
GENBI_EXPLORATION_RUNTIME=local
GENBI_LLM_PROVIDER=minimax
GENBI_ANALYSIS_MODEL=MiniMax-M3
GENBI_EXPLORATION_MODEL=MiniMax-M3
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_API_KEY=...
GENBI_CODEX_PROVIDER=minimax # 可省略；GENBI_LLM_PROVIDER=minimax 时自动映射
GENBI_CODEX_API_KEY=...      # OpenAI/Codex 时使用；MiniMax 默认复用 MINIMAX_API_KEY
```

修改 `.env` 后，`docker compose restart` 不一定重新注入变量；需要：

```bash
docker compose up -d --force-recreate --no-deps backend
```

## 验证

```bash
cd frontend
cmd /c npm run test
cmd /c npm run build

python -m unittest discover -s backend\tests -v
docker compose config
```

## 文档入口

- `AGENTS.md`：协作规则。
- `docs/product/product-scope.md`：产品边界。
- `docs/architecture/overview.md`：架构边界。
- `docs/plans/current.md`：当前分支状态。

文档只保留能帮助人继续做事的信息；历史过程交给 Git。
