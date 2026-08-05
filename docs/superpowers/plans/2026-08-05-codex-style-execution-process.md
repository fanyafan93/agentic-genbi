# Codex-Style Execution Process Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display Codex/MiniMax reasoning summaries, tool activity, expandable tool details, elapsed time, and the final answer in their real event order without exposing hidden reasoning or credentials.

**Architecture:** Extend the existing Codex SDK adapter instead of inventing a parallel progress protocol. Native reasoning-summary and Item lifecycle notifications are sanitized, projected, streamed through SSE, folded into the existing per-Turn frontend activity model, and restored from persisted Item projections after refresh.

**Tech Stack:** Python 3.12, openai-codex 0.144.4, FastAPI SSE, unittest/pytest, TypeScript 5.9, React 19, Next.js 16, Vitest, Testing Library, Docker Compose.

## Global Constraints

- `turn/completed` remains the only Turn terminal lifecycle event.
- Never create `turn/failed` or `item/failed`.
- Display `item/reasoning/summaryTextDelta`; never display `item/reasoning/textDelta`.
- Tool details may include commands, parameters, SQL, outputs, results, and errors.
- Credentials must be redacted on the backend before persistence or SSE delivery.
- The frontend must not infer business stages from tool names.
- Delta fragments update a stable activity entry and must not create duplicate visible messages.
- Preserve all pre-existing dirty-worktree changes; inspect staged hunks before every commit.

---

### Task 1: Backend detail sanitization boundary

**Files:**
- Create: `backend/harness/codex_event_sanitizer.py`
- Create: `backend/tests/test_codex_event_sanitizer.py`

**Interfaces:**
- Produces: `sanitize_codex_value(value: Any) -> Any`
- Produces: `REDACTED = "[REDACTED]"`
- Produces: `TRUNCATED_SUFFIX = "\n...[truncated]"`
- Consumed by: Task 2 notification mapping.

- [ ] **Step 1: Write failing sanitizer tests**

```python
from backend.harness.codex_event_sanitizer import REDACTED, sanitize_codex_value


def test_redacts_sensitive_keys_without_removing_sql() -> None:
    value = {
        "sql": "select * from dm.sales where channel = '京东'",
        "api_key": "sk-secret",
        "nested": {"Authorization": "Bearer abc", "page": 3},
    }

    assert sanitize_codex_value(value) == {
        "sql": "select * from dm.sales where channel = '京东'",
        "api_key": REDACTED,
        "nested": {"Authorization": REDACTED, "page": 3},
    }


def test_redacts_credentials_embedded_in_text_and_connection_urls() -> None:
    value = {
        "stdout": "Authorization: Bearer abc123",
        "headers": "Cookie: session_id=private-cookie",
        "dsn": "postgresql://analyst:password@db.internal:5432/genbi",
    }

    sanitized = sanitize_codex_value(value)
    assert "abc123" not in sanitized["stdout"]
    assert "private-cookie" not in sanitized["headers"]
    assert "analyst:password" not in sanitized["dsn"]


def test_truncates_long_strings_with_an_explicit_marker() -> None:
    sanitized = sanitize_codex_value({"stdout": "x" * 25_000})
    assert len(sanitized["stdout"]) < 25_000
    assert sanitized["stdout"].endswith("...[truncated]")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_codex_event_sanitizer.py -q
```

Expected: collection fails because `backend.harness.codex_event_sanitizer` does not exist.

- [ ] **Step 3: Implement recursive sanitization**

Create a focused helper with these exact limits:

```python
REDACTED = "[REDACTED]"
TRUNCATED_SUFFIX = "\n...[truncated]"
MAX_STRING_CHARS = 20_000
MAX_COLLECTION_ITEMS = 200
MAX_DEPTH = 8

_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|token|password|passwd|secret|authorization|cookie|credential)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+")
_HEADER_SECRET = re.compile(r"(?im)^(\s*(?:authorization|cookie)\s*:\s*).+$")
_INLINE_SECRET = re.compile(
    r"(?i)\b(api[_-]?key|token|password|passwd|secret|credential)\s*[:=]\s*[^\s,;]+"
)
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<credentials>[^/@\s]+)@")


def sanitize_codex_value(value: Any, *, _depth: int = 0) -> Any:
    if _depth >= MAX_DEPTH:
        return "[max depth reached]"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_COLLECTION_ITEMS:
                output["..."] = "[truncated]"
                break
            output[str(key)] = (
                REDACTED
                if _SENSITIVE_KEY.search(str(key))
                else sanitize_codex_value(item, _depth=_depth + 1)
            )
        return output
    if isinstance(value, (list, tuple)):
        items = list(value[:MAX_COLLECTION_ITEMS])
        output = [sanitize_codex_value(item, _depth=_depth + 1) for item in items]
        if len(value) > MAX_COLLECTION_ITEMS:
            output.append("[truncated]")
        return output
    if isinstance(value, str):
        text = _BEARER.sub(r"\1[REDACTED]", value)
        text = _HEADER_SECRET.sub(r"\1[REDACTED]", text)
        text = _INLINE_SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
        text = _URL_CREDENTIALS.sub(r"\g<scheme>[REDACTED]@", text)
        return text if len(text) <= MAX_STRING_CHARS else text[:MAX_STRING_CHARS] + TRUNCATED_SUFFIX
    if hasattr(value, "model_dump"):
        return sanitize_codex_value(value.model_dump(), _depth=_depth + 1)
    if isinstance(value, Enum):
        return sanitize_codex_value(value.value, _depth=_depth + 1)
    if hasattr(value, "__dict__"):
        return sanitize_codex_value(vars(value), _depth=_depth + 1)
    return value
```

