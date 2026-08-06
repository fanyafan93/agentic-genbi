# 当前分支状态

更新时间：2026-08-07 Asia/Shanghai

## 分支

- 当前分支：`feature/report-editing`
- 基线：`Agentic-GenBI`
- 本次提交在同一分支整合 Report、分析工作台、系统管理 MCP、上下文与模型连接管理改动；未覆盖或重置既有实现。

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
   - Codex 通过 `GenBI_report` MCP Server 使用 9 个渐进式工具：`start_report_build`、`get_report_build`、`set_report_filters`、`upsert_report_query`、`upsert_report_chart`、`upsert_report_table`、`set_report_layout`、`validate_report_build`、`publish_report_build`。
   - 每一步修改先持久化到 `report_builds`；前端可按 revision 恢复并渲染未发布 Build。只有校验通过并成功发布后，才原子创建正式 Report。
   - 旧 `create_report` / `update_report` 只保留服务端兼容路径，不再暴露给 Agent；Build 过程只投影不含 SQL、参数或数据行的元数据事件，正式发布时投影 `genbi/report/created`。
   - 连续 3 个 provider round 没有 Report 工具进展时终止 Turn；已有未发布 Build 的 Turn 即使收到 Codex 原生 `turn/completed`，也会被标记为 `failed`，不会把半成品误报为成功。

4. 前端与数据运行时
   - Puck 管布局，Ant Design 管筛选，ECharts 管图表，VTable 管表格。
   - AG Grid 依赖和 Report 渲染代码已移除，不做兼容。
   - 简单 `ReportContext` 保存筛选值、调用查询接口，并把运行时数据交给图表和表格。
   - `queries` 保存数据源、只读 SQL、参数绑定与分页配置；后端执行只读校验、参数绑定和分页。

5. 当前明确不做
   - 旧 Report 迁移、Report 版本、异步/百万行 Excel 导出和自动拆 Sheet。
   - 租户/RLS、复杂审计。
   - 缓存、取消查询和复杂组件联动。

6. 分析工作台布局
   - 侧栏默认收起，对话区默认 34%，状态移到任务标题栏右侧。
   - 无 Report 时显示新的报告蓝图空状态；空闲态不显示外层背景和大圆角框，并在完整报告区域内居中；分析运行时继续显示默认蓝图，只有恢复已有 Report 时显示“报告加载中”。
   - 这些布局改动与 Report 架构改动一并纳入当前分支。

7. 抖音订单示例 Report
   - `scripts/seed_report_examples.py` 使用现有 Report API，按 owner 与标题幂等创建或覆盖示例，不保存数据行。
   - “抖音订单简版示例”包含日期筛选、1 个 ECharts 图表和 1 个 VTable 表格。
   - “抖音订单经营分析（复杂示例）”包含日期筛选、4 个 ECharts 图表、2 个 VTable 表格和 5 个后端查询。
   - 新增“复杂表格（多筛选）”“多栏经营看板（多筛选）”“双区域独立筛选”“表格能力示例”“经营驾驶舱（图片布局模板）”五份示例；七份示例均查询 `ods.ods_dy_order`，默认日期为 `2026-07-05` 至 `2026-08-03`。
   - “表格能力示例”同时展示两级可展开分组表、Pivot 交叉表和 `ods.ods_dy_order` 全部 53 字段宽表；宽表对收件人、电话和地址字段做 SQL 脱敏。
   - “经营驾驶舱（图片布局模板）”按图片结构使用首行 4+8、次行 4+4+4、底部 12 栏布局，包含雷达图、柱线组合图、堆叠图、仪表盘、漏斗图和层级汇总表。
   - VTable 保留配置列宽和固定可视高度，使用独立横向、纵向原生滚动条；分页支持 20 / 50 / 100 条。
   - 表头原生下拉支持声明字段的升序、降序、清除排序和枚举值筛选；后端在分页前对完整查询结果执行安全字段白名单排序与筛选。
   - Puck 运行时使用 12 栏布局，示例支持 4 / 6 / 12 栏跨度；双区域 Report 的两组筛选只刷新各自绑定的查询。

8. 输入框分析模式 UI
   - 会话输入框左下角新增“方案模式 / 协作模式 / 托管模式”选择器，默认协作模式，并在菜单中展示三种模式的行为说明。
   - 模式选择只保存在当前页面，刷新后恢复协作模式；Turn 运行中禁止切换。
   - 本轮仅实现 UI，模式不进入 AgentInput、不传给后端，也不改变消息提交和执行策略。

