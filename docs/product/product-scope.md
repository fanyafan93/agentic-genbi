# 产品边界

## 定位

Agentic GenBI 是面向数据分析师和运营人员的 AI Agent BI 系统。它不是一次性问答工具，而是一个让分析成果、自动化流程与 Agent 能力持续沉淀、更新、组合和复用的工作台。

核心闭环：

```text
用户提问
→ Agent 理解、追问与执行
→ 生成或更新 Artifacts
→ 继续追问和迭代
→ 资产复用、自动刷新或提炼为 Agent
→ 发布到 Agent 中心供其他人调用
```

本仓库当前是前端优先的 mock-first 原型。目标定义不代表已实现能力；实际完成状态以 `docs/plans/current.md` 为准。

## 一级入口

### 工作台

个人工作入口：最近会话、常用 Artifact、常用 Agent、自动化运行摘要、待回答的 Agent 追问和快捷入口。

### 会话

产品主操作界面，也是创建和迭代资产的地方。

```text
左侧：会话列表
中间：用户与 Agent 对话、Agent 追问、Run 执行过程
右侧：当前会话生成、更新或引用的 Artifacts
```

### 知识探索

面向分析构建者和 BI Agent 的调查工作区，而不是先维护一套大而全的指标库。它统一提供：

- **我的探索**：探索任务列表。每个任务包含一个探索会话 Agent，用对话方式检索资源库、展示过程、追问用户并形成结论。
- **资源库**：表、字段、历史 SQL、ETL 代码、报表源文件、Git 记录和样例数据的检索与关联。
- **知识库**：管理语义层知识、探索沉淀结论和治理信息，包括指标、维度、业务实体、字段映射、口径公式、报表逻辑、认证、标签、版本和 Agent 可见性。

Agent 优先复用已有实现，再检查表结构和数据；仅在存在具体疑点时追溯 ETL，最后执行、对账和验证查询。
知识探索当前只保存到知识库，不直接生成 Artifact 或可复用 Agent；这两类能力仍归属会话、Artifact 和 Agent 中心。

### Agent 中心

用于发现、使用、发布、维护和共享 Agent。

- **专业分析师 Agent**：理解业务目标、追问、规划、组织分析和维护资产。
- **工作流 Agent**：稳定执行刷新、日报、异常检测、通知等固定流程。
- 专业分析师 Agent 可以组合调用工作流 Agent。

### 系统

仅管理员可见，用于管理用户、团队、权限、数据源连接、模型与工具、运行限额、审计和全局配置。

## 核心对象

| 对象 | 职责 |
| --- | --- |
| `Conversation` | 保存用户与 Agent 的探索和协作过程。 |
| `Run` | 保存一次可追踪、可审计的 Agent 执行：消息、计划、工具调用、事件、结果、错误和成本。 |
| `Artifact` | 保存可复用成果，可包含 SQL、Python、数据表、图表、报告、仪表板、文档、数据集、工作流或 Agent 定义等。 |
| `Artifact Version` | Artifact 的不可变历史版本；引用默认跟随最新已发布版本，Run 记录实际使用版本。 |
| `Automation` | 以 Artifact 或 Agent 为入口的定时或事件触发运行，保留运行历史并产出新结果或更新资产。 |
| `Agent` | 可复用、可组合、可发布的能力包，具有输入、输出、工具、权限、版本和运行记录。 |
| `Knowledge Item` | 知识库中的可治理知识资产，可表示指标定义、维度、实体、字段映射、口径公式、业务规则、数据链路、报表逻辑或探索结论。 |
| `Knowledge Exploration Context` | 提供资源库、知识库和数据库元数据，让 Agent 能像 BI 开发人员一样查证、复用和验证。 |

对象关系：

```text
Conversation → Run → Messages / Plan / Tool Calls / Artifacts
Artifact → Versions / References / Automations / Agent inputs and outputs
Agent → 专业分析师 Agent 或工作流 Agent → 可组合调用其他 Agent
Knowledge Exploration Context → 为 Conversation、Run、Artifact 和 Agent 提供可检索、可验证的业务与数据上下文
Knowledge Item → Type / Tags / Approvals / Versions / Evidence / Agent usage
```

## 产品原则

- **Artifact 为中心**：会话是探索过程，Artifact 是可维护、可复用的成果。
- **持续协作**：Agent 可以追问；用户可以基于当前上下文继续更新或新增资产。
- **默认跟随最新版**：引用默认使用原始 Artifact 最新已发布版本，同时保留版本和 Run 快照以便追溯与回滚。
- **自动化即资产能力**：用户从 Artifact 或 Agent 上配置刷新、触发、通知和运行历史，而非进入割裂的调度产品。
- **Agent 是可治理资产**：成功的 Run 和 Artifact 可提炼为 Agent，并在 Agent 中心共享与组合。
- **可解释与受控**：用户能查看执行过程、输入、产物与来源；Agent 不绕过权限和数据安全边界。
- **前端先行，契约稳定**：先以 mock 后端验证体验和对象边界，后续以同一契约替换真实实现。

## 当前未实现

当前已具备最小飞书登录和 DB session，用于区分用户并隔离知识探索列表；这不是完整权限体系。

完整会话/Artifact 持久化、真实 Agent Runtime 治理、自动化调度、Agent 发布中心、团队权限、数据权限和审计仍未在本仓库实现。