Import `Enum` from `enum`. Apply model/enum conversion before returning unknown object types so every sanitized value remains JSON serializable.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_codex_event_sanitizer.py -q
```

Expected: 3 passed.

- [ ] **Step 5: Review and commit the isolated new files**

Run:

```powershell
git diff --check -- backend/harness/codex_event_sanitizer.py backend/tests/test_codex_event_sanitizer.py
git add -- backend/harness/codex_event_sanitizer.py backend/tests/test_codex_event_sanitizer.py
git diff --cached --check
git commit -m "feat: sanitize Codex execution details"
```

Expected: the staged diff contains only the two new files. If any unrelated path appears, unstage it before committing.

---

### Task 2: Codex notification mapping and durable reasoning Items

**Files:**
- Modify: `backend/harness/codex_sdk_runner.py:348-580`
- Modify: `backend/tests/test_codex_sdk_runner.py:1-160`
- Modify: `backend/tests/test_analysis_api.py`

**Interfaces:**
- Consumes: `sanitize_codex_value(value: Any) -> Any` from Task 1.
- Produces native GenBI `AgentEvent` types:
  - `item/reasoning/summaryTextDelta`
  - `item/started`
  - `item/completed`
- Produces sanitized payload fields:
  - reasoning: `summary_index`, `delta`, `summary`
  - MCP: `mcp_server`, `mcp_tool`, `mcp_status`, `mcp_arguments`, `mcp_result`, `mcp_error`, `duration_ms`
  - command: `command`, `cwd`, `aggregated_output`, `exit_code`, `duration_ms`, `command_status`

- [ ] **Step 1: Add failing SDK mapping tests**

Extend `_FakeTurn.stream()` or call `_notification_to_event()` directly:

```python
def test_maps_reasoning_summary_delta_but_not_raw_reasoning_text(self) -> None:
    runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)
    summary = runtime._notification_to_event(
        SimpleNamespace(
            method="item/reasoning/summaryTextDelta",
            payload=SimpleNamespace(
                turn_id="codex_turn_1",
                item_id="reasoning_1",
                summary_index=0,
                delta="正在检查渠道口径。",
            ),
        ),
        codex_thread_id="codex_thread_1",
    )
    raw = runtime._notification_to_event(
        SimpleNamespace(
            method="item/reasoning/textDelta",
            payload=SimpleNamespace(
                turn_id="codex_turn_1",
                item_id="reasoning_1",
                content_index=0,
                delta="hidden chain of thought",
            ),
        ),
        codex_thread_id="codex_thread_1",
    )

    self.assertEqual(summary.type, "item/reasoning/summaryTextDelta")
    self.assertEqual(summary.payload["delta"], "正在检查渠道口径。")
    self.assertEqual(summary.payload["summary_index"], 0)
    self.assertIsNone(raw)
```

Add Item lifecycle and sanitization coverage:

```python
def test_maps_started_and_completed_tool_items_with_sanitized_details(self) -> None:
    runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)
    item = SimpleNamespace(
        id="tool_1",
        type="mcpToolCall",
        server="BI_doris",
        tool="mysql_query",
        status=SimpleNamespace(value="completed"),
        arguments={"sql": "select 1", "api_key": "secret-value"},
        result={"content": [{"type": "text", "text": "one row"}]},
        duration_ms=1250,
    )

    started = runtime._notification_to_event(
        SimpleNamespace(
            method="item/started",
            payload=SimpleNamespace(turn_id="turn_1", item=SimpleNamespace(root=item)),
        ),
        codex_thread_id="session_1",
    )
    completed = runtime._notification_to_event(
        SimpleNamespace(
            method="item/completed",
            payload=SimpleNamespace(turn_id="turn_1", item=SimpleNamespace(root=item)),
        ),
        codex_thread_id="session_1",
    )

    self.assertEqual(started.payload["codex_item_id"], "tool_1")
    self.assertEqual(completed.payload["mcp_arguments"]["sql"], "select 1")
    self.assertEqual(completed.payload["mcp_arguments"]["api_key"], "[REDACTED]")
    self.assertNotIn("secret-value", repr(completed.payload))
