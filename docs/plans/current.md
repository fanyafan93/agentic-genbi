# 当前分支状态

更新时间：2026-08-06 Asia/Shanghai

## 分支

- 当前分支：`feature/report-editing`
- 基线：`Agentic-GenBI`
- 工作区存在本轮 Report 收尾改动，以及此前尚未提交的分析工作台布局改动；未覆盖或重置这些改动。

## 当前实现

1. Report 领域直接切换
   - 产品和代码统一使用 `Report`，不再使用 Report-domain 的 Analysis Report、Interactive Report 或 Report Artifact。
   - PostgreSQL 使用 `reports` 与 `report_shares`；旧 `analysis_reports`、`analysis_report_versions`、`analysis_report_shares` 直接丢弃，不迁移旧 Report。
   - Report 只保留当前记录；`update_report` 全量覆盖，不保存历史版本。
   - 主记录保存 `layout`、`filters`、`charts`、`tables`、`queries`，不持久化查询结果行。

2. Report 来源与新建会话
   - Report 仅保存可空 `turnId`；有值时通过 Turn 反查来源 Codex Session。
   - 有来源 Session：显示“回到会话”和“新建会话”。
   - 无来源 Session：只显示“新建会话”。
   - “新建会话”先进入 `/analysis/new` 草稿，不预创建 Session、不自动发消息；用户首次提问时才创建 Codex Session，并把当前 Report 作为 `initial_report` 引用上下文。

3. Agent 工具链
   - Codex 通过 `GenBI_report` MCP Server 调用 `create_report(report)` 与 `update_report(report_id, report)`。
   - MCP 校验完整 Report 配置；服务端 projector 负责持久化并投影 `genbi/report/created`、`genbi/report/updated`、`genbi/report/failed`。
   - 新系统提示词迁移已发布 direct Report 工具说明。

4. 前端与数据运行时
   - Puck 管布局，Ant Design 管筛选，ECharts 管图表，VTable 管表格。
   - AG Grid 依赖和 Report 渲染代码已移除，不做兼容。
   - 简单 `ReportContext` 保存筛选值、调用查询接口，并把运行时数据交给图表和表格。
   - `queries` 保存数据源、只读 SQL、参数绑定与分页配置；后端执行只读校验、参数绑定和分页。

5. 当前明确不做
   - 旧 Report 迁移、Report 版本、Excel 导出。
   - 租户/RLS、复杂审计。
   - 缓存、取消查询和复杂组件联动。

6. 分析工作台待提交布局改动
   - 侧栏默认收起，对话区默认 34%，状态移到任务标题栏右侧。
   - 无 Report 时显示新的报告蓝图空状态。
   - 这些改动已保留在工作区，没有被 Report 架构提交覆盖。

## 已验证

- `python -m pytest backend/tests -q -p no:cacheprovider`
  - 212 passed，3 subtests passed。
- `npm.cmd test`
  - 24 test files，142 tests passed。
- `npx.cmd tsc --noEmit --incremental false`
  - passed。
- `docker compose config --quiet`
  - passed；Docker CLI 仍报告本机 `config.json` 读取权限警告，不影响配置结果。
- 容器运行
  - frontend、backend、postgres 均已重建并运行。
  - frontend production build 与 TypeScript 检查通过。
  - `GET /analysis/new` 返回 200。
  - `GET /health` 返回 `{"status":"ok"}`。
  - `GET /api/reports?limit=1` 返回 200。
- PostgreSQL
  - 仅存在 `reports`、`report_shares`；旧三张 Report 表不存在。
  - Prisma migration `20260806000000_direct_report_prompt` 已完成。
- 内置浏览器
  - 新前端标签控制台无 error / warning。
  - 代码创建的无来源示例 Report 仅显示“预览 / 删除 / 新建会话”，不显示“回到会话”。
  - 点击“新建会话”进入 `/analysis/new`，右侧保留当前 Report，未自动发送消息。

## 风险与待验证

- 标准 backend Docker build 曾因 `files.pythonhosted.org` 下载 128.8 MB Codex CLI wheel 超时；最终基于现有同版本 backend 镜像安装本轮新增的 `PyMySQL==1.2.0`、`sqlglot==30.15.0` 并覆盖源码，运行态验证通过。网络恢复后仍应再跑一次标准 `docker compose build --pull=false backend`。
- 真实数据源查询依赖运行环境的数据源配置和只读账号；本轮只验证了查询服务单元测试和 API 装载，未对生产业务表执行查询。
- 有来源 Report 的双按钮行为已有前端回归测试；本轮数据库按“不迁移旧 Report”清空后没有来源 Report 可做同等页面 smoke。

## 下一步

1. 通过代码或 Agent 生成包含多 Chart、多 Table 和筛选绑定的示例 Report。
2. 使用真实只读数据源做筛选、分页和刷新数据的页面验证。
3. 网络稳定后补跑标准 backend 镜像全量构建。
