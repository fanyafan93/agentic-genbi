# Task 6 and Task 8 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现受控元数据发现与 MiniMax Agent 报告叙述，保持动态 SQL 路径关闭。

**Architecture:** Task 6 将 SQLAlchemy Inspector 访问封装为仅暴露 `Settings.allowed_tables` 的类型化工具。Task 8 先运行固定查询，再以 MiniMax OpenAI 兼容 Chat Completions 调用单 Agent，最终只合并模型叙述字段与服务端持有的可信查询数据。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2、MySQL 8.4、OpenAI Agents SDK、MiniMax、pytest、uv。

## Global Constraints

- 不实现 Task 7、动态 SQL 生成、SQL 解析或动态 SQL 执行。
- `ALLOWED_TABLES` 是 Task 6 唯一授权来源，不探测白名单之外的名称。
- API key、原始供应商输出、异常堆栈和隐藏元数据不能进入 API 响应。
- 常规测试使用 fake，不访问网络、不要求 MiniMax API key。
- MiniMax M 系列不支持原生 JSON Schema；runner 必须以 Pydantic 验证提示生成的 JSON。

---

### Task 1: Add typed allowlisted metadata tools

- [x] 新增 `backend/app/schemas/tools.py`、`backend/app/database/metadata.py`、`backend/app/tools/list_tables.py` 和 `backend/app/tools/get_table_schema.py`。
- [x] 增加 `ALLOWED_TABLES` 配置与稳定、可 JSON 序列化的表和列契约。
- [x] 测试白名单过滤、列元数据和 `TABLE_NOT_AVAILABLE` 脱敏错误。
- [x] 验证命令：`uv run --frozen pytest tests/tools/test_list_tables.py tests/tools/test_get_table_schema.py -v`。

### Task 2: Add MiniMax Agent narrative runtime

- [x] 锁定 `openai-agents==0.18.2`，新增 Agent、提示词和可注入 runner。
- [x] 使用 `OpenAIChatCompletionsModel` 与 `https://api.minimaxi.com/v1` 调用 `MiniMax-M3`，运行时关闭 tracing。
- [x] 固定查询结果由服务端保留；模型只生成标题、摘要、图表映射、假设和警告。
- [x] 映射 `PROVIDER_NOT_CONFIGURED`、`PROVIDER_ERROR` 和 `INVALID_REPORT`。
- [x] 新增 fake runner、提示词、任务失败映射和可选 live smoke 测试。
- [x] 验证命令：`uv run --frozen pytest -q`；真实模型：`RUN_LIVE_AGENT_SMOKE_TEST=true uv run --frozen pytest tests/agents/test_live_smoke.py -m live_agent -v`。

### Task 3: Record verified scope and handoff

- [x] 更新 Docker 环境注入、`.env.example`、README、项目计划和交接文档。
- [x] 标记 Task 6、Task 8 完成，明确 Task 7 保持待办。
- [x] 验证 `docker compose config --no-interpolate`，确认编排包含 `ALLOWED_TABLES`、`MINIMAX_API_KEY`、`MINIMAX_BASE_URL` 和 `MINIMAX_MODEL`。
