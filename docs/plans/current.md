# 当前分支状态

更新时间：2026-08-05 Asia/Shanghai

## 分支

- 本轮开发分支：`feature/docker-runtime-cleanup`
- 基线：`Agentic-GenBI`
- 合并状态：`feature/docker-runtime-cleanup` 已合入 `Agentic-GenBI`；开发分支保留在远端。
- 本轮结果：完成 Docker runtime 清理、分析运行问题收口、Report 单记录与草稿新会话链路，以及可真实持久化、受服务端权限保护的系统管理 V1。

## 本轮已处理

1. Session management 合入主开发分支
   - `feature/session-management` 已合并到 `Agentic-GenBI`。
   - 合并后 `Agentic-GenBI` 已推送到 Gitee。
   - 镜像仓库已执行 Gitee → GitHub 同步。

2. Docker runtime 清理
   - 新建 `feature/docker-runtime-cleanup` 分支。
   - `backend` compose 环境显式固定：
     - `GENBI_BACKEND_WORKERS=1`
     - `UVICORN_WORKERS=1`
     - `WEB_CONCURRENCY=1`
   - `frontend` compose 不再加载整份 `.env`，只保留前端运行所需变量。
   - `frontend` compose 启动命令去掉每次启动时的 `npm install`，依赖改由镜像构建阶段提供。

3. 旧任务历史迁移
   - 新增 `scripts/migrate_legacy_thread_store.py`，用于把旧 `.resource-index/thread-store.jsonl` 迁入当前 PostgreSQL。
   - 迁移保持新 Session 契约：`session_id == codex_session_id`；旧 `codexThreadId` 保存在 metadata 的 `legacy_codex_session_id`。
   - 迁移保持新 Turn 契约：`turn_id == codex_turn_id`；旧 `codexTurnId` 保存在 metadata 的 `legacy_codex_turn_id`。
   - 旧 session 非 `archived` 状态统一映射为当前可用的 `active`。
   - 旧 thread `title` 为空时，使用对应首个 Turn 的 `question/inputText` 回填任务名称。
   - 旧 Turn 缺少 item projection 时，合成稳定的 `userMessage` item，确保任务详情页能显示历史提问内容。
   - 已在 backend 容器内对 `/app/.resource-index/thread-store.jsonl` 执行 `--apply`：
     - read / migrated threads：88 / 88
     - read / migrated turns：86 / 86
     - read / migrated items：2 / 88（其中 86 个为从 Turn question 合成的 userMessage）
   - API `GET /api/analysis/sessions?limit=200` 当前返回 active session 数：89。

4. 历史任务前端恢复
   - 前端列表请求从默认 `/api/analysis/sessions` 改为 `/api/analysis/sessions?limit=200`，避免历史任务被默认分页截断。
   - 前端详情恢复同时兼容顶层 `codexItemProjections` 与每个 Turn 内的 `timeline`。
   - 已重建并重启 frontend 容器，当前 `http://192.168.101.12:3000/` 返回 200。

