# Agentic GenBI

## 一句话

用户在分析工作台提出业务问题；Codex 负责通用 Agent 工程底座，GenBI 负责业务语义、数据权限、受控 SQL 工具、Artifact 版本和治理。

## 当前方向

```text
分析工作台：提出问题、追问、查看过程、生成和修改当前分析结果。
业务语义库：维护 FineReport 语义案例、指标、字段、关联规则和业务知识。
我的分析：查看已保存的分析结果、历史版本和分析模板。
系统：管理数据源、权限、安全、模型、工具、审计和成本。
```

单一主入口是分析工作台。

## 最终边界

Codex 负责：

- Agent Loop
- Thread
- Turn
- Item
- 上下文与上下文压缩
- 工具调度
- 流式执行事件
- 中断和追加指令
- Sandbox / Approval
- 失败、重试和内部请求尝试

GenBI 负责：

- 用户和租户
- 数据权限
- 数据源
- FineReport 语义案例
- 指标与关联规则
- 受控 SQL 工具
- Artifact
- Artifact 版本和血缘
- 分享、发布和治理

## 目标架构

```text
交互层：统一分析工作台
Codex：Agent Loop / Thread / Turn / Item / 上下文 / 工具调度 / 事件流
语义层：业务语义库，包含 FineReport 语义案例、指标和业务知识
数据层：只读、安全、可审计地访问 MySQL、Doris、报表、ETL、金蝶等数据源
Artifact 层：版本化保存报告、图表、SQL、数据快照、分析路径和 SKILL.md
治理层：RBAC / RLS、敏感字段、审批、发布、审计、成本和运行安全边界
```

MiniMax、OpenAI-compatible 或其他模型只是 Codex 的 model adapter，不是系统架构本身。能用 Codex 的能力，就不在 GenBI 里重复实现。

## 当前实现快照

- 前端：Next.js + TypeScript。分析工作台提供左侧分析线程和右侧交互式分析结果；结果以 Puck JSON 描述布局，ECharts / AG Grid 渲染图表与表格，并优先读写后端报告版本接口。
- 后端：FastAPI。分析工作台主入口收敛到 Codex Thread / Turn / Item；资源库工具、数据库只读工具、知识记录、分析资产最小存储、Codex Item projection、交互式报告版本已经可用。
- 登录：Auth.js + 飞书 OAuth + PostgreSQL session。
- 运行：Docker Compose 启动 frontend、backend、postgres。
- 待完成：Codex 工具/MCP/Skill 接入、完整业务语义库持久化、完整 Artifact 治理、团队权限/RLS、生产数据源治理。

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
GENBI_LLM_PROVIDER=minimax
GENBI_ANALYSIS_MODEL=MiniMax-M3
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_API_KEY=...
GENBI_CODEX_PROVIDER=minimax
GENBI_CODEX_API_KEY=...
```

修改 `.env` 后，`docker compose restart` 不一定重新注入变量；需要：

```bash
docker compose up -d --force-recreate --no-deps backend
```

## 验证

```bash
cd frontend
npm.cmd test
npm.cmd run build

python -m unittest discover backend\tests -v
docker compose config
```

## 文档入口

- `AGENTS.md`：协作规则。
- `docs/product/product-scope.md`：产品边界。
- `docs/architecture/overview.md`：架构边界。
- `docs/plans/current.md`：当前分支状态。

文档只保留能帮助继续做事的信息；历史过程交给 Git。
