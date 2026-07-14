# 最新交接

更新时间：2026-07-14

## 当前任务

任务 5「固定 SQL 查询垂直切片」已完成，当前分支为 `task-5-fixed-sql-query`，基于已合并任务 1 至任务 4 的 `Agentic-GenBI-MVP`。

## 已完成内容

- 新增 `DATABASE_URL` 必填配置，使用 Pydantic `SecretStr` 保存，配置校验错误不回显连接串。
- 新增 `app.database`，集中提供 SQLAlchemy engine 和会自动关闭连接的上下文管理器。
- Docker Compose 的 MySQL 8.4 在首次启动时创建 `analytics.sales_channel_monthly`，写入 6 条确定性脱敏数据。
- 初始化 `readonly_user`，仅授予 `analytics.*` 的 `SELECT` 权限；后端容器使用该账号。
- 宿主机端口使用 `3307`，避免占用本机已有 `3306` MySQL；容器内仍使用 `mysql:3306`。
- 真实集成测试验证 `SELECT` 成功，且 MySQL 本身拒绝 `INSERT` 和 `DROP TABLE`。
- 默认 FastAPI 任务现执行开发者拥有的固定查询，返回 `sales_channel_monthly` 的 6 条记录和按渠道分组的月度销售额折线图。
- 查询层将 `Decimal`、`date`、`datetime` 和 `null` 转换为 JSON 兼容值；浏览器和 API 都不接受 SQL 输入。

## 主要文件

- `backend/app/config.py`
- `backend/app/database.py`
- `backend/tests/database/test_config.py`
- `backend/tests/database/test_database.py`
- `backend/tests/database/test_connection.py`
- `mysql/init/001-schema-and-readonly-user.sql`
- `docker-compose.yml`
- `backend/app/query.py`
- `backend/app/services/fixed_analysis.py`

## 验证结果

- `uv run --frozen pytest -q`：15 项后端测试通过。
- `uv run --frozen pytest tests/database/test_connection.py -q -m integration`：1 项真实 MySQL 权限测试通过。
- MySQL 容器健康检查通过，初始化日志确认 schema 和只读用户已创建。

## 下一步

进入任务 6「数据库元数据工具」。元数据工具只能访问允许列表内的表和字段；SQL 安全策略与任意模型 SQL 的执行仍属于任务 7 之后的范围。