9. 系统管理 MCP 重构
   - 系统入口使用与主工具栏一致的线性滑杆图标，移除独立外轮廓、顶部边线和额外内边距。
   - MCP 管理按“全部 / 系统内置 / 外部接入”分类；`GenBI_report` 为代码维护的系统内置项，可检查工具和启停，不可编辑、复制或删除。
   - 外部 MCP 支持新增、编辑、复制、启停、真实协议检查与工具发现、删除；服务名创建后不可修改。
   - 传输方式支持 Codex 原生 stdio（command、args、env）和 Streamable HTTP（URL、Bearer Token 环境变量、OAuth Client ID / Resource）。
   - 管理接口只允许管理员通过 Next.js 网关访问；Python 内部接口继续由 `GENBI_SYSTEM_API_TOKEN` 保护。
   - 密钥以前端明文录入，后端使用独立环境主密钥和 AES-256-GCM 加密后写入 `McpServer.encryptedSecrets`；普通列表只返回掩码，管理员可直接查看、复制、隐藏，页面 30 秒后自动隐藏。
   - 旧 `BI_doris` 环境配置首次加载时自动导入数据库；安全升级已把 `MYSQL_PASS` 从明文 JSON 移入加密信封。
   - 本轮不新增完整审计能力，不改 Report 查询链路、数据源管理或多数据库配置。

10. 工作台暂时清空
   - 工作台产品方向尚未确定，当前仅保留顶部品牌栏和左侧主导航。
   - 点击“工作台”后自动收起二级侧栏；侧栏不再错误复用系统管理内容，主区域不显示标题、说明、占位卡片或其他模块内容。
   - 分析工作台、报表中心、业务语义库和系统管理行为保持不变。

11. 业务语义库入口图标
   - 主导航中的业务语义库图标由数据库圆柱改为知识图谱：一个中心节点连接三个语义节点。
   - 图标继续复用现有 `24×24` 视口、`1.8` 线宽以及统一的悬停和选中态。

12. Agent Report 生成契约收敛
   - `GenBI_report` 保留结构化 `report` 输入，并新增等价的 `report_json` 字符串输入，解决部分模型网关压平深层工具参数的问题。
   - MCP Schema 现在完整描述 layout、filters、queries、charts 与 tables 的嵌套结构；Agent 指令优先使用 `report_json`，不再提交空占位配置。
   - 后端拒绝前端不可渲染的 lowercase/未知布局块、缺少原生 ECharts `series` 的图表、缺少 VTable `columns` 的表格，以及不受支持的 `${name}` SQL 模板。
   - 布局块只允许 `FilterBlock`、`ChartBlock`、`TableBlock`、`SectionBlock`、`MarkdownBlock`；SQL 筛选统一使用 `:name` 与同名 `parameters` 安全绑定。

13. Report 中心封面与软删除
   - Report 中心使用 3:4 PDF 形态卡片；`ReportCover` 只根据 Report JSON 绘制布局、筛选、图表和表格结构缩略图，不调用数据查询接口。
   - Report 卡片网格固定使用 6 个等宽列，不根据屏幕宽度降列；六列平分完整内容区，不在右侧保留额外空白。
   - 点击卡片主体打开完整 Report；悬停或键盘聚焦后显示“删除 / 回到会话 / 新建会话”，不再显示单独的“预览”按钮。
   - “回到会话”始终显示；无来源会话或来源会话已删除时留在 Report 中心并提示“无关联会话或会话已经删除”。
   - 删除使用页面内确认弹层，不调用浏览器 `window.confirm`；确认后由后端设置 `deleted_at`，正常读取、列表、更新与分享入口均排除软删除记录，暂不提供回收站。

14. 上下文管理
   - 系统管理中的“系统提示词”入口已替换为“上下文管理”，统一展示上下文总览、内置基础指令、系统提示词、权限与运行环境、Skills 上下文和 MCP 工具上下文。
   - 内置基础指令与系统提示词由管理员直接保存至 `SystemSetting`；不提供草稿、版本、发布、回滚或恢复默认。未保存自定义基础指令时继续使用 Codex 原生基础指令。
   - 权限与运行环境、Skills、MCP 工具均为只读展示；Skills 仅返回名称、说明与范围，MCP 上下文不返回密钥或环境变量值。
   - Codex SDK 启动或恢复线程时读取当前直接配置；系统提示词优先使用新配置，并兼容现有已发布系统提示词作为初始回退。本轮未修改会话表、会话页面或新增快照。

