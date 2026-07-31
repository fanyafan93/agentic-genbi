# Agentic GenBI 协作卡片

## 一句话目标

做一个安全、可解释、可复用的 Agentic BI 系统：用户在分析工作台提出业务问题，Codex Harness 调度业务语义库、数据层和工具，产出可复用分析资产。

## 先读这五个文件

1. `AGENTS.md`：协作规则。
2. `README.md`：项目一页总览。
3. `docs/product/product-scope.md`：产品边界。
4. `docs/architecture/overview.md`：架构边界。
5. `docs/plans/current.md`：当前分支状态。

读完再看 `git status --short --branch`。工作区有改动时，不覆盖、不重置；先判断是否属于当前切片。

## 当前稳定方向

- 单一主入口：分析工作台。
- 编排基座：openai-codex Python SDK / Codex 优先；能用 Codex 的，绝不自研。需要更底层能力时再研究 codex-core。
- 业务语义库：语义模型 + 业务知识。
- 分析资产库：报告、图表、SQL、数据快照、分析路径、`SKILL.md`。
- 安全边界在服务端：权限、SQL 只读、RLS、审计、数据访问都不能靠前端或提示词。

## 文档规则

只维护这几份长期文档：

- `README.md`：一页总览，不写实现流水账。
- `docs/product/product-scope.md`：产品边界，只写用户入口、核心对象、非目标。
- `docs/architecture/overview.md`：架构边界，只写分层、契约、安全边界和演进方向。
- `docs/plans/current.md`：当前分支快照，只写当前状态、验证、风险、下一步。

不要新建 `HANDOFF.md`、`backlog.md`、临时计划文档或重复接口说明。历史交给 Git。

## 开发规则

- 长期集成分支是 `Agentic-GenBI`。
- 业务功能只在独立 `feature/*` 分支开发。
- 一个分支只承载一个可理解、可验证的垂直切片。
- 不改写历史、不强推、不使用破坏性 Git 命令，除非用户明确要求。
- 使用 Conventional Commit。
- 修改前先看现有模式；不要把新领域逻辑继续堆进 `AnalysisWorkspace.tsx`，新增领域放到对应模块。

## 实现原则

- 本项目是 vibe coding：用户定方向，AI 快速做可运行切片。
- 前端优先、mock-first 可以，但 mock 必须贴近未来真实契约。
- 不确定的产品体验先用可替换 mock 验证。
- 成熟框架和 SDK 优先；Codex 已有的能力优先于任何自研实现。
- openai-codex Python SDK / Codex 负责通用 Agent 工程底座；本项目只自研业务语义库、数据安全访问、分析资产治理、前端工作台和 Codex 适配层。
- 模型 provider、工具、MCP、Skills、Apps / Connectors、sandbox、approval、apply_patch、file search、git 等能力优先接 Codex 生态，不重复造轮子。

## 验证要求

- 后端：pytest。
- 前端：Vitest；涉及布局交互时补 Playwright 或浏览器验证。
- 改 SQL 安全边界：加拒绝用例。
- 改认证/权限：覆盖未登录、越权、退出和非法 state。
- 合入前至少运行相关最小测试；准备合入 `Agentic-GenBI` 前运行全量前端、后端和 `docker compose config`。

## 收尾要求

完成一次开发会话前，更新 `docs/plans/current.md`：

- 当前分支和工作区状态。
- 本轮做了什么。
- 已运行验证。
- 风险或未完成。
- 下一步 1 到 3 条。

只写已验证事实。未知内容标为“待验证假设”。