```

Add a completed reasoning Item assertion:

```python
def test_completed_reasoning_item_contains_display_summary(self) -> None:
    summary_part = SimpleNamespace(root=SimpleNamespace(text="正在核验数据。"))
    root = SimpleNamespace(
        id="reasoning_1",
        type="reasoning",
        summary=[summary_part],
        content=[SimpleNamespace(root=SimpleNamespace(text="hidden reasoning"))],
    )
    runtime = CodexSdkAnalysisRuntime(async_codex_factory=_FakeAsyncCodex)

    event = runtime._notification_to_event(
        SimpleNamespace(
            method="item/completed",
            payload=SimpleNamespace(turn_id="turn_1", item=SimpleNamespace(root=root)),
        ),
        codex_thread_id="session_1",
    )

    self.assertEqual(event.payload["summary"], "正在核验数据。")
    self.assertNotIn("hidden reasoning", repr(event.payload))
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_codex_sdk_runner.py -q
```

Expected: reasoning-summary and item-started assertions fail because `_notification_to_event()` returns `None`.

- [ ] **Step 3: Implement native notification mapping**

In `CodexSdkAnalysisRuntime._notification_to_event()`:

```python
if method == "item/reasoning/summaryTextDelta":
    delta = _string_or_none(getattr(payload, "delta", None))
    if not delta:
        return None
    return AgentEvent(
        type=method,
        turn_id=turn_id,
        payload={
            "runtime": "openai-codex",
            "eventSource": "codex",
            "codex_method": method,
            "codex_thread_id": codex_thread_id,
            "codex_turn_id": _payload_turn_id(payload),
            "codex_item_id": _payload_item_id(payload),
            "codex_item_type": "reasoning",
            "summary_index": int(getattr(payload, "summary_index", 0) or 0),
            "delta": delta,
        },
    )
if method == "item/reasoning/textDelta":
    return None
if method in {"item/started", "item/completed"}:
    return _item_lifecycle_event(
        method=method,
        payload=payload,
        turn_id=turn_id,
        codex_thread_id=codex_thread_id,
    )
```

Update `_payload_turn_id()` and `_payload_item_id()` to read direct notification fields before nested Item fields:

```python
def _payload_item_id(payload: Any) -> str | None:
    direct = _string_or_none(getattr(payload, "item_id", None) or getattr(payload, "itemId", None))
    if direct:
        return direct
    item = _payload_item(payload)
    root = getattr(item, "root", item)
    return _item_id(root)
```

Add the lifecycle mapper and focused payload helpers:

```python
def _item_lifecycle_event(
    *,
    method: str,
    payload: Any,
    turn_id: str,
    codex_thread_id: str | None,
) -> AgentEvent:
    item = _payload_item(payload)
    root = getattr(item, "root", item)
    root_type = _item_type(root)
    event_payload: dict[str, Any] = {
        "runtime": "openai-codex",
        "eventSource": "codex",
        "codex_method": method,
        "codex_thread_id": codex_thread_id,
        "codex_turn_id": _payload_turn_id(payload),
        "codex_item_id": _item_id(root),
        "codex_item_type": root_type,
    }
    if root_type == "reasoning":
        event_payload["summary"] = _reasoning_summary_text(root)
    elif root_type == "mcpToolCall":
        event_payload.update(_mcp_tool_call_payload(root))
    elif root_type == "commandExecution":
        event_payload.update(_command_execution_payload(root))
    elif root_type == "fileChange":
        event_payload.update(_file_change_payload(root))
    elif _is_agent_message(root):
        event_payload.update({"role": "assistant", "content": _item_text(root)})
    return AgentEvent(type=method, turn_id=turn_id, payload=event_payload)


def _reasoning_summary_text(root: Any) -> str:
    texts: list[str] = []
    for part in getattr(root, "summary", None) or []:
        value = getattr(part, "root", part)
        text = _string_or_none(getattr(value, "text", None))
        if text:
            texts.append(text)
    return "\n\n".join(texts)


def _command_execution_payload(root: Any) -> dict[str, Any]:
    if _item_type(root) != "commandExecution":
        return {}
    return sanitize_codex_value({
        "command": getattr(root, "command", None),
        "cwd": getattr(root, "cwd", None),
        "aggregated_output": getattr(root, "aggregated_output", None),
        "exit_code": getattr(root, "exit_code", None),
        "duration_ms": getattr(root, "duration_ms", None),
        "command_status": getattr(getattr(root, "status", None), "value", None)
        or getattr(root, "status", None),
    })


def _file_change_payload(root: Any) -> dict[str, Any]:
    if _item_type(root) != "fileChange":
        return {}
    return sanitize_codex_value({
        "changes": getattr(root, "changes", None),
        "file_change_status": getattr(getattr(root, "status", None), "value", None)
        or getattr(root, "status", None),
    })
