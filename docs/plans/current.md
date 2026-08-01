# 当前任务

更新时间：2026-08-01（Asia/Shanghai）

## 当前分支

- 仓库：`E:\my_repo\agentic genbi`
- 分支：`feature/interactive-analysis-result`
- 当前切片：交互式分析结果持久化与 Codex 草稿桥接。左侧保留分析对话，右侧展示并编辑一份当前分析结果；保存后的结果写入 Postgres 并进入“我的分析”。

## 当前产品方向

用户从分析工作台提出业务问题。左侧对话承载问题、追问和 Agent 过程；右侧持续生成、修改当前结果。结果确认后可保存、分享、导出或提炼为模板。

第一类结果是 `Interactive Report`：布局用 Puck JSON 表达，图表、表格和运行时筛选按独立契约渲染。产品前台使用“分析结果 / 我的结果 / 分析模板”；`Artifact` 只保留给内部治理与 API 契约。

## 本轮改动

- 新增交互式报告契约：报告 JSON 包含 Puck 布局、筛选定义、查询引用、图表 Spec、表格 Spec 和来源 `thread / turn / run`。
- 分析工作台右侧改为单一“分析结果”面板，使用 Puck 渲染布局、ECharts 渲染图表、AG Grid 渲染明细表。
- 月份、品牌、区域筛选只改变运行时数据视图；不会写回 Puck 文档，也不会创建版本。
- 新增“保存、分享、提炼为模板、导出、编辑结果”操作；当前分享、模板和导出明确为 Mock。
- 新增 `analysis_reports` 与 `analysis_report_versions`：前者保存结果归属、来源和最新版本；后者以 JSONB 保存不可变的 Puck 布局、筛选定义、查询、图表和表格 Spec。
- 新增报告 API：`POST /api/analysis/reports`、`GET /api/analysis/reports`、`GET /api/analysis/reports/{id}`、版本列表与指定版本读取接口；陈旧版本保存会返回 `409`。
- Puck 编辑器发布会调用报告 API 并使用服务端返回的版本号；“保存”也创建新的报告版本。运行时筛选不写入任何版本。
- Codex 最终回复可显式附带 `<interactive_report_draft>` JSON；服务端严格校验最小 Puck 契约，剥离聊天正文中的 JSON，补齐报告 ID 与 `thread / turn / run` 来源，再发出 `interactive_report.draft`。
- `interactive_report.draft` 会随 Run 保存为 `report` Item；前端已校验并消费此事件，右侧优先展示本轮 Codex 草稿。
- 新增第一个受控 `queryRef`：`finereport-operation-management-channel-sales`。它基于已解析的“财务经营管报日报”来源表 `dm.dm_fina_operation_mgmt_rpt`，只接受 `month / brand / region` 三个筛选键，汇总 `销售额 / 收入净额 / 退款金额`，并在服务端计算 `salesShare`。
- 新增第二个受控 `queryRef`：`finereport-operation-management-region-channel-sales`。它按 FineReport 已解析字段 `vregion`（线下区域）与 `vchannel_type`（渠道类型）共同聚合；“按区域拆开”的授权 Run 会选择它，而不是把区域误当作单一筛选条件。
- 新增 `POST /api/analysis/report-queries/{queryRef}`：浏览器不提交 SQL；服务端登记固定 SQL 模板，先经 SQL AST 只读校验，再将命名筛选转换为数据库参数绑定。右侧报告在 backend 模式下通过该接口读取运行时数据。
- 前端报告筛选的品牌、区域值已与数据库业务口径统一为中文实际值（如“花西子”“华东”）；不再使用仅供 mock 的 `florasis / east` 等内部代号，从而保证同一筛选状态在 mock 与 backend 模式语义一致。
- 新增“我的分析”页：优先读取当前 Auth.js 用户的后端报告；未登录开发态或 API 不可用时才回退到浏览器 `localStorage`。
- 右侧分析结果已增加“历史版本”入口：后端存储模式下可读取版本列表并打开指定版本；打开历史版本只切换当前阅读/编辑对象，后续保存才创建新版本，运行时筛选仍不写入版本。
- 每个报告版本现在都冻结自己的 `sourceThreadId / sourceTurnId / sourceRunId`；读取历史版本时以前述版本来源为准，不再误用报告最新版本的来源。Postgres 启动时会为既有版本回填当前报告来源，并将三个新列收紧为不可空。
- 分析工作台已增加“使用受控数据与语义摘要”逐次授权开关：默认关闭，仅后端模式展示；勾选后当前 `start / message / reply` Run 才会发送 `metadata.data_egress_authorized=true` 与 `metadata.semantic_context_egress_authorized=true`，发送后立即复位，避免继承到下一轮。
- FineReport 报表解析已接入受控语义摘要：仅在本轮语义外发授权成立时，服务端才向 Codex / MiniMax 发送至多三份完整解析报表的 `id / name / sheetNames / counts / datasets / bindings`。摘要排除原始 SQL、连接名、CPT 路径、参数默认值、单元格正文与含用户、凭证、令牌、联系方式等敏感标识的参数或字段；事件审计只保留报表 ID、数量和 Thread / Turn / Run 关联。
- 当本轮已获得受控聚合数据快照时，Codex prompt 会强制要求输出完整的交互式报告草稿；即使模型只返回普通文本或 HTML Artifact，服务端也会基于已登记的 `queryRef` 生成最小 Puck 报告草稿，确保右侧分析结果不断流。
- 若模型在同一份草稿中混入未登记的 `queryRef`，服务端会移除该未知查询及其引用的图表/表格，只保留已登记的受控部分；若整份草稿只含未知查询，仍会拒绝，不会把未授权查询带入右侧报告。
- 用户继续对话时，前端会把右侧当前报告作为“修改基线”随 Run 一并提交；服务端只在本轮已明确授权外发受控数据时接收该上下文，并剥离来源等无关字段、限制为 60KB、校验所有 `queryRef` 均为服务端登记后，才发送给 Codex / MiniMax。模型必须返回完整的新报告草稿，右侧随即切换；用户保存后才创建新的报告版本。
- 基于已有报告继续对话时，受控上下文会保留原报告 ID；服务端生成的草稿继承该 ID，但来源更新为新的 `thread / turn / run`。右侧优先显示本轮草稿，用户保存时以原报告最新版本为并发基线写入下一版本，而不会误创建另一份报告。
- 草稿解析会容错模型可判定的 JSON 格式错误（字符串中的原始控制字符、少量尾部花括号、`document` 内误嵌顶层报告字段、扁平的 Puck `props`）；修复后仍必须通过完整报告契约与登记 `queryRef` 校验。若本轮已授权、存在当前报告基线且已取得区域渠道快照，但模型仅漏掉草稿外壳，服务端会保守地把已有图表/表格绑定切换到区域渠道 `queryRef`，保持右侧结果不断流。
- 工作台移除旧分析资产库状态和入口依赖，避免“当前结果”与旧资产卡片模型同时占据右侧。
- README、产品范围和架构文档已补充交互式结果与运行时筛选契约。

