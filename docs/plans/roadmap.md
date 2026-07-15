# 长远路线图（Post-MVP）

> 与 `current.md` 不重不冲突。`current.md` 记录 MVP 实施阶段，
> `roadmap.md` 记录 MVP 跑通之后的下一波投入方向以及明确**不该**
> 做的事。文件可随公司战略调整，每季度复核一次。
>
> 复盘基准：[handoffs/latest.md 的"INVALID_REPORT 双轮修复"章节](../handoffs/latest.md)
> —— MVP v0.1.0 的主线任务（动态 SQL Agent + 硬边界 + 步骤
> finished_at + watchdog + 跨 schema 通配）已在 `9a82f78` 端到端跑通。

## 当前状态

MVP 跑通以下能力：

| 维度 | 已经能跑 |
| --- | --- |
| 自然语言 → 只读 SQL | ✅ 5 题验收 3 题 succeeded，2 题语义化失败 |
| 跨 schema 通配 | ✅ `dm.*` / `dw.*` 元数据解 |
| 硬边界（硬边界取代 LLM 自决） | ✅ `MAX_SQL_RETRIES=2` + `MAX_TOOL_CALLS=12` + `fail_fast` |
| Watchdog（任务总时长） | ✅ `TASK_TIMEOUT_SECONDS=90` 默认 |
| 步骤事件（前置 + 后置） | ✅ 每个 step 必带 `finished_at` |
| 前端步骤 UI | ✅ TaskStatus 卡片 + 中文状态标签 |
| 验收 / e2e / 外部只读 MySQL | ✅ pytest 89 / 2 / 5 题 / 外部库集成 |
| INVALID_REPORT detail 透传 | ✅ runner + coordinator 双 raise 都带 `Detail:` |

**MVP 不该再“补洞”**；下面这些是**下一步**。

## 为什么我们要克制

1. **MVP 的护城河是“只读、安全、确定”**，任何把 Agent 推向“写权 / 自由执行
   / 任意代码”的改动都是自毁城墙。所以路线图**主动排除**了几个常见 wishful 想法。
2. **新功能必须保证 60 天内能跑通、上线、被使用**。盲目开 15 个并行分支就是
   什么都不会推进。
3. **每条都要准一个"何时做不了"的退路**——比如向量库方案如果 60 天实验不达
   标应该扔掉而不是再添新分支。

## 阶段 1：**让 MVP 产生可分享的输出**（1–2 月，目标：商业化出头）

| 序号 | 特性 | 工作量 | 文件落点 | 完成定义 |
| --- | --- | --- | --- | --- |
| 1.1 | **PDF 导出** | 1–2 周 | `backend/app/services/pdf_renderer.py`（新）+ `app/api/analysis_tasks.py` 加 `GET .../pdf` | 点按钮能在 10 秒内拿到含图表与表格的 PDF |
| 1.2 | **仪表板编辑器** | 2–4 周 | `frontend/src/features/dashboard/` + `backend/app/api/dashboards.py` + `app/services/dashboards/`（新目录） | 用户能拖拽多张分析报告到一个 dashboard，访客能匿名看，URL 能分享 |
| 1.3 | **定时任务** | 1–2 周 | 引入 APScheduler（不是 Celery），跑现有 `analysis_tasks` API + 加 `app/services/scheduler.py` + `app/api/schedules.py` | 用户能配置每日 / 每周的某个问题，报告自动寄送邮件 |

**为什么这个排第一位**：这三个都是**拿出能交付的能力**而不动摇现有架构，
收钱信号最强，可以同时塞进当前 docker-compose 仓库。

## 阶段 2：**让数据源与运行时隔离**（2–4 月，目标：可几台服务器部署）

| 序号 | 特性 | 工作量 | 文件落点 | 完成定义 |
| --- | --- | --- | --- | --- |
| 2.1 | **多数据库支持** | 2–4 周 | `backend/app/database/adapters/`（新目录，Postgres / ClickHouse / StarRocks 各一个 adapter），只读 schema discovery | 选择一个 schema，所有只读查询都能跨库走 metadata abstraction |
| 2.2 | **向量数据库** 混合检索 | 2–4 周 | `backend/app/database/vector.py`（新），存储 `metadata.text_embeddings` 用于选择候选 table；不代替 SQL，只裁减可选范围 | 1k 个表的库，list_tables 首次返回耗时降至 5 秒以内部可接受范围 |
| 2.3 | **Redis 缓存** | 1–2 周 | `backend/app/cache/`（新），热表 schema / hot result cache；老补 `Config.get_redis` | 同一问题 5 分钟内第二次查询走 cache |
| 2.4 | **Celery 任务队列** | 2–4 周 | `backend/app/worker/`（新）+ `docker-compose.worker.yml`，与当前 fastapi 进程可并行升级 | 可以不担心单进程 OOM，重负载下 0.5 秒起 task state 已同步到硬盘 |