```

Apply `sanitize_codex_value()` to MCP arguments, results, errors, command details, and file-change details before creating `AgentEvent`.

- [ ] **Step 4: Add and run a persistence regression**

Use the existing fake runtime/API fixture in `backend/tests/test_analysis_api.py` to emit:

```python
AgentEvent(
    type="item/completed",
    turn_id="turn_reasoning",
    payload={
        "codex_method": "item/completed",
        "codex_item_type": "reasoning",
        "codex_item_id": "reasoning_1",
        "summary": "正在核验数据。",
        "codex_thread_id": "session_reasoning",
        "codex_turn_id": "turn_reasoning",
    },
)
```

Assert the session detail contains one completed reasoning projection whose payload contains `summary` and does not contain reasoning `content`.

Run:

```powershell
python -m pytest backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Review the modified dirty files before committing**

Run:

```powershell
git diff --check -- backend/harness/codex_sdk_runner.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py
git diff -- backend/harness/codex_sdk_runner.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py
```

These files were already dirty before this plan. Do not stage or commit them unless the complete path diff is confirmed to belong to the current branch work. If confirmed, commit with:

```powershell
git add -- backend/harness/codex_sdk_runner.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py
git diff --cached --check
git commit -m "feat: stream Codex execution summaries"
```

---

### Task 3: Frontend event mapping and historical replay

**Files:**
- Modify: `frontend/src/modules/analysis/agentClients/types.ts`
- Modify: `frontend/src/modules/analysis/agentClients/backendClient.ts`
- Modify: `frontend/tests/analysis-backend-client.test.ts`

**Interfaces:**
- Produces `AgentEvent`:

```typescript
{
  type: "process";
  nodeId: string;
  text: string;
  mode: "delta" | "replace";
  summaryIndex: number;
  itemId?: string;
}
```

- Produces `FlowActivity` reasoning entries in Task 4.
- Historical ordering consumes `sequence` before `createdAt`.
- Extends tool state to `"queued" | "running" | "done" | "failed"`.

- [ ] **Step 1: Write failing live mapping tests**

```typescript
test("maps reasoning summary deltas to stable process events", () => {
  const events = Array.from(mapBackendEvents([
    {
      type: "item/reasoning/summaryTextDelta",
      turn_id: "turn_1",
      created_at: "2026-08-05T10:00:00Z",
      payload: {
        codex_method: "item/reasoning/summaryTextDelta",
        codex_item_type: "reasoning",
        codex_item_id: "reasoning_1",
        summary_index: 0,
        delta: "正在检查数据。",
      },
    },
  ], "start"));

  expect(events).toEqual([
    expect.objectContaining({
      type: "process",
      nodeId: "agent-turn_1",
      text: "正在检查数据。",
      mode: "delta",
      itemId: "reasoning_1:0",
      codexItemId: "reasoning_1",
    }),
  ]);
});

test("maps completed reasoning summary as replace for delta dedupe", () => {
  const events = Array.from(mapBackendEvents([
    {
      type: "item/completed",
      turn_id: "turn_1",
      created_at: "2026-08-05T10:00:01Z",
      payload: {
        codex_method: "item/completed",
        codex_item_type: "reasoning",
        codex_item_id: "reasoning_1",
        summary: "正在检查数据。",
      },
    },
  ], "start"));

  expect(events[0]).toMatchObject({
    type: "process",
    mode: "replace",
    text: "正在检查数据。",
    itemId: "reasoning_1:0",
  });
});
```

Add a tool-detail assertion that expects arguments and result sections instead of only the first SQL string:

```typescript
expect(events[0]).toMatchObject({
  type: "step",
  label: "BI_doris / mysql_query",
  state: "done",
  detail: expect.stringMatching(/Arguments:[\s\S]*SELECT 1[\s\S]*Result:[\s\S]*one row/),
});
```

- [ ] **Step 2: Run mapping tests and verify RED**

Run:

```powershell
Set-Location frontend
npm test -- analysis-backend-client.test.ts
```

Expected: `process` event assertions fail.

- [ ] **Step 3: Extend frontend event types and mapping**

Add to `AgentEvent`:

```typescript
| ({
    type: "process";
    nodeId: string;
    text: string;
    mode: "delta" | "replace";
    summaryIndex: number;
  } & AgentEventSystemContext)
```

Extend the existing `step` state union:

```typescript
state: "queued" | "running" | "done" | "failed";
```

Map delta and completion events before the existing generic reasoning branch:

```typescript
if (event.type === "item/reasoning/summaryTextDelta" || method === "item/reasoning/summaryTextDelta") {
  const summaryIndex = Number(event.payload.summary_index ?? 0);
  const codexItemId = asString(event.payload.codex_item_id);
  yield {
    type: "process",
    nodeId: getAgentNodeId(event),
    text: asString(event.payload.delta),
    mode: "delta",
    summaryIndex,
    itemId: `${codexItemId}:${summaryIndex}`,
    ...context,
  };
  continue;
}
```

For a completed reasoning Item with `payload.summary`, emit the same stable `itemId` with `mode: "replace"`. Keep the existing `thinking` event only when no summary text exists.

