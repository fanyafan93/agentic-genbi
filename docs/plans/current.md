# 当前任务

更新时间：2026-08-03 Asia/Shanghai

本页只记录当前可验证状态。历史过程交给 Git。

## 切片：Codex CLI 容器内安装 + SDK 注入 MCP 配置

分支：`feature/codex-sdk-mcp-config`（基于 `Agentic-GenBI`）。

### 本轮要做

- A. `backend/Dockerfile` 安装 codex CLI，使容器内可启动 Codex 子进程。
- B. `CodexSdkAnalysisRuntime._config_overrides` 从 `.env` 读 MCP server 配置并生成 TOML 覆盖串，注入到 CodexConfig。
- C. `.env.example` 加 `GENBI_CODEX_MCP_<N>_*` 示例（不填真实密码）。
- D. 单测覆盖 `_config_overrides` 在 MCP 配置存在时正确生成 TOML。
- E. `docker compose config` 通过；`python -m unittest discover backend\tests -v` 全绿。

### 切片边界

- 只动 codex CLI 安装 + MCP 配置注入，不重写 CodexSdkAnalysisRuntime 的事件流。
- MCP 配置从 `.env` 读，**不**依赖容器内 `~/.codex/config.toml`，**不**依赖宿主机配置。
- `GENBI_CODEX_MCP_*` 的解析失败（缺字段 / 数量不匹配）只发 warning 日志，不阻塞 runtime 启动。

### 待验证假设

- Codex 进程支持通过 `CodexConfig.config_overrides` 注入 `mcp_servers.*` 配置（基于 SDK 0.144.4 的 schema dump）。
- `npx -y @benborla29/mcp-server-mysql` 在容器内可用（要求容器能访问 npm registry）。

## 当前状态

- 分支：`feature/async-analysis-create-path`。
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
- 修复非流式 create 路径的 event loop 风险：`POST /api/analysis/threads/turns` 和 `POST /api/analysis/threads/{thread_id}/turns` 改为 async 路由，并统一走 `async_stream`。
- 补充 async 测试，验证已有 event loop 中创建分析 Turn 时不会调用同步 `stream()`。

## 本轮验证

- `python -m unittest discover backend\tests -v`：40 个测试通过。
- `npm.cmd test`（frontend）：52 个测试通过。
- `npx.cmd tsc --noEmit --pretty false`（frontend）：通过。
- `npm.cmd run build`（frontend）：通过。
- `docker compose config`：通过；存在 Docker 用户 config 权限 warning。

## 工作区状态

- 工作区包含 `feature/async-analysis-create-path` 分支上的 async create 路径修复。
- `AGENTS.md` 有一处用户已有的未提交改动，本轮未修改、未回退。

## 风险 / 未完成

- 本轮没有新增报告生成工具。右侧报告面板仍需等待真实注册的 Codex 工具产出 interactive-report Artifact。
- 生产数据访问、RLS、分享、发布和完整 Artifact 治理仍未完成。
- 真实配置 Codex provider 后的浏览器/SSE 实测仍待验证。

## 下一步

1. 仅在 GenBI 业务工具契约准备好后，通过 Codex 注册受控业务工具。
2. 继续补生产数据访问、RLS、分享、发布和治理切片。
3. 使用真实 Codex provider 验证一次 live SSE turn，确认 UI 按 Codex Item 事件增量渲染。

---

## 切片收尾：`feature/codex-sdk-mcp-config`

更新时间：2026-08-03 Asia/Shanghai

### 本轮完成

- `backend/Dockerfile` 增加 Node.js 20.x 和 `@openai/codex` 全局安装步骤，后端容器内可直接启动 codex CLI 子进程。
- 新增 `backend/harness/codex_mcp_config.py`，从 `GENBI_CODEX_MCP_<N>_*` 环境变量解析 MCP server 条目，并转换为 CodexConfig.config_overrides 的 TOML 字符串列表。
- `CodexSdkAnalysisRuntime._config_overrides` 现在附加 MCP server TOML 覆盖串，与原有 `model_providers.*` 配置共存。
- `.env.example` 增加 `GENBI_CODEX_MCP_*` 五行一组的标准格式说明（不填真实密码）。
- 新增 `backend/tests/test_codex_mcp_config.py`，覆盖：环境变量解析、空值/无效值跳过、TOML 转义、`openai` provider 也会输出 MCP 覆盖串。

### 本轮验证

- `python -m unittest discover backend\tests -v`：51 个测试通过（含 11 个新增 MCP 测试）。
- `docker compose config`：通过；环境变量绑定和 volume 挂载未变。

