# 本地开发与验收

## 本地脱敏样例栈

从仓库根目录执行：

```powershell
docker compose up --build -d
docker compose ps
```

前端为 `http://localhost:3000`，后端健康检查为 `http://localhost:8000/health`。

运行本地测试：

```powershell
Set-Location backend
uv run --frozen pytest -q

Set-Location ..\frontend
npm ci
npm run test -- --run
```

本地样例库仅用于确定性自动化测试。结束后可执行：

```powershell
Set-Location ..
docker compose down -v
```

## 外部只读 MySQL

外部连接信息只能放在本机 `.env` 或部署密钥管理系统，禁止提交。使用 URL 编码后的密码：

```dotenv
APP_ENV=development
DATABASE_URL=mysql+pymysql://readonly_user:<url-encoded-password>@<host>:3306
ALLOWED_TABLES=dm.*,dw.*
MAX_QUERY_ROWS=500
QUERY_TIMEOUT_MS=5000
MAX_TOOL_CALLS=12
MAX_SQL_RETRIES=2
```

`ALLOWED_TABLES` 可使用精确表名（如 `dw.dim_product`）或 schema 通配规则（如 `dm.*`）。跨 schema SQL 必须写成 `dm.table_name`、`dw.table_name`；未列出的 schema 和表仍会被拒绝。

运行外部只读验收前，确认 `.env` 中已设置数据库连接和白名单，然后执行：

```powershell
Set-Location backend
$env:RUN_EXTERNAL_MYSQL_CHECK = "true"
uv run --frozen pytest tests/e2e/test_external_mysql.py -m integration -v
Remove-Item Env:RUN_EXTERNAL_MYSQL_CHECK
```

该检查会列出白名单元数据、读取一行常量，并提交 `DELETE ... WHERE 1 = 0` 来验证数据库权限拒绝写入；该谓词始终不匹配任何行。

## MVP 验收问题

针对本地脱敏样例库，依次验证趋势、对比、排名、构成和一次可修复 SQL 错误。每题都应显示任务状态、步骤、最终 SQL、结果表、图表或表格回退与文字结论。外部库只验证同一链路和权限边界，不对真实业务数值做固定断言。
