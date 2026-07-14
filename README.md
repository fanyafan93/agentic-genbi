# Agentic GenBI MVP

一个面向单个 MySQL 测试库的最小 Web 数据分析 Agent。目标是让用户通过自然语言提出分析问题，由单个 Agent 探查允许访问的表结构、生成并安全执行只读 SQL，在可修复错误发生时最多自动重试两次，并返回表格、图表配置、最终 SQL 和文字结论。

## 当前阶段

当前处于 **MVP 架构与项目文档阶段**。仓库尚未包含可运行的前后端业务代码、Docker Compose 配置或依赖锁文件。本文中的启动、环境变量和测试命令是已批准的目标约定，将在对应实施任务完成后变为可执行命令。

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
├── docker-compose.yml                # 规划：本地前后端编排
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

目录在首次骨架任务中按需创建，不提前建立空目录。

## 本地启动方式

待项目骨架实现后，目标命令为：

```bash
docker compose up --build
```

计划访问地址：前端 `http://localhost:3000`，后端健康检查 `http://localhost:8000/health`。端口仍是待验证假设，以首次骨架提交为准。

## 规划环境变量

| 变量 | 用途 | 是否敏感 |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI API 身份凭据 | 是 |
| `OPENAI_MODEL` | Agent 使用的模型，由部署环境显式配置 | 否 |
| `DATABASE_URL` | MySQL 只读连接串 | 是 |
| `ALLOWED_TABLES` | 允许暴露给 Agent 的表白名单 | 否 |
| `MAX_QUERY_ROWS` | 查询最大返回行数 | 否 |
| `QUERY_TIMEOUT_SECONDS` | 单次查询超时 | 否 |
| `MAX_TOOL_CALLS` | 单任务工具调用硬上限 | 否 |
| `MAX_SQL_RETRIES` | SQL 修复重试上限，MVP 必须为 `2` | 否 |
| `OPENAI_AGENTS_TRACE_INCLUDE_SENSITIVE_DATA` | 是否在 SDK trace 中包含敏感输入输出，默认应关闭 | 否 |

密钥只通过本地 `.env` 或部署环境注入，禁止提交到 Git。默认值和示例将在项目骨架任务中验证后写入 `.env.example`。

## 规划测试命令

```bash
cd backend && pytest
cd frontend && npm run test
```

这些命令在依赖和测试骨架尚未创建前不可运行。

## 当前尚未实现

除本仓库文档外，前端页面、FastAPI 应用、任务状态存储、数据库连接、SQL 安全检查、Agent、工具、报告生成、Docker Compose 和自动化测试均尚未实现。WrenAI、LangGraph、多 Agent、多租户、Redis、Celery、多数据库、PDF、仪表板编辑器和任意代码执行明确不在 MVP 范围内。

## 文档导航

- 产品范围：`docs/product/mvp-scope.md`
- 架构总览：`docs/architecture/overview.md`
- 接口协议：`docs/architecture/interfaces.md`
- 当前计划：`docs/plans/current.md`
- 最新交接：`docs/handoffs/latest.md`
