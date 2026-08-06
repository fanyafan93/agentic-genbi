# Report 分步生成与实时渲染设计

日期：2026-08-06
状态：已完成对话设计，等待书面规格复核

## 背景

当前 `GenBI_report` MCP Server 只提供：

```text
create_report(report)
update_report(report_id, report)
```

Agent 必须一次生成包含 `layout`、`filters`、`queries`、`charts` 和
`tables` 的完整 Report。真实 MiniMax 验证已经暴露出三个问题：

1. 深层、宽大的 Report Schema 容易产生参数类型和引用错误。
2. 一处校验失败会让模型重新组织整份 Report，修复成本和漂移风险都很高。
3. Agent 可能反复说明“即将调用工具”，却没有新的成功工具 Item，导致 Turn
   长时间没有可见产物。

本设计把 Agent 的一次性完整写入改为服务端持久化的分步构建。用户在右侧看到
Report 逐步出现；刷新页面、切换会话再返回后，已经生成的内容仍能恢复。只有完整
校验通过的构建结果才能成为正式 Report。

## 目标

- Agent 每次只提交一小段、扁平且可独立校验的 Report 配置。
- 标题、筛选器、图表和表格能够随着成功工具调用逐步渲染。
- 构建状态保存在 PostgreSQL，刷新和切换会话后可以恢复。
- 单个步骤失败不清空已经生成且有效的部分。
- 发布过程是原子的，不产生残缺的正式 Report。
- 保留现有 Report 单记录模型，不引入 Report 版本。
- 保留 Codex 原生 Thread、Turn、Item 和终态事件，不自研第二套 Agent 生命周期。

## 非目标

- 本轮不重构已有 Report 编辑流程。
- 本轮不实现 Report 版本、历史回滚或多人协同编辑。
- 本轮不持久化查询结果行。
- 本轮不改变 Puck、ECharts、VTable 和 Ant Design 的职责。
- 本轮不调整租户、RLS、分享、发布审批或复杂审计。
- 本轮不把构建中的 Report 展示到 Report 中心。
- 本轮不让前端直接写入 Report 或 ReportBuild。

## 核心术语

### Report

已经通过完整校验的正式分析结果。继续使用当前单记录结构：

```text
title
subtitle
layout
filters
queries
charts
tables
```

### ReportBuild

服务端持久化的 Report 构建状态。它是生成过程，不是 Report 版本，也不作为独立
产品对象暴露给普通用户。界面只显示“正在生成报告”及当前可渲染内容，不显示
“Draft”术语。

## 总体流程

```text
用户提出分析问题
→ Codex 创建 Turn
→ Agent 查询并验证真实数据
→ start_report_build
→ 分步写入 filters / queries / charts / tables
→ 前端按 revision 实时获取并渲染当前 ReportBuild
→ set_report_layout
→ validate_report_build
→ publish_report_build
→ 原子写入正式 Report
→ 投影 genbi/report/created
```

每一次成功的分步写入都形成一个真实 Codex Tool Item。GenBI 不把 ReportBuild
状态伪装成新的 Turn 或 Item 生命周期。

## 数据模型

新增 PostgreSQL 表 `report_builds`：

```text
id                    text primary key
owner_id              text not null
session_id            text not null
turn_id               text not null
target_report_id      text null
status                text not null
content               jsonb not null
validation_errors     jsonb not null default '[]'
revision              bigint not null default 0
published_report_id   text null
last_successful_step  text null
step_attempts         jsonb not null default '{}'
created_at            timestamptz not null
updated_at            timestamptz not null
expires_at            timestamptz not null
```

最低索引：

```text
primary key (id)
index (session_id, updated_at desc)
index (turn_id)
index (owner_id, status, updated_at desc)
index (expires_at)
```

`target_report_id` 为后续复用同一构建链路修改已有 Report 预留。本轮新建路径必须
为 `null`，不借此扩展 Report 编辑范围。

`content` 始终保持与正式 Report 相同的顶层结构。创建时使用可渲染的空骨架：