### 工作区状态

- 分支：`feature/codex-sdk-mcp-config`（基于 `Agentic-GenBI`）。
- 修改文件：`backend/Dockerfile`、`backend/harness/codex_sdk_runner.py`、`.env.example`、`docs/plans/current.md`。
- 新增文件：`backend/harness/codex_mcp_config.py`、`backend/tests/test_codex_mcp_config.py`。
- 未提交到任何环境；等待合入 `Agentic-GenBI`。

### 风险 / 未完成

- 待验证假设 1（Codex SDK 0.144.4 接受 `mcp_servers.*` 形式的 `config_overrides`）：基于 SDK schema dump 和当前版本的 Codex CLI 0.146.0 推断，**未在容器内实测**。
- 待验证假设 2（`npx -y @benborla29/mcp-server-mysql` 在容器内能跑通）：依赖容器能访问 npm registry + `8.134.63.30:9030`。
- `.env` 还没填 `GENBI_CODEX_MCP_*`；需要部署方手动补齐真实密码后才能让 Codex 调起 BI_doris。
- 业务层"保存报告"的 MCP tool 还没做：Codex 推理后如何把数据交给 GenBI 落库 + 推 SSE 仍然是未完。

### 下一步

1. 在部署环境把 `GENBI_CODEX_MCP_*` 写入 `.env`，跑一次 `docker compose up -d --build`。
2. 触发一次最小问题（"查 dm.dm_channel_mtsg_sale_total 2026-07 各渠道销售额"），观察 Codex 是否真的调起 BI_doris MCP。
3. 实测成功后，规划下一步"GenBI 业务 MCP server（保存报告 tool）"切片。

---

## 切片收尾：`feature/upgrade-openai-codex`

更新时间：2026-08-03 Asia/Shanghai

### 本轮完成

- 引入 `GENBI_CODEX_BIN` 环境变量：`CodexSdkAnalysisRuntime` 接收 `codex_bin` 参数并传给 `CodexConfig.codex_bin`，让 SDK 启动时用全局 0.146.0 codex CLI 而不是 SDK 内置的 0.144.4 二进制。
- 引入 `GENBI_CODEX_HOME` 环境变量：`CodexSdkAnalysisRuntime.__init__` 在启动时把 provider + MCP 配置渲染到 `$GENBI_CODEX_HOME/config.toml`，并通过 `CodexConfig.env={"CODEX_HOME": ...}` 让 Codex 子进程读这个文件，绕开 SDK `config_overrides` 注入对 0.144.4/0.146.0 行为不一致的问题。
- `Dockerfile` 增加 `ln -s /usr/local/lib/nodejs/bin/codex /usr/local/bin/codex` 让 `codex` 在 PATH 上稳定可用。
- 重写 `CODEX_ANALYSIS_INSTRUCTIONS` developer prompt：明确 BI_doris MCP 工具、销售/财务管报表 schema、强制真实数据查询。
- `.env` / `.env.example` 增加 `GENBI_CODEX_BIN` / `GENBI_CODEX_HOME` / `GENBI_CODEX_PROVIDER` / `GENBI_CODEX_BASE_URL` / `GENBI_CODEX_API_KEY` / `GENBI_CODEX_MODEL` 配套配置。
- 新增 `codex_bin` / `codex_home` / `provider+mcp` 渲染三个测试用例（共 5 个新测试）。

### 本轮验证

- `python -m unittest discover backend\tests -v`：55 个测试通过。
- `docker compose config`：通过。
- 容器内 `codex --version`：返回 `codex-cli 0.146.0`（之前是 SDK 内置 0.144.4）。
- SSE 端到端 turn：
  - Codex 启动 minimax provider（**不再 401**，配置生效）。
  - Codex 在 item 事件里发起 **5 次 mcpToolCall + 1 次 commandExecution**（启动 MCP server）。
  - Codex 输出端到端 SSE 流式响应（28+ delta 事件 + 完整 item/completed）。
- MCP server 启动 handshake 失败（`MCP server 'BI_doris' was not ready for this step`），需要预热 / 重试。

### 工作区状态

- 分支：`feature/upgrade-openai-codex`（基于 `feature/codex-sdk-mcp-config`）。
- 修改文件：`backend/Dockerfile`、`backend/harness/codex_sdk_runner.py`、`.env`、`.env.example`、`backend/tests/test_codex_mcp_config.py`、`docs/plans/current.md`。
- 未提交到任何环境；等待合入 `Agentic-GenBI`。

### 风险 / 未完成