15. 公开示例 Report
   - `reports.is_example` 标记公开示例；普通 `create_report` / `update_report` 不接受该字段，种子脚本通过受 `GENBI_SYSTEM_API_TOKEN` 保护的内部接口发布示例。
   - 报表中心新增“示例报表”分区；示例不再混入“我的报表”或“分享给我”，所有登录用户均可打开并“新建会话”，不显示“删除”或“回到会话”。
   - 七个抖音示例标题作为公开示例；数据库中不同 owner 的同标题重复种子记录继续保留，报表中心按标题只展示最近更新的一份。
   - “代码示例：独立 Report”已通过 `deleted_at` 软删除。
   - 我的、分享、示例三类卡片都在标题说明区展示完整 Report ID；ID 使用等宽小字、允许任意位置换行，不使用省略号。
16. 模型连接管理
   - 系统管理新增“模型连接”，沿用现有治理台主从布局，支持 OpenAI、MiniMax 与 OpenAI-compatible 连接的新增、编辑、启停、删除、设为默认和真实运行检查。
   - API Key 由管理员在网页明文录入，服务端使用 AES-256-GCM 加密后写入 `ModelConnection.encryptedApiKey`；普通列表不返回密钥，显式查看接口禁用缓存，页面查看后 30 秒自动隐藏。
   - 第一个启用连接自动成为默认；默认连接不能直接停用或删除。模型选择已从运行策略移出，运行策略只保留审批、沙箱与内置工具。
   - 每个新 Turn 只解析一次不可变模型连接快照；切换默认连接仅影响后续 Turn。数据库无可用连接时继续兼容现有 env 作为引导与应急回退。
   - MiniMax 使用按连接名隔离的本地 Responses 适配入口，实际上游地址和密钥来自该连接快照，不再固定读取进程启动时的模型 env。

17. Report 明细表 Excel 导出
   - 仅保存后的 list 表格可通过非空 `exportColumns` 显式开启导出；Pivot、构建草稿和未声明导出列的表格不显示按钮。
   - 前端提交当前 Report 筛选、列头筛选和排序；后端复用已保存的只读 SQL，只查询声明的导出列，同步生成单 Sheet `.xlsx`，上限 10 万行。
   - `create_report` / `update_report` 的 MCP 工具名、调用路径和现有必填字段不变；Report 表格 Schema 只增加可选 `type` 与 `exportColumns`，旧 Report 保持兼容。
   - 当前“抖音订单表格能力示例”的 53 字段宽表配置 10 个固定导出列；示例 SQL 仍保留原有 `LIMIT 1000`，没有扩大既有查询量。

## 已验证

- 五次复杂驾驶舱 Report 真实验收（2026-08-07）
  - 仅统计独立来源 Session、Turn 终态为 `completed`、正式 Report 已发布且内置浏览器可恢复渲染的结果；失败 Turn 和未发布 Build 不计数：
    - `report_53645fa7676249bbb9ad98c1de9058d7`（Session `019fd8df-3d5f-7bd2-873c-653bd5d62615`，复杂驾驶舱验收 1：渠道经营总览）
    - `report_01e82043f9b74146843c8bc168aa893f`（Session `019fd8f0-d183-7a03-bcb9-1653cde84f3d`，复杂驾驶舱验收 2：渠道效率总览）
    - `report_b57193fcfebf4aca9757a02c91fba921`（Session `019fd8ff-aa35-7551-ab32-281e663b210c`，复杂驾驶舱验收 3：渠道量额协同驾驶舱）
    - `report_1d0ae5cf30094d7bbfa0adaeaccf9b0e`（Session `019fd8f8-8f1c-7fb2-857e-89e8de2bf758`，复杂驾驶舱验收 4：渠道结构与趋势）
    - `report_4315615505f54164b63b7eb30ab64c34`（Session `019fd8f8-8f37-7fd0-ac5e-a3bd93fe80bf`，复杂驾驶舱验收 5：七日经营复盘）
  - 五份 Report 均包含 4 个 Doris 只读查询、8 个 ECharts 图表、3 张 VTable 和 14 个 Puck `layout.content` 块；每份 `sourceSessionId` 与来源 Session 一致。
  - 20 条 Report 查询均通过真实接口执行：每份 KPI 返回 1 行、每日趋势返回 5 或 7 行、渠道 Top10 返回 10 行、渠道明细返回 20 行。
  - 第 2 份 Report 首次浏览器加载暴露错误源字段 `sales_amt` / `sales_qty` / `vsku_name`；通过现有 Report 更新接口修正为 `nsales_amt` / `nsales_qty` / `vupc_code` 后，4 条查询均返回 200，标题和布局中文编码复核正常。
  - 内置浏览器逐份刷新核验：每份均显示 3 个业务章节、11 个内容 article（8 图 + 3 表）和 3 个表格滚动区，页面未出现 Report API、500 或加载失败错误。