```json
{
  "title": "渠道销售分析",
  "subtitle": "按渠道查看销售表现",
  "layout": {"content": [], "zones": {}},
  "filters": {},
  "queries": {},
  "charts": {},
  "tables": {}
}
```

查询结果行不写入 `content`。

## 状态机

```text
building
  ├─ successful mutation → building
  ├─ validate            → validating
  └─ unrecoverable error → failed

validating
  ├─ validation failed   → failed
  └─ validation passed   → building

failed
  └─ successful mutation → building

building
  └─ publish succeeded   → published
```

`published` 是终态。发布后的正式内容从 `reports` 读取。

失败不删除构建内容。`updated_at` 连续七天未变化的 `building` 或 `failed` 构建
可以清理；成功发布的构建保留 24 小时用于诊断后清理。清理是后台维护动作，不
影响发布事务。

## Agent 工具契约

正常分析运行时只向 Agent 暴露以下九个 ReportBuild 工具。

### 1. `start_report_build`

输入：

```text
title
subtitle
```

`owner_id`、`session_id` 和 `turn_id` 必须来自服务端执行上下文，模型不能传入或
覆盖。调用成功后返回 `buildId` 和初始 `revision`。

### 2. `get_report_build`

输入：

```text
build_id
```

返回当前构建的完整规范化 `content`、状态、revision 和校验错误，但不回传查询
结果行。完整 content 用于跨 Turn 恢复，避免 Agent 根据不完整摘要重复创建组件。
只允许读取当前 Principal 有权访问且属于当前分析上下文的构建。

### 3. `set_report_filters`

输入：

```text
build_id
filters
```

一次设置完整筛选器集合。服务端立即校验 filter 类型、标签、选项和默认值；如果
现有 query 仍引用即将被删除或变得不兼容的 filter，则拒绝本次修改。

### 4. `upsert_report_query`

输入：

```text
build_id
query_id
query
```

一次新增或更新一条查询。服务端校验只读 SQL、单语句、参数占位符、筛选器绑定、
分页和受控字段。

### 5. `upsert_report_chart`

输入：

```text
build_id
chart_id
chart
```

一次新增或更新一张 ECharts 图表。引用的 `queryId` 必须已经存在，`option.series`
必须有效。

### 6. `upsert_report_table`

输入：

```text
build_id
table_id
table
```

一次新增或更新一个 VTable 表格。引用的 `queryId` 必须已经存在，
`options.columns` 必须有效。

### 7. `set_report_layout`

输入：

```text
build_id
layout
```

设置完整布局。布局只能引用当前构建中已经存在的 filter、chart 和 table。

在显式布局尚未生成时，读取服务根据已有筛选器、图表和表格派生确定性的临时自动
布局，使组件能够立即出现。临时布局不写回 `content.layout`，因此 chart/table
mutation 仍只修改自己的 section。`set_report_layout` 成功后以显式布局为准。

### 8. `validate_report_build`

输入：

```text
build_id
```

对当前 `content` 执行与正式 Report 相同的完整校验，并返回所有可定位错误，而不
只返回第一处错误。校验失败时保存结构化错误：

```json
{
  "path": "queries.q_top10.parameters",
  "code": "invalid_type",
  "message": "query parameters must be an object"
}
```

### 9. `publish_report_build`

输入：

```text
build_id
```

仅在完整校验通过后发布。成功返回 `reportId`、`buildId` 和最终 `revision`。

## 旧工具兼容

现有 ReportStore、REST API 和内部 `create_report` / `update_report` 能力继续
保留。现有正式 Report 的读取和编辑不受影响。

正常 Agent 分析运行时的工具 allowlist 不再包含一次性完整
`create_report` / `update_report`，避免模型绕过分步链路。若迁移期必须保留旧 MCP
调用，只能通过默认关闭的兼容配置启用，不能同时作为 Agent 推荐路径。

## 写入、并发与幂等

