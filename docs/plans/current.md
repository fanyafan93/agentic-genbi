# 当前任务

更新时间：2026-08-04 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 当前分支

- 分支：`Agentic-GenBI`
- 工作区：本轮修复待提交。
- 分支状态：本地从回滚中恢复到 `29c0e0f`，远端仍停在回滚后的 `82db24b`，提交后需要用一次非强推合并把远端历史纳入。

## 本轮完成

- 恢复主开发分支到 `29c0e0f merge: feature/report-artifact-design → Agentic-GenBI`。
- 确认 `119e4c5 fix(frontend): align flow.start/send/reply signature with AgentInput threadId` 内容已包含在恢复点中，cherry-pick 为空补丁。
- 修复 FineReport 报表画像加载：
  - 默认目录从 `资源库/finereport/解析` 改为 `资源库/finereport/报表画像`。
  - Docker 后端环境变量同步改为 `/app/资源库/finereport/报表画像`。
  - 后端 repository 支持递归读取报表画像目录下普通单文件 `*.json`，不再只依赖旧的 `*.原始解析.json` 或 `01/02/03` 分片命名。
  - 后端读取并返回 `report_usage`，统一为 `reportUsage`。
  - 前端“报表解析”恢复为“报表画像”，并新增“使用情况”页签。
- 修复新建分析任务 404：
  - 当前运行前端仍可能调用旧入口 `POST /api/analysis/tasks`。
  - 后端新增兼容入口 `POST /api/analysis/tasks`，内部复用 canonical `POST /api/analysis/threads` 创建逻辑，并返回 `{ task }` envelope。

## 已运行验证

- `python -m pytest backend/tests/test_finereport_reports.py -q`：2 passed。
- `npm.cmd test -- tests/finereport-report-browser.test.tsx`：2 passed。
- `python -m pytest backend/tests/test_analysis_api.py backend/tests/test_finereport_reports.py -q`：26 passed。
- 后端本地 repository 验证：`资源库/finereport/报表画像` 可读出 692 个报表画像。
- 真实接口验证：`GET http://127.0.0.1:8000/api/business-semantics/finereport/reports` 返回 692 条。
- 真实接口验证：`POST http://127.0.0.1:8000/api/analysis/tasks` 从 404 修复为 200。
- 服务重启验证：backend health ready，frontend ready。

## 风险或未完成

- 当前分支与远端存在历史分叉；推送时需要保留本地恢复后的代码状态，同时合并远端历史，避免强推。
- PowerShell 控制台直接显示 API 表格时中文可能乱码；Python 读取同一接口验证中文正常。
- `.pytest_cache` 目录权限警告仍存在，不影响本轮测试结果。
- PowerShell profile 中 `starship` 未安装的提示仍存在，不影响服务。

## 下一步

1. 提交本轮恢复修复。
2. 用非强推方式合并远端分叉历史并推送 `Agentic-GenBI`。
3. 推送后在浏览器复测：新建分析任务、报表画像列表、报表画像使用情况页签。
