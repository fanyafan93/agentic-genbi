# 当前任务

更新时间：2026-08-03 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 当前分支

- 分支：`Agentic-GenBI`。
- 工作区：有未提交改动，集中在 Codex SDK runtime、MiniMax-Codex adapter、Codex 原生 MCP 配置、Postgres item 兼容迁移、前端流式展示和对应测试。

## 当前结论

- 分析工作台主路径已经收敛到 Codex Thread / Turn / Item；GenBI 不再保留旧 Run、exploration、alias MCP server 或自研 Agent runner 主路径。
- `GenBI -> Codex SSE -> MiniMax adapter -> Codex MCP -> BI_doris -> Doris` 已端到端跑通，能产生真实 `mcpToolCall` 并返回基于真实查询结果的中文分析。
- MiniMax-Codex adapter 只做 provider 协议兼容，不承担业务工具调度。
- Codex `developer_instructions` 已收敛为最小业务约束，不再重复声明模型身份、MCP 工具清单、Doris 连接信息或具体表名；工具能力由 Codex 原生 MCP 列表提供。
- 前端按真实 Codex Item 顺序展示过程消息、工具调用和最新回答；追问用户消息通过 `turn/started.question` 和 `userMessage.content` 兜底展示。

## 本轮完成

- 后端固定容器内 Codex CLI 0.146.0，并把 provider 与 MCP server 渲染到 `$CODEX_HOME/config.toml`。
- 新增 `/api/codex-minimax/v1/responses` 本地 provider proxy，适配 MiniMax 与 Codex Responses/MCP namespace tool 协议差异。
- 删除 GenBI alias MCP server 及对应测试，MCP server 回到 Codex 原生配置。
- 修复 `analysis_items.run_id` 旧约束兼容，避免 Codex 原生 item 缺少 `run_id` 时写库失败。
- 修复后端 SSE 追问消息缺失：Codex `turn/started` 未携带问题正文时，GenBI 转发时补入本轮 `question`。
- 前端移除示例任务 mock 历史，普通对话不再渲染原始 debug 折叠块；工具调用显示为可展开 SQL 的活动项。

## 已运行验证

- `python -m unittest backend.tests.test_minimax_codex_adapter -v`：6 个测试通过。
- `python -m unittest backend.tests.test_codex_sdk_runner -v`：8 个测试通过。
- `python -m unittest backend.tests.test_codex_mcp_config -v`：16 个测试通过。
- `python -m unittest backend.tests.test_analysis_api -v`：8 个测试通过。
- `python -m unittest discover backend\tests -v`：64 个测试通过。
- `npm.cmd test -- analysis-backend-client.test.ts analysis-flow-streaming.test.ts analysis-task-copy.test.ts`：36 个测试通过。
- `npm.cmd run build`：Next.js 生产构建和 TypeScript 检查通过。
- `docker compose config --quiet`：通过。
- `docker compose restart backend`：后端已重启并运行。
- `docker compose restart frontend`：前端已重启并运行。
- `Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/health'`：返回 `{"status":"ok"}`。
- `git diff --check`：无空白错误，仅有既有 CRLF 提示。

## 风险或未完成

- MiniMax-Codex adapter 目前只覆盖已实测的 namespace MCP tools 展平/还原路径；更复杂 Responses event 类型仍需按实测补充。
- `.env` 仍含真实密钥和数据库密码；本轮没有处理密钥历史清理。
- 右侧 Artifact/报告生成仍未通过业务工具落库；当前只打通模型调用 MCP 查询数据。
- 内置浏览器连接当前工作台标签页曾超时，登录态页面的最终视觉结果仍需人工刷新确认。

## 下一步

1. 用带登录态的浏览器真实发送中文问题，确认页面展示和 UTF-8 链路。
2. 增加 adapter 脱敏诊断日志开关，便于排查 provider 兼容性。
3. 规划 Artifact 生成工具，让 Codex 查询后的报告结果通过 GenBI 受控 Artifact API 落到右侧报告面板。
