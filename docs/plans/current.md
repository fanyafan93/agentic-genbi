# 当前任务

更新时间：2026-08-01（Asia/Shanghai）

## 当前分支

- 仓库：`E:\my_repo\agentic genbi`
- 分支：`feature/codex-runtime-cleanup`
- 当前切片：业务语义库接入真实 FineReport 解析结果，提供报表目录、结构预览和解析详情，并保持固定桌面画布行为。

## 当前产品方向

用户只从分析工作台提出业务问题。后端通过 Codex / openai-codex 作为编排运行入口，负责理解意图、推进分析、生成事件流，并逐步接入业务语义库、只读数据工具和分析资产治理。

原则：能用 Codex 的，绝不自研；本项目只做业务语义、数据安全、分析资产治理、前端体验和 Codex 适配层。

## 本轮改动

- 新增 `backend/analysis/runner_contracts.py`，只保留分析 runner 的结果、协议和 prompt builder。
- 删除 `backend/analysis/agent_runner.py`，分析侧不再保留旧运行实现。
- 收缩 `backend/exploration/agent_runner.py` 为纯协议与文本清理工具，不再包含模型 provider、旧 runner 或 SDK 事件归一化。
- `backend/api/exploration_api.py` 中 `GENBI_ANALYSIS_RUNTIME` 只支持 `codex`、`local`、`mock`；默认值改为 `codex`，不再回退旧 runner。
- `backend/resource_library/exploration_agent.py` 不再构造旧 SDK agent；保留资源库、只读数据库和知识沉淀工具函数，后续包装为 Codex tools / MCP / Skills。
- 移除 `backend/requirements.txt` 中旧依赖，只保留 `openai-codex` 运行链路。
- 更新相关测试，测试目标从旧 SDK runner 改为 Codex-compatible runner contract。
- README 默认配置改为 `GENBI_ANALYSIS_RUNTIME=codex`、`GENBI_EXPLORATION_RUNTIME=local`。
- `frontend/src/modules/business-semantics/components/BusinessSemanticLibrary.tsx`：业务语义库改为两个一级模块：结构化知识、语义。
- 结构化知识模块以 FineReport、Apache Hop、数据库、金蝶四类来源组织侧栏入口，表达“系统里实际存在什么”。
- 语义模块统一承载业务主题、数据对象、查询路由、关系规则、字段语义、指标、维度、业务规则、查询案例，并通过状态区分全部、待确认、已发布、草稿、已废弃。
- 页面补充“结构化知识 → 语义候选 → 人工确认 → 发布为语义”的关系说明。
- 业务语义库的“结构化知识 / 语义”切换已移动到第二竖栏。
- FineReport、Apache Hop、数据库、金蝶已作为“结构化知识”下的二级入口放入第二竖栏，只保留名称和基本介绍。
- 业务语义库右侧主内容区默认只在 FineReport 入口展示真实报表解析浏览器；Apache Hop、数据库、金蝶和语义入口继续留空。
- 新增 `backend/business_semantics/finereport_reports.py`，从只读资源库自动聚合同名的三类解析 JSON，规范化报表摘要、数据集、参数交互、Sheet、单元格坐标和跨行跨列信息。
- 新增 FineReport 列表与详情接口：`GET /api/business-semantics/finereport/reports`、`GET /api/business-semantics/finereport/reports/{report_id}`。
- 新增 FineReport 前端 API 契约、报表目录、概览、报表预览、数据集与 SQL、参数与交互、结构详情五个视图。
- 报表预览使用 CSS Grid 根据 `row / columnIndex / rowspan / colspan` 还原结构，支持 Sheet 切换、60% 至 160% 缩放、横纵滚动和单元格公式/绑定查看。
- 修复业务语义库图标重复点击或历史折叠状态导致第二竖栏不显示的问题：进入业务语义库会强制展开第二竖栏。
- 所有页面统一使用 1180px 最小桌面画布；窗口变小时不隐藏侧栏、不改变列数、不把卡片改成单列，空间不足时通过页面横向滚动查看。
- 删除 900px、620px、520px 三组会改变页面结构的响应式断点，只保留减少动画等不影响结构的媒体规则。

## 已验证

- `python -m py_compile backend\analysis\runner_contracts.py backend\analysis\run_service.py backend\harness\codex_sdk_runner.py backend\exploration\agent_runner.py backend\exploration\run_service.py backend\resource_library\exploration_agent.py backend\api\exploration_api.py`：通过。
- `python -m unittest backend.tests.test_agent_runner backend.tests.test_analysis_agent_runner backend.tests.test_analysis_run_service backend.tests.test_codex_sdk_runner backend.tests.test_analysis_api backend.tests.test_exploration_agent backend.tests.test_exploration_run_service -v`：39 个后端测试通过。
- 旧运行时关键词扫描通过：后端、README 和三份文档中不再出现旧 SDK 入口、依赖和 runner 名称。
- `cmd /c npm run test -- tests/analysis-task-copy.test.ts`：1 个前端测试文件 / 12 个测试通过。
- `cmd /c npm run build`：Next.js build 通过。
- `cmd /c npm run test`：10 个前端测试文件 / 73 个测试通过。
- `cmd /c npm run build`：固定桌面画布修改后 Next.js production build 通过。
- 浏览器在 1366x844 与 390x844 视口完成对比验证；390px 视口下画布保持 1180px，主体三栏保持 `56px / 240px / 874px`，页面横向滚动范围为 1180px。
- 逐页验证工作台、分析工作台、分析资产库、业务语义库和系统页：窗口变小时仍保持桌面端侧栏和既有列结构，通过横向滚动查看未显示区域。
- 浏览器验证业务语义库：第二竖栏包含 4 个结构化知识二级入口；FineReport 展示真实报表浏览器，其他入口保持空白；侧栏宽度保持 240px，页面画布宽度保持 1180px。
- FineReport 后端真实数据验证：识别 3 张完整报表；分别包含 137、272、2364 个单元格，数据集、参数控件、交互规则、公式和字段绑定统计均可读取。
- `python -m unittest backend.tests.test_finereport_reports -v`：FineReport 聚合与 API 测试通过。
- `python -m unittest discover -s backend\tests -v`：后端全量 91 个测试通过。
- 浏览器验证三张真实报表可切换；最大报表渲染 2364 个单元格，横纵滚动正常，13 个数据集和 SQL 视图可打开；最终示例报表包含 2 个 Sheet、111 个当前 Sheet 单元格，控制台无错误。

## 风险

- 探索侧真实 LLM runner 已移除，当前探索接口没有真实 agent runner；符合“不要两个并列 Agent 入口”的方向，后续应通过分析工作台背后的 Codex tools 接入语义查证能力。
- 业务语义库除 FineReport 真实解析文件浏览外仍为前端占位，尚未接完整持久化、状态流转、审核发布和 Codex tools。
- FineReport 当前直接读取解析 JSON，尚未持久化到 Postgres；视觉预览只能还原现有 JSON 中的结构，原始行高、列宽、字体、颜色、边框和数字格式仍需解析器补充。
- 只读数据库和 Artifact tools 尚未接入 Codex runner。
- 固定桌面画布意味着窄窗口必须横向滚动；这是当前明确的产品取舍，不是响应式缺陷。

## 下一步

1. 合并当前分支到 `Agentic-GenBI` 并推送远端。
2. 下一切片设计业务语义库真实数据契约和 Codex tools / MCP / Skills 接入。
