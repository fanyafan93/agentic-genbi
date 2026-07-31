# 产品边界

## 产品定义

Agentic GenBI 是一个围绕业务问题展开的 Agentic BI 工作台。

核心闭环：

```text
用户提出业务问题
→ openai-codex Python SDK / Codex 制定计划并调度工具
→ 业务语义库提供口径、字段、血缘和经验
→ 数据层安全取数
→ 生成报告、图表、SQL、数据快照、分析路径或 SKILL.md
→ 用户确认、修改、保存、复用
```

## 一级入口

| 入口 | 做什么 | 不做什么 |
| --- | --- | --- |
| 工作台 | 看最近分析、待确认口径、常用资产和运行状态 | 不承载复杂分析流程 |
| 分析工作台 | 用户提出问题、看 Agent 过程、回答追问、修改当前任务资产 | 不展示团队共享资产库 |
| 分析资产库 | 查看共享、已保存、可复用分析资产，并回到分析工作台继续 | 不做当前任务里的草稿编辑主界面 |
| 业务语义库 | 维护语义模型和业务知识 | 不作为普通用户分析问题的第二 Agent 入口 |
| 系统 | 管理数据源、权限、安全、模型、工具、审计和成本 | 不承载业务分析过程 |

## 核心对象

| 对象 | 定义 |
| --- | --- |
| `Analysis Task` | 产品层的分析任务，对应系统层 `Thread`。 |
| `Analysis Session` | 产品层的分析会话，对应用户在一个 `Thread` 中与 Agent 的协作过程。 |
| `Analysis Asset` | 产品层的分析资产，对应可复用 `Artifact`。 |
| `Thread` | 一个持续工作上下文，可对应分析任务、历史知识探索任务、资产继续编辑任务。 |
| `Turn` | 用户触发的一轮 Agent 工作，从用户输入开始，到 Agent 暂停、追问、失败或完成结束。 |
| `Run` | 一次实际执行尝试；多数情况下一个 `Turn` 对应一个 `Run`，重试、回放或多 Agent 并行时一个 `Turn` 可以有多个 `Run`。 |
| `Item` | `Turn` 内产生的结构化单元，如 message、tool_call、tool_result、plan、question、artifact、sql、chart、report。 |
| `Plan` | Codex Harness 生成的分析计划，是一种 `Item`。 |
| `Codex Harness Runtime` | 基于 openai-codex Python SDK / Codex 的编排执行基座，负责规划、执行、反思、工具调度、上下文管理、事件流和 Artifact 生成。 |
| `Business Semantic Library` | 业务语义库，统一承载语义模型和业务知识。 |
| `Semantic Model` | 让 Agent 看懂数据和系统，如报表语义、表字段、ETL 血缘、SQL 示例、指标维度。 |
| `Business Knowledge` | 让 Agent 记住被确认的业务经验，如口径、规则、字段来源、分析经验。 |
| `Artifact` | 可复用分析资产，如报告、图表、SQL、Python、数据快照、分析路径、`SKILL.md`；Artifact 也会作为 `Item` 出现在生成它的 `Turn` 中。 |
| `Artifact Version` | Artifact 的不可变历史版本。 |
| `Data Source` | MySQL、Doris、金蝶、FineReport、ETL、文件和其他业务系统连接。 |

产品层叫“分析任务 / 分析会话 / 分析资产”；系统层统一叫 `Thread / Turn / Item`。业务用户不需要看到这些系统术语。

## 分析模式

- **快速分析**：少追问，先产出可用初稿；不确定处标注假设和风险。
- **深度分析**：先补齐口径、范围、排除规则、维度、数据源和验证方式，再产出可复用资产。

模式只影响交互策略，不是安全边界。

## 产品原则

- 单一用户入口：用户只提出分析需求，不选择“分析 Agent”或“探索 Agent”。
- 业务语义库优先：稳定口径、字段、血缘和业务经验，比微调模型更重要。
- 分析资产库为中心：分析任务是过程，分析资产是可复用结果。
- 规划-执行-反思：复杂分析必须拆计划、调工具、校验结果、必要时追问。
- 可解释：用户能看到过程、证据、资产来源和假设。
- 可控：权限、SQL 安全、数据访问和审计必须在服务端。
- 可替换：模型供应商只是 adapter，不能绑死产品架构。
- Codex 优先：Codex 已有的编排、工具调用、MCP、Skills、Apps / Connectors、sandbox、approval、apply_patch、file search、git、模型适配和状态机制，优先复用，不自研替代品。

## 当前非目标

- 不做两个并列 Agent 入口。
- 不把浏览器端隐藏按钮、筛选或提示词当安全边界。
- 不在前端 mock 中伪装真实权限、真实共享或真实审批。
- 不优先建设 Agent 中心；`SKILL.md` 先作为分析资产治理。
- 不把 OpenAI Agents SDK 作为目标编排基座。
- 不自研 Codex 已经提供的通用 Agent 工程底座；本项目只做业务语义、数据安全、分析资产治理、前端体验和 Codex 适配。
