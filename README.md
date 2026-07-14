# Agentic GenBI MVP

一个面向单个 MySQL 测试库的最小 Web 数据分析 Agent。目标是让用户通过自然语言提出分析问题，由单个 Agent 探查允许访问的表结构、生成并安全执行只读 SQL，在可修复错误发生时最多自动重试两次，并返回表格、图表配置、最终 SQL 和文字结论。

## 当前阶段

项目已完成任务 1 至任务 4：项目骨架与健康检查、固定分析任务 API、固定前端报告，以及数据库级只读 MySQL 连接。当前前端仍展示固定报告；真实业务查询、SQL 安全策略、元数据工具和 Agent 仍在后续任务中实现。

## 规划中的 MVP 能力

- 网页提交一个自然语言分析问题。
- FastAPI 创建进程内分析任务，前端通过轮询查看状态和执行步骤。
- OpenAI Agents SDK 运行单个数据分析 Agent。
- Agent 调用 `list_tables`、`get_table_schema` 和 `execute_sql`。
- Python 安全层与 MySQL 只读账号共同阻止写入和越权查询。
- 普通 SQL 错误结构化返回，Agent 最多修复并重试两次。
- 成功后返回统一的 `AnalysisReport`，前端展示 SQL、表格、ECharts 图表和结论。

## 目标目录

```text
.
├── AGENTS.md                         # Agent 协作与安全规则
├── CLAUDE.md                         # 引用 AGENTS.md
├── README.md                         # 项目入口
├── docker-compose.yml                # 本地前后端与 MySQL 编排
├── docs/
│   ├── product/mvp-scope.md          # 产品范围与验收标准
│   ├── architecture/overview.md      # 架构、流程与安全边界
│   ├── architecture/interfaces.md    # API、模型和错误契约
│   ├── architecture/decisions/       # 架构决策记录
│   ├── plans/current.md              # 当前实施计划与状态
│   ├── handoffs/latest.md            # 最新会话交接
│   └── runbooks/                     # 规划：运行与排障手册
├── backend/
│   ├── app/
│   │   ├── api/                      # FastAPI 路由与 HTTP 映射
│   │   ├── agents/                   # Agent 定义、提示与运行器
│   │   ├── tools/                    # Agent 函数工具适配层
│   │   ├── database/                 # SQLAlchemy、元数据与查询执行
│   │   ├── schemas/                  # Pydantic 契约
│   │   ├── services/                 # 任务编排、安全与报告服务
│   │   └── core/                     # 配置、日志和应用生命周期
│   └── tests/                        # pytest 单元与集成测试
└── frontend/
    ├── src/
    │   ├── app/                      # Next.js 路由和页面
    │   ├── components/               # 通用展示组件
    │   ├── features/analysis/        # 分析任务垂直功能
    │   ├── services/                 # FastAPI 客户端与轮询
    │   └── types/                    # 前端 API 类型
    └── tests/                        # Vitest 测试
```

任务 1 只创建了启动骨架实际需要的目录和文件；其余业务目录会在对应任务中按需创建。

## 本地启动方式

从仓库根目录运行：

```bash
docker compose up --build
```

前端地址为 `http://localhost:3000`，后端健康检查为 `http://localhost:8000/health`。两者已在 Docker Compose 中验证。

## 本地 MySQL 测试库

MySQL 容器会在首次启动时创建 `analytics.sales_channel_monthly` 的 6 条确定性脱敏样例数据，并创建只拥有 `SELECT` 权限的 `readonly_user`。为了避免占用本机既有 MySQL，宿主机使用 `3307` 端口；容器内后端仍通过 `mysql:3306` 访问。

```bash
docker compose up -d mysql
cd backend
uv run --frozen pytest tests/database/test_connection.py -v -m integration
```

集成测试会证明该应用账号能读取样例表，同时数据库拒绝 `INSERT` 与 `DROP TABLE`。测试连接可通过 `INTEGRATION_DATABASE_URL` 覆盖；默认值为隔离容器的 `127.0.0.1:3307`。

## 规划环境变量

| 变量 | 用途 | 是否敏感 |
| --- | --- | --- |
| `APP_ENV` | 当前骨架必须提供，取值为 `development`、`test` 或 `production` | 否 |
| `OPENAI_API_KEY` | OpenAI API 身份凭据 | 是 |
| `OPENAI_MODEL` | Agent 使用的模型，由部署环境显式配置 | 否 |
| `DATABASE_URL` | MySQL 只读连接串 | 是 |
| `ALLOWED_TABLES` | 允许暴露给 Agent 的表白名单 | 否 |
| `MAX_QUERY_ROWS` | 查询最大返回行数 | 否 |
| `QUERY_TIMEOUT_SECONDS` | 单次查询超时 | 否 |
| `MAX_TOOL_CALLS` | 单任务工具调用硬上限 | 否 |
| `MAX_SQL_RETRIES` | SQL 修复重试上限，MVP 必须为 `2` | 否 |
| `OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA` | 是否在 SDK trace 中包含敏感输入输出，默认应关闭 | 否 |

密钥只通过本地 `.env` 或部署环境注入，禁止提交到 Git。`DATABASE_URL` 已由任务 4 作为后端必填配置验证，并以 `SecretStr` 保存，避免其出现在配置验证错误中；`OPENAI_API_KEY` 等其余配置将在对应功能接入时启用。

## 骨架测试命令

```bash
docker compose config
docker compose run --rm --no-deps backend uv run pytest tests/test_health.py -v
docker compose run --rm --no-deps frontend npm run test -- --run tests/health.test.tsx
```

也可在本机分别运行 `cd backend && uv sync --all-groups && uv run pytest tests/test_health.py -v` 和 `cd frontend && npm ci && npm run test -- --run tests/health.test.tsx`。

## 当前尚未实现

已实现 FastAPI `/health`、任务状态 API、固定报告前端、受管 SQLAlchemy 连接和数据库级只读 MySQL 测试库。真实业务查询、SQL 安全检查、元数据工具、Agent、SQL 自动修复和基于查询的报告生成仍未实现。WrenAI、LangGraph、多 Agent、多租户、Redis、Celery、多数据库、PDF、仪表板编辑器和任意代码执行明确不在 MVP 范围内。

## 文档导航

- 产品范围：`docs/product/mvp-scope.md`
- 架构总览：`docs/architecture/overview.md`
- 接口协议：`docs/architecture/interfaces.md`
- 当前计划：`docs/plans/current.md`
- 最新交接：`docs/handoffs/latest.md`
