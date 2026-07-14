# Task 6 和 Task 8：元数据工具与结构化 Agent 设计

## 目标

交付白名单 MySQL 元数据工具，以及使用 OpenAI Agents SDK 和 MiniMax 的单 Agent 结构化报告生成。Task 7 的动态 SQL 安全策略与受限执行不在本次范围内。

## 实现边界

- `ALLOWED_TABLES` 是元数据访问唯一授权来源；不可用表统一为 `TABLE_NOT_AVAILABLE`，不探测隐藏名称。
- Agent 不注册工具、不生成或执行动态 SQL。它只基于固定查询产生的可信表格上下文生成标题、摘要、图表映射、假设与警告。
- 服务端保留固定 SQL、结果行、列、行数、耗时和 SQL 尝试次数，模型输出无法覆盖这些字段。
- MiniMax 使用 `https://api.minimaxi.com/v1` 的中国区 OpenAI 兼容 Chat Completions 端点，默认模型 `MiniMax-M3`；Agents SDK 通过 `OpenAIChatCompletionsModel` 调用它，并关闭 tracing。
- MiniMax M 系列不支持原生 JSON Schema `response_format`；Agent 被提示只返回 JSON，runner 移除残留思考块或 JSON 围栏后以 Pydantic 严格校验，不合规结果仍为 `INVALID_REPORT`。
- 缺失凭据、供应商错误和无效结构化输出分别以脱敏任务失败返回，不返回密钥、原始响应或堆栈。