- MCP server handshake 失败：npx 第一次启动需要下载 `@benborla29/mcp-server-mysql`，Codex 0.146.0 等不到 ready 就放弃。需要后端预热（启动时 `npx -y ... &`）或 Codex 端加 timeout。
- `CODEX_HOME` 路径 `/tmp/codex-home` 在容器里**每次重启会丢**——实际部署应该挂载到 volume 或写到 `/app/.codex-home`。
- 真实数据查询还没成功（"BI_doris was not ready"）——还需要一次实测，确认 Codex 调用 MCP 后能拿到真数据。
- `.env` 仍然含真实密码 `liran@2026` / `MINIMAX_API_KEY`，没移出 git 控制（之前 commit 没把这些行删过）。

### 下一步

1. 给后端加 MCP 预热钩子：在 Codex runtime 第一次实例化前 spawn `npx -y @benborla29/mcp-server-mysql` 等它 ready 再继续。
2. 把 `GENBI_CODEX_HOME` 从 `/tmp/codex-home` 改到挂载卷（如 `/app/.codex-home`），避免重启丢配置。
3. 真实数据 turn 端到端验证：Codex 拿到查询结果 → 后端落库 → 前端渲染报告。
4. 把 `.env` 真实密钥行从 git 历史里清除（用 git filter-repo 或重新 commit 一版不带密钥的 .env）。

---

## 切片收尾：`feature/upgrade-openai-codex`（续 / MCP 预热）

更新时间：2026-08-03 Asia/Shanghai

### 本轮完成

- `backend/Dockerfile` 增加 `npm install -g @benborla29/mcp-server-mysql@latest`，把 MCP server 包**预下载到镜像全局 node_modules**——容器启动后 `npx --no-install` 直接从本地找包，跳过网络下载。
- 改写 `CODEX_ANALYSIS_INSTRUCTIONS` prompt：明确 BI_doris MCP 服务的工具名为 **`mysql_query`（不带前缀）**，参数 schema `{"sql": "..."}`。
- 探测脚本 `probe_mcp_tools.py`：通过 stdio JSON-RPC 直接调 `@benborla29/mcp-server-mysql`，确认 `tools/list` 返回 `[{name: "mysql_query", inputSchema: {sql: string}}]`。

### 本轮验证

- `python -m unittest discover backend\tests -v`：55 个测试通过（prompt 改动未引入新失败）。
- 容器内 `npx --no-install @benborla29/mcp-server-mysql`：可启动，`tools/list` 返回 `mysql_query`。
- SSE 端到端 turn：
  - Codex **收到 MCP server ready 信号**（不再是 "was not ready"）→ 主动调用 `mcp__BI_doris__mysql_query` 5 次。
  - 但 MCP server 返回 `unsupported call: mcp__BI_doris__mysql_query`——**Codex LLM 自动加 `mcp__` 前缀**，但 `@benborla29/mcp-server-mysql` 只接受裸 `mysql_query` 名字。
  - Codex 自身 fallback：在 sandbox 里写 SQL 文件 → 用 `mysql` 客户端直连 `8.134.63.30:9030` 跑 SQL（**实际拿到数据**），后端日志看到 `path: queries/quick_candidate.sql`。
- 后端落库时报 `psycopg.errors.NotNullViolation: null value in column "run_id" of relation "analysis_items"`——Codex 0.146.0 的 commandExecution item 没把 `run_id` 放在 schema 期望的顶层字段。

### 工作区状态

- 分支：`feature/upgrade-openai-codex`（未提交，等 review）。
- 修改：`backend/Dockerfile`、`backend/harness/codex_sdk_runner.py`、`docs/plans/current.md`。

### 风险 / 未完成

- Codex LLM 加 `mcp__BI_doris__` 前缀的命名习惯改不掉——`@benborla29/mcp-server-mysql` 注册的工具名是裸 `mysql_query`，不识别前缀。这是 Codex 0.146.0 + 当前 LLM 训练行为决定的，**没法从 prompt 改**。
- 真要 "MCP 路径成功" 需要：(a) 找接受前缀的 MCP server 包；或 (b) 写自定义 MCP server 把工具名注册成 `mcp__BI_doris__mysql_query`；或 (c) 升级到 Codex 0.147+ 看是否解决了 LLM 命名。
- Codex 自己用 sandbox 跑 mysql 客户端**绕过了 MCP**——这条路径**能拿到数据**但没走 RLS / 受控数据访问的边界，违反 AGENTS.md "数据访问必须受控" 的精神。
- 后端 `analysis_items.run_id` 非空约束在 Codex 0.146.0 item 形态下被违反——后端写入逻辑需要兼容 "没有 run_id 的 mcpToolCall / commandExecution item"。