- 每个 mutation 在数据库事务中读取并锁定目标 `report_builds` 行。
- 成功 mutation 只更新自己负责的 section，清除已修复错误，然后递增
  `revision`。
- 步骤校验失败不修改 `content`，但持久化结构化错误、`failed` 状态和尝试次数，
  并递增 `revision`，使刷新后仍能恢复真实失败状态。
- `query_id`、`chart_id` 和 `table_id` 是稳定键；重复调用执行 upsert，不创建重复
  组件。
- mutation 不接收整份 Report，因此不能用旧快照覆盖其他 section 的新内容。
- Tool Item 或网络重试使用同一个稳定 ID，结果保持幂等。
- `revision` 只由服务端递增，模型不能指定。
- 前端忽略小于当前 revision 的更新，防止乱序事件回退画面。

## 校验策略

### 步骤校验

每个写工具只校验本步骤及其直接依赖：

- filter 自身结构；
- query 自身结构、SQL 安全和 filter 引用；
- chart/table 自身结构和 query 引用；
- layout 自身结构和全部组件引用。

步骤失败不修改 `content`，也不清空之前内容；失败状态和结构化错误按上述写入规则
持久化。

### 完整校验

`validate_report_build` 和 `publish_report_build` 都执行正式 Report 的完整校验。
`publish_report_build` 不相信此前校验结果，必须在发布事务中再次校验，避免校验
后状态发生变化。

## 发布事务

`publish_report_build` 在一个数据库事务中完成：

```text
锁定 ReportBuild
→ 确认未发布
→ 完整校验 content
→ 创建正式 Report
→ 写入 ownerId 和当前 turnId
→ 将 ReportBuild 标记为 published
→ 记录 published_report_id
→ 提交事务
```

任一步失败都回滚，不留下残缺 Report。重复发布同一个已经 `published` 的 build
幂等返回原 `published_report_id`，不会创建第二份 Report。

本轮只创建新 Report，不更新已有 Report，不产生 Report 版本。

## 实时事件与前端恢复

Codex 的工具执行继续使用原生：

```text
item/started
item/completed
turn/completed
```

GenBI 只补充 Report 领域投影。每次持久化的 ReportBuild 状态变化都投影同一种
状态事件：

```text
genbi/report/build_updated
```

最小载荷：

```json
{
  "eventSource": "genbi_projection",
  "buildId": "build_xxx",
  "sessionId": "session_xxx",
  "turnId": "turn_xxx",
  "status": "building",
  "revision": 5,
  "changedSection": "charts"
}
```

构建失败仍使用同一个 `build_updated` 事件并携带 `status: failed`，不创建
`turn/failed`、`item/failed` 或新的 ReportBuild 失败生命周期事件。

发布成功继续投影现有：

```text
genbi/report/created
```

前端收到 `build_updated` 后按 `buildId + revision` 获取服务端权威状态。事件不携带
整份 Report、SQL、查询结果或敏感工具参数。

进入或切回一个会话时：

1. 正常加载已有正式 Report。
2. 查询该会话最新的未过期 `building`、`validating` 或 `failed` ReportBuild。
3. 若存在构建态，恢复其 `content`、状态和 revision。
4. 新建 Report 场景直接显示构建内容。
5. 未来编辑已有 Report 时，正式 Report 保持可见，构建态作为未发布修改恢复；该
   编辑行为不属于本轮实现。

## 构建态查询与渲染

ReportBuild 复用现有 ReportRenderer、ReportContext、ECharts 和 VTable，不新增
第二套渲染器。

为使构建中的图表和表格能够显示真实数据，查询服务接受一个经过授权和校验的
ReportBuild 作为查询配置来源。它继续执行现有只读 SQL、参数绑定、分页和结果
裁剪规则。

```text
正式 Report：report_id + query_id
构建态：build_id + query_id
```

两条路径调用同一个底层查询执行服务。查询结果只保存在浏览器运行时内存，刷新后
重新执行，不写入 `report_builds`。

## 无进展与重试保护