5. 飞书登录恢复
   - Docker runtime 清理后 frontend 容器缺少 NextAuth 服务端所需的 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_REDIRECT_URI`。
   - 表现为 `/api/auth/feishu-login` 跳转到飞书时 `client_id=undefined`。
   - 已在 `docker-compose.yml` 的 frontend environment 中显式补回飞书 auth 变量，不恢复整份 `.env`。
   - 已重建并重启 frontend 容器。

6. Turn 异常终态补偿
   - 修复 Codex Runtime / artifact projection 在已 provision Turn 后抛异常时，Turn 仍停留 `running` 导致前端一直显示“思考中”的问题。
   - buffered 与 SSE streaming 两条路径都会在未收到真实 `turn/completed` 时补写一次 `turn/completed`，`status=failed`。
   - 失败终态的 `error/detail` 会写入 Turn metadata，便于详情页和排障识别具体异常。
7. 前端思考占位终态收口
   - 已确认 `019fd0c6-339b-75a2-8988-c45ce037180c` 后端最新 Turn 为 `completed`，且已持久化完整 agent message；原标签页仍显示“思考中”属于前端本地占位状态未收口。
   - `useFlow` 现在处理 `done` 事件：移除无内容、无工具过程的空思考占位；有内容或执行过程的 agent 节点保留，并将 `thinking` 置为 `false`。
8. 首轮 Session ID 归位不中断事件流
   - 进一步确认真正的稳定复现路径：首轮收到 `session/created` 后，Workspace 更新路由中的 Session ID；原 `useFlow` effect cleanup 会把仍在消费的首轮 SSE 标记为 cancelled，导致后续 agent message 与 `done` 被丢弃。
   - 已把 Session/历史初始化与组件卸载取消拆开，并显式识别当前首轮刚 provision 的 Session ID；该次 ID 归位只更新路由锚点，不重置或取消正在消费的流。
9. Turn 收尾数据库终态回查
   - 仅依赖浏览器完整接收 SSE 仍可能留下本地思考状态；`useFlow` 现在会在流结束后按已解析的 Session ID 调用收尾回查。
   - Workspace 使用 `GET /api/analysis/sessions/{session_id}` 读取持久化 Turn/Item，并以数据库中的完整节点覆盖本地流状态；回查暂时失败时仍保留已收到的 SSE 内容。
10. 终态回查 Item 去重
   - Session 详情同时包含顶层 `codexItemProjections` 与每个 Turn 的 `timeline`；同一个 Item 会在两处出现。
   - 恢复层现在按 `codexItemId` 去重，顶层 projection 优先；缺少 Item ID 的历史记录继续保留，避免误删。
11. MiniMax SSE 中文乱码修复
   - 根因是代理逐个网络字节块执行 UTF-8 解码；中文字符跨 `read()` 边界时会被 `errors="replace"` 写成不可逆的 `�`。
   - SSE 读取现改为 UTF-8 增量解码，在流结束时统一冲刷尾部字节，避免拆分多字节字符。
   - 已落库的旧 `�` 不做猜测性修复；修复只保证新 Turn 不再由该链路产生乱码。
12. 实时回复源头去重
   - 之前只验证并去重了 Turn 结束后的数据库回查结果，无法阻止页面在回查前短暂显示两条相同回复。
   - 根因是同一 Agent 回复先通过多个 `item/agentMessage/delta` 完整展示，紧接着 `item/completed` 又携带相同完整内容并生成第二个可见事件。
   - Backend Agent Client 现在在同一 Turn 节点内累计 delta；完成内容与累计文本相同时，不再生成第二个可见 `agent` 事件。没有 delta 或最终内容确实不同时，仍保留最终替换事件。
13. 报表 MCP 空 artifact 兼容
   - Session `019fd0ee-dc4c-76a3-9fff-f7bd13301469` 的数据查询成功，但 `create_interactive_report` 两次收到 `artifact: {}` 后都把空对象当成完整 ReportArtifact 校验，因缺少必填结构返回 `validation_failed`，因此没有产生 `genbi/artifact/updated`，也没有写入 `analysis_reports`。
   - `artifact` 为空对象时现在按“未提供完整 artifact”处理，改用顶层 `title` / `summary` / `rows` 编译并校验报告；非空 artifact 仍保持原有完整结构校验。
14. 报表新建分析首条消息契约
   - 根因是“新建会话”只预分配 Codex threadId 就中止 `thread_start`，没有生成可恢复 rollout；首条问题随后走 continuation `thread_resume`，触发 `no rollout found for thread id`。
   - “新建会话”现在只打开 `/analysis/new` 本地草稿并附带当前 Report，不提前创建 Session；首条手工问题或建议问题统一走 sessionless `flow.start`。
   - 后端按 `source_report_id` 读取当前 Report，写入新 Session metadata，并以 Codex 原生多段文本输入把问题和 Report JSON 一起交给首个 Turn。
15. 分析任务深链接刷新
   - 新增 Next.js 动态路由 `/analysis/[sessionId]`，`/analysis/{session_id}` 与 `/analysis/new` 不再只依赖浏览器 `history.pushState`。
   - 动态路由继续执行服务端登录校验；登录后把 URL 中的 Session ID 传给 Workspace。
   - Workspace 初始化时读取 Session 详情、历史 Turn/Item 和关联报告；恢复既有 Session 时不会创建新 Session。
   - 首次部署后发现登录态 SSR 在任务列表尚未加载时会读取不存在的 `currentAnalysisThread.latestTurnStatus`，触发 “This page couldn’t load”；状态读取现允许 Session 摘要暂时为空。
16. 官方 Codex Item 驱动的执行过程
   - 后端以 Codex 原生通知为唯一事实源，新增映射：
     - `item/reasoning/summaryTextDelta`
     - `item/started` / `item/completed`
     - `item/commandExecution/outputDelta`
     - `item/mcpToolCall/progress`
   - `item/reasoning/textDelta` 继续忽略，不展示隐藏原始推理；MiniMax 未返回 reasoning summary 时不伪造阶段文案。
   - 新增统一事件脱敏器；命令、参数、SQL、结果和错误可进入工具详情，密钥、Token、密码、Cookie、Authorization 和连接 URL 凭据在后端投影前替换为 `[REDACTED]`。
   - 前端实时按 Codex Item ID 合并 reasoning summary delta，工具 started/completed 更新同一行；最终 Agent Message 独立显示，不与执行过程混排。
   - 历史恢复按 Item `sequence` 重建；工具失败状态优先读取原生 `mcp_status` / `command_status` / `file_change_status`，失败调用与成功重试不会错误合并。
   - UI 改为 Codex 风格三级折叠：
     - Turn 执行过程：运行时展开，完成后折叠并显示耗时。
     - reasoning summary 与其后相邻工具组成步骤组。
     - 工具详情默认折叠，展开后显示脱敏后的参数、SQL、输出、结果与错误。
   - reasoning 没有 summary、但工具已经开始时，静态“思考中...”立即消失，改由真实工具活动表明 Turn 仍在运行。
17. Session 切换与停止竞态修复
   - 分析中的 Session 现在可以切换到其他 Session；切换只改变当前视图，不取消原 Session 的 Codex Turn。
   - 前端按 Session ID 隔离流状态、Agent Client、Turn token 和任务列表运行标记；后台 Session 的事件继续写入自己的快照，切回后恢复最新执行状态和结果。
   - 后台 Session 的终态数据库回查在异步返回后会重新锁定原 Session，不能覆盖当前正在查看或执行的另一个 Session。
   - “停止”仍只调用既有 Codex Turn cancel/interrupt 契约；停止后立即清理当前 Session 的思考状态，不影响其他 Session。
   - 停止后发送新消息时，用户消息立即进入当前 Session；新的 Codex Turn 等原生 interrupt 请求结束后才启动，旧 Turn 的收尾不能再覆盖新 Turn 的运行状态。
   - 本轮未新增后台任务、轮询、跨进程 registry 或新的 Turn/Item 生命周期事件。
18. Session 选择与深链接同步
   - 修复侧栏切换 Session 只更新 React state、没有更新地址栏的问题。
   - 点击既有 Session 后立即把 URL 更新为 `/analysis/{session_id}`；后台 Turn 是否运行、详情请求是否完成都不影响当前选择对应的深链接。
19. Report 单记录与可选会话来源
   - Report 不再维护版本号、版本 API 或版本表；同一 Report ID 保存时直接覆盖当前内容。
   - PostgreSQL 启动迁移把每个旧 Report 的最新版本内容写入 `analysis_reports` 主表，随后删除 `analysis_report_versions` 和 `latest_version`。
   - `source_thread_id` / `source_turn_id` 改为可空；代码案例可用 `originType=seed` 创建不绑定会话的 Report。
   - 有来源会话的 Report 显示“回到会话”和“新建会话”；无来源会话的 Report 只显示“新建会话”。
   - “新建会话”点击阶段不创建 Session；首条消息由 Codex Runtime 分配真实 Session ID，并把当前 Report 作为 `initial_report_artifact` 引用上下文。
20. 系统管理 V1
   - 系统入口统一为“系统”，页面不暴露底层编排实现名称；导航包含系统总览、用户与权限、MCP 服务、系统提示词、模型与运行策略。
   - 用户管理使用 Auth.js 当前登录态与 PostgreSQL `User` 表，支持管理员/普通用户、启用/停用；禁止移除最后一个有效管理员。
   - 当前数据库没有管理员时，任一已登录且有效的用户可执行一次性管理员认领；事务 advisory lock 保证并发下只能成功一次。
   - MCP 服务由后端环境配置定义，管理后台保存启停覆盖并写审计；后续新建或继续分析前会刷新运行配置，停用服务不再加载。
   - 系统提示词采用不可变版本，支持草稿、发布和回滚；分析运行时读取当前已发布版本，数据库不可用时回退到代码内安全默认值。
   - 模型、审批策略、沙箱边界和内置工具开关统一持久化；线程级配置优先使用管理策略，全权限沙箱不在后台开放。
   - 所有系统 API 都由服务端校验管理员权限；前后端内部系统接口增加独立 token，不向浏览器暴露后端凭据。
   - 新增 `SystemPromptVersion`、`SystemSetting`、`SystemAuditLog` 和 `User.status` migration；前端镜像显式执行 `prisma generate`，避免匿名依赖卷使用旧 Client。
21. 系统管理 UI 与工作台风格统一
   - 系统模块状态上提到工作台，左侧“系统”面板成为唯一模块导航；内容区不再重复渲染第二套导航。
   - 保留用户、MCP、系统提示词和运行策略的原有服务端契约与操作逻辑。
   - 移除系统页独立的米色网格、衬线标题和大留白，统一使用分析工作台的白色卡片、海军蓝/珊瑚红配色、圆角、阴影、字号和密度。
   - 总览卡片、用户表格、MCP 主从面板、提示词版本编辑器、运行策略表单及初始化/无权限状态已统一视觉规则。
22. 归档 Session 深链接恢复修复
   - Session `019fd1bb-9b83-7f03-ae9a-9399ac369a5b` 在 PostgreSQL 中只有一条记录，状态为 `archived`；刷新没有重复创建 Session。
   - 根因是详情 API 允许读取归档 Session，而分析工作台的深链接恢复逻辑没有过滤状态，会把该记录重新加入活动任务列表。
   - 主工作台现在遇到归档 Session 深链接时使用 `replaceState` 回到 `/analysis/new`，不恢复历史消息、报告或列表项；后端归档记录保持不变。
   - 同时收紧报告加载判断，避免新建页因两个空 Session ID 相等而误显示“报告加载中”。
23. 全量测试脚本导入稳定性
   - 全量 pytest 收集时，环境中的同名第三方 `scripts` 包可能先进入模块缓存，导致迁移测试无法导入仓库脚本。
   - 迁移测试改为按仓库绝对文件路径加载 `migrate_legacy_thread_store.py`；只修正测试导入，不改变迁移脚本和业务运行逻辑。

## 已验证

- 合并后后端相关回归：
  - `python -m pytest backend\tests\test_codex_projection_store_purity.py backend\tests\test_postgres_p0_compat.py backend\tests\test_codex_sdk_runner.py backend\tests\test_analysis_api.py -q`
  - 107 passed，3 subtests passed
- 合并后前端客户端回归：
  - `npm.cmd test -- analysis-backend-client.test.ts`
  - 29 passed
- `docker compose config`
  - passed
- `docker compose build frontend`
  - passed
- `docker compose build backend`
  - passed
- `git diff --check`
  - passed
- 旧任务迁移单测：
  - `python -m pytest backend\tests\test_legacy_thread_store_migration.py -q`
  - 1 passed
- 旧任务迁移容器执行：
  - `docker compose cp scripts\migrate_legacy_thread_store.py backend:/tmp/migrate_legacy_thread_store.py`
  - `docker compose exec -T backend sh -lc "cd /app && PYTHONPATH=/app python /tmp/migrate_legacy_thread_store.py /app/.resource-index/thread-store.jsonl --apply"`
  - migrated threads / turns / items：88 / 86 / 88
- 服务级 API smoke：
  - `GET http://192.168.101.12:8000/api/analysis/sessions?limit=200`
  - active_count=89
  - `GET http://192.168.101.12:8000/api/analysis/sessions/conv_analysis_f1b9cb2006d5`
  - confirmed title=`analyze channel sales`，timeline 包含 synthetic `codex/userMessage`
