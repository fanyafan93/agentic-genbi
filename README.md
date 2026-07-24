# Agentic GenBI

Agentic GenBI 是面向公司内部业务人员的智能 BI 平台：用户通过自然语言提出分析问题，系统在受控范围内规划和执行查询，并返回可核对的 SQL、表格、图表描述和结论。当前已支持多个登录用户的任务隔离；长期产品边界包括持续会话、语义模型、分析资产以及个人和团队仪表板，但不做多租户。

## 文档入口

接手项目时按以下顺序阅读：

1. [`AGENTS.md`](AGENTS.md)：协作、安全和验证规则。
2. [`docs/product/product-scope.md`](docs/product/product-scope.md)：产品目标、阶段边界和非目标。
3. [`docs/architecture/overview.md`](docs/architecture/overview.md)：系统结构、技术和安全边界。
4. [`docs/plans/current.md`](docs/plans/current.md)：当前任务、验证事实、风险和下一步。

历史实现与旧决策通过 Git 提交记录追溯；不要创建额外的交接、当前计划或接口契约文档。

## 已实现能力

- 自然语言问题到受控只读 MySQL 查询的完整链路。
- SQLGlot AST 校验、全局表白名单、最大行数、查询超时和数据库只读账号。
- 结构化 `AnalysisReport`、公开执行步骤和前端报告展示。
- 与分析库分离的应用状态 MySQL schema 和账号、最小用户/会话记录与幂等迁移。
- 飞书 OAuth 登录、后端 Cookie 会话、当前用户查询、退出和前端用户卡片；过期会话会被拒绝并清理。
- 分析任务持久化到应用状态 MySQL，并按登录用户隔离；服务重启后可以读取已完成任务。

当前任务运行方式、待开发能力与已知风险以 [`docs/plans/current.md`](docs/plans/current.md) 为准。

## 本地启动

```bash
docker compose up --build
```

- 前端：`http://localhost:3000`
- 后端健康检查：`http://localhost:8000/health`
- 本地 MySQL：宿主机 `127.0.0.1:3307`，容器内 `mysql:3306`

Compose 项目名固定为 `agentic-genbi`，不依赖本地仓库目录名。

## 配置

| 变量 | 用途 | 敏感 |
| --- | --- | --- |
| `APP_ENV` | `development`、`test` 或 `production` | 否 |
| `MINIMAX_API_KEY` | MiniMax API 凭据 | 是 |
| `MINIMAX_BASE_URL` / `MINIMAX_MODEL` | 模型兼容端点和模型名 | 否 |
| `DATABASE_URL` | 只读分析数据库连接串 | 是 |
| `APP_DATABASE_URL` | 应用状态 MySQL 连接串；本地默认使用独立 schema 和账号 | 是 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_REDIRECT_URI` | 飞书 OAuth 配置 | ID/URI 否；Secret 是 |
| `FRONTEND_BASE_URL` | 公开前端地址；用于 OAuth 回跳、后端 CORS 与前端服务端重定向 | 否 |
| `ALLOWED_TABLES` | Agent 可见的全局表白名单 | 否 |
| `MAX_QUERY_ROWS` / `QUERY_TIMEOUT_MS` | 查询资源上限 | 否 |
| `MAX_TOOL_CALLS` / `MAX_SQL_RETRIES` | Agent 调用与 SQL 修复上限 | 否 |

将真实凭据放在未提交的 `.env`，不要写入源码、文档、提交记录或对话。

## 验证

```bash
docker compose config
docker compose run --rm --no-deps backend uv run pytest
docker compose run --rm --no-deps frontend npm run test -- --run
```

只验证健康检查时：

```bash
docker compose run --rm --no-deps backend uv run pytest tests/test_health.py -v
docker compose run --rm --no-deps frontend npm run test -- --run tests/health.test.tsx
```