- 同一个步骤按 `(tool_name, object_id)` 识别，使用同一对象 ID 自动修复最多
  两次。
- `start_report_build` 成功后开始计算无进展次数；一个模型回合指 provider
  完成一次响应。任何成功的 ReportBuild mutation 都把计数清零。
- 连续三个模型回合没有产生成功的 ReportBuild mutation 时，终止当前 Turn。
- 超出 Turn 总时限时按 Codex 原生中断路径结束。
- Turn 失败或取消不删除 ReportBuild，用户下一次提问可以从服务端状态继续。
- 终止时使用 `turn/completed`、`status: failed` 和结构化 `error`；取消继续使用
  当前 Codex 取消终态，不新增生命周期事件。

## 安全边界

- `owner_id`、`session_id`、`turn_id` 和 Principal 来自服务端上下文，不能相信
  MCP 参数。
- 所有 get、mutation、validate、publish 和构建态查询都校验 Principal 与会话
  归属。
- SQL 继续通过现有只读安全校验和受控数据源执行。
- 事件不返回凭据、Token、Cookie、连接字符串或完整工具环境。
- 前端不能直接修改 `content`、revision 或 status。

## API 边界

前端只需要只读恢复与查询入口：

```text
GET  /api/report-builds/{build_id}
GET  /api/analysis/threads/{session_id}/report-builds/active
POST /api/report-builds/{build_id}/queries/{query_id}/run
```

所有写操作由 Agent 的 MCP 工具经服务端 ReportBuildService 完成。API 和 MCP 共用
同一个 ReportBuildService、校验器和权限检查，不复制领域逻辑。

## 测试与验收

### 后端

- migration 可在全新数据库创建 `report_builds`，重复执行幂等。
- 九个工具的 Schema 都是小范围输入，不包含完整 Report 联合参数。
- 服务端上下文覆盖 owner/session/turn，模型无法伪造归属。
- 每个成功 mutation 只修改目标 section 并递增一次 revision。
- 步骤失败保持 content 不变，同时持久化错误、失败状态和新 revision。
- 重复 upsert 同一稳定 ID 不产生重复组件。
- 两个并发 mutation 不会互相覆盖。
- 步骤校验失败不修改构建内容。
- 完整校验一次返回所有可定位错误。
- publish 原子创建一个正式 Report；重复 publish 不重复创建。
- 未授权读取、修改、查询和发布被拒绝。
- 构建态查询复用现有 SQL 安全、参数绑定和分页规则。
- 旧 Report CRUD、渲染和查询测试继续通过。

### 前端

- 标题、筛选器、图表和表格按 revision 逐步出现。
- 较旧 revision 事件不能覆盖较新画面。
- 刷新页面后恢复当前构建内容。
- 切换会话不会取消 Turn；切回后恢复构建状态和最新内容。
- 单个组件失败时保留其他已成功组件。
- 发布成功后无闪烁地切换到正式 Report。
- Report 中心不显示未发布 ReportBuild。
- 构建态和正式态使用同一 ReportRenderer。

### 端到端

- 使用真实 PostgreSQL 验证创建、恢复、并发 upsert 和原子发布。
- 使用真实 MiniMax 连续执行至少三次全新 Session 的 Report 生成。
- 三次都必须产生真实 ReportBuild 工具 Item、逐步渲染并最终写入一个可查询、
  可刷新恢复的正式 Report。
- 参数校验失败场景必须在有限重试内修复或以原生失败终态结束，不能无限循环。
- 浏览器控制台没有新增 error 或 warning。

## 完成标准

只有同时满足以下条件，本切片才算完成：

```text
Agent 默认不再一次提交完整 Report
九个 ReportBuild 工具可发现且可执行
生成中的内容持久化并按 revision 实时渲染
刷新和切换会话能够恢复
失败不清空已生成内容
无进展循环能够终止
发布原子且幂等
正式 Report 模型和现有渲染行为不变
真实 PostgreSQL 并发验证通过
真实 MiniMax 三次重复生成通过
现有 Report 前后端回归测试通过
```