For tool lifecycle mapping:

```typescript
const completedStatus = asString(event.payload.mcp_status)
  || asString(event.payload.command_status)
  || asString(event.payload.file_change_status);
const state = event.type === "item/started"
  ? "running"
  : ["failed", "error", "cancelled"].includes(completedStatus)
    ? "failed"
    : "done";
```

Include `commandExecution` and `fileChange` in the tool/activity Item type set. `toolLabelFromPayload()` uses the command text for command Items and `File changes` for file-change Items when MCP server/tool fields are absent.

Replace `toolCallDetail()` with formatted sections:

```typescript
function toolCallDetail(payload: Record<string, unknown>): string | undefined {
  const sections: string[] = [];
  const args = asRecord(payload.mcp_arguments) || asRecord(payload.arguments);
  const result = asRecord(payload.mcp_result) || asRecord(payload.result);
  const command = asString(payload.command);
  const output = asString(payload.aggregated_output);
  if (command) sections.push(`Command:\n${command}`);
  if (args) sections.push(`Arguments:\n${formatToolDetail(args)}`);
  if (result) sections.push(`Result:\n${formatToolResult(result)}`);
  if (output) sections.push(`Output:\n${output}`);
  if (Array.isArray(payload.changes)) {
    sections.push(`Changes:\n${truncateToolDetail(JSON.stringify(payload.changes, null, 2))}`);
  }
  if (payload.exit_code != null) sections.push(`Exit code: ${String(payload.exit_code)}`);
  const error = asString(payload.mcp_error) || asString(payload.error);
  if (error) sections.push(`Error:\n${error}`);
  return sections.length > 0 ? truncateToolDetail(sections.join("\n\n")) : undefined;
}
```

Set `truncateToolDetail()` to 20,000 characters and append `\n...[truncated]`.

- [ ] **Step 4: Add historical replay tests**

Add a session detail with explicit sequence:

```typescript
codexItemProjections: [
  {
    codexItemId: "reasoning_1",
    itemType: "reasoning",
    status: "completed",
    sequence: 0,
    payload: { summary: "正在核验数据。" },
    createdAt: "2026-08-05T10:00:02Z",
    genbiTurnId: "turn_1",
  },
  {
    codexItemId: "tool_1",
    itemType: "mcpToolCall",
    status: "completed",
    sequence: 1,
    payload: {
      mcp_server: "BI_doris",
      mcp_tool: "mysql_query",
      mcp_arguments: { sql: "select 1" },
    },
    createdAt: "2026-08-05T10:00:01Z",
    genbiTurnId: "turn_1",
  },
  {
    codexItemId: "message_1",
    itemType: "agentMessage",
    status: "completed",
    sequence: 2,
    payload: { content: "最终结论。" },
    createdAt: "2026-08-05T10:00:00Z",
    genbiTurnId: "turn_1",
  },
]
```

Assert replay follows `sequence`, producing reasoning then tool activity and keeping `最终结论。` as final content.

Add `sequence?: number` to the top-level projection type and `completedAt?: string` to the Turn type. Sort normalized projections by numeric `sequence` first, then `createdAt`, then `codexItemId`. Pass the Turn timestamps into `agentNodeFromTurnProjections()` so restored Agent nodes receive `processStartedAt: turn.createdAt` and `processCompletedAt: turn.completedAt`.

- [ ] **Step 5: Run tests and review dirty paths**

Run:

```powershell
Set-Location frontend
npm test -- analysis-backend-client.test.ts
Set-Location ..
git diff --check -- frontend/src/modules/analysis/agentClients/types.ts frontend/src/modules/analysis/agentClients/backendClient.ts frontend/tests/analysis-backend-client.test.ts
```

Expected: selected tests pass. Because two files were already dirty, inspect their complete diffs before any path-level commit. If all hunks belong to branch work:

```powershell
git add -- frontend/src/modules/analysis/agentClients/types.ts frontend/src/modules/analysis/agentClients/backendClient.ts frontend/tests/analysis-backend-client.test.ts
git diff --cached --check
git commit -m "feat: map Codex execution activity"
```

---

### Task 4: Ordered process activity reducer

**Files:**
- Modify: `frontend/src/modules/analysis/hooks/use-flow.ts`
- Modify: `frontend/tests/analysis-flow-streaming.test.ts`

**Interfaces:**
- Consumes: `AgentEvent.type === "process"` from Task 3.
- Extends `FlowActivity`:

```typescript
{ kind: "reasoning"; content: string; itemId: string }
```

Extend every tool-state union in `FlowActivity`, `FlowNode.steps`, and reducer helpers to include `"failed"`.

- Extends Agent `FlowNode`:

```typescript
processRunning?: boolean;
processStartedAt?: string;
processCompletedAt?: string;
```

- Produces ordered `activity` consumed by Task 5.

- [ ] **Step 1: Write failing reducer tests**

Add a stream with fragmented summaries, a tool, and a final answer:

