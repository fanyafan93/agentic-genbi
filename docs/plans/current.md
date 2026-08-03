# 当前任务

更新时间：2026-08-03 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 当前状态

- 分支：`feature/codex-runtime-boundary-cleanup`。
- 产品主线仍是单一分析工作台。
- Codex 负责 `Thread / Turn / Item`、上下文、工具调度、流式事件、中断、重试、sandbox 和 approval。
- GenBI 负责用户、租户、数据权限、数据源、FineReport 语义案例、指标与规则、Artifact 版本、血缘、分享、发布和治理。
- 分析工作台 API 通过 `CodexSdkAnalysisRuntime` 直接流式转发 Codex 事件；GenBI 只补充 `thread_id`、`turn_id`、Artifact 血缘等业务归档上下文。
- 分析回复由真实 Codex Item 事件渲染。右侧报告面板只渲染真实 interactive-report Artifact，或者显示空状态。

## 本轮完成

- 删除自研 `AnalysisTurnService` 执行层和 `AnalysisAgentRunner` runner 协议文件。
- 删除 GenBI 侧 prompt 构造、正则问题分类、语义模型计划、追问问题生成、自造 item id 和自造 turn 生命周期投影。
- 分析 API 改为直接调用 `CodexSdkAnalysisRuntime`，并把 Codex 返回的事件保存到 `ThreadStore`。
- `CodexSdkAnalysisRuntime` 改为从 Codex notification 产出 `AgentEvent`，不再返回自定义 final-result wrapper。
- 前端删除 `conversation-init`；当前 thread、turn 和 Codex 血缘改为从流式事件上下文中获取。
- 补充测试，约束旧执行层文件不得再存在，并验证连续追问会从 `ThreadStore` 恢复 `codex_thread_id`。

## 本轮验证

- `python -m unittest discover backend\tests -v`：39 个测试通过。
- `npm.cmd test`（frontend）：52 个测试通过。
- `npx.cmd tsc --noEmit --pretty false`（frontend）：通过。
- `npm.cmd run build`（frontend）：通过。
- `docker compose config`：通过；存在 Docker 用户 config 权限 warning。

## 工作区状态

- 工作区包含 `feature/codex-runtime-boundary-cleanup` 分支上的 Codex runtime 边界收敛改动。
- 未回退用户无关改动。

## 风险 / 未完成

- 本轮没有新增报告生成工具。右侧报告面板仍需等待真实注册的 Codex 工具产出 interactive-report Artifact。
- 生产数据访问、RLS、分享、发布和完整 Artifact 治理仍未完成。
- 真实配置 Codex provider 后的浏览器/SSE 实测仍待验证。

## 下一步

1. 仅在 GenBI 业务工具契约准备好后，通过 Codex 注册受控业务工具。
2. 继续补生产数据访问、RLS、分享、发布和治理切片。
3. 使用真实 Codex provider 验证一次 live SSE turn，确认 UI 按 Codex Item 事件增量渲染。
