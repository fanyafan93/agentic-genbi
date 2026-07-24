# Agentic GenBI 协作指南

## 项目目标

持续交付安全、可解释的 Web 数据分析 Agent：用户用自然语言提问，并返回可核对的报告。

长期集成分支是 `Agentic-GenBI`。业务功能只能在独立 `feature/*` 分支开发并合入；不要直接在集成分支实现业务功能。

## 每次接手先做什么

按顺序阅读：

1. `AGENTS.md`
2. `README.md`
3. `docs/product/product-scope.md`
4. `docs/architecture/overview.md`
5. `docs/plans/current.md`

然后检查 `git status`、当前分支和最近提交。工作区有未知改动时，不覆盖、不重置；先在 `docs/plans/current.md` 记录归属或向用户确认。

## 文档规则

项目文档只保留以下三份职责明确的来源：

- `docs/product/product-scope.md`：产品边界——面向业务，随产品阶段、用户反馈和业务目标变化而更新。
- `docs/architecture/overview.md`：架构边界——面向技术，随系统复杂度、技术约束、部署方式和安全边界变化而更新。
- `docs/plans/current.md`：当前任务——当前切片、实际进度、验证、风险与下一步；同时承担交接职责。

`README.md` 是入口与稳定概览，不重复三份正文。Git 提交记录用于追溯历史；不要新建 `HANDOFF.md`、`backlog.md`、接口契约或临时计划文档。

### 如何更新文档

- 产品承诺、阶段目标或非目标变化：更新 `product-scope.md`。
- 架构、技术栈、公开接口、数据模型、安全边界、运行配置或部署方式变化：更新 `architecture/overview.md`；必要时同步 README 摘要。
- 每次开发会话结束前更新 `plans/current.md`：当前分支与工作区、当前切片、关键变更、已运行验证、风险/阻塞与一到三个下一步。只写已验证事实；未知内容标为“待验证假设”。
- 未合入 `Agentic-GenBI` 的功能不得写成已实现；普通修复不记录为长期事实，细节由 Git 提交追溯。

## AI 开发流程

使用 Superpowers 的开发方法，但不把其 plans、specs 当作项目正式文档。

- 新功能或较大改动：先确认目标、范围、非目标和验收标准，再开始实现。
- 新功能与 bug 修复：优先先写或补充测试，再做最小实现。
- 遇到失败、异常或安全问题：先定位根因，不直接猜测性修改。
- 修改完成后：运行与改动相关的最小测试；合入前运行全量测试和 `docker compose config`。
- 功能按可独立验证的最小切片开发，不顺手扩展后续能力。
- 详细推理、临时计划和过程草稿不写入仓库；稳定信息写入对应边界文档，当前进度写入 `plans/current.md`。

## 协作与 Git

- 一个功能分支只承载一个能独立理解和验证的垂直切片。
- 新分支从最新 `Agentic-GenBI` 创建；前置切片合入后再开始依赖它的下一切片。
- 不合并功能分支到另一个功能分支，不改写历史、不强推、不使用破坏性 Git 命令，除非用户明确要求。
- 使用 Conventional Commit。提交前查看 `git diff`，确保不包含其他人的无关改动。
- 在 Codex 与 Trae 之间切换时，先更新 `docs/plans/current.md`；新工具只从本文件、README 和两份边界文档获取上下文，不猜测未记录状态。

## 测试与完成标准

- 后端使用 pytest，前端使用 Vitest。
- 改 SQL 安全边界时增加拒绝用例。
- 改认证时覆盖成功登录、非法 OAuth state、未登录访问和退出。
- 改任务所有者逻辑时覆盖两个用户的越权拒绝。
- 完成功能前运行相关最小测试；合入 `Agentic-GenBI` 前运行全量后端测试、全量前端测试和 `docker compose config`。

任务完成的条件：实现符合产品与架构边界，安全边界未弱化，必要测试通过或已记录无法运行的原因与风险，并且 `docs/plans/current.md` 已更新。
