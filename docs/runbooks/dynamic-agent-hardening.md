# 动态 SQL Agent 边界与故障排查

## 背景

Agent 通过三个白名单工具读取元数据并执行只读 SQL。
Agent 自身可能出现"自驱反复重试"或"分析卡死"两类边界问题，
本运行手册描述本次加固的硬边界以及遇到异常后如何排查。

## 强边界（由代码而非提示词强制）

| 边界 | 设置位置 | 默认值 | 生效点 |
| --- | --- | --- | --- |
| `MAX_SQL_RETRIES` | `app/config.py`、`backend/.env` | `2` | `ApprovedAnalysisTools.execute_sql` 入口；超过即置 `terminal_error` 并 raise `AgentRunError.with_code("SQL_RETRY_EXHAUSTED", ...)` 中断当前轮次 |
| `MAX_TOOL_CALLS` | 同上 | `12` | `ApprovedAnalysisTools._claim_tool_call`；超过即 raise `AgentRunError.with_code("TOOL_BUDGET_EXCEEDED", ...)` |
| `QUERY_TIMEOUT_MS` | 同上 | `5_000`（本次外部库上调到 `15_000`） | `SqlExecutor` 单独运行 |
| `TASK_TIMEOUT_SECONDS` | 同上 | `90` | `TaskService._start_watchdog` 启动 `Timer`；超时静默调 `fail_task` 写 `ANALYSIS_TIMEOUT` |
| 工具入口硬关断 | `ApprovedAnalysisTools._fail_fast_if_terminal` | — | 一旦 `terminal_error` 落地，再次调用工具立刻 raise `AgentRunError`，不再返回错误字典让 LLM 自决 |

提示词只是软引导；超过上述上限由 Python 强制中断。

## 步骤状态完整关闭

`ExecutionStepRecorder` 持有 `_open_steps` 列表，
`DynamicAnalysisCoordinator.run()` 外层包了
`try/except Exception: step_recorder.finalize_open_steps(FAILED); raise`。
任何已开始但未 finish 的步骤都会被标记为 FAILED，
所以任务终止时**所有步骤必有 `finished_at`**。

## 故障排查流程

### 1. 任务停在 `failed` 而且错误是 `SQL_TIMEOUT`

`QUERY_TIMEOUT_MS` 不够；按表实际聚合时间上调。建议从 5s → 10s → 15s 阶梯式上调，
并在 `.env` 加注释说明调整时间与原因。

### 2. 任务停在 `failed` 而且错误是 `SQL_RETRY_EXHAUSTED`

Agent 已尝试 `max_sql_retries + 1` 次 SQL。SQL 改动后让 Agent 重新生成的结果仍然失败。

排查方向：
- 后端日志看 `execute_sql` 步骤的 failure title 与 attempt 编号
- 在 `.env` 把 `ALLOWED_TABLES` 精确到问题中涉及到的表（先小后大），让 `list_tables` 更快返回
- 若问题里有歧义，提示用户补充业务指标

### 3. 任务停在 `failed` 而且错误是 `ANALYSIS_TIMEOUT`

任务总体超过 `TASK_TIMEOUT_SECONDS`（默认 90 秒）。
说明 Agent SDK 在 LLM 端反复调用工具。

排查方向：
- 后端日志检查 `agent_started` 步骤耗时是否接近上限
- 把 `TASK_TIMEOUT_SECONDS` 上调到 180 看是否仅为误限
- 若 LLM 持续触发 `sql_validation`，说明工具入口 `_fail_fast_if_terminal` 已生效，
  任务应提前结束；如仍有 5+ 次 `sql_validation`，请提交 issue 附 task_id

### 4. 任务停在 `failed` 但 `finished_at` 缺失

若出现这种情况，说明 `ExecutionStepRecorder` 的兜底 `try/except` 没生效——
请立刻记录 task_id 并回滚到本次加固版本之前，先用 reproduction 脚本跑一次。

### 5. 任务出现 `Analysis provider request failed.`

- `minimax_api_key` 失效/余额不足 → 后端 stdout 应有 `PROVIDER_ERROR` 详细错误
- 模型连接闪断 → 可重提同样问题（前端"再次提问"按钮会复用 task_id）
- 模型返回非 JSON → 已加固成 `InvalidAgentReport`，任务 FAILED

### 6. 跨 schema 查询

`.env` 的 `ALLOWED_TABLES` 需要精确包含两边的 schema，例如：
```
ALLOWED_TABLES=dm.*,dw.*
```
只配置 `dm.sales_fact` 不会授权 `dw.dim_product`。
SQL 中也要写 `dm.sales_fact`、`dw.dim_product` 这种完整限定名。

### 7. 外部只读 MySQL

- 用 URL 编码后的密码，例如冒号 `%3A`、`@` `%40`
- `.env` 不要提交到仓库（已经放在 `.gitignore`）
- 重启后端进程后，旧 task_id 会返回 `TASK_NOT_FOUND`（MVP 已知限制）

## 配置参考

```dotenv
APP_ENV=development
DATABASE_URL=mysql+pymysql://readonly_user:<url-encoded-password>@<host>:3306
ALLOWED_TABLES=dm.*
MAX_QUERY_ROWS=500
QUERY_TIMEOUT_MS=15000
MAX_TOOL_CALLS=12
MAX_SQL_RETRIES=2
TASK_TIMEOUT_SECONDS=90
```

## 单测入口

```bash
cd backend
uv run --frozen pytest \
    tests/agents/test_coordinator.py \
    tests/services/test_task_service.py -v
```

重点测试：

| 测试名 | 覆盖点 |
| --- | --- |
| `test_coordinator_always_closes_every_started_step_even_on_unexpected_error` | Agent 自身异常时所有 started 步骤都有 `finished_at` |
| `test_coordinator_closes_report_step_when_build_report_raises` | `report_generation` 步骤异常时也会被标记 FAILED |
| `test_coordinator_aborts_agent_loop_when_budget_is_exceeded` | 工具预算耗尽会中断 Agent SDK 当前轮次 |
| `test_task_service_watchdog_fails_task_when_runner_hangs` | `TASK_TIMEOUT_SECONDS` watchdog 在主线程卡住时标记 `ANALYSIS_TIMEOUT` |
| `test_task_service_watchdog_noop_when_runner_finishes_quickly` | 主线程提前结束不会污染任务状态 |
| `test_runner_rejects_non_json_provider_output` | 模型返回非 JSON 时转为 `InvalidAgentReport` |
| `test_coordinator_marks_report_generation_failed_for_non_json_output` | `report_generation` 异常也会被关成 FAILED |
