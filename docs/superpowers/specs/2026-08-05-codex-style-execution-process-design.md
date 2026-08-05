# Codex 风格执行过程展示设计

## 背景

分析任务已经通过 Codex SDK 流式执行，但 GenBI 当前只转发少数通知：

- `turn/started`
- `item/agentMessage/delta`
- `item/completed`
- `turn/completed`

Codex SDK 同时提供 `item/reasoning/summaryTextDelta`、`item/started` 等通知。当前适配器忽略这些通知，因此模型仍在连续处理时，前端往往只能显示静态的“思考中”。

目标体验参考 Codex 客户端：中间说明、工具活动和最终回复按照真实发生顺序留在同一个执行过程里，而不是用一条状态文案轮播替换。

## 目标

- 实时展示模型实际返回的 reasoning summary。
- 中间说明、工具活动、最终回复按照事件顺序交错展示。
- 流式小片段在同一个条目内累积，不产生逐字消息或重复回复。
- 执行期间过程自动展开；完成后显示总耗时并默认折叠。
- 刷新后可从已保存的 Turn 和 Item 恢复过程。
- 工具活动只显示安全名称、状态和耗时，不展示参数、SQL 或结果明细。

## 非目标

- 不展示 `item/reasoning/textDelta` 原始隐藏推理。
- 不展示系统提示词、开发者指令、鉴权信息或 Provider 原始协议包。
- 不由前端根据工具名称猜测业务阶段。
- 不调整 Thread、Turn、Item 生命周期契约。
- 不新增 `turn/failed`、`item/failed` 等非原生终态事件。

## 事件契约

### Reasoning summary

后端转发 Codex 原生通知：

```text
item/reasoning/summaryTextDelta
```

GenBI 事件负载只保留：

```text
session_id
turn_id
codex_session_id
codex_turn_id
codex_item_id
summary_index
delta
codex_method
codex_item_type = reasoning
```

前端以 `(turn_id, codex_item_id, summary_index)` 作为稳定键，将 delta 累积为一个过程说明条目。

### Item 生命周期

后端补充转发：

```text
item/started
item/completed
```

对于 `mcpToolCall`，前端创建或更新同一个工具活动条目：

```text
started   → running
completed → done / failed
```

可见内容仅包括安全工具标签、状态和可计算耗时。参数、SQL、结果和错误原文不进入浏览器事件；失败只显示统一错误说明。

### Agent message 与 Turn 终态

继续使用现有契约：

```text
item/agentMessage/delta
item/completed (agentMessage)
turn/completed
```

`turn/completed` 仍是唯一 Turn 终态。GenBI 不补发第二个同名完成事件。

## 后端数据流

```text
MiniMax Responses
→ Codex app-server
→ openai-codex Notification
→ CodexSdkAnalysisRuntime._notification_to_event()
→ CodexTurnRunner enrich + projection
→ SSE
→ Frontend mapBackendEvents()
```

`CodexSdkAnalysisRuntime` 负责严格区分：

- reasoning summary：可展示并转发。
- reasoning text：忽略。
- agent message：按现有方式转发。
- tool item：只投影安全活动字段。
- 未知通知：忽略并保留可观测日志，不向前端透传原始负载。

Reasoning Item 完成时，优先从 Item 的 `summary` 字段保存最终文本。增量通知只负责实时展示，完成 Item 负责持久化与刷新恢复。

## 前端模型与交互

一个 Agent Turn 节点维护有序活动列表：

```text
reasoning-summary
tool
agent-message
```

渲染结构：

```text
分析了 1分36秒  [展开/折叠]
  中间说明
  工具活动
  中间说明
  工具活动

最终回复
```

行为规则：

- 执行中自动展开，新增内容追加到尾部。
- reasoning delta 只更新对应说明条目，不新增重复条目。
- 同一工具 Item 的 started/completed 更新同一行。
- 过程区和最终回复分开，最终回复不会被过程内容覆盖。
- Turn 完成后记录耗时并默认折叠。
- 用户手动展开或折叠后，本次页面生命周期内尊重用户选择。
- 没有任何过程通知时保留现有“思考中”作为最低兜底；收到第一条过程通知后立即替换。

## 历史恢复

- Reasoning 完成 Item 保存 summary 文本和 sequence。
- Tool Item 保存安全名称、状态、起止时间和 sequence。
- Session 详情按 sequence 恢复活动顺序。
- 实时 delta 不单独持久化，避免碎片记录；异常中断时允许只恢复最后已完成的 Item。

## 错误与降级

- SDK 没有 reasoning summary：不伪造中间说明。
- 只有 reasoning text：不展示隐藏推理，继续显示“思考中”兜底。
- 工具失败：工具行显示失败，Turn 是否继续由后续原生事件决定。
- SSE 中断：停止运行态动画并显示连接中断错误。
- 重复 completed/delta：按稳定键和最终文本去重。
- 刷新恢复缺少 started 时间：展示活动顺序，不展示不可靠耗时。

## 测试

### 后端

- reasoning summary delta 被正确映射。
- reasoning text delta 被忽略。
- reasoning completed Item 保存 summary。
- item started/completed 使用同一个 Item ID。
- 工具参数、SQL 和结果不会进入前端事件。
- `turn/completed` 只出现一次。

### 前端

- summary delta 合并到同一条活动。
- 多个 summary 和工具 Item 按顺序交错。
- tool started/completed 更新同一行。
- 最终 Agent Message 与过程区分开。
- 完成后过程默认折叠且显示耗时。
- 历史恢复不产生重复消息。

### 端到端

- 使用 Chrome 提交真实分析问题。
- 确认等待期间出现 MiniMax/Codex reasoning summary。
- 确认工具活动不泄露参数、SQL 或结果。
- 确认最终回复只显示一次。
- 刷新后确认过程与最终回复均可恢复。
