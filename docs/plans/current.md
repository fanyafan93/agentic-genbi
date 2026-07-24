# 当前任务

更新时间：2026-07-25（Asia/Shanghai）

## 当前状态
- 当前仓库：`E:\my_repo\agentic genbi`
- 当前切片：从现有 `GenBI/frontend/public/ui-demo.html` 静态 demo 起步，搭建 Agentic GenBI 前端工程骨架。
- 已迁移：`AGENTS.md`、`README.md`、`docs/product/product-scope.md`、`docs/architecture/overview.md`、`docs/plans/current.md` 模板。
- 已保留静态参考：`frontend/public/ui-demo.html` 与 `frontend/public/brand-logo.png`。
- 已新建前端：Next.js App Router + TypeScript；页面入口只组合 `AnalysisWorkspace`，业务代码位于 `src/modules/analysis`，图表协议与 ECharts 适配位于 `src/shared/charts`。
- 数据流：组件通过 `analysisApi.getCurrentRun()` 取 mock 数据；当前未接真实 FastAPI。
- Docker：已新增只包含 frontend 服务的 `docker-compose.yml` 与 `frontend/Dockerfile`。
- Git：已在本目录初始化独立仓库，初始提交为 `2b14a24 chore: bootstrap agentic genbi frontend`。

## 已验证
- `npm install` 成功；npm audit 报告 4 个依赖安全告警（1 moderate、3 high），暂未自动强制升级。
- `npm run test` 通过：1 个测试文件，1 个用例。
- `npm run build` 通过：Next.js 成功生成静态 `/` 页面。
- `docker compose config` 通过。

## 风险与边界
- 当前是 Mock-first 前端切片，不代表后端、认证、权限或真实分析链路已经迁移。
- `ui-demo.html` 作为视觉和交互参考保留在 `public`，正式页面已开始迁移到 React 组件。

## 下一步
1. 用浏览器检查桌面和窄屏布局。
2. 后续接入 MSW 或 FastAPI 前，先固定 `/api/analysis-runs` 等前后端接口契约。
3. 处理 npm audit 报告的 4 个依赖安全告警。