- 历史任务前端恢复回归：
  - `npm.cmd test -- analysis-backend-client.test.ts`
  - 30 passed
- frontend 容器重建：
  - `docker compose up -d --build frontend`
  - frontend ready，`GET http://192.168.101.12:3000/` 返回 200
- 飞书登录 smoke：
  - `GET http://192.168.101.12:3000/api/auth/feishu-login`
  - 返回 307，`client_id` 为配置的飞书 App ID，`redirect_uri=http://192.168.101.12:3000/api/auth/callback/feishu`
- Turn 异常终态回归：
  - `python -m pytest backend\tests\test_analysis_api.py::AnalysisApiTest::test_runtime_exception_marks_provisioned_turn_failed -q`
  - 1 passed
- 后端 analysis API / projection store 回归：
  - `python -m pytest backend\tests\test_analysis_api.py backend\tests\test_codex_projection_store_purity.py -q`
  - 84 passed，3 subtests passed
- 前端 backend client 回归：
  - `npm.cmd test -- analysis-backend-client.test.ts`（在 `frontend` 目录执行）
  - 30 passed
- `docker compose config --quiet`
  - passed
- `git diff --check`
  - passed
- backend 容器重建：
  - `docker compose up -d --build backend`
  - backend started
- backend API smoke：
  - `GET http://192.168.101.12:8000/api/analysis/sessions?limit=1`
  - 返回 200