- 渐进式 ReportBuild 与五次正式 Report 验收
  - 5 个独立来源 Session 均成功发布正式 Report，失败 Turn、未发布 Build 和同一 Build 的续跑不计入验收数量：
    - `report_377ae0f9070d4cd597b1b604d2027c7a`（Session `019fd7f3-651c-7730-8cf9-a1e42320c718`）
    - `report_dac0f6c23cdd43bd824a4a81ffdefb5e`（Session `019fd800-bb66-7ec0-a0ce-b4ea0ce7da68`）
    - `report_837ed6504e8247188e9dbfe80bef343e`（Session `019fd80c-4062-7441-89cb-961f8035eea2`）
    - `report_d2c38e1c0c4244749d187bba8eeaf113`（Session `019fd811-df7d-76b1-9546-d90a36999260`）
    - `report_06273e7dacd540c5845f8acdfd9dd7ad`（Session `019fd823-cd6f-7b41-afdf-585ab21a0356`）
  - 五份 Report 均通过后端读取核验，且各自包含 1 个只读查询、1 个图表、1 个表格和 Puck 布局；内置浏览器逐份确认来源 Session 中的标题、图表与表格可恢复渲染。
  - 第五份 Report 使用 `vdate BETWEEN '2026-07-30' AND '2026-08-05'` 与 `ORDER BY sales_amt DESC LIMIT 5`；浏览器终检显示正式 Report ID、横向柱状图、明细表及 Excel 导出入口，验收后的控制台新增 error / warning 为 0。
  - 真实 PostgreSQL ReportBuild smoke 通过：两个 Build 并发修改互不覆盖；同一 Build 重复发布只创建一个 Report；临时记录在 `finally` 中精确清理。
  - 全量后端 `339 passed, 3 subtests passed`；全量前端 `34 files, 204 tests passed`；`npx.cmd tsc --noEmit --incremental false`、`npx.cmd prisma validate`、`docker compose config --quiet` 与 `git diff --check` 均通过。
  - 真实未发布 Build 的恢复 Turn 已验证不会误报完成：Codex 原生完成事件被保留为唯一终态事件，但状态转换为 `failed`，错误码为 `report_build_incomplete`。
- Report 明细表 Excel 导出
  - 后端相关回归 68 tests passed；前端相关回归 5 files、29 tests passed；TypeScript `--noEmit --incremental false` 通过。
  - backend Docker 镜像成功构建并安装 XlsxWriter 3.2.9；frontend 独立镜像构建在 `npm install` 遇到 `ECONNRESET`，现有源码挂载容器完成 Next.js production build、迁移检查并恢复运行。
  - `http://127.0.0.1:8000/health` 与 `http://127.0.0.1:3000/analysis/new` 返回 200；实际导出接口返回 200、标准 `.xlsx` MIME 与附件文件名，文件包含 workbook 和首个 worksheet。
  - 内置浏览器打开“抖音订单表格能力示例”后，两个复杂/透视表无导出按钮，53 字段宽表显示唯一“导出 Excel”按钮；点击后后端导出接口返回 200，页面无导出错误。
