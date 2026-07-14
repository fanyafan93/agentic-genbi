# MVP 验收矩阵

| 产品验收项 | 证据 | 当前状态 |
| --- | --- | --- |
| 网页提交非空、长度受限问题 | `backend/tests/api/test_analysis_tasks.py`、`frontend/tests/analysis-page.test.tsx` | 自动通过 |
| 创建任务并轮询状态 | API 与前端轮询测试 | 自动通过 |
| 单进程单任务容量限制 | `backend/tests/services/test_task_service.py` | 自动通过 |
| Agent 仅使用三个工具 | `backend/tests/agents/test_coordinator.py` | 自动通过 |
| 只读单语句、白名单、行数与超时 | SQL policy 和 executor 测试 | 自动通过 |
| MySQL 只读账号 | 本地集成测试；外部库 opt-in 测试 | 本地与外部通过 |
| 最多两次 SQL 修复 | 协调器回归测试与五题验收的修复场景 | 自动通过 |
| Pydantic 结构化报告 | Agent runner 与报告测试 | 自动通过 |
| 状态、执行步骤、SQL、表格、图表和结论 | 前端 Vitest、生产构建、Docker 首页响应 | 自动通过；浏览器自动化待补 |
| 禁止 SQL 不到达数据库 | `backend/tests/security/test_sql_policy.py` | 自动通过 |
| 错误映射、重试预算和澄清状态 | 错误、重试、任务服务测试 | 自动通过 |
| 五类端到端问题 | `backend/tests/e2e/test_acceptance_suite.py` | 自动通过 |

## 执行记录

- 后端完整测试：`81 passed, 2 skipped`。
- 前端测试：`4 个测试文件、7 项通过`。
- 前端生产构建：成功。
- Docker Compose：后端、前端、MySQL 均启动；后端 `/health` 和前端首页均返回 `200`。
- 浏览器自动化：当前环境的浏览器插件缺少运行文件，未执行；前端组件测试和生产构建已覆盖对应界面契约。
- 外部 MySQL：`dm` 可见 278 张表、`dw` 可见 541 张表；受控跨 schema 常量查询通过，数据库拒绝零行 `DELETE`。未将凭据或真实表名写入仓库。
