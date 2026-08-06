# Public Example Reports Design

## Goal

在 Report 中心新增“示例报表”区域，把现有 7 份抖音订单示例转为所有已登录用户可查看和复用的公开示例；删除已经无用的“代码示例：独立 Report”。同时在所有 Report 卡片上展示完整 Report ID，便于定位具体记录。

## Scope

本次实现公开示例的数据标记、Report Center API 返回、前端第三个区域、示例卡片操作限制、现有示例转换和 Report ID 展示。

本次不做管理员维护界面、示例分类、推荐排序、匿名访问、回收站、恢复、批量发布、审核流程或新的 Report 权限系统。已有软删除、完整 Report 预览、新建会话引用上下文和固定六列布局保持不变。

## Data Contract

`reports` 表新增：

```text
is_example BOOLEAN NOT NULL DEFAULT false
```

- `false` 表示普通 Report。
- `true` 表示系统公开示例。
- 软删除仍由 `deleted_at` 独立控制；已软删除记录不能出现在任何区域。
- `ReportRecord`、JSON 开发存储和 Report API 响应都包含 `isExample`。
- 普通 `create_report` 与 `update_report` 不负责发布示例，避免 Agent 在生成业务 Report 时意外公开内容。

新增一个仅供代码播种脚本使用的内部标记入口。入口复用现有 `GENBI_SYSTEM_API_TOKEN` 校验，并调用 Store 的显式示例标记方法；本次不为该入口建设管理员页面。

PostgreSQL migration 完成两项一次性数据处理：

1. 将下列 7 个标题且未删除的现有 Report 标记为 `is_example = true`：
   - 抖音订单简版示例
   - 抖音订单经营分析（复杂示例）
   - 抖音订单复杂表格（多筛选示例）
   - 抖音订单多栏经营看板（多筛选示例）
   - 抖音订单双区域独立筛选示例
   - 抖音订单表格能力示例
   - 抖音订单经营驾驶舱（图片布局模板）
2. 将标题为“代码示例：独立 Report”且未删除的记录设置 `deleted_at`，沿用软删除而不是物理删除。

`scripts/seed_report_examples.py` 在创建或覆盖每份示例后调用内部标记入口，保证以后重新播种或在新数据库播种时仍进入“示例报表”。

## Report Center Contract

`GET /api/report-center` 返回：

```json
{
  "mine": [],
  "sharedWithMe": [],
  "examples": []
}
```

规则如下：

- `mine`：当前用户拥有、未删除且 `is_example = false`。
- `sharedWithMe`：分享给当前用户、未删除且 `is_example = false`。
- `examples`：所有未删除且 `is_example = true` 的 Report，与当前用户无关。
- 示例 Report 不同时出现在“我的报表”或“分享给我”。
- 三个区域都按 `updated_at` 降序并沿用现有 `limit`。

示例不是“分享给所有人”。系统不创建通配接收人，也不为每个用户生成 `report_shares` 记录。

## Frontend

Report 中心按以下顺序显示：

1. 我的报表
2. 分享给我
3. 示例报表

三个区域继续使用固定 6 个等宽列并填满内容区。

示例卡片行为：

- 点击卡片主体打开完整 Report。
- 悬停或键盘聚焦后只显示“新建会话”。
- 不显示“删除”。
- 不显示“回到会话”。
- “新建会话”把当前示例 Report 作为引用上下文，沿用现有首次提问时创建 Codex Session 的行为。

所有“我的报表”“分享给我”“示例报表”卡片都在标题信息区展示完整 `report.id`。ID 使用小号等宽字体和 `overflow-wrap: anywhere`，不能只显示截断前缀或省略号，以保证用户可以直接定位完整记录。

## Error Handling

- 示例标记入口缺少或使用错误的系统 Token 时返回 401。
- 标记不存在、已删除或所有者不匹配的 Report 时按不可标记处理。
- Report Center 加载失败时保持现有整体错误回退，不显示过期的示例列表。
- 示例 Report 被软删除后，列表、按 ID 打开和查询执行都继续按不存在处理。

## Verification

后端覆盖：

- JSON Store 与 PostgreSQL Store 的普通、分享、示例三类列表互斥。
- 示例对不同用户返回相同结果。
- 软删除示例不再返回。
- 内部标记入口的 Token 拒绝、所有者限制和成功路径。
- migration 包含字段新增、7 个标题转示例和独立 Report 软删除。
- 播种脚本在每份示例 upsert 后执行示例标记。

前端覆盖：

- Report Center 类型和加载状态接收 `examples`。
- 第三个“示例报表”区域渲染。
- 示例卡片只有“新建会话”，没有“删除”和“回到会话”。
- 所有类型的卡片展示完整 Report ID。

完成后运行相关 pytest、相关 Vitest、全量前后端测试、TypeScript、`docker compose config --quiet`，重启必要服务，并用内置浏览器确认 7 份示例、完整 ID、六列布局、示例操作和控制台状态。