- 模型连接管理
  - Prisma migration `20260806210000_model_connections` 已应用，数据库 schema 为最新；现有 env MiniMax 配置已自动导入为唯一默认连接。
  - 数据库只读聚合检查返回 1 条连接，密钥信封以 `v1:` 开头且长度大于 40；明文接口返回 200、与引导密钥一致并带 `Cache-Control: no-store`。
  - 后端全量 318 tests passed、3 subtests passed；前端全量 34 files、201 tests passed；本地 Next.js production build、Prisma validate 与 `docker compose config --quiet` 通过。
  - backend 与 frontend 已按 Compose 方式重建，PostgreSQL 数据卷未重建；`127.0.0.1` 和 `192.168.101.12` 的前端与健康接口均返回 200。
  - 管理员登录态浏览器已验收模型连接导航、主从详情、添加表单、密钥查看与隐藏、运行策略无模型输入；页面控制台无 error / warning。
  - 真实 MiniMax 运行检查返回“连接成功，Responses API 可用”，运行状态返回 `connectionName=minimax`、`connectionSource=managed`。
  - 额外的 frontend Docker 镜像构建在依赖层等待 10 分钟后超时；当前 Compose 通过源码挂载完成 production build 并正常运行，该超时未影响本轮服务发布，独立镜像重建仍待后续排查。
- 公开示例 Report 专项
  - Prisma migration `20260806190000_public_example_reports` 已应用；数据库现有七个示例标题各两份，共 14 条 live `is_example = true` 记录，报表中心按标题去重后返回 7 份公开示例。
  - “代码示例：独立 Report”原记录仍在，`deleted_at IS NOT NULL`。
  - JSON / PostgreSQL / API 相关回归 29 tests passed；示例生成与发布脚本、API 专项合计 16 tests passed。
  - 全量前端 31 files、182 tests passed；`npx.cmd tsc --noEmit --incremental false`、`docker compose config --quiet`、`git diff --check` 通过。
  - 全量后端 276 tests passed、2 failed、3 subtests passed；两项失败来自并行工作区中的 ReportBuild PostgreSQL 默认构造和 MiniMax provider 环境配置，不涉及本轮公开示例 Report。
  - backend、frontend 已重启；frontend 成功应用迁移，Next.js production build 与 TypeScript 通过并恢复 `Ready`，backend Uvicorn 启动正常。
  - 内置浏览器通过 `http://192.168.101.12:3000/analysis/new` 验收管理员登录态：我的报表 0、分享给我 0、示例报表 7；七张示例卡均显示完整 `report_...` ID，均只有“新建会话”，没有“删除”或“回到会话”。
  - 示例网格首行 6 张、第二行 1 张，六列计算宽度约 `122.33px`，第六张与网格右边缘差值为 `0`；悬停后操作区由隐藏变为可点击。
  - 打开“抖音订单简版示例”后完整 Report、日期筛选、图表和表格均加载完成；干净验收标签页控制台无 error / warning。
  - `http://10.87.84.25:3000` 当前从开发机与内置浏览器均返回空响应；本机实际 WLAN 地址为 `192.168.101.12`，本轮浏览器验收使用后者访问同一容器实例。
- 临时内网访问切换
  - `.env` 的 `AUTH_URL`、`FEISHU_REDIRECT_URI`、`GENBI_PUBLIC_API_BASE_URL` 已切换到 `192.168.101.12`；CORS 同时保留内网地址与原 `10.87.84.25` 固定入口。
  - frontend、backend 已使用新环境变量重新创建，PostgreSQL 未重建；frontend production build 与 TypeScript 检查通过并恢复 Ready。
  - `http://192.168.101.12:3000/` 与 `http://192.168.101.12:8000/health` 均返回 200；飞书授权跳转返回 307，最终授权地址携带的回调已确认是 `http://192.168.101.12:3000/api/auth/callback/feishu`。
- 上下文管理专项与全量测试
  - 前端专项 4 files、11 tests passed；全量前端 31 files、181 tests passed。
  - 后端专项 24 tests passed；全量后端 252 tests passed、3 subtests passed。
  - `npx.cmd tsc --noEmit`、`git diff --check`、`docker compose config --quiet` 均通过。
  - frontend 容器使用挂载源码完成 Next.js production build 与 TypeScript 检查，构建产物包含 `/api/system/context`；backend 与 frontend 已重启，PostgreSQL 未重建。
  - `http://127.0.0.1:3000/` 与 backend `/health` 均返回 200。
  - backend `/api/system/context/skills` 通过内部令牌返回 200，并发现 6 个 Skills；未登录访问 frontend `/api/system/context` 返回 401。
  - 内置浏览器在服务重启后访问局域网地址时出现 `ERR_EMPTY_RESPONSE`，随后被浏览器 URL 策略阻止继续自动验收；页面视觉与登录态交互待手动刷新复核。

