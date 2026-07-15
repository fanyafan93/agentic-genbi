# ADR-001：MVP 使用 OpenAI Agents SDK

- 状态：已接受
- 日期：2026-07-14

## 背景

MVP 需要一个数据分析 Agent 按需调用元数据与 SQL 工具，在普通 SQL 错误后继续推理，并输出符合固定 schema 的报告。当前需求明确指定 OpenAI Agents SDK，且第一版只需要单 Agent、有限工具和短生命周期运行。

## 决策

第一版使用 OpenAI Agents SDK 的 Python 运行时，注册 `list_tables`、`get_table_schema` 和 `execute_sql` 三个 function tools，并使用 Pydantic 类型作为结构化最终输出。FastAPI 的 Analysis Service 包装 SDK runner，拥有全部硬性预算和终止策略。

SDK tracing 只用于开发诊断。默认关闭 trace 中敏感模型和工具数据；是否启用远端 trace 需要在接入测试数据前人工确认。

## 原因

- 与 Python/FastAPI/Pydantic 技术栈一致。
- SDK 原生支持函数工具、结构化输出、运行生命周期与 tracing，足以覆盖单 Agent MVP。
- 运行时保持轻量，避免为了一个短流程先建设图编排和持久状态基础设施。
- 工具背后的数据库与安全服务不依赖 SDK 装饰器，未来替换运行时不会迫使重写核心安全逻辑。

上述能力已于 2026-07-14 对照 OpenAI Agents SDK 官方文档核对；实施时仍需锁定并测试具体 SDK 版本。

## 为什么暂不使用 LangGraph

当前流程只有一个 Agent、三个工具、一个有限重试循环和一个最终输出，没有复杂分支、跨会话持久状态、人工审批节点或可暂停恢复需求。引入 LangGraph 会增加状态模型、节点/边定义、检查点和测试维度，却不能替代 SQL 安全层或数据库权限。

本决策不是认为 LangGraph 无价值，而是当前没有足够复杂度证明它的成本合理。

## 未来引入 LangGraph 的触发条件

只有出现以下一个或多个已验证需求时才重新评估：

- 工作流需要跨进程持久化、暂停、恢复或人工审批。
- 出现多个复杂分支，使用普通服务代码后状态转换已难以理解和测试。
- 单任务跨越长时间、多外部系统，并要求节点级重放或补偿。
- 多 Agent 协作成为真实需求，且需要显式路由、共享状态和确定性控制。

评估前必须先证明简单 Analysis Service 无法以清晰、可测试的方式满足需求。

## 优点

- 最少运行时组件，交付路径短。
- 工具契约可直接由 Python 类型生成和校验。
- Agent 最终输出可直接绑定 Pydantic 契约。
- 官方 tracing 可辅助定位模型、工具和运行问题。

## 代价与风险

- SDK 和模型行为会变化，必须锁版本并通过固定问题评测。
- Agent 工具选择和 SQL 生成仍具概率性，不能把安全托付给 SDK。
- 内置 tracing 可能包含敏感输入和工具结果，必须显式关闭敏感数据或完全禁用。
- 简单 runner 不提供持久任务恢复；这是进程内 MVP 的已接受限制。

## 缓解措施

- 所有数据库访问经过独立、安全可单测的服务。
- 工具调用、SQL 尝试、任务时长和输出校验由 FastAPI 侧硬限制。
- 锁定 SDK 与模型配置，维护至少 5 个固定端到端问题。
- Agent 上下文不提供文件、网络、代码执行或数据库写入工具。

## 参考

- OpenAI Agents SDK Agents：`https://openai.github.io/openai-agents-python/agents/`
- OpenAI Agents SDK Tools：`https://openai.github.io/openai-agents-python/tools/`
- OpenAI Agents SDK Tracing：`https://openai.github.io/openai-agents-python/tracing/`