## 已验证

- `python -m unittest discover -s backend/tests -v`：112 个后端测试通过。
- `npm.cmd test`：13 个前端测试文件、81 个测试通过。
- `npm.cmd run build`：Next.js production build 通过。
- 前端版本列表客户端测试通过；页面级检查确认右侧报告头部展示“历史版本”按钮。
- 前端逐次授权请求契约、页面控件可见性与勾选/复位行为已验证。
- `docker compose up -d --build backend`：FastAPI backend 已重建，Postgres 健康。
- Docker 端到端验收：通过运行中的 FastAPI 保存报告 v1、保存 v2、读取版本列表 `[2, 1]`、读回 v1 内容；临时验收记录已删除。
- Postgres 结构验证：`analysis_report_versions.source_thread_id / source_turn_id / source_run_id` 已存在且均为 `NOT NULL`。
- 测试覆盖：报告 Puck 契约、运行时筛选不修改报告 JSON、筛选后的指标重新计算、后端保存/列表/最新版本/历史版本/陈旧版本冲突。
- 定向契约验证：Codex 草稿会成为 `report` Item，不泄漏 JSON 到聊天正文；前端可将草稿事件映射为右侧报告状态。
- 真实 smoke：候选表字段与 FineReport 解析一致；数据区间为 `2024-01` 至 `2026-05`。通过 API 查询 `2026-05` 已返回四个渠道的真实聚合行，未读取业务明细。
- 真实续聊 smoke：在逐次授权和当前报告基线均存在时，`run_analysis_66b148ea4c0c` 以 `run.completed` 结束并返回 1 个 `interactive_report.draft`。服务端也能容错处理模型在 Markdown 字符串中写入的未转义换行，仍只接受校验通过的完整报告草稿。
- 真实区域拆分 smoke：新查询接口对 `2026-05` 返回 `region / channel / salesAmount / netRevenue / refundAmount / salesShare` 六列、10 行且未截断；`run_analysis_f38fac46978b` 选择区域渠道快照、以 `run.completed` 结束并返回 1 个 `interactive_report.draft`，草稿来源 Run 与实际 Run 一致且只引用区域渠道登记查询。
- 真实 FineReport 语义摘要 smoke：`run_analysis_1f631a326622` 在仅携带 `semantic_context_egress_authorized=true`、不请求业务数据的条件下，发出 `authorized_finereport_semantic_summary` 事件并关联 3 份报表；Codex / MiniMax 流式回复与 `run.completed` 正常结束。
- 报告草稿连续性验证：`python -m unittest backend.tests.test_analysis_agent_runner -v` 通过 19 个测试，其中覆盖“已授权渠道快照但模型只返回普通文本”时仍发出 `interactive_report.draft`，以及混入未知查询时保留已登记部分。重建 backend 后的真实 UTF-8 SSE smoke 同时收到 `agent.evidence.available`、`interactive_report.draft` 与 `run.completed`；包含“平台”的请求只保留渠道 `queryRef`，不会放行未登记的平台查询。