- 前端思考占位终态回归：
  - `npm.cmd test -- analysis-flow-streaming.test.ts analysis-backend-client.test.ts flow-node-view.test.tsx`
  - 47 passed
- `019fd0c6` 页面验证：
  - 后端详情返回 `latestTurnStatus=completed`，包含完整 agent message。
  - 重建 frontend 后重新打开该任务，页面显示完整回复，不再显示“思考中”。
- 首轮路由切换回归：
  - `npm.cmd test -- analysis-flow-streaming.test.ts analysis-backend-client.test.ts flow-node-view.test.tsx analysis-task-copy.test.ts`
  - 65 passed
- 首轮页面端到端验证：
  - 从新分析页面发送“你好”，URL 自动切换到 `/analysis/019fd0d2-c123-7d11-a2c5-ce0d88c68781`。
  - 页面无需刷新即从“思考中”切换为完整回复，`.flow-thinking` 数量为 0。
  - 后端对应 Turn 状态为 `completed`，持久化 1 条 agent message。
- Chrome DevTools 实际页面验证：
  - 在实际 Chrome 标签页强制无缓存加载新 frontend 后发送“你好”，创建 Session `019fd0d8-d07a-7570-bdb5-4580c8f80b32`。
  - Network：`POST /api/analysis/sessions/turns/stream` 返回 200；随后自动执行 `GET /api/analysis/sessions/019fd0d8-d07a-7570-bdb5-4580c8f80b32` 并返回 200。
  - DOM：`思考中...` 消失，完整 agent message 出现，发送按钮恢复，侧栏状态为“已完成”。