```typescript
mockSend.mockImplementation(async function* (): AsyncIterable<AgentEvent> {
  yield { type: "user", nodeId: "user-1", content: "分析渠道销售", turnId: "turn-1" };
  yield {
    type: "process",
    nodeId: "agent-1",
    text: "正在确认",
    mode: "delta",
    summaryIndex: 0,
    itemId: "reasoning-1:0",
  };
  yield {
    type: "process",
    nodeId: "agent-1",
    text: "数据范围。",
    mode: "delta",
    summaryIndex: 0,
    itemId: "reasoning-1:0",
  };
  yield {
    type: "step",
    nodeId: "agent-1",
    label: "BI_doris / mysql_query",
    state: "done",
    detail: "Arguments:\n{\"sql\":\"select 1\"}",
    itemId: "tool-1",
  };
  yield {
    type: "process",
    nodeId: "agent-1",
    text: "正在生成报告。",
    mode: "replace",
    summaryIndex: 1,
    itemId: "reasoning-2:1",
  };
  yield { type: "tokens", nodeId: "agent-1", text: "最终结论。", codexItemId: "message-1" };
  yield { type: "done", turnId: "turn-1" };
});
```

Assert:

```typescript
expect(result.current.nodes[1]).toMatchObject({
  role: "agent",
  content: "最终结论。",
  processRunning: false,
  activity: [
    { kind: "reasoning", itemId: "reasoning-1:0", content: "正在确认数据范围。" },
    { kind: "tool", itemId: "tool-1", state: "done" },
    { kind: "reasoning", itemId: "reasoning-2:1", content: "正在生成报告。" },
  ],
});
```

Add a replacement dedupe test where the completed summary replaces the identical accumulated delta without creating a second activity.

- [ ] **Step 2: Run reducer tests and verify RED**

Run:

```powershell
Set-Location frontend
npm test -- analysis-flow-streaming.test.ts
```

Expected: TypeScript or assertion failure because `process` and reasoning activity are not handled.

- [ ] **Step 3: Implement stable process activity folding**

Add:

```typescript
function ensureAgentNode(nodes: FlowNode[], nodeId: string): FlowNode[] {
  const next = nodes
    .filter((node) => node.id !== "agent-pending")
    .map((node) => ({ ...node }) as FlowNode);
  if (!next.some((node) => node.role === "agent" && node.id === nodeId)) {
    next.push({
      id: nodeId,
      role: "agent",
      content: "",
      mode: "delta",
      thinking: false,
      processRunning: true,
      processStartedAt: new Date().toISOString(),
      steps: [],
      activity: [],
    });
  }
  return next;
}


if (event.type === "process") {
  const next = ensureAgentNode(currentNodes, event.nodeId);
  const targetIndex = next.findIndex((node) => node.role === "agent" && node.id === event.nodeId);
  const target = next[targetIndex];
  if (target?.role !== "agent") return currentNodes;

  const activity = [...(target.activity ?? [])];
  const index = activity.findIndex(
    (item) => item.kind === "reasoning" && item.itemId === event.itemId,
  );
  const previous = index >= 0 && activity[index].kind === "reasoning"
    ? activity[index].content
    : "";
  const content = event.mode === "replace"
    ? cleanDisplayText(event.text)
    : previous + cleanDisplayText(event.text);
  const entry: FlowActivity = { kind: "reasoning", content, itemId: event.itemId ?? "" };
  if (index >= 0) activity[index] = entry;
  else activity.push(entry);

  next[targetIndex] = {
    ...target,
    id: event.nodeId,
    thinking: false,
    processRunning: true,
    processStartedAt: target.processStartedAt ?? new Date().toISOString(),
    activity,
  };
  setNodes(next);
  return next;
}
```

Refactor the shown logic into a small local helper if needed, but preserve the exact stable-key and replace/delta behavior.

When applying `done`, set `processRunning: false` and `processCompletedAt` on the Agent node for `event.turnId`. Do not delete reasoning activity.

- [ ] **Step 4: Run streaming tests and verify GREEN**

Run:

```powershell
Set-Location frontend
npm test -- analysis-flow-streaming.test.ts
```

Expected: all selected tests pass, including existing duplicate-response and pending-placeholder regressions.

- [ ] **Step 5: Review dirty paths before committing**

Run:

```powershell
Set-Location ..
git diff --check -- frontend/src/modules/analysis/hooks/use-flow.ts frontend/tests/analysis-flow-streaming.test.ts
git diff -- frontend/src/modules/analysis/hooks/use-flow.ts frontend/tests/analysis-flow-streaming.test.ts
```

Both paths were already dirty. Commit only after confirming all hunks:

```powershell
git add -- frontend/src/modules/analysis/hooks/use-flow.ts frontend/tests/analysis-flow-streaming.test.ts
git diff --cached --check
git commit -m "feat: preserve ordered execution activity"
```

---

### Task 5: Codex-style collapsible process UI