- `python -m pytest backend/tests -q -p no:cacheprovider`
  - 249 passed，3 subtests passed。
- `npm.cmd test`
  - 28 test files，172 tests passed。
- `npx.cmd tsc --noEmit --incremental false`
  - passed。
- `docker compose config --quiet`
  - passed；Docker CLI 仍报告本机 `config.json` 读取权限警告，不影响配置结果。
- 容器运行
  - frontend、backend、postgres 均已重建并运行。
  - 当前局域网入口已切换为 `http://10.87.84.25:3000`；前端 API 指向 `http://10.87.84.25:8000`，飞书回调为 `http://10.87.84.25:3000/api/auth/callback/feishu`，后端 CORS 已包含新入口。
  - 本轮仅重建 frontend、backend；运行两天的 PostgreSQL 容器未重建。新入口前后端均返回 200，飞书 provider 正常加载。
  - 标准命令 `docker compose --progress plain build --pull=false backend` 已完整构建成功；新 backend 容器的镜像 ID 与 `agentic-genbi-backend:latest` 一致。
  - 标准镜像内发行包版本：`PyMySQL==1.2.0`、`sqlglot==30.15.0`、`openai-codex==0.144.4`；Codex CLI 为 `0.146.0`。
  - frontend production build 与 TypeScript 检查通过。
  - `GET /analysis/new` 返回 200。
  - `GET /health` 返回 `{"status":"ok"}`。
  - `GET /api/reports?limit=1` 返回 200。
- PostgreSQL
  - 仅存在 `reports`、`report_shares`；旧三张 Report 表不存在。
  - Prisma migration `20260806000000_direct_report_prompt` 已完成。
  - Prisma migration `20260806150000_mcp_management` 已完成；`BI_doris` 的 `MYSQL_PASS` 不存在于 config 明文字段，已登记为 secret key，密文信封长度为 79。
  - 重建后只读复核：249 个 Session、306 个 Turn、15 个 Report，历史数据仍在。
- 内置浏览器
  - 新前端标签控制台无 error / warning。
  - 代码创建的无来源示例 Report 显示“删除 / 回到会话 / 新建会话”；点击“回到会话”提示“无关联会话或会话已经删除”。
  - 点击“新建会话”进入 `/analysis/new`，右侧保留当前 Report，未自动发送消息。
  - 报表中心显示原两份示例与新增的复杂表格、多栏经营看板、双区域独立筛选三份示例。
  - 简版渲染 1 图、1 表和日期筛选；复杂版渲染 4 图、2 表、日期筛选和三个业务章节。
  - 复杂版日期范围两端完整显示，预览画布无横向溢出；两张表铺满内容区，商品表五列均在同一视口内。
  - 复杂版商品表分页已从 `1 / 2` 切换到 `2 / 2` 并恢复到第一页；浏览器控制台无错误。
  - 复杂表格显示三项筛选、独立横纵滚动条和 20 / 50 / 100 条下拉；表头升降序菜单和状态筛选菜单可用，状态筛选后可见行均为所选状态。
  - 多栏经营看板显示三列图表与两列表格；双区域独立筛选 Report 显示两套互不相交的筛选区、图表和表格。
  - Doris 连接恢复后，在最新前端镜像再次执行列头降序和状态筛选；结果正确，浏览器控制台无 error / warning，未再出现 VTable `menuHandler` 错误。
  - 报表中心当前显示 8 份 Report，其中“表格能力示例”渲染两级可展开分组表、Pivot 交叉表和 53 字段宽表；分组行已实测收起并切换到下一组。
  - 53 字段宽表横向内容宽 9000px、视口宽 681px，已滚动到 2100px 且前两列保持冻结；纵向内容高 2040px、视口高 506px，已滚动到 700px。
  - 宽表从 `1 / 20` 切换到 `2 / 20`；请求期间三个 VTable canvas 均保留，同时显示“正在加载第 2 页…”，完成后加载提示消失、三个 canvas 继续存在。
  - 浏览器发现并修复 VTable 横向滚动后用视口高度覆盖总行高的问题；修复后横向滚动前后纵向范围均保持 2040px。
  - 图片布局模板的五张 ECharts canvas 均完成渲染；实测几何为首行 224px + 460px、次行 224px + 224px + 224px、底部表格 695px，对应 12 栏的 4+8、4+4+4、12 布局。