**为什么顺序**：多数据库 → 隔离合约 → 缓存 → 队列。这四步中任何两步换序只会增加
重写面。

## 阶段 3：**智能维度提升**（3–6 月，目标：开始反统 LLM-as-a-judge 产品）

| 序号 | 特性 | 工作量 | 文件落点 | 完成定义 |
| --- | --- | --- | --- | --- |
| 3.1 | **多 Agent**（1 个 supervisor + N 个 expert） | 4–8 周 | `backend/app/agents/multi/`（新），复用现有 `ApprovedAnalysisTools`。专家可以是别的领域的 LLM e.g. financial / ops | supervisor 能驱动至少 2 个专家（schema、SQL 修复、chart 选择）；每个专家可独立关闭 |
| 3.2 | **LangGraph 编排** | 4–8 周 | 可与 3.1 合并写：动态 DAG 取代手写 LLM tool loop，引入 `langgraph` 依赖。`backend/app/agents/graph.py` | 业务逻辑（含带 above 11 项步骤生命周期）移到 DAG；能在 LangGraph Studio 可视化重现 |
| 3.3 | **WrenAI** 集成 | 4–8 周 | `backend/app/agents/wrenai_client.py`（新），WrenAI SQL generator + 你现在的 dynamic agent = Plan-B | WrenAI 为首选生成器，DynamicAgent 作为修复闭环 |

**风险**：3.1/3.2 会重写 12ba23f 那部分动态协调器。开始前需冻上一版 `v0.2.0`
tag 让快金户走 fallback。

## 阶段 4：**主动不自动化**（这些不是规划，是产品边界）

下面这些是**严禁**在任何 roadmap 里以"该项需完成"出现。理由是
他们会交出 MVP 遗留下来的产品护城河：

| 议题 | 为什么不能动 | 替代路线 |
| --- | --- | --- |
| **自动修改数据库** | DDL/DML 一旦 Agent 能跑出，安全责任会完全压缩为 LLM 验证 → 不能交 | 仅限"人是最后一步”：Agent 生成 ALTER TABLE语句 -> 人在 UI 看到 DDL -> 人工确认提交；不要默认开 DDL |
| **自由执行任意代码** | LLM-generated shell/python 是 RCE 风险；需要 sandbox + 白名单 + 全审计。MVP 不为 RCE 服务 | 仅能在限定 sandbox 内跑 SQL结果 数据处理；上 RCE 是另一个产品线 |
| **Kubernetes** | 当前是 docker-compose；上 K8s 是不能同时跨个三个阶改造。提前上 K8s 会变成"为了 K8s 而 K8s" | 要等 2.4 Celery 跑完 + 2.1 multi-DB 走完 + 能部署到多台，才考虑 K8s；先上 docker swarm / nomad |
| **完整用户权限系统** | 需要从 schema 到 connection pool 全部重写：每个 query 都要過 authz。MVP 的快速表达会失去 | 先交个简单的 "analyst / viewer" 二种角色够商务交表；后来以 6+月重做 IAM |
| **多租户** | 同上，需要全栈 schema isolation + 数据隔离 + API gateway；不再 MVP 3 阶能变 | 起步理解为"单个租户 + 多个 workspace"，不要上"多租户"那个词。 |

## 阶间隔的设计原则

- 一个阶段之内最多同时开 2 个分支。
- 本阶段任务全部跑通才进入下一阶段。
- 每个阶段都出验收基线（backend integration / e2e / dogfooding），不达标不进入下一阶段。

## 依赖关系（明确）

- **1.3 定时任务**依赖现有 `analysis_tasks` API 已稳定，可以独立起步。
- **阶段 3 需要阶段 2.4 Celery 达到稳态**，否则 supervisor Agent 会连不上 worker。所以阶段 3 不能与阶段 2.4 并行。
- **WrenAI 集成**与前端仪表板呈现需要一起约定 UI。两者并发会增加 UI 重写面，所以优先仪表板（1.2）→ 再 WrenAI（3.3）。

---

最后修改：2026-07-15 Beijing。