**Files:**
- Modify: `frontend/src/modules/analysis/components/FlowNodeView.tsx`
- Modify: `frontend/src/app/globals.css:201-225`
- Create: `frontend/tests/flow-node-view.test.tsx`

**Interfaces:**
- Consumes `FlowNode.activity`, `processRunning`, `processStartedAt`, and `processCompletedAt`.
- Produces an accessible `<details aria-label="执行过程">` region.

- [ ] **Step 1: Write failing component tests**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { FlowNodeView } from "../src/modules/analysis/components/FlowNodeView";

describe("FlowNodeView execution process", () => {
  test("renders reasoning and collapsed tool details before the final answer", () => {
    render(<FlowNodeView node={{
      id: "agent-1",
      role: "agent",
      content: "最终结论。",
      processRunning: false,
      processStartedAt: "2026-08-05T10:00:00.000Z",
      processCompletedAt: "2026-08-05T10:01:36.000Z",
      activity: [
        { kind: "reasoning", content: "正在核验数据。", itemId: "reasoning-1:0" },
        { kind: "tool", label: "BI_doris / mysql_query", state: "done", detail: "SELECT 1", itemId: "tool-1" },
      ],
    }} />);

    const process = screen.getByRole("group", { name: "执行过程" });
    expect(process).not.toHaveAttribute("open");
    expect(screen.getByText("分析了 1分36秒")).toBeInTheDocument();
    expect(screen.getByText("最终结论。")).toBeInTheDocument();

    fireEvent.click(screen.getByText("分析了 1分36秒"));
    expect(screen.getByText("正在核验数据。")).toBeInTheDocument();
    expect(screen.getByLabelText("工具 BI_doris / mysql_query")).not.toHaveAttribute("open");
  });

  test("starts expanded while execution is running", () => {
    render(<FlowNodeView node={{
      id: "agent-1",
      role: "agent",
      content: "",
      processRunning: true,
      processStartedAt: "2026-08-05T10:00:00.000Z",
      activity: [{ kind: "reasoning", content: "正在分析。", itemId: "reasoning-1:0" }],
    }} />);

    expect(screen.getByRole("group", { name: "执行过程" })).toHaveAttribute("open");
  });
});
```

- [ ] **Step 2: Run component tests and verify RED**

Run:

```powershell
Set-Location frontend
npm test -- flow-node-view.test.tsx
```

Expected: the process group and elapsed-time summary do not exist.

- [ ] **Step 3: Implement the process container**

Add a local `AgentProcess` component in `FlowNodeView.tsx` so process open-state hooks are not called conditionally inside the role branches:

```tsx
const [processOpen, setProcessOpen] = useState(Boolean(node.processRunning));
const wasRunning = useRef(Boolean(node.processRunning));

