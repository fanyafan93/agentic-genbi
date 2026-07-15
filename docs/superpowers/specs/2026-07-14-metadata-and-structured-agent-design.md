# Task 6 和 Task 8：元数据工具与结构化 Agent 设计

## 目标

交付受服务器白名单约束的 MySQL 元数据发现工具，以及使用 OpenAI Agents SDK 和 MiniMax 的单 Agent 报告叙述生成。Task 7 的动态 SQL 安全策略和受限执行不在本次范围内。

## 范围与边界

- Task 6 只读取 `ALLOWED_TABLES` 中明确配置的表，通过 SQLAlchemy Inspector 返回表名、注释、列名、类型、可空性和注释。
- Task 8 的 Agent 不注册工具、不生成或执行动态 SQL；它只根据用户问题和固定查询得到的可信表格上下文生成标题、摘要、图表映射、假设与警告。
- 服务端保留固定 SQL、表格、行数、截断标记、耗时与 SQL 尝试次数，模型输出无法覆盖这些字段。
- 未配置 `MINIMAX_API_KEY` 时任务以 `PROVIDER_NOT_CONFIGURED` 失败；原始模型响应、异常堆栈、密钥和隐藏表元数据不会返回浏览器。

## 架构

`Settings.allowed_tables` 是元数据工具唯一的授权来源。`app.database.metadata` 只对允许的表使用 SQLAlchemy Inspector；`app.tools.list_tables` 与 `app.tools.get_table_schema` 是无副作用的 Pydantic 类型化包装器。未知表统一返回 `TABLE_NOT_AVAILABLE`，不检查或暗示该名称是否在数据库中存在。

Task 8 先执行固定只读查询，再将结果作为可信上下文传给单 Agent。MiniMax 通过中国区 OpenAI 兼容 Chat Completions 端点 `https://api.minimaxi.com/v1` 调用，默认模型为 `MiniMax-M3`，Agents SDK 使用 `OpenAIChatCompletionsModel`，并关闭 tracing。

MiniMax M 系列不支持原生 JSON Schema `response_format`。因此 Agent 被提示只返回 JSON，runner 在移除残留的思考块或 JSON 围栏后使用 Pydantic 严格校验；无效结果统一成为 `INVALID_REPORT`。服务端再将模型叙述与可信查询数据组装为最终 `AnalysisReport`。

```mermaid
flowchart LR
  U["用户问题"] --> Q["固定只读查询"]
  Q --> C["可信查询上下文"]
  C --> A["单 Agent：报告叙述"]
  A --> V["Pydantic 校验"]
  V --> R["服务端组装 AnalysisReport"]
  M["ALLOWED_TABLES"] --> T["Task 6 元数据工具"]
```

Task 6 工具暂不注册给 Agent；Task 9 才接入。Task 7 完成前不存在模型生成 SQL 的执行路径。

## 验证

- 元数据工具使用 fake inspector 测试白名单、稳定顺序、列属性与隐藏表错误。
- Agent runner 使用 fake runner 测试，不联网且不读取 API key。
- 缺失凭据、供应商异常与无效结构化输出必须成为脱敏的失败任务。
- `RUN_LIVE_AGENT_SMOKE_TEST=true` 时运行真实 MiniMax smoke test，验证输出可通过 Pydantic 校验。