## 风险

- 当前 Puck 文档仍有 mock 初始内容；首个渠道与区域渠道报告已能在 backend 模式按运行时筛选读取真实受控聚合数据，但尚未覆盖更多指标、时间对比和多报表数据集。
- 当前只有一个固定报表查询切片；没有用户身份绑定、RLS 条件注入或独立查询审计表，不能将其视为完整的数据治理能力。
- Codex 草稿协议已通过 fake runner 契约验证。用户已明确授权：受控聚合数据与裁剪后的 FineReport 报表语义摘要可在每轮开关明确同意后发送给 MiniMax 用于生成分析报告。
- 每次需要发送聚合数据的 Run 都必须显式传入 `metadata.data_egress_authorized=true`；仅当问题命中渠道销售且包含合法月份时，服务端才执行登记 `queryRef` 并将至多 100 行聚合快照放入 Codex prompt。真实端到端 smoke 已完成：`2026-05` 查询返回 4 行渠道聚合数据，MiniMax 返回文字结论与 `interactive_report.draft`，SSE 以 `run.completed` 结束。
- 当前报告基线上下文仅在用户勾选“使用受控数据”的那一轮发送给外部模型；前端不发送时服务端也会再次拒绝该上下文。上下文不含来源字段，且未知 `queryRef`、不完整报告或超过 60KB 的内容会被丢弃。
- 报表查询审计已写入 Postgres `analysis_report_query_audits`：只保存 `queryRef`、筛选、行数、耗时、截断标记、调用来源、Thread/Run、用户标识和外发授权标记，不保存 SQL 正文或查询结果行。真实验证中，`run_analysis_3eb253084aaf` 与其审计记录均关联到同一 Thread，记录 `2026-05` 的 4 行受控聚合查询。
- Codex 草稿中的 `queries` 也受同一登记表约束；未知 `queryRef` 会被拒绝，不会进入右侧结果。
- API 使用前端传入的 `ownerId` 记录归属；尚未由后端认证上下文强制绑定，不能作为权限边界。
- 真实分享权限、模板提炼、PDF/XLSX 导出，以及数据源/RLS/只读 SQL 仍未接入。
- 报告列表为当前用户逐条读取详情，适合当前小规模开发数据；团队规模前需改为后端一次性返回摘要与最新版本。

## 后续阶段（暂缓）

以下能力不属于本次已完成的“分析结果闭环”切片，用户已决定后续再做：

- 权限与 RLS：由后端认证上下文绑定用户，并按用户、角色或数据范围限制可查询和可查看的数据行。
- 团队分享与模板：将确认后的分析结果以权限受控方式分享给团队，并提炼为可复用的分析模板。
- 更多语义工具：把更多已治理的指标口径、字段、ETL 血缘和业务知识以受控检索或 `queryRef` 提供给 Codex。
- 导出与治理：提供 PDF/XLSX 导出、数据血缘、审计和可解释说明。

## 下一步

1. 当前“分析结果闭环”切片不继续扩展，等待合入或由用户指定下一项后续阶段能力。
2. 启动后续阶段时，优先明确用户范围、数据权限模型和需要覆盖的数据源，再实施权限与 RLS。
3. 团队分享、模板、更多语义工具、导出与治理均保持暂缓，直到用户重新排期。