useEffect(() => {
  if (node.processRunning && !wasRunning.current) setProcessOpen(true);
  if (!node.processRunning && wasRunning.current) setProcessOpen(false);
  wasRunning.current = Boolean(node.processRunning);
}, [node.processRunning]);
```

Add exact duration helpers:

```tsx
function formatDuration(milliseconds: number): string {
  const totalSeconds = Math.max(0, Math.round(milliseconds / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}秒`;
  if (seconds === 0) return `${minutes}分`;
  return `${minutes}分${seconds}秒`;
}

function processSummary(node: Extract<FlowNodeData, { role: "agent" }>): string {
  if (node.processRunning) return "正在处理";
  const started = node.processStartedAt ? Date.parse(node.processStartedAt) : Number.NaN;
  const completed = node.processCompletedAt ? Date.parse(node.processCompletedAt) : Number.NaN;
  if (Number.isFinite(started) && Number.isFinite(completed) && completed >= started) {
    return `分析了 ${formatDuration(completed - started)}`;
  }
  return "执行过程";
}
```

Render activities inside:

```tsx
<details
  className="agent-process"
  aria-label="执行过程"
  open={processOpen}
  onToggle={(event) => setProcessOpen(event.currentTarget.open)}
>
  <summary>{processSummary(node)}</summary>
  <ol className="agent-activity" aria-label="本轮执行过程">
    {activity.map((item, index) => (
      <li
        className={`agent-activity-item activity-${item.kind}${item.kind === "tool" ? ` ${item.state}` : ""}`}
        key={`${item.itemId ?? item.kind}-${index}`}
      >
        {item.kind === "reasoning" || item.kind === "message" ? (
          <div className="message-body-markdown activity-message-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown>
          </div>
        ) : item.detail ? (
          <details className="tool-step-detail" aria-label={`工具 ${cleanToolLabel(item.label)}`}>
            <summary>
              <span className="agent-activity-tool-icon" aria-hidden="true">TOOL</span>
              <strong>{cleanToolLabel(item.label)}</strong>
            </summary>
            <pre>{(item.details?.length ? item.details : [item.detail]).join("\n\n")}</pre>
          </details>
        ) : (
          <span className="agent-activity-tool-label">
            <span className="agent-activity-tool-icon" aria-hidden="true">TOOL</span>
            <strong>{cleanToolLabel(item.label)}</strong>
          </span>
        )}
      </li>
    ))}
  </ol>
</details>
```

`processSummary(node)` returns:

- running: `正在处理`
- completed with reliable timestamps: `分析了 ${formatDuration(milliseconds)}`
- completed without timestamps: `执行过程`

Render `kind === "reasoning"` as Markdown text. Keep tool details nested and collapsed by default. Render `node.content` after the process `<details>` as the final answer.

- [ ] **Step 4: Add focused styling**

Extend `frontend/src/app/globals.css` with:

```css
.agent-process { min-width: 0; border: 0; }
.agent-process > summary {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: var(--text-muted);
  font-size: .76rem;
  list-style: none;
}
.agent-process > summary::-webkit-details-marker { display: none; }
.agent-process > summary::after {
  content: "";
  width: 6px;
  height: 6px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(45deg);
  transition: transform 140ms ease;
}
.agent-process[open] > summary::after { transform: rotate(225deg); }
.agent-process > .agent-activity {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(30,58,95,.08);
}
.agent-activity-item.activity-reasoning {
  color: var(--text-secondary);
  padding: 2px 0;
}
.agent-activity-item.activity-tool.failed,
.timeline-step.failed { color: var(--danger); }
```

- [ ] **Step 5: Run UI and regression tests**

Run:

```powershell
Set-Location frontend
npm test -- flow-node-view.test.tsx analysis-flow-streaming.test.ts analysis-backend-client.test.ts
```

Expected: all selected tests pass.

- [ ] **Step 6: Review and commit**

Run:

```powershell
Set-Location ..
git diff --check -- frontend/src/modules/analysis/components/FlowNodeView.tsx frontend/src/app/globals.css frontend/tests/flow-node-view.test.tsx
git add -- frontend/src/modules/analysis/components/FlowNodeView.tsx frontend/src/app/globals.css frontend/tests/flow-node-view.test.tsx
git diff --cached --check
git commit -m "feat: render Codex-style execution process"
```

Do not commit if the staged diff includes unrelated pre-existing CSS or component changes.

---

### Task 6: Integrated verification, runtime rebuild, and branch snapshot

**Files:**
- Modify: `docs/plans/current.md`
- No production code should be introduced in this task.

**Interfaces:**
- Consumes all prior tasks.
- Produces verified Docker runtime behavior and an updated branch snapshot.

- [ ] **Step 1: Run focused backend and frontend suites**

Run:

```powershell
python -m pytest backend/tests/test_codex_event_sanitizer.py backend/tests/test_codex_sdk_runner.py backend/tests/test_analysis_api.py -q
Set-Location frontend
npm test -- analysis-backend-client.test.ts analysis-flow-streaming.test.ts flow-node-view.test.tsx
Set-Location ..
```

Expected: all selected tests pass.

- [ ] **Step 2: Run project-level verification**

Run:

```powershell
python -m pytest backend/tests -q
Set-Location frontend
npm test
npm run build
Set-Location ..
docker compose config
```

Expected: all commands exit 0.

- [ ] **Step 3: Rebuild services using the project restart procedure**

Follow `fanyafan_skill_restart_service` before issuing runtime commands. Rebuild the services affected by backend and frontend changes:

```powershell
docker compose up -d --build backend frontend
docker compose ps
```

Expected: backend and frontend containers are healthy/running.

- [ ] **Step 4: Verify with Chrome against the real frontend**

Open:

```text
http://192.168.101.12:3000/
```

Submit a new analysis question and verify:

1. The static “思考中” is replaced when the first reasoning summary arrives.
2. Reasoning summaries persist in event order instead of flashing and disappearing.
3. Tool rows appear between summaries and are collapsed by default.
4. Expanding a tool row reveals actual details.
5. No test Token, password, Cookie, Authorization value, or URL credential appears in the DOM or SSE payload.
6. The final answer appears once.
7. Completion collapses the process and shows elapsed time.
8. Refreshing the deep link restores process Items and the final answer in sequence order.

- [ ] **Step 5: Update the current branch snapshot**

Record only verified facts in `docs/plans/current.md`:

```markdown
- Codex reasoning summary notifications are streamed and restored as execution activity.
- Tool Item details are expandable and sanitized before SSE/persistence.
- Raw reasoning text remains hidden.
```

Append one bullet per command or browser check with its observed pass/fail result and exact test total; do not claim an unrun check.

- [ ] **Step 6: Inspect the final diff before any commit**

Run:

```powershell
git status --short --branch
git diff --check
git diff --stat
```

Because the worktree contained pre-existing modifications, do not perform a catch-all `git add .`. Stage only reviewed paths and inspect `git diff --cached` before a final documentation commit:

```powershell
git add -- docs/plans/current.md
git diff --cached --check
git commit -m "docs: record execution process verification"
```