- Turn 收尾回查回归：
  - `npm.cmd test -- analysis-flow-streaming.test.ts analysis-backend-client.test.ts flow-node-view.test.tsx analysis-task-copy.test.ts`
  - 66 passed
- Item 去重回归：
  - `npm.cmd test -- analysis-backend-client.test.ts analysis-flow-streaming.test.ts flow-node-view.test.tsx analysis-task-copy.test.ts`
  - 67 passed
- Chrome DevTools 回复去重验证：
  - 打开出现重复的 Session `019fd0da-708b-7541-aacb-579ef36dccde`，原 Turn 的 agent reply 只显示 1 次。
  - 在同一 Session 继续发送“你好”，新 Turn 完成后新 agent reply 只显示 1 次，`.flow-thinking` 数量为 0。
- MiniMax SSE UTF-8 边界回归：
  - `python -m unittest backend.tests.test_analysis_api backend.tests.test_minimax_codex_adapter -v`
  - 83 passed；新增用例明确把中文字符的 UTF-8 字节拆到两次 `read()`，结果不含 `�`。
- backend 容器部署：
  - `docker compose build --pull=false backend`
  - `docker compose up -d --no-deps --force-recreate backend`
- Chrome DevTools 中文端到端验证：
  - 在 Session `019fd0df-086b-7e50-a1f8-fe82820fd25f` 发送“请只回复……你好！有什么我可以帮你的吗？随时告诉我。”。
  - 新 Turn `019fd0e3-441a-72c0-8b09-f570f35a3781` 状态为 `completed`。
  - 页面与后端持久化的最新 agent message 都是完整中文“你好！有什么我可以帮你的吗？随时告诉我。”，不含 `�`。
- 实时回复源头去重回归：
  - 先修改测试契约并确认失败：原映射器在两段 delta 后仍生成一次完整 `agent` 事件。
  - `npm.cmd test -- analysis-backend-client.test.ts analysis-flow-streaming.test.ts flow-node-view.test.tsx analysis-task-copy.test.ts`
  - 67 passed。
- frontend 部署验证：
  - `docker compose build --pull=false frontend`
  - `docker compose up -d --no-deps --force-recreate frontend`
  - 容器内 Next.js build 编译及 TypeScript 检查通过，页面返回 200。
- Chrome DevTools 回答全过程验证：
  - 新建 Session `019fd0eb-a5ff-7570-8c61-850bdb622c38`，随后发送第二轮“请只回复……第二轮实时去重通过”。
  - MutationObserver 记录每次 DOM 变化：`思考中...` → `第二轮实时去` → `第二轮实时去重通过` → 完成。
  - 目标短语在任一快照中最多出现 2 次（用户问题 1 次、Agent 回复 1 次），从未出现第 3 次，因此实时阶段没有第二条 Agent 回复。
- 报表 MCP 空 artifact 回归：
  - `python -m pytest backend/tests/test_genbi_report_mcp_server.py -q`
  - 10 passed；新增用例复现 `019fd0ee` 的 `artifact: {}` 与 `$text` 行包装。
