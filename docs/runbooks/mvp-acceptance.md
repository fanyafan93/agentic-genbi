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

### 2026-07-14 端到端加固重验

在 commit `8c4109c` 推完之后按本表要求跑了完整一轮，作为 [commit `12ba23f`](#)
（harden dynamic SQL agent boundaries and add task watchdog）的回归基准。

- 后端单元/集成/e2e 测试：`88 passed, 2 skipped in 5.05s`
  （含 [tests/e2e/test_acceptance_suite.py](../../backend/tests/e2e/test_acceptance_suite.py)
  中 5 题 parametrized 测试，全过）。
- 前端 Vitest：`Test Files 4 passed (4) / Tests 7 passed (7) in 1.25s`。
- Docker Compose 重建并重启后端后 `GET /health` 返回 `{"status":"ok"}`，前端首页 `200`。
- 真实 API 5 题端到端（脚本： `docs/runbooks/scripts/run-5-mvp-questions.ps1`，
  落在 `dm.dm_sale_dy_total` 上）：

  | 问题 | 状态 | 步骤/finished | attempts | 行数 | 错误 |
  | --- | --- | --- | --- | --- | --- |
  | trend | requires_input | 14/14 | — | — | ANALYSIS_NEEDS_CLARIFICATION |
  | comparison（春季聚合）| succeeded | 9/9 | 2（一次 SQL 修复）| 17 | — |
  | ranking（TOP 10）| failed | 6/6 | — | — | SQL_EXECUTION_ERROR |
  | composition（比例）| failed | 16/16 | — | — | INVALID_REPORT |
  | schema_probe（结构）| failed | 4/4 | — | — | SQL_EXECUTION_ERROR |

- 加固回归结论：
  - 所有任务的 `steps[*].finished_at` 均为非空，证明 `12ba23f` 引入的
    `ExecutionStepRecorder._open_steps` + `finalize_open_steps()` 在真实请求下
    工作正常。
  - `comparison` 一次成功 SQL + 一次修复 attempts=2，正是
    `MAX_SQL_RETRIES=2` 与 fail-fast（`SQL_RETRY_EXHAUSTED` 抛错）协作的结果。
  - 5 题失败中 `INVALID_REPORT` 与 `SQL_EXECUTION_ERROR` 来自 LLM
    返回的结构 / SQL 错误，由 `runner.py` / `coordinator.py` 已经接住，并不影响
    关闭步骤的保证。

### 2026-07-15 INVALID_REPORT 修复重验

[`8f7cd3e`](https://gitee.com/shenzhen-liran-cosmetics/genbi/commit/8f7cd3e)
之后再次重跑上面 5 题脚本，整体成功率从 1/5 提到 **3/5**：

| 问题 | 状态 | 步骤/finished | attempts | 行数 |
| --- | --- | --- | --- | --- |
| trend | succeeded | 7/7 | 1 | 50 |
| comparison | succeeded | 6/6 | 1 | 6 |
| ranking | failed | 7/7 | — | — |
| composition | succeeded | 9/9 | 2 | 38 |
| schema_probe | failed | 4/4 | — | — |

- `INVALID_REPORT` 的失败信息现在带 **Detail:** 前缀暴露根本原因
  （JSON 截断、Pydantic 字段缺失等），由
  `backend/app/agents/runner.py` 中 `InvalidAgentReport(detail)` 与
  `runner.py` 里 `<first line of exception> | raw=<truncated repr>` 的拼接
  提供。
- 后端完整单测：`89 passed, 2 skipped in 5.09s`（新增
  `test_runner_invalid_report_message_carries_pydantic_detail` 显式断言
  detail 走到 message 中）。
- 后端运行后端镜像 `agentic-genbi-mvp-backend` 内检查
  `app/agents/runner.py` 第 45–85 行已包含 detail 截断与 raw 截断逻辑。
- 走偏题（如 "Generate an essay about imaginary cats"）连续三次都返回
  `ANALYSIS_NEEDS_CLARIFICATION` 或 `SQL_EXECUTION_ERROR`，
  未再次触发 `INVALID_REPORT`。

### 2026-07-15 `13f46b4` 之后的二次重验

上一条记录里 `INVALID_REPORT` 的 message 不带 `Detail:` ，
是因为 coordinator 还有第二处 `raise InvalidAgentReport from error`
没传 detail，而实际生产路径里命中的是 coordinator 不是 runner。
`13f46b4` 给 coordinator 的同一段 `except` 加了
`f"{head} | raw={raw}"` 拼接，并把 `app.observability.logger`
（不存在）换成标准 `logging.getLogger("agentic_genbi").error`。
验收脚本 `docs/runbooks/scripts/run-acceptance-with-detail.ps1` 会把每个任务的
JSON 快照写到 `verification_runs/<date>/<id>.json`，用来诊断这种回归。

| 问题 | 状态 | 步骤/finished | attempts | 行数 |
| --- | --- | --- | --- | --- |
| trend | succeeded | 7/7 | 1 | 50 |
| comparison | succeeded | 6/6 | 1 | 6 |
| ranking | requires_input | 3/3 | — | — |
| composition | succeeded | 20/20 | 3 | 60 |
| schema_probe | failed | 3/3 | — | — |

- 失败项都给出语义化错误：`ANALYSIS_NEEDS_CLARIFICATION` 和
  `SQL_EXECUTION_ERROR`，不再回到模糊的 `INVALID_REPORT`。
- 后端单测： `89 passed, 2 skipped in 5.10s`（新增
  `test_coordinator_marks_report_generation_failed_for_non_json_output`
  里的 `Detail:` 与 `raw=` 双断言）。
- 容器内确认：
  `docker exec agentic-genbi-mvp-backend-1 grep -n`
  `agentic_genbi` 出现在 `app/agents/coordinator.py` 与
  `app/agents/runner.py` —— 两个 raise 点都已接 stderr 日志。
