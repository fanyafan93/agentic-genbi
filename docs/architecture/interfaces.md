# MVP 接口与数据契约

状态：架构草案，供实施时按测试固化

日期：2026-07-14

## 约定

- HTTP 路径统一以 `/api/v1` 开头，JSON 字段使用 `snake_case`。
- 时间使用 UTC ISO 8601 字符串，例如 `2026-07-14T03:00:00Z`。
- 所有 ID 由服务端生成，建议使用 UUID；具体实现由骨架任务锁定。
- 未知字段默认拒绝，避免前后端悄悄接受拼写错误。
- 成功响应与错误响应使用明确模型，不使用任意字典作为长期契约。
- 原始数据库错误、凭据、堆栈和敏感 trace 不返回前端。

## API 草案

### `GET /health`

用于容器和本地开发的进程健康检查，不探测外部服务。

```json
{"status": "ok"}
```

### `POST /api/v1/analysis-tasks`

创建进程内分析任务。

- 请求：`AnalysisRequest`
- 成功：HTTP `202 Accepted`，返回 `AnalysisTaskStatus`
- 校验失败：HTTP `422`
- 容量已满：HTTP `429`

```json
{
  "question": "查询最近三个月各品牌销售额趋势，并分析下降最大的品牌。",
  "client_request_id": "optional-client-id"
}
```

```json
{
  "task_id": "b8ce5e63-8b64-4df5-a742-56571f25027a",
  "status": "queued",
  "steps": [],
  "report": null,
  "error": null,
  "created_at": "2026-07-14T03:00:00Z",
  "updated_at": "2026-07-14T03:00:00Z"
}
```

### `GET /api/v1/analysis-tasks/{task_id}`

返回任务当前快照。

- 成功：HTTP `200`，返回 `AnalysisTaskStatus`
- 不存在或服务重启后状态丢失：HTTP `404`，错误码 `TASK_NOT_FOUND`
- 前端在 `queued` 或 `running` 时继续轮询，在 `succeeded`、`failed` 或 `requires_input` 时停止。

MVP 不提供任务列表、删除、恢复和取消接口。

## Pydantic 模型草案

以下代码是接口草案，不代表仓库已有实现。

```python
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4000)
    client_request_id: str | None = Field(default=None, max_length=128)


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REQUIRES_INPUT = "requires_input"


class StepState(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentExecutionStep(StrictModel):
    step_id: str
    sequence: int = Field(ge=1)
    kind: Literal[
        "agent_started",
        "list_tables",
        "get_table_schema",
        "sql_validation",
        "execute_sql",
        "sql_repair",
        "report_generation",
    ]
    status: StepState
    title: str
    detail: str | None = None
    attempt: int | None = Field(default=None, ge=1, le=3)
    started_at: datetime
    finished_at: datetime | None = None


class AnalysisTaskStatus(StrictModel):
    task_id: str
    status: TaskState
    steps: list[AgentExecutionStep] = Field(default_factory=list)
    report: "AnalysisReport | None" = None
    error: "ApiError | None" = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class SqlErrorCategory(StrEnum):
    PARSE = "parse"
    UNKNOWN_TABLE = "unknown_table"
    UNKNOWN_COLUMN = "unknown_column"
    SYNTAX = "syntax"
    GROUPING = "grouping"
    SAFETY = "safety"
    PERMISSION = "permission"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


class SqlError(StrictModel):
    code: str
    category: SqlErrorCategory
    message: str                 # 已净化、可提供给 Agent/前端的消息
    retryable: bool
    attempt: int = Field(ge=1, le=3)
    database_code: int | str | None = None
    raw_message: str | None = Field(default=None, exclude=True)


class ResultColumn(StrictModel):
    name: str
    data_type: str


class SqlExecutionResult(StrictModel):
    success: bool
    sql: str
    columns: list[ResultColumn] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = Field(default=0, ge=0)
    truncated: bool = False
    duration_ms: int = Field(default=0, ge=0)
    error: SqlError | None = None


class ReportTable(StrictModel):
    columns: list[ResultColumn]
    rows: list[dict[str, Any]]
    row_count: int = Field(ge=0)
    truncated: bool = False


class ChartSpec(StrictModel):
    type: Literal["line", "bar", "pie"]
    title: str
    x_field: str
    y_fields: list[str] = Field(min_length=1)
    series_field: str | None = None


class AnalysisReport(StrictModel):
    title: str
    summary: list[str] = Field(min_length=1, max_length=8)
    sql: str
    table: ReportTable
    chart: ChartSpec | None
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    warnings: list[str] = Field(default_factory=list, max_length=8)
    query_duration_ms: int = Field(ge=0)
    sql_attempts: int = Field(ge=1, le=3)


class ApiError(StrictModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] | None = None
```