- 本轮相关验证
  - `python -m pytest backend/tests/test_report_query_service.py -q -p no:cacheprovider`：11 passed。
  - `npm.cmd test -- tests/report-renderer.test.tsx tests/report-context.test.tsx`：2 files、13 tests passed。
  - `npm.cmd test -- tests/report-empty-state.test.tsx tests/report-renderer.test.tsx`：2 files、15 tests passed。
  - `npm.cmd test -- tests/report-renderer.test.tsx`：13 tests passed，包含滚动事件不得缩小已知横纵内容范围的回归用例。
  - `npx.cmd tsc --noEmit --incremental false`：passed。
  - `docker compose config --quiet`：passed，仅有本机 Docker `config.json` 权限警告。
  - 五份 Report 的 15 个查询均通过真实接口执行；复杂表格列筛选返回 48 行，100 条分页和支付金额降序正确。
  - `npm.cmd test -- tests/flow-composer.test.tsx tests/analysis-task-thread-layout.test.tsx tests/report-draft-session.test.tsx tests/analysis-task-copy.test.ts`：4 files、22 tests passed。
  - `npx.cmd tsc --noEmit --incremental false`：passed。
  - frontend production 容器已重建，`http://10.87.84.25:3000/` 返回 200；内置浏览器确认三种模式菜单、模式切换和刷新恢复默认值，干净页面控制台无 error / warning。
  - MCP 专项后端：注册表、加密、API、stdio 协议探测共 15 tests passed；Codex MCP 配置与 SDK 相关回归 50 tests passed。
  - MCP 专项前端：分类、添加表单、密钥 30 秒隐藏、管理员 401/403、统一图标共 7 tests passed。
  - `npx.cmd prisma validate`、frontend production build、`docker compose config --quiet` 均通过。
  - 真实 `GenBI_report` MCP 握手成功，发现 `create_report` 与 `update_report`。
  - backend、frontend、postgres 容器均已运行；backend `/api/runtime/status` 与 frontend `/` 返回 200。
  - 管理员登录态下完成 MCP 页面真实浏览器验收：系统入口图标与主工具栏一致；“全部 / 系统内置 / 外部接入”分类正确；`GenBI_report` 无编辑、复制和删除入口；`BI_doris` 保留编辑、复制、删除与密钥查看入口；密钥明文可直接显示并立即隐藏；stdio 与 Streamable HTTP 添加表单均可打开且未提交测试数据；内置 MCP 运行检查发现 2 个工具；控制台无 error / warning。
  - 系统总览旧文案已修正：不再宣称当前已具备完整审计或禁止浏览器回显密钥，明确“审计后续统一建设”与“管理员可按需直接查看明文”。
  - 工作台清空回归用例按 TDD 先失败后通过；相关前端 3 个测试文件共 27 tests passed，TypeScript 检查通过。frontend production 容器已重建；管理员登录态下刷新并点击“工作台”后，二级侧栏为空且收起、主区域为空，新增控制台 error / warning 为 0。
  - 业务语义库知识图谱图标回归用例按 TDD 先失败后通过；相关前端 3 个测试文件共 28 tests passed，TypeScript 检查通过。仅重建 frontend 容器，backend 与 postgres 未重启；浏览器确认未选中/选中态清晰，稳定刷新后新增控制台 error / warning 为 0。
  - 使用真实 Doris 表 `dm.dm_channel_mtsg_sale_total` 完成 Agent 端到端生成；Session `019fd64d-3431-73a3-9fb6-4114a24923cb` 的修正 Turn `019fd659-d351-7e40-aa26-8308e758df52` 状态为 `completed`。
  - 可渲染 Report `report_0a70cc4883924ace89616f6806f3d9d7` 已写入 PostgreSQL；刷新恢复后右侧包含日期筛选、6 个图表块与 1 个分页明细表，浏览器检测为 0 个查询错误、0 个加载中、7 个 canvas。
  - 目标表查证结果：`vdate` 范围为 `2024-01-31` 至 `2026-08-05`，`vchannel_type` 与 `vchannel_type2` 全为空，Report 按 `vchannel_name` 进行渠道分组。
  - 对同一目标表追加 3 次全新会话重复验证，结果均未写入 Report：Session `019fd67f-f0ea-7d02-bca0-51fd6a61c4de` 的 Turn 完成但只回复执行计划；Session `019fd681-2838-7463-a2cf-ec8e565720af` 成功查询 Doris 后报告 `unsupported call`；Session `019fd68a-6886-7483-ab4c-bd8d6cda7108` 使用裸 `create_report` 后产生真实 `GenBI_report` 工具 Item，但因 `queries.q_top10.parameters` 不是 object 校验失败，随后重复生成调用说明，7 分 17 秒后人工取消。
  - 重复验证后的 PostgreSQL 只读核验：上述三个 Session 的有效 Report 数均为 0，Turn 终态依次为 `completed`、`completed`、`cancelled`。
  - 同期 `GenBI_report` 独立 MCP 探测仍为健康，能发现 `create_report`、`update_report` 两个工具；因此当前问题不是 MCP 进程不可启动，而是模型工具名适配、首次执行约束和 Report Schema 自纠错链路仍不稳定。
  - Report 中心卡片与软删除专项前端用例 8 tests passed；全量前端 28 files、172 tests passed，TypeScript 检查通过。
  - 全量后端 249 tests passed；`docker compose config --quiet`、`git diff --check`、frontend 200 与 backend health 均通过。
  - frontend 容器使用挂载源码重新执行 production build，Next.js 编译和 TypeScript 均通过并恢复 Ready；PostgreSQL 容器未重建。
  - 内置浏览器确认删除操作打开页面内 `role="dialog"`，无 JavaScript 系统弹窗；取消后卡片保留，确认后卡片立即消失且刷新不恢复。
  - 浏览器验收临时 Report `report_1bbe33517c474b5ba9ef9f3191287fbd` 删除后 API 返回 404，PostgreSQL 原记录仍存在且 `deleted_at` 已设置。
  - 固定六列修改后的全量前端 28 files、172 tests passed，TypeScript 检查通过；frontend 容器 production build 完成并恢复 Ready。
  - 干净内置浏览器标签确认 6 个等宽列均为 `162.429px`，前六张卡片同一行、第七张换行，第六张卡片与网格右边缘差值小于 `0.0001px`，控制台无 error / warning。

