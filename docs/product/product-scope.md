# 产品边界

## 产品定义

Agentic GenBI 是一个围绕业务问题展开的 Agentic BI 分析工作台。

核心闭环：

```text
用户提出业务问题
-> Codex 在同一个 Thread 中创建 Turn 并调度 Item
-> GenBI 提供业务语义、受控数据工具和权限边界
-> Codex 产出分析过程与结果
-> GenBI 保存 Artifact、版本和血缘
-> 用户确认、修改、保存、复用、分享或发布
```

## 单一入口

| 入口 | 做什么 | 不做什么 |
| --- | --- | --- |
| 分析工作台 | 左侧对话、过程、追问；右侧持续生成和修改当前分析结果 | 不暴露第二个分析入口 |
| 我的分析 | 查看已保存结果、历史版本和分析模板，并回到分析工作台继续 | 不承载独立执行链路 |
| 业务语义库 | 维护 FineReport 语义案例、指标、字段、关联规则和业务知识 | 不作为普通用户提出分析问题的第二入口 |
| 系统 | 管理数据源、权限、安全、模型、工具、审计和成本 | 不承载业务分析过程 |

## 核心对象

| 对象 | 定义 |
| --- | --- |
| `Analysis Task` | GenBI 业务任务记录，保存用户、租户、工作空间、标题、权限归属和 `codexThreadId`。 |
| `Analysis Result` | 产品层的分析结果；第一类结果是交互式分析报告。 |
| `Codex Thread` | Codex 管理的真实 Agent 会话、上下文和压缩状态。 |
| `Codex Turn` | 用户触发的一轮 Agent 工作。 |
| `Codex Item` | Turn 内产生的消息、推理、工具调用、工具结果、模型输出和产物。 |
| `Business Semantic Library` | 业务语义库，承载 FineReport 语义案例、指标、字段、关联规则和业务知识。 |
| `Data Source` | MySQL、Doris、金蝶、FineReport、ETL、文件和其他业务系统连接。 |
| `Artifact` | 可复用分析资产，如报告、图表、SQL、数据快照、分析路径和 `SKILL.md`。 |
| `Artifact Version` | Artifact 的不可变历史版本。 |
| `Artifact Lineage` | Artifact / Version 与 Codex Thread / Turn / Item 的来源关系。 |
| `Interactive Report` | 结构化 JSON：页面布局、筛选定义、查询引用、Chart Spec 与 Grid Spec。 |

## 最终边界

Codex 负责：

- Agent Loop
- Thread
- Turn
- Item
- 上下文
- 上下文压缩
- 工具调度
- 流式执行事件
- 中断和追加指令
- Sandbox / Approval
- 失败、重试和内部请求尝试

GenBI 负责：

- 用户和租户
- 数据权限
- 数据源
- FineReport 语义案例
- 指标与关联规则
- 受控 SQL 工具
- Artifact
- Artifact 版本和血缘
- 分享、发布和治理

## 产品原则

- 单一用户入口：用户只提出分析需求，不选择不同 Agent。
- Codex 优先：Codex 已有的 Agent Loop、Thread、Turn、Item、上下文、工具调度、sandbox、approval 和事件流不自研替代。
- 业务语义库优先：稳定口径、字段、血缘和业务经验比微调模型更重要。
- 分析结果为中心：聊天是协作过程，交互式报告才是用户要保存、分享、导出与复用的交付物。
- 服务端安全边界：权限、SQL 安全、数据访问和审计必须在服务端。

## 当前非目标

- 不做两个并列 Agent 入口。
- 不把浏览器端隐藏按钮、筛选或提示词当安全边界。
- 不在前端 mock 中伪装真实权限、真实共享或真实审批。
- 不自研 Codex 已经提供的通用 Agent 工程底座。