### 下一步

1. **绕过 MCP 命名不匹配**：写 GenBI 自己的 MCP server（暴露 `mcp__BI_doris__mysql_query` 这个名字的工具，转发到 `@benborla29/mcp-server-mysql`）。这是干净的"工具别名转发"模式，但需要新起切片。
2. **接受 sandbox 路径**（短期）：放宽 `sandbox` 设置让 Codex 跑 `mysql` client，加审计（Codex 跑的每条 SQL 进 `analysis_items`），作为过渡方案。
3. **修后端 item 写入**：让 `_codex_item_projections_from_events` / `_items_from_events` 兼容缺 `run_id` 的 item（设为 NULL 或自动生成）。
4. 拆 commit：本切片累计 5 个文件改动，按 "Dockerfile / SDK 注入 / prompt / 测试 / docs" 拆 5 个 commit。

---

## 切片收尾：`feature/genbi-mcp-server-alias`

更新时间：2026-08-03 Asia/Shanghai

### 本轮要做

- 新增 `backend/harness/genbi_mcp_server.py`：stdio MCP server，暴露工具 `mcp__BI_doris__mysql_query`，参数 `{"sql": "..."}`，内部转发到 `@benborla29/mcp-server-mysql` 子进程（stdio JSON-RPC）。
- 启动该 server 时把 `@benborla29` 的子进程启动、握手、转交请求。
- SDK 层把用户配置的 `BI_doris` 原始 MCP server 自动包装成 GenBI alias server：实际启动 `python -m backend.harness.genbi_mcp_server`，把原 command/args/env 转成 `GENBI_MCP_DOWNSTREAM_*` 环境变量下发。

### 切片边界

- 只做工具名映射 + stdio 透明转发，不新增 SQL 校验、不改 RLS、不改 Artifact 落库逻辑。
- 包装策略保持原有 server name 不变（仍是 `BI_doris`），Codex LLM 继续发出 `mcp__BI_doris__mysql_query`，由 GenBI alias server 在本地剥离前缀再转下游。
- 非 MySQL 型 MCP server（如 filesystem、openmetadata）原样透传，不走 alias 代理。

### 本轮完成

- `backend/harness/genbi_mcp_server.py`：
  - 单文件 stdio MCP server。暴露工具名 `mcp__BI_doris__mysql_query`（由 `GENBI_MCP_SERVER_NAME` 控制）。
  - 支持 `initialize` / `notifications/initialized` / `tools/list` / `tools/call` 四个必需方法。
  - `DownstreamClient` 管理 `@benborla29/mcp-server-mysql` 子进程生命周期（stdio JSON-RPC）。
  - `_resolve_downstream_command` 同时接受空格分隔和 JSON-array 两种 args 格式。
- `backend/harness/codex_mcp_config.py`：
  - 新增 `_is_mysql_mcp_server` / `wrap_server_with_genbi_alias` / `apply_genbi_alias_wrapping` 三函数。
  - 自动识别 `BI_doris` 名称或 `@benborla29/mcp-server-mysql` 参数的 server，改写为 `python -m backend.harness.genbi_mcp_server` 启动，原始配置全部打包进 `GENBI_MCP_SERVER_NAME` / `GENBI_MCP_DOWNSTREAM_COMMAND` / `GENBI_MCP_DOWNSTREAM_ARGS` / `GENBI_MCP_DOWNSTREAM_ENV_*` 环境变量。
- `backend/harness/codex_sdk_runner.py`：
  - `_config_overrides()` 和 `__init__` 中渲染 `$CODEX_HOME/config.toml` 的两处都改成先 `apply_genbi_alias_wrapping(raw_mcp_servers)`。
  - `CODEX_ANALYSIS_INSTRUCTIONS` 不变（LLM 仍按 `mysql_query(sql=...)` 思路推理，alias 层处理命名不匹配）。

### 本轮验证

- `python -m unittest discover backend\tests -v`：**67 个测试全绿**（新增 6 个 alias wrapping / integration 测试；另有 8 个原有 genbi_mcp_server 测试）。
- `docker compose config`：**通过**。
- 单测覆盖内容：
  - alias server `tools/list` 正确返回带前缀工具名。
  - `tools/call` 转发时把 `mcp__BI_doris__mysql_query` 剥为 `mysql_query`，response id 用上游请求的 id。
  - `wrap_server_with_genbi_alias` 保留原 server name，command 换 Python 模块，env 生成 GENBI_MCP_* 前缀。
  - `apply_genbi_alias_wrapping` 让 filesystem/openmetadata 等其他 MCP 透传。
  - `CodexSdkAnalysisRuntime._config_overrides` 输出的 TOML 不再包含 `npx` command，替换成 alias Python command + GENBI_MCP_* env。
  - `$GENBI_CODEX_HOME/config.toml` 渲染结果也是 alias 包装后的配置。