### 模型不变量

- `SqlExecutionResult.success` 为 `true` 时 `error` 必须为空；为 `false` 时 `error` 必须存在，且结果行必须为空。
- `AnalysisTaskStatus.status` 为 `succeeded` 时 `report` 与 `completed_at` 必须存在且 `error` 为空。
- `failed` 或 `requires_input` 时 `error` 与 `completed_at` 必须存在且 `report` 为空。
- `queued` 和 `running` 时 `report`、终态错误与 `completed_at` 都为空。
- `ChartSpec` 的 `x_field`、`y_fields` 和 `series_field` 必须引用 `table.columns` 中存在的字段。
- `sql_attempts` 包含首次执行，因此取值为 1 到 3；“最多重试两次”对应最大值 3。
- `raw_message` 只供内部审计，不进入 API JSON 或模型上下文。

## Agent 工具契约

### `list_tables`

输入：无业务参数，白名单和任务上下文由依赖注入提供。

```json
{
  "tables": [
    {"name": "sales_orders", "comment": "脱敏销售订单"}
  ]
}
```

失败只返回稳定工具错误，例如元数据连接失败；不得返回未授权表。

### `get_table_schema`

输入：

```json
{"table_name": "sales_orders"}
```

成功：

```json
{
  "table_name": "sales_orders",
  "columns": [
    {
      "name": "brand_name",
      "data_type": "varchar(128)",
      "nullable": false,
      "comment": "品牌名称"
    }
  ]
}
```

非白名单表返回 `TABLE_NOT_AVAILABLE`，不说明该表是否真实存在。

### `execute_sql`

输入：

```json
{"sql": "SELECT brand_name, SUM(amount) AS sales FROM sales_orders GROUP BY brand_name"}
```

输出始终符合 `SqlExecutionResult`。普通可修复错误以 `success: false` 返回给 Agent，而不是抛出并终止 runner。安全违规、系统异常和预算耗尽可由编排器在记录结构化错误后终止任务。

工具不接受用户传入的超时、行数或重试参数，防止调用方扩大安全预算。

## 为什么没有 `build_report` 工具

`build_report` 没有外部系统副作用，也不提供 Agent 缺失的信息。把它做成工具会增加一次工具选择、参数解析和失败重试，却不能增强安全性。MVP 将 `AnalysisReport` 设为 Agent 的结构化最终输出，并在服务层执行以下确定性校验：

1. Pydantic schema 校验。
2. 报告 SQL 必须等于最后一次成功执行的 SQL。
3. 报告表格必须来自最后一次查询结果，Agent 不得重新生成数值。
4. 图表字段必须存在于结果列。
5. 结论不得声称结果中不存在的精确数值。

实施时应由服务层注入不可修改的 SQL 和查询结果，Agent 只生成标题、摘要和受控图表字段映射；服务层组装最终报告，进一步降低数值幻觉风险。

## 报表 JSON 协议

对需求中的最小 JSON 做了三项调整：

- `y_field` 改为 `y_fields`，因为折线或柱状图常需要多个度量序列。
- `chart` 允许为 `null`，避免为不适合可视化的单值或文本结果伪造图表。
- 表格增加列类型、行数和截断标记，并增加耗时与 SQL 尝试次数，便于展示与审计。