- 报表新建分析首条消息回归：
  - `npm.cmd test -- analysis-task-copy.test.ts interactive-report-api-client.test.ts report-center-card-actions.test.tsx`
  - 24 passed；覆盖手工输入和建议问题均使用已有 Session continuation。
- 容器部署及报表工具 smoke：
  - `docker compose up -d --build backend frontend`
  - backend / frontend / postgres 均 running，前后端 HTTP 均返回 200。
  - backend 容器内以 `artifact: {}` 调用 `create_interactive_report`，返回 `ok=true`、`status=validated`、`artifactType=interactive_report`。
- 分析任务深链接回归：
  - `npm.cmd test -- analysis-deep-link-route.test.ts analysis-backend-client.test.ts analysis-flow-streaming.test.ts flow-node-view.test.tsx analysis-task-copy.test.ts interactive-report-api-client.test.ts report-center-card-actions.test.tsx`
  - 7 test files、78 tests passed；包含带 URL Session ID、但 Session 摘要尚未加载时的真实 React 服务端渲染用例。
  - frontend 容器生产构建通过，Next.js route manifest 包含动态路由 `ƒ /analysis/[sessionId]`。
  - `GET /analysis/019fd0ee-dc4c-76a3-9fff-f7bd13301469` 与 `GET /analysis/new` 均返回 200。
  - 修复后 frontend 日志不再出现 `Cannot read properties of undefined (reading 'latestTurnStatus')`。
  - Chrome 打开并刷新目标 Session URL 后仍停留原 URL，显示登录页而不是 404/加载失败页，控制台无 error；当前 Chrome 无飞书登录态，登录后的会话内容恢复由 SSR 路由回归与后端 Session 200 smoke 覆盖。
- 官方 Codex 执行过程后端回归：
  - `python -m pytest backend/tests/test_codex_event_sanitizer.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py -q`
  - 93 passed，3 subtests passed。
- 官方 Codex 执行过程前端回归：
  - `npm.cmd test`
  - 19 test files、115 tests passed。
  - `npx.cmd tsc --noEmit --incremental false`
  - passed。
- Docker 生产构建与服务重建：
  - `docker compose up -d --build`
  - backend / frontend / postgres 正常运行；frontend Next.js production build 与 TypeScript 检查通过；前端 3000 返回 200，后端 `/health` 返回 `{"status":"ok"}`。
- Chrome DevTools MCP 真实页面验证：
  - 新建 Session `019fd151-eadc-79d1-96a1-d83a9f37117f`，提问“请查询数据库当前时间，并简要告诉我结果。”
  - SSE 原生 Item 顺序包含 reasoning、一次失败的 `mysql_query`、一次成功重试和最终 Agent Message；MiniMax 本轮 reasoning Item 未提供 summary，因此页面没有伪造摘要。
  - 完成后显示折叠的“分析了 12秒”；展开后失败与成功工具调用为两条独立记录，再展开可见实际 SQL、解析错误、查询结果和耗时。
  - 同 Session 第二轮实时 MutationObserver 验证：工具进入 `running` 时 `.flow-thinking` 从 1 变为 0；完成后过程折叠为“分析了 7秒”，最终回复只出现 1 次。
  - 页面仅有 `/favicon.ico` 404；业务 API、SSE、历史回查和页面渲染均为 200。
- Session 切换与停止回归：
  - `npm.cmd test`
  - 19 test files、121 tests passed。
  - 覆盖运行中从 Session A 切到 B、A 后台完成后切回恢复结果、A 终态回查与 B 实时事件交错隔离、停止立即清理思考状态、停止后继续发送，以及新 Turn 等待原生 interrupt 完成。
- Session 深链接同步回归：
  - 从 `/analysis/session-a` 点击 Task B 后，浏览器 pathname 必须变成 `/analysis/session-b`。
  - 该用例修改前稳定失败，修复后与相关 Session 切换测试一起通过。
