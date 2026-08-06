# Agentic GenBI

## 一句话

用户在分析工作台提出业务问题；Codex 负责通用 Agent 工程底座，GenBI 负责业务语义、受控数据访问、Report 和分析资产治理。

## 当前方向

```text
分析工作台：提出问题、追问、查看过程、生成和修改当前分析结果。
业务语义库：维护 FineReport 语义案例、指标、字段、关联规则和业务知识。
我的分析：查看、复用和分享已保存的 Report。
系统：管理数据源、权限、安全、模型、工具、审计和成本。
```

单一主入口是分析工作台。

## 最终边界

Codex 负责：

- Agent Loop
- Thread
- Turn
- Item
- 上下文与上下文压缩
- 工具调度
- 流式执行事件
- 中断和追加指令
- Sandbox / Approval
- 失败、重试和内部请求尝试

GenBI 负责：

- 用户和租户
- 数据权限
- 数据源
- FineReport 语义案例
- 指标与关联规则
- 受控 SQL 工具
- Report
- 可复用分析资产及其治理
- 分享、发布和治理

## 目标架构

```text
交互层：统一分析工作台
Codex：Agent Loop / Thread / Turn / Item / 上下文 / 工具调度 / 事件流
语义层：业务语义库，包含 FineReport 语义案例、指标和业务知识
数据层：只读、安全、可审计地访问 MySQL、Doris、报表、ETL、金蝶等数据源
Report 层：单记录保存布局、筛选、图表、表格和查询配置
分析资产层：保存 SQL、数据快照、分析路径和 SKILL.md 等可复用资产
治理层：RBAC / RLS、敏感字段、审批、发布、审计、成本和运行安全边界
```

MiniMax、OpenAI-compatible 或其他模型只是 Codex 的 model adapter，不是系统架构本身。能用 Codex 的能力，就不在 GenBI 里重复实现。

## 当前实现快照

- 前端：Next.js + TypeScript。分析工作台提供左侧分析线程和右侧 Report；Puck 管布局、Ant Design 管筛选、ECharts 管图表、VTable 管表格。
- 后端：FastAPI。Report 直接保存为当前单记录，不做版本管理；查询配置保存只读 SQL 和筛选参数绑定，数据由后端按需执行并分页返回。list 明细表可通过 `exportColumns` 显式开启同步 Excel 导出。
- 登录：Auth.js + 飞书 OAuth + PostgreSQL session。
- 运行：Docker Compose 启动 frontend、backend、postgres。
- 待完成：完整业务语义库持久化、团队权限/RLS、生产数据源治理和更复杂的 Report 联动能力。

详细状态看 `docs/plans/current.md`，不要从历史段落推断当前完成度。

## 本地运行

Windows 推荐使用启动脚本，它会先确认 Docker daemon 可用，再启动 compose 并检查前后端健康状态：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-services.ps1
```

需要重建镜像或强制重建容器时：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-services.ps1 -Build -ForceRecreate
```

直接使用 Docker Compose：

```bash
docker compose up -d --build
```

访问：

```text
frontend: http://localhost:3000 或 http://192.168.101.12:3000
backend:  http://localhost:8000 或 http://192.168.101.12:8000
health:   http://192.168.101.12:8000/health
runtime:  http://192.168.101.12:8000/api/runtime/status
```

前端开发：

```bash
cd frontend
npm install
npm run dev
```

## 常用配置

项目根目录 `.env`：

```bash
NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME=backend
GENBI_PUBLIC_API_BASE_URL=http://192.168.101.12:8000

GENBI_ANALYSIS_RUNTIME=codex
GENBI_MCP_ENCRYPTION_KEY=replace-with-a-long-random-key
```

模型连接和 API Key 由“系统管理 → 模型连接”维护并加密保存到 PostgreSQL。模型相关 env 仅用于首次引导或应急回退，数据库已有默认连接后可以移除；`GENBI_MCP_ENCRYPTION_KEY` 必须长期保持不变，否则已保存的模型与 MCP 密钥无法解密。

修改 `.env` 后，`docker compose restart` 不一定重新注入变量；需要：

```bash
docker compose up -d --force-recreate --no-deps backend
```

## 验证

```bash
cd frontend
npm.cmd test
npm.cmd run build

python -m pytest backend/tests -q -p no:cacheprovider
docker compose config
```

## 文档入口

- `AGENTS.md`：协作规则。
- `docs/product/product-scope.md`：产品边界。
- `docs/architecture/overview.md`：架构边界。
- `docs/plans/current.md`：当前分支状态。

文档只保留能帮助继续做事的信息；历史过程交给 Git。