## 风险与待验证

- 首期 Excel 导出为同步请求；10 万行以内仍受数据源查询速度、反向代理超时和服务内存限制影响。若后续恢复百万行需求，需要另做异步任务、对象存储和自动拆 Sheet。
- 真实数据源查询依赖运行环境的数据源配置和只读账号；当前本地环境需要 Doris MySQL 协议端口 `9030`。
- Agent 已完成 5 份正式 Report 验收，但不是 5 次连续“一轮即成功”：真实运行中仍出现过数据工具参数错误、无进展 Turn 和持久化 Build 后续跑成功的情况。当前会确定性终止无进展 Turn、保留可恢复 Build，并禁止把未发布 Build 报为成功；后续仍可单独优化 MiniMax 首轮工具选择效率。
- 五份验收 Report 已在来源 Session 和后端 API 中验证，但当前管理员的报表中心“我的报表”仍显示 0。直接 Agent 路径持久化的 `ownerId` 与登录 Principal 的用户 ID 尚未统一，因此本轮不宣称“自动进入我的报表”链路验收通过。
- 示例的默认日期是本轮按源表最大日期确认的固定区间；后续若希望“每次生成都取最新 30 个完整自然日”，需要在生成器中增加默认日期发现步骤。
- 有来源 Report 的双按钮行为已有前端回归测试；本轮数据库按“不迁移旧 Report”清空后没有来源 Report 可做同等页面 smoke。
- `BI_doris` 旧密码在首次安全升级导入过程中曾短暂进入普通配置字段，随后已迁入 AES-256-GCM 密文信封并从普通字段删除；建议尽快轮换一次该密码。

## 下一步

1. 统一 Agent 发布 Report 的 owner 与登录 Principal 映射，让正式 Report 出现在对应用户的“我的报表”。
2. 单独优化 MiniMax 在首次 Turn 中的数据工具参数和渐进式 Report 工具选择，减少可恢复失败与续跑次数。
3. 网络稳定后重建标准 backend 镜像，替换当前为补齐 XlsxWriter 而临时修补的运行镜像。