- Session 列表切换稳定性回归：
  - 已复现运行中从 Session A 点击 Session B 时，A 的旧 `running` 快照会把 B 的 `updatedAt` 改为当前时间并置顶。
  - 仅在用户选择 Session 的过渡帧跳过列表同步；真正发送消息和 Turn 状态变化仍沿用原更新时间与排序行为。
  - `npm.cmd test -- tests/analysis-deep-link-route.test.ts`：5 passed。
  - `npm.cmd test`：23 test files、136 tests passed。
  - 前端容器生产构建与 TypeScript 检查通过，动态路由 `/analysis/[sessionId]` 保留；目标页面 HTTP 200。
  - 容器首次重建命中了挂载卷中的旧 Prisma Client，刷新生成物后构建通过；未修改系统管理代码。
  - 内置浏览器点击“继续”前后，真实列表前六项的顺序和时间完全一致，URL 正确切到 `/analysis/019fd15c-5973-7a62-ab8b-daccfd27ffab`。
  - 当前后端没有 `running` Session，因此运行中切换的精确页面场景由回归测试覆盖，未为验证额外创建 Turn。
- TypeScript：
  - `npx.cmd tsc --noEmit --incremental false`
  - passed。
- Codex Runner / Analysis API 相关后端回归：
  - `python -m pytest backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py -q`
  - 90 passed，3 subtests passed。
- 本轮 frontend 容器部署：
  - 最终源码使用 `docker compose build --pull=false frontend` 构建，并用 `docker compose up -d --no-deps --force-recreate frontend` 重建容器。
  - Next.js production build、TypeScript 和动态路由 `/analysis/[sessionId]` 均通过；`GET http://192.168.101.12:3000/analysis/new` 返回 200，`GET http://192.168.101.12:8000/health` 返回 `{"status":"ok"}`。
  - 第一次最终重建因 Docker Hub 基础镜像元数据请求 EOF 失败；改用本机缓存基础镜像后成功，不是源码构建失败。
- `git diff --check`
  - passed。
- Report 单记录后端回归：
  - `python -m pytest backend/tests/test_analysis_api.py backend/tests/test_postgres_p0_compat.py backend/tests/test_genbi_report_mcp_server.py backend/tests/test_interactive_report_api.py -q`
  - 98 passed，3 subtests passed。
- 后端其余全量回归：
  - `python -m pytest backend/tests --ignore=backend/tests/test_legacy_thread_store_migration.py -q`
  - 191 passed，3 subtests passed。
- 前端全量回归：
  - `npm.cmd test`
  - 23 test files、136 tests passed。
  - `npx.cmd tsc --noEmit --incremental false`
  - passed。
- Report PostgreSQL 迁移与 API smoke：
  - backend 镜像已重建，`GET /health` 返回 `{"status":"ok"}`。
  - `analysis_report_versions` 已不存在；`analysis_reports` 已包含非空 `document` / `filters` / `queries` / `chart_specs` / `grid_specs` / `datasets` / `origin_type`，会话来源列允许为空。
  - `GET /api/analysis/reports?limit=1` 返回主表中的完整当前 Report，不再返回版本对象。
- `docker compose config --quiet`
  - passed。
- 系统管理前端回归：
  - `npm.cmd test`
  - 23 test files、136 tests passed。
  - `npx.cmd tsc --noEmit --incremental false`
  - passed。
- 系统管理后端回归：
  - `python -m pytest backend/tests/test_codex_mcp_config.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py -q -p no:cacheprovider`
  - 114 passed，3 subtests passed。
  - `python -m pytest backend/tests -q -p no:cacheprovider --ignore=backend/tests/test_legacy_thread_store_migration.py`
  - 191 passed，3 subtests passed。
- 系统管理生产构建与迁移：
  - `docker compose up -d --build --renew-anon-volumes frontend`
  - migration `20260805000000_system_management` 已应用；Next.js production build、TypeScript、全部系统 API 路由生成通过。
  - `docker compose up -d --build backend frontend`
  - frontend / backend / postgres 正常运行；前端首页与后端 report-center smoke 均返回 200。
- 系统管理真实页面验证：
  - 已登录用户可见“系统”入口；当前无管理员时显示一次性“初始化系统管理员”页面。
  - 1360px 桌面布局无横向结构回退，页面可见区未出现底层编排实现名称，浏览器 console 无 error / warning。
- 系统管理 UI 重构回归：
  - `npm.cmd test -- system-admin-page.test.tsx analysis-deep-link-route.test.ts`
  - 2 test files、8 tests passed；覆盖工作台侧栏唯一导航和模块切换。
  - `docker compose up -d --build frontend` 完成，Next.js production build 与容器内 TypeScript 检查通过，frontend / backend / postgres 均正常运行。
  - Chrome DevTools 逐页验证系统总览、用户、MCP、系统提示词和运行策略；系统导航只有 1 个且不在主内容区，页面和系统内容均无横向溢出，相关系统 API 均返回 200。
  - 浏览器唯一 404 为项目既有的 `/favicon.ico`，与本轮 UI 无关。