### 工作区状态

- 分支：`feature/genbi-mcp-server-alias`。
- 修改文件：`backend/harness/genbi_mcp_server.py`、`backend/harness/codex_mcp_config.py`、`backend/harness/codex_sdk_runner.py`、`backend/tests/test_genbi_mcp_server.py`、`backend/tests/test_codex_mcp_config.py`、`docs/plans/current.md`。
- 未提交到任何环境；等待合入 `Agentic-GenBI`。

### 风险 / 未完成

- **Codex SSE turn 跑通但 LLM 端持续被 provider 限流**：5 次连续 turn，每次都是 userMessage item 30 秒后 `We're currently experiencing high demand` / `429 Too Many Requests`（最新一次换了新 `MINIMAX_API_KEY` 后仍然命中限流）。这是 provider 上游问题，跟 alias 链路无关。
- alias server stdio 单链路已**端到端真拿到数据**（见本节新加的"端到端验证"块）——剩下 Codex LLM 调用 alias 这一步要等 provider 限流恢复或切其他 provider。
- 后端 `analysis_items.run_id` 非空约束问题（Codex 0.146.0 的 mcpToolCall / commandExecution item 不总带 `run_id`）仍然未修——这是前一切片遗留问题，不阻塞 MCP 链路，但会在 Codex fallback 到 sandbox mysql 客户端的写入路径上触发。
- Windows 上 `python -m backend.harness.genbi_mcp_server` 依赖正确的工作目录（`backend/` 作为包）——容器内 `/app` 工作目录正确；但本机纯交互调试时可能需要手动 `cd` 到仓库根。

### 端到端验证（已通过）

容器内直起 GenBI alias server stdio，模拟 Codex LLM 发出的请求（带 `mcp__BI_doris__` 前缀的工具名）：

```
[probe] step 1: initialize
init_resp: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"genbi-mcp-alias","version":"0.1.0"}}}

[probe] step 2: tools/list
tools_list_resp: ... {"name":"mcp__BI_doris__mysql_query","description":"Run a read-only SQL query against the GenBI business database. Forwarded to the @benborla29/mcp-server-mysql MCP server.","inputSchema":{"type":"object","properties":{"sql":{...}},"required":["sql"]}, ...}

[probe] step 3: tools/call (real DB query)
tools_call_resp: {"jsonrpc":"2.0","id":4,"result":{"content":[
  {"type":"text","text":"[
    {\"vmonth_code\":\"2026-07\",\"vchannel_name\":\"屈原氏\",\"nsales_amt\":\"4552.4000\"},
    {\"vmonth_code\":\"2026-07\",\"vchannel_name\":\"屈原氏\",\"nsales_amt\":\"4193.0000\"},
    {\"vmonth_code\":\"2026-07\",\"vchannel_name\":\"屈原氏\",\"nsales_amt\":\"3653.9000\"},
    {\"vmonth_code\":\"2026-07\",\"vchannel_name\":\"屈原氏\",\"nsales_amt\":\"3474.2000\"},
    {\"vmonth_code\":\"2026-07\",\"vchannel_name\":\"屈原氏\",\"nsales_amt\":\"3354.4000\"}
  ]"},
  {"type":"text","text":"Query execution time: 170.43 ms"}
],"isError":false}}
```

链路：`stdio client (模拟 Codex) → GenBI alias server → @benborla29/mcp-server-mysql → Doris 8.134.63.30:9030 → 真实数据 ✅`。alias 层只做"剥前缀 + 转交"。

### 下一步

1. **Codex 完整 turn**：等 MiniMax provider 限流恢复（或换 OpenAI）后，再触发一次分析 turn，确认 Codex LLM 通过 alias server 拿到数据并写入 `analysis_items`。
2. **修 `analysis_items.run_id` 非空**：让 item 投影层允许 `run_id=NULL` 或在 mcpToolCall/commandExecution 缺该字段时生成占位值。
3. 规划"GenBI 业务 MCP server（保存报告 tool）"切片：把 Codex 产出的报告数据通过受控 MCP tool 落库，不依赖 sandbox 写文件。
4. `.env` 真实密钥清出 git 历史：用 git filter-repo 或重 commit 一版不带 `liran@2026` / `MINIMAX_API_KEY` 的 `.env`。
