# Task 6 and Task 8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 增加白名单 MySQL 元数据工具和单个 OpenAI Agents SDK 运行时，在不启用动态 SQL 的前提下生成校验后的报告叙述。

**Architecture:** Task 6 将 SQLAlchemy Inspector 访问封装为仅暴露 `Settings.allowed_tables` 的类型化工具。Task 8 先运行现有固定查询，通过 MiniMax OpenAI 兼容 Chat Completions 和 Agents SDK 的 `OpenAIChatCompletionsModel` 调用结构化输出 Agent，再仅合并模型生成的叙述字段与服务端持有的查询数据。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、MySQL 8.4、OpenAI Agents SDK、pytest、uv。

## Global Constraints

- 不实现 Task 7、动态 SQL 生成、SQL 解析或动态 SQL 执行。
- `ALLOWED_TABLES` 是 Task 6 的唯一授权来源，不探测白名单之外的名称。
- API key、原始供应商输出、异常堆栈和隐藏元数据不能进入 API 响应。
- 常规测试全部用 fake，不访问网络、不要求 MiniMax API key。
- MiniMax 默认配置为 `MINIMAX_BASE_URL=https://api.minimax.io/v1` 与 `MINIMAX_MODEL=MiniMax-M3`；密钥仅放入被忽略的 `.env`。

---

### Task 1: Add typed allowlisted metadata tools

**Files:**
- Create: `backend/app/schemas/tools.py`
- Create: `backend/app/database/metadata.py`
- Create: `backend/app/tools/list_tables.py`
- Create: `backend/app/tools/get_table_schema.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/tools/test_list_tables.py`
- Test: `backend/tests/tools/test_get_table_schema.py`

- [ ] 写出 fake inspector 的失败测试，断言只返回白名单表、列属性可序列化、禁止表只抛出 `TABLE_NOT_AVAILABLE`。
- [ ] 运行 `uv run --frozen pytest tests/tools/test_list_tables.py tests/tools/test_get_table_schema.py -v`，确认工具缺失导致失败。
- [ ] 用 Pydantic 工具契约、`Settings.allowed_tables` 与 Inspector 包装器实现最小通过代码。
- [ ] 重跑同一命令，确认测试通过。
- [ ] 提交 `feat: add allowlisted metadata tools`。

### Task 2: Add structured Agent runtime and trusted report assembly

**Files:**
- Create: `backend/app/agents/prompts.py`
- Create: `backend/app/agents/analysis_agent.py`
- Create: `backend/app/agents/runner.py`
- Create: `backend/tests/agents/fakes.py`
- Test: `backend/tests/agents/test_runner.py`
- Modify: `backend/app/schemas/analysis.py`
- Modify: `backend/app/config.py`
- Modify: `backend/app/services/task_service.py`
- Modify: `backend/app/main.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`
- Modify: `.env.example`

- [ ] 写出 fake runner 的失败测试，验证有效叙述、无效输出、供应商异常、缺失 API key 和查询字段不可被模型替换。
- [ ] 运行 `uv run --frozen pytest tests/agents/test_runner.py tests/services/test_task_service.py -v`，确认当前代码不满足结构化运行时契约。
- [ ] 增加一个锁定的 `openai-agents` 依赖、`ReportNarrative`、Agent 构造器和可注入 runner 协议。
- [ ] 修改任务服务：先执行固定查询，再运行 Agent，并以可信 SQL/表格/耗时组装最终 `AnalysisReport`。
- [ ] 重跑 Agent 测试和完整 `uv run --frozen pytest -q`；常规测试必须不联网。
- [ ] 显式配置 API key 后，可选运行一次受 `RUN_LIVE_AGENT_SMOKE_TEST=true` 门控的 live smoke test。
- [ ] 提交 `feat: add structured analysis Agent runtime`。

### Task 3: Record verified scope and handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/current.md`
- Modify: `docs/handoffs/latest.md`

- [ ] 标记 Task 6、Task 8 完成，明确 Task 7 仍待办且没有任何动态 SQL 路径。
- [ ] 运行 `rg -n "任务 6|任务 7|任务 8|Task 6|Task 7|Task 8" README.md docs` 核对任务状态一致性。
- [ ] 提交 `docs: record Task 6 and Task 8 completion`。
