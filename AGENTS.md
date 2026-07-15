# Agentic GenBI MVP 协作指南

## 项目目标

构建一个最小可用的 Web 数据分析 Agent：用户提交自然语言分析问题，后端通过 OpenAI Agents SDK 查看单个 MySQL 测试库的元数据、生成并安全执行只读 SQL，在普通 SQL 错误发生时最多自动修复两次，最终返回统一的结构化报表 JSON。

## 开始任务前必须阅读

1. `README.md`
2. `docs/product/mvp-scope.md`
3. `docs/architecture/overview.md`
4. `docs/architecture/interfaces.md`
5. `docs/plans/current.md`
6. `docs/handoffs/latest.md`
7. 与任务相关的 `docs/architecture/decisions/` ADR

## MVP 范围

范围内只有一条端到端链路：网页提问、FastAPI 创建分析任务、单个分析 Agent 调用数据库元数据与查询工具、SQL 安全检查、只读查询、最多两次修复重试、结构化报告生成，以及前端轮询并展示状态、步骤、SQL、表格、图表和结论。

本阶段禁止擅自加入 WrenAI、LangGraph、多 Agent、多租户、完整权限系统、Redis、Celery、Kubernetes、MinIO、PDF 导出、仪表板编辑器、定时任务、多数据库、向量数据库、任意代码执行或数据库写入能力。新增范围必须先更新范围文档并获得人工确认。

## 技术栈

- 前端：Next.js、React、TypeScript、Ant Design、ECharts、Vitest
- 后端：Python、FastAPI、Pydantic、OpenAI Agents SDK、SQLAlchemy、pytest
- 数据库：单个 MySQL 测试库或脱敏库
- 本地部署：Docker Compose

具体版本在项目骨架任务中锁定；没有验证前不得在文档中伪造版本号。

## 架构边界

- 前端只调用 FastAPI，不接触数据库凭据或 OpenAI API 密钥。
- FastAPI 负责 HTTP 契约、任务生命周期、硬性预算、Agent 编排、结果校验和错误映射。
- OpenAI Agents SDK 负责单 Agent 的推理、函数工具调用和结构化最终输出，不负责安全授权。
- `list_tables` 和 `get_table_schema` 只能暴露白名单内元数据。
- `execute_sql` 必须先经过 SQL 安全层；工具不得绕过安全层直接使用 SQLAlchemy。
- SQL 安全层负责语句类型、单语句、危险语法、表白名单、行数和超时限制。
- MySQL 连接必须使用只读账号；数据库权限是 Python 安全检查之外的第二道强制边界。
- 报表使用 `AnalysisReport` 契约；第一版不把 `build_report` 注册为 Agent 工具，而是使用 Agent 结构化输出并由 Pydantic 校验。
- MVP 任务状态保存在 FastAPI 单进程内存中。不得将其描述为持久、可恢复或支持多实例。

## SQL 安全规则

以下规则必须由 Python 代码和数据库权限共同执行，不能只写在提示词中：

- 只允许一条 `SELECT` 或以 `WITH` 开始且最终为查询的语句。
- 拒绝 `INSERT`、`UPDATE`、`DELETE`、`DROP`、`ALTER`、`TRUNCATE` 及其他写入、DDL、管理语句。
- 拒绝多语句、注释绕过和未授权表访问。
- 强制最大返回行数和查询超时；具体默认值在项目骨架任务中配置并记录。
- Agent 每个任务的工具调用总数有硬上限；SQL 初次执行后最多修复并重试两次。
- 安全拒绝、权限错误、超时、连接失败和预算耗尽不得交给 Agent 反复尝试。
- 审计原始 SQL、每次修复 SQL、结构化数据库错误、最终状态与结果摘要；不得在普通日志中泄露凭据或不必要的敏感数据。

## 测试要求

- 后端使用 pytest 覆盖数据模型、工具、安全策略、错误分类和重试上限。
- 前端使用 Vitest 覆盖状态轮询、报告渲染和错误状态。
- 至少维护 5 个固定分析问题作为端到端验收样例，其中包含成功、字段修复和表名修复场景。
- 涉及 SQL 安全边界的改动必须添加拒绝用例，不能只测试成功路径。
- 任务完成前运行与改动相关的最小测试集；里程碑完成前运行全量测试。

## Git 工作要求

- 开始前检查 `git status`，不得覆盖或回退不属于当前任务的改动。
- 每个提交只包含一个可独立理解和验证的垂直切片。
- 使用清晰的 Conventional Commit 风格信息，如 `feat: add analysis task health check`。
- 未经明确要求不改写历史、不强推、不使用破坏性 Git 命令。
- 提交前检查差异、测试结果和文档一致性。

## 任务完成标准

任务只有在实现与契约一致、相关测试通过、安全限制未弱化、README/架构/接口文档按需更新，并且 `docs/handoffs/latest.md` 已记录本次状态后才算完成。若测试无法运行，必须在交接文档和最终回复中说明原因与剩余风险。

## 会话交接

每次开发会话结束前必须更新 `docs/handoffs/latest.md`。只记录已验证事实；未知内容标记为“待验证假设”，未完成内容不得写成已完成。
