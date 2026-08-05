# Report Architecture Design

## 目标

第一阶段只建立一条简单、可运行的 Report 主链路：

```text
Agent 生成或全量修改 Report JSON
→ 后端保存 Report 配置
→ 前端用 Puck 布局
→ Ant Design 提供筛选
→ 后端按筛选执行只读 SQL
→ ECharts 和 VTable 渲染查询结果
```

四个固定职责：

```text
Puck 管位置
ECharts 管图表
VTable 管表格
后端管数据
```

本设计不建设完整 BI 引擎，也不引入完整 `ReportRuntime`。

## 对象边界

产品层只保留 `Report`，不再使用以下 Report 领域概念：

```text
Analysis Report
Interactive Report
Report Artifact
artifactType
renderer
document
chartSpecs
gridSpecs
datasets
```

通用 Artifact 是否继续承载 SQL、Skill 等其他分析资产，不属于本次范围。

Report API 返回一个直接的 Report JSON：

```json
{
  "id": "report_001",
  "title": "渠道销售分析",
  "subtitle": "2026 年 8 月",
  "turnId": "turn_001",
  "layout": {},
  "filters": {},
  "charts": {},
  "tables": {},
  "queries": {}
}
```

`id`、`turnId`、`ownerId` 和时间字段由服务端管理。Agent 创建或修改时提交标题、副标题和五块配置。

## 数据模型

新建 `reports` 表：

```text
reports
├── id
├── title
├── subtitle
├── owner_id
├── turn_id nullable
├── layout JSONB
├── filters JSONB
├── charts JSONB
├── tables JSONB
├── queries JSONB
├── created_at
└── updated_at
```

保留 Report 分享功能，新建 `report_shares` 表：

```text
report_shares
├── report_id
├── recipient_user_id
├── permission
└── created_at
```

`permission` 沿用现有的 `view` 和 `view_and_reuse`；同一个 Report 与接收用户只保留一条分享记录。删除 Report 时级联删除对应分享记录。

数据库迁移直接删除旧 `analysis_report_shares` 和 `analysis_reports`。旧 Report 不迁移，旧数据不会进入新链路。

### Turn 关系

`reports.turn_id` 表示当前 Report 内容最后由哪个 Codex Turn 生成或修改：

```text
reports.turn_id
→ analysis_turns.id
→ analysis_turns.session_id
→ Codex threadId
```

规则：

- Agent 创建或覆盖 Report 时，服务端写入当前 Turn ID。
- 代码直接创建示例 Report 时，`turn_id` 为空。
- 一个 Turn 可以创建或修改多个 Report。
- Report 只记录当前内容对应的最新 Turn，不做版本管理。
- “新建会话”只引用 Report，不修改 `turn_id`。
- 新会话中的 Agent 真正修改并保存 Report 后，才更新 `turn_id`。
- Turn 被删除时，Report 保留，`turn_id` 置空。

不再保存 `source_thread_id` 或 `source_turn_id`。

## Report JSON

### Layout

`layout` 使用 Puck Data，只保存布局、内容块和组件引用：

```json
{
  "layout": {
    "content": [
      {
        "type": "FilterBlock",
        "props": {"filterIds": ["dateRange", "region"]}
      },
      {
        "type": "ChartBlock",
        "props": {"chartId": "sales-chart"}
      },
      {
        "type": "TableBlock",
        "props": {"tableId": "sales-table"}
      }
    ],
    "zones": {}
  }
}
```

Puck 不保存图表、表格、查询数据或筛选运行值。

### Filters

第一阶段只支持：

```text
select
multiSelect
date
dateRange
```

示例：

```json
{
  "filters": {
    "dateRange": {
      "type": "dateRange",
      "label": "日期范围",
      "defaultValue": ["2026-08-01", "2026-08-31"]
    },
    "region": {
      "type": "select",
      "label": "区域",
      "defaultValue": "华东",
      "options": [
        {"label": "华东", "value": "华东"},
        {"label": "华南", "value": "华南"}
      ]
    }
  }
}
```

筛选定义和默认值保存在 Report 中。用户当前筛选值只保存在浏览器内存，刷新后恢复默认值。

### Queries

`queries` 保存后端可执行的查询配置，不保存连接凭据：

```json
{
  "queries": {
    "sales-query": {
      "dataSource": "doris",
      "sql": "SELECT region, SUM(sales_amount) AS salesAmount FROM sales WHERE sale_date BETWEEN :startDate AND :endDate GROUP BY region",
      "parameters": {
        "startDate": {
          "filterId": "dateRange",
          "valueIndex": 0,
          "type": "date"
        },
        "endDate": {
          "filterId": "dateRange",
          "valueIndex": 1,
          "type": "date"
        }
      },
      "pagination": false
    }
  }
}
```

要求：

- SQL 只能是单条只读查询。
- 所有筛选值必须通过参数绑定进入 SQL，禁止字符串拼接。
- `dataSource` 只引用后端已有的数据源配置。
- 图表通常使用非分页聚合查询。
- VTable 明细通常使用分页查询。
- 图表和表格可以引用同一 query，也可以分别引用不同 query。

### Charts

`charts` 直接保存 ECharts option，不再设计中间 Chart DSL：

```json
{
  "charts": {
    "sales-chart": {
      "queryId": "sales-query",
      "option": {
        "xAxis": {"type": "category"},
        "yAxis": {"type": "value"},
        "series": [
          {
            "type": "bar",
            "encode": {"x": "region", "y": "salesAmount"}
          }
        ]
      }
    }
  }
}
```