```json
{
  "title": "最近三个月品牌销售额趋势",
  "summary": [
    "品牌 A 的销售额下降幅度最大。",
    "结论仅基于当前测试库返回的数据。"
  ],
  "sql": "SELECT ...",
  "table": {
    "columns": [
      {"name": "month", "data_type": "date"},
      {"name": "brand_name", "data_type": "varchar"},
      {"name": "sales_amount", "data_type": "decimal"}
    ],
    "rows": [
      {"month": "2026-04-01", "brand_name": "品牌 A", "sales_amount": "120000.00"}
    ],
    "row_count": 1,
    "truncated": false
  },
  "chart": {
    "type": "line",
    "title": "各品牌月度销售额",
    "x_field": "month",
    "y_fields": ["sales_amount"],
    "series_field": "brand_name"
  },
  "assumptions": ["销售额按订单金额字段汇总，未进行币种换算。"],
  "warnings": [],
  "query_duration_ms": 84,
  "sql_attempts": 2
}
```

十进制和日期的实际 JSON 序列化策略是待验证假设。推荐金额使用字符串以避免 JavaScript 浮点精度损失，前端在展示层格式化。

## 错误协议

所有 HTTP 错误使用统一外壳：

```json
{
  "error": {
    "code": "TASK_NOT_FOUND",
    "message": "分析任务不存在或状态已因服务重启而丢失。",
    "retryable": false,
    "details": null
  }
}
```

推荐稳定错误码：

| 错误码 | HTTP | 是否自动重试 | 说明 |
| --- | ---: | --- | --- |
| `VALIDATION_ERROR` | 422 | 否 | 请求格式或长度错误 |
| `TASK_CAPACITY_EXCEEDED` | 429 | 稍后人工重试 | 进程内任务容量已满 |
| `TASK_NOT_FOUND` | 404 | 否 | ID 错误或服务已重启 |
| `ANALYSIS_NEEDS_CLARIFICATION` | 200（任务终态） | 否 | 状态为 `requires_input` |
| `SQL_RETRY_EXHAUSTED` | 200（任务终态） | 否 | 两次修复已用尽 |
| `SQL_SAFETY_VIOLATION` | 200（任务终态） | 否 | 明确安全违规 |
| `DATABASE_UNAVAILABLE` | 200（任务终态） | 否 | 连接、权限或资源问题 |
| `AGENT_OUTPUT_INVALID` | 200（任务终态） | 否 | 最终结构化输出无效 |
| `INTERNAL_ERROR` | 500 | 否 | 未分类服务错误，响应不含堆栈 |

任务运行中的业务失败通过 `AnalysisTaskStatus` 终态表达，只有请求级失败使用非 2xx。这样轮询客户端始终能读取最终步骤和错误。

## 前后端通信约定

- 前端创建任务成功后立即保存 `task_id`，建议每 1 秒轮询；具体间隔需在前端任务中验证。
- 网络失败采用有限指数退避，但不自动重复创建任务。`client_request_id` 仅用于追踪，MVP 不承诺幂等创建。
- UI 只能展示后端提供的公开步骤摘要，不能从 trace 或日志拼装内部推理过程。
- ECharts option 由前端根据受控 `ChartSpec` 构建；后端不返回可执行 JavaScript。
- 后端可在不改变字段语义的前提下增加新的可选字段；删除、重命名或改变枚举需要版本化或同步修改前端。
- MVP 不使用 WebSocket 或 SSE；若轮询成本成为已验证问题，再新增 ADR 评估替换。

## 审计记录草案

审计不是公开 API，但每个任务至少记录：任务 ID、时间、状态、问题摘要或哈希、工具名、工具调用次数、每次 SQL、SQL 错误分类、内部原始错误、耗时、行数、截断状态和最终错误码。日志保留策略和脱敏规则需在接入真实测试库前人工确认。
