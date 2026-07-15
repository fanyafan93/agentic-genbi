# 最新交接

更新时间：2026-07-15 03:58（Asia/Shanghai）

## 当前分支

`Agentic-GenBI-MVP`。自 12:00 起累计 6 个独立 commit 完成：
1. `12ba23f` — fix：边界加固 + watchdog + 步骤 finished_at 兜底
2. `70eb286` — feat：跨 schema 通配符
3. `bf55476` — feat：前端步骤 UI
4. `b5e7578` — test+docs：acceptance 套件 + 运维 runbooks
5. `8c4109c` — chore：忽略 frontend-test.html
6. `e3c3e66` / `5b8de00` / `93494c1` — docs + scripts + INVALID_REPORT 双轮修复

## INVALID_REPORT 双轮修复（`8f7cd3e` → `93494c1`）

第一次端到端验收时 5 题里 1 题
`INVALID_REPORT`。`8f7cd3e` 让
[`InvalidAgentReport.__init__`](file:///e:/my_repo/Agentic-GenBI-MVP/backend/app/agents/runner.py#L42-L52)
接受可选 `detail` 参数并把异常摘要拼到 `message` 里，runner.py
接 `<exception first line> | raw=<200-char repr>`。但重跑验收时
发现线上 API 仍然把 message 显示成纯裸的
`"Analysis provider returned an invalid report."`。

根因：`InvalidAgentReport` 在仓库内**有两个** raise 点，
12ba23f/8f7cd3e 都只修了
[`runner.py`](file:///e:/my_repo/Agentic-GenBI-MVP/backend/app/agents/runner.py)
一处；
[coordinator.py 380–393](file:///e:/my_repo/Agentic-GenBI-MVP/backend/app/agents/coordinator.py#L380-L393)
report_generation 仍然 `raise InvalidAgentReport from error`
（不带 detail）。生产路径里这一处会先于 runner 命中，所以
detail 没流到 API。

`93494c1` 修复：

| 文件 | 改动 |
| --- | --- |
| `backend/app/agents/coordinator.py` | 同 try 块拼接 `<head> | raw=<raw>` 传给 InvalidAgentReport |
| `backend/app/agents/runner.py` | `app.observability.logger`（不存在）替换成标准 `logging.getLogger("agentic_genbi").error` |
| `backend/tests/agents/test_coordinator.py` | `test_coordinator_marks_report_generation_failed_for_non_json_output` 新增 `Detail:` + `raw=` 双断言 |
| `docs/runbooks/scripts/run-acceptance-with-detail.ps1` | 把每个任务 JSON 写到 `verification_runs/<date>/`，是诊断这次"detail 跑不到 API"回归的关键 |
| `docs/runbooks/mvp-acceptance.md` | 新增 2026-07-15 重验章节 |

`93494c1` 后端单测：`89 passed, 2 skipped in 5.10s`。
`93494c1` 后 live 5 题验收：3/5 succeeded（trend 50 行、comparison
6 行、composition 60 行 attempts=3），失败项都是语义化
（`ANALYSIS_NEEDS_CLARIFICATION` / `SQL_EXECUTION_ERROR`），
不再是模糊的 `INVALID_REPORT`。

## 本次改动

### 1. 修复：每个 started 步骤必有 `finished_at`

之前 `DynamicAnalysisCoordinator.run()` 在 `report_generation`
抛出非 `ValidationError` 异常（例如 `JSONDecodeError`、
`ValueError`、未捕获的系统异常）时，已开始的步骤会保持
`finished_at=None` 进入任务终态。本次提交：

- `ExecutionStepRecorder` 新增 `_open_steps: list[AgentExecutionStep]`、
  `finalize_open_steps(status)`，步骤 `finish()` 时从列表移除。
- `DynamicAnalysisCoordinator.run()` 外层包
  `try/except Exception: _finalize_open_steps(step_recorder); raise`,
  主线程结束后兜底关闭任何半开步骤。
- 同步把 `validate_narrative_output` 的 `JSONDecodeError` / `ValueError`
  在 `coordinator.py` 与 `runner.py` 统一转成 `InvalidAgentReport`，
  让 `report_generation` 步骤异常被显式标记为 FAILED 而不是静默漏掉。

### 2. 加固：工具入口硬边界取代 LLM 自决

LLM 在反复失败时会持续调用 `sql_validation`/`execute_sql`，
此前 `_claim_tool_call` 拦截失败后只返回错误字典，
LLM 看到错误继续重试，对应任务产生 5+ 次 `sql_validation` 步骤。

本次提交：

- 新增 `ApprovedAnalysisTools._fail_fast_if_terminal(step, kind)`，
  三个工具方法（`list_tables` / `get_table_schema` / `execute_sql`）
  入口都改为先调用；`terminal_error` 已落地或预算耗尽时，
  立即 `raise AgentRunError.with_code(...)` 中断 Agent SDK 当前轮次。
- `AgentRunError` 改造：用 `AgentRunError.with_code(code, message)` 工厂
  显式带实例 `code`，子类 `AgentProviderNotConfigured` /
  `AgentProviderError` / `InvalidAgentReport` 仍走类变量 `code`。

### 3. 加固：任务总时长 watchdog

`TaskService.run_analysis` 启动 `threading.Timer` 守护线程；
超过 `TASK_TIMEOUT_SECONDS`（默认 90 秒，可通过 `.env` 调整）
时静默调 `fail_task` 写入错误
`code=ANALYSIS_TIMEOUT`。主线程继续但不重复 `fail_task`，
避免 `ValueError("only running tasks may fail")` 透出。

`fail_task` 与 `succeed_task` 改为"非 RUNNING 时静默返回当前快照"，
避免主线程晚于 watchdog 唤醒时再次改状态。

### 4. 配置变更

| 配置项 | 默认 | 本次调整 |
| --- | --- | --- |
| `QUERY_TIMEOUT_MS` | `5_000` | 外部库聚合查询上调到 `15_000` |
| `MAX_SQL_RETRIES` | `2` | 不变 |
| `MAX_TOOL_CALLS` | `12` | 不变 |
| `TASK_TIMEOUT_SECONDS` | (新增) | `90`，10 ≤ 默认 ≤ 600 |

`.env.example`、`backend/.env` 都已更新，
`config.py` 也新增 `task_timeout_seconds` 字段。

## 验证结果

| 维度 | 修复前 | 修复后 |
| --- | --- | --- |
| 后端单测 | 85 通过 | **88 通过**（新增 3 项） |
| 端到端聚合查询 | `failed` (SQL_TIMEOUT, 12 步、7 次 sql_validation 失败) | **`succeeded`** (6 步、耗时 962ms、attempts=1、31 行)|
| 所有步骤 `finished_at` | 部分缺失（report_generation 之后无值）| **100% 完整** |
| 任务总耗时 | 卡死 230s+（无 watchdog） | ≤ 90s 自动 ANALYSIS_TIMEOUT |

新增 3 个单测：

- `test_coordinator_always_closes_every_started_step_even_on_unexpected_error`
- `test_coordinator_closes_report_step_when_build_report_raises`
- `test_coordinator_aborts_agent_loop_when_budget_is_exceeded`
- `test_task_service_watchdog_fails_task_when_runner_hangs`
- `test_task_service_watchdog_noop_when_runner_finishes_quickly`

> 其中前 3 个对应加固 1+2，最后 2 个对应加固 3。

## 影响范围

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `backend/app/agents/coordinator.py` | 修改 | 步骤记录器、hard-cap、异常捕获、终态保护 |
| `backend/app/agents/runner.py` | 修改 | `AgentRunError.with_code` 工厂 + JSONDecodeError 转 `InvalidAgentReport` |
| `backend/app/config.py` | 修改 | 新增 `task_timeout_seconds` |
| `backend/app/services/task_service.py` | 修改 | watchdog 实现 + succeed_task/fail_task 静默返回 |
| `backend/tests/agents/test_coordinator.py` | 修改 | 新增 4 个测试，更新现有测试以适配 `raise AgentRunError` 语义 |
| `backend/tests/agents/test_runner.py` | 修改 | 更新非 JSON 输出测试以匹配新签名 |
| `.env.example` | 修改 | 新增 `TASK_TIMEOUT_SECONDS`、注释 cross schema 支持 |
| `docs/plans/current.md` | 修改 | 任务 11/12/13 标"已完成"，追加"本次加固"段落 |
| `docs/runbooks/dynamic-agent-hardening.md` | 新建 | 运维硬边界配置 + 故障排查流程 |

## 兼容性与破坏性变更

- **行为变化：** Agent 工具入口触发 `terminal_error` 时改为 `raise`,
  原行为是"返回错误字典"。这会让 LLM 立即停止当前轮次，
  但**不会**影响 LLM 通过初始几轮进入该错误。
- **错误码：** `TASK_TIMEOUT_SECONDS` 触发后错误为 `ANALYSIS_TIMEOUT`。
- **数据格式：** `AnalysisTaskStatus.steps` 所有项目状态终必带 `finished_at`。

## 已知限制（保持 MVP 范围内）

- 任务状态仍存于 FastAPI 进程内，进程重启后旧 task_id 消失
- watchdog 仅覆盖任务级总时长，不打断 LLM 单次 stream 调用
- `dm.*` 全表 schema 包含 280 张表，`list_tables` 首次可能 5 秒内返回
- LLM 偶尔返回无法 `ReportNarrative.model_validate` 的字符串（missing
  field、JSON 截断、extra `analysis` 段），这时任务会变成
  `failed` 且 `error.code = INVALID_REPORT`。这条路径下 `error.message`
  现在带上 **Detail:** 前缀的原始异常摘要（最多 300 字符），方便快速
  判断是字段缺失、JSON 截断还是其他原因。具体测试见
  `test_runner_rejects_non_json_provider_output` 与
  `test_runner_invalid_report_message_carries_pydantic_detail`。
  `93494c1` 之后 `coordinator.py` 的 raise 也带同样的 detail；
  触发时 `agentic_genbi` logger 也会写一行
  `validate_narrative_output_failed: <head> | raw=<raw>` 到 stderr
  （`docker logs agentic-genbi-mvp-backend-1` 可查）。

## 复现与回退

```bash
# 后端单测
cd backend
uv run --frozen pytest tests/agents tests/services tests/e2e -v

# 端到端聚合（修复前会失败，修复后应返回 ~31 行）
curl -X POST http://localhost:8000/api/v1/analysis-tasks \
    -H "Content-Type: application/json" \
    -d '{"question":"dm.dm_sale_dy_total 表 2026 年 3 月的销售额，按渠道分组和抖音号"}'
```

回退：`git revert HEAD` 然后 `docker compose up -d --build backend`。