前端把查询结果写入 `option.dataset.source` 后交给 ECharts。

### Tables

`tables` 直接保存 VTable options，不兼容 AG Grid：

```json
{
  "tables": {
    "sales-table": {
      "queryId": "sales-detail-query",
      "options": {
        "columns": [
          {"field": "region", "title": "区域"},
          {"field": "salesAmount", "title": "销售额"}
        ]
      }
    }
  }
}
```

前端把查询结果写入 VTable `records`。分页由后端查询接口完成。

## 前端 ReportContext

只实现一个轻量 `ReportContext`：

```text
ReportContext
├── 当前筛选值
├── 每个 query 的 rows / columns / total
├── 每个 query 的 loading / error
├── 执行 query
└── 修改筛选后重新执行受影响 query
```

它不负责缓存、请求取消、并发合并、复杂联动、权限或 SQL 生成。

运行流程：

```text
读取 Report
→ 初始化筛选默认值
→ 执行页面所引用的 queries
→ 保存查询结果
→ ChartBlock 和 TableBlock 按 ID 读取配置和结果
```

筛选变化：

```text
Ant Design 筛选值变化
→ 找出参数绑定了该 filterId 的 queries
→ 重新执行这些 queries
→ 更新对应图表和表格
```

表格翻页只重新执行对应的分页 query，不触发其他图表查询。

## 后端 API

Report CRUD：

```text
POST   /api/reports
GET    /api/reports
GET    /api/reports/{report_id}
PUT    /api/reports/{report_id}
DELETE /api/reports/{report_id}
```

分享：

```text
POST   /api/reports/{report_id}/shares
DELETE /api/reports/{report_id}/shares/{recipient_user_id}
GET    /api/report-center
```

查询：

```text
POST /api/reports/{report_id}/queries/{query_id}
```

查询请求：

```json
{
  "filters": {
    "dateRange": ["2026-08-01", "2026-08-31"],
    "region": "华东"
  },
  "page": 1,
  "pageSize": 50
}
```

查询响应：

```json
{
  "columns": [
    {"field": "region", "label": "区域", "type": "string"},
    {"field": "salesAmount", "label": "销售额", "type": "number"}
  ],
  "rows": [
    {"region": "华东", "salesAmount": 120000}
  ],
  "page": 1,
  "pageSize": 50,
  "total": 1
}
```

前端不提交 SQL。后端按 `report_id + query_id` 从数据库读取查询配置，绑定筛选参数并执行。

第一阶段不在查询接口中实现用户级 Report 权限、数据源权限、租户隔离、RLS 或复杂审计。现有“我的报表 / 分享给我”产品功能继续保留。

## Agent 工具

Report 工具统一为：

```text
create_report(report)
update_report(report_id, report)
```

`update_report` 全量覆盖 Report 配置，不支持局部 Patch。服务端保留 `id`、`owner_id` 和 `created_at`，自动更新 `turn_id` 与 `updated_at`。

全量覆盖采用 last-write-wins。第一阶段不做版本、并发冲突检测或字段合并。

Report 领域事件使用：

```text
genbi/report/created
genbi/report/updated
```

不再使用 Report 领域的 `genbi/artifact/*` 事件。

## 校验与错误处理

保存 Report 时校验：

- Puck 引用的 `filterId`、`chartId` 和 `tableId` 存在。
- chart/table 引用的 `queryId` 存在。
- SQL 是单条只读查询。
- 查询参数绑定到已定义 filter。
- filter、chart、table、query 配置结构有效。

错误响应：

- Report JSON 无效：`422`。
- SQL 包含写操作或多语句：`422`。
- 筛选参数缺失或类型错误：`400`。
- Report 或 query 不存在：`404`。
- 数据库执行失败：返回通用错误，不泄露连接信息。

前端按 query 显示加载、失败和重试状态；一个 query 失败不清空其他 query 的结果。

## 数据保存

PostgreSQL 只保存 Report 配置，不保存查询结果快照。

浏览器内存保存：

- 当前筛选值。
- 当前 query rows、columns、total。
- loading 和 error。

刷新页面后重新执行查询。查询结果不写回 Report。

## 明确不做

- 旧 Report 迁移或兼容。
- AG Grid 兼容。
- Excel 导出。
- 完整 `ReportRuntime`。
- 查询结果持久化。
- 缓存、请求取消、请求去重。
- 复杂筛选联动。
- Report 版本管理。
- 局部更新或 JSON Patch。
- 并发冲突检测。
- 用户级 Report 查询权限。
- 数据源权限。
- 租户隔离与 RLS。
- 复杂审计。

## 验收

后端：

- migration 新建 `reports` 和 `report_shares`，删除旧 Report 表。
- 新 Report CRUD、覆盖更新、删除和分享正常。
- `turn_id` 能关联到所属 Session/Thread，代码创建时允许为空。
- `create_report` 和 `update_report` 使用新 Report JSON。
- 写 SQL、多语句和无参数绑定的筛选输入被拒绝。
- 查询接口正确绑定筛选并返回分页结构。

前端：

- Puck 只保存布局和组件引用。
- Ant Design 筛选触发绑定 query。
- ECharts 使用查询结果。
- VTable 使用查询结果并支持后端分页。
- 一个 query 失败不影响其他 query。
- AG Grid 依赖和 Report 渲染代码被移除。
- Report 中不再出现旧 Artifact 字段和命名。

全量：

- 现有非 Report 的 Analysis Session、Turn、Codex Item 和通用分析资产行为不变。
- 前端 Vitest、TypeScript、后端 pytest 和 Compose 配置通过。