- `git diff --check`
  - passed。
- Report 草稿新建会话回归：
  - `npm.cmd test`
  - 24 test files、140 tests passed。
  - `npx.cmd tsc --noEmit --incremental false`
  - passed。
  - `python -m pytest backend/tests -q -p no:cacheprovider --ignore=backend/tests/test_legacy_thread_store_migration.py`
  - 193 passed，3 subtests passed。
  - `docker compose config --quiet` 与 `docker compose up -d --build backend frontend` 通过，三个容器正常运行。
- Report 草稿真实页面验证：
  - 已登录页面点击“本月抖音销售分析（2026-08-01 ~ 2026-08-04）”的“新建会话”后进入 `/analysis/new`，右侧保留 Report，Session 数量不变。
  - 发送“这个 Report 的标题是什么？只回复标题。”后才创建 Session `019fd1cb-1abf-7fa3-aab2-385ff72e6475`，URL 同步为 `/analysis/{session_id}`。
  - 新 Session metadata 包含 `source_report_id=report_4e97b4433252` 和完整 `initial_report_artifact`；首个 Turn 状态为 `completed`，Codex 正确回复 Report 标题。
  - backend 日志显示新链路调用 sessionless `POST /api/analysis/sessions/turns/stream`，没有 `no rollout found`。
- 归档 Session 深链接回归：
  - `npm.cmd test -- tests/analysis-deep-link-route.test.ts`：7 passed。
  - `npm.cmd test`：24 test files、141 tests passed。
  - frontend 容器生产构建与 TypeScript 检查通过，服务进入 Ready。
  - 内置浏览器直接打开 `019fd1bb-9b83-7f03-ae9a-9399ac369a5b` 后地址替换为 `/analysis/new`；连续刷新后归档任务仍未出现在列表，页面显示“当前任务尚无报告”而非“报告加载中”。
- feature 分支及合并后的 `Agentic-GenBI` 全量门禁：
  - `npm.cmd test`：24 test files、141 tests passed。
  - `python -m pytest backend/tests -q -p no:cacheprovider`：194 passed，3 subtests passed。
  - `docker compose config --quiet`：passed。

测试警告：

- 本机 pytest cache 目录无写权限；不影响测试结果。
- Docker CLI 读取 `C:\Users\Jason\.docker\config.json` 无权限；不影响本次 `config` / `build` 结果。

## 尚未处理

1. 跨进程 turn registry
   - V1 已通过单 worker guard 阻断多 worker。
   - 后续如果要支持多 worker，需要 Redis/数据库级 live turn registry 或 reconciliation。

2. FineReport stash
   - 合并前保存了未提交改动：`stash@{0}: wip finereport profile index before session merge`。
   - 该 stash 包含 `docs/plans/current.md` 与 `scripts/finereport/build_profile_index.py` 的后续改动；本轮未恢复，避免污染 Docker 分支。

3. 报表生成仍需登录态页面 smoke
   - 报表 MCP 已在重建后的 backend 容器内通过无持久化 smoke。
   - “已有报表 → 新建会话 → 首条消息引用 Report”已完成登录态页面验证；从新分析生成并首次保存 Report 的完整页面链路仍待单独验证。

4. 本轮 Chrome DevTools MCP 页面验证待补
   - 重建后两次调用 Chrome DevTools MCP 均在连接浏览器时超时；一次等待 60 秒后主动终止，直接 `list_pages` 再次等待 300 秒后超时。
   - 因浏览器控制通道不可用，本轮未把“运行中切换 Session / 停止后立即续问”的真实页面路径标记为已验证；代码回归、TypeScript、容器构建和 HTTP 健康检查均已通过。

5. Session `019fd1a0` 报告保存失败
   - 原始 Codex rollout 中两次 `create_interactive_report` 的完整 artifact 都缺少 `ownerId`。
   - `validate_report_artifact` 未校验 `ownerId`，报告先通过工具校验；`InteractiveReportStore.save_report` 随后按持久化契约拒绝并投影为 `interactive_report_save_failed`。
   - 本轮按范围只定位原因，未修改报告生成或持久化契约。
## 下一步

1. Chrome DevTools MCP 恢复后，补跑“运行中切换 Session → 切回恢复”和“停止 → 立即续问 → 再停止”真实页面路径。
2. 由当前登录用户确认并执行一次性管理员认领后，再用真实管理员态操作用户、MCP、提示词和运行策略。
3. 为无来源会话的 seed Report 补一次“只显示新建会话 → 首条消息引用 Report”的真实页面 smoke。
