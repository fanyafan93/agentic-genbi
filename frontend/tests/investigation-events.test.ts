import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildKnowledgePayload,
  buildResourceProfileItems,
  buildResourceSignalGroups,
  buildResourceExplorationPrompt,
  createExplorationRun,
  deleteKnowledge,
  filterResources,
  findResourceByEvidenceRef,
  getRuntimeStatus,
  listExplorationRuns,
  listKnowledge,
  mapRunEventsToExploration,
  parseExplorationSse,
  readExplorationRun,
  readResourceExcerpt,
  readRunTrace,
  saveKnowledgeFromExploration,
  formatBytes,
  mapRunTraceSummary,
} from "../src/modules/investigation/api/exploration-runs";
import { parseLatexFormula, splitMarkdownMath } from "../src/modules/investigation/components/MarkdownContent";
import { getComposerKeyIntent } from "../src/modules/investigation/composer-keys";
import { shouldContinueExploration } from "../src/modules/investigation/exploration-continuation";
import { shouldShowExplorationWaiting } from "../src/modules/investigation/exploration-waiting";
import { shouldShowExplorationMessage } from "../src/modules/investigation/message-visibility";
import type { Exploration, ExplorationRunEvent } from "../src/modules/investigation/types";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.NEXT_PUBLIC_GENBI_API_BASE_URL;
});

describe("mapRunEventsToExploration", () => {
  it("maps backend exploration events into the conversation UI model", () => {
    const events: ExplorationRunEvent[] = [
      { type: "run.created", run_id: "run_1", created_at: "2026-07-27T00:00:00Z", payload: { conversation_id: "conv_1", question: "q" } },
      { type: "agent.title.generated", run_id: "run_1", created_at: "2026-07-27T00:00:00Z", payload: { title: "首购后 30 天复购率" } },
      {
        type: "agent.evidence.available",
        run_id: "run_1",
        created_at: "2026-07-27T00:00:00Z",
        payload: {
          title: "资源库命中",
          items: [{ resource_id: "res_1", name: "复购分析.cpt", relative_path: "LR/SALES/复购分析.cpt" }],
        },
      },
      {
        type: "agent.question.requested",
        run_id: "run_1",
        created_at: "2026-07-27T00:00:00Z",
        payload: { question: "按会员 ID 还是手机号去重？", reason: "已有实现冲突" },
      },
      {
        type: "run.completed",
        run_id: "run_1",
        created_at: "2026-07-27T00:00:00Z",
        payload: { status: "awaiting_user_confirmation", next_action: "等待用户确认" },
      },
    ];

    const exploration = mapRunEventsToExploration("首购后 30 天复购率怎么计算？", events);

    expect(exploration.id).toBe("conv_1");
    expect(exploration.title).toBe("首购后 30 天复购率");
    expect(exploration.status).toBe("待确认");
    expect(exploration.resources).toBe(1);
    expect(exploration.messages.some((message) => message.details?.[0]?.items[0].includes("复购分析.cpt"))).toBe(true);
  });

  it("groups tool calls into readable summaries and shows run failures", () => {
    const events: ExplorationRunEvent[] = [
      { type: "run.created", run_id: "run_failed", created_at: "2026-07-27T00:00:00Z", payload: { question: "探索复购率" } },
      { type: "agent.title.generated", run_id: "run_failed", created_at: "2026-07-27T00:00:00Z", payload: { title: "探索复购率" } },
      {
        type: "agent.message.created",
        run_id: "run_failed",
        created_at: "2026-07-27T00:00:01Z",
        payload: { title: "阶段输出", content: "Step 1：资源库搜索（复购率）" },
      },
      {
        type: "agent.message.created",
        run_id: "run_failed",
        created_at: "2026-07-27T00:00:01Z",
        payload: { title: "探索进展", content: "   " },
      },
      {
        type: "tool.call.started",
        run_id: "run_failed",
        created_at: "2026-07-27T00:00:02Z",
        payload: {
          tool: "search_resources",
          tool_label: "搜索资源库",
          tool_label_full: "搜索资源库 search_resources",
          call_id: "call_1",
        },
      },
      {
        type: "tool.call.completed",
        run_id: "run_failed",
        created_at: "2026-07-27T00:00:03Z",
        payload: {
          tool: "save_verified_knowledge",
          call_id: "call_1",
          output: "{'results': []}",
        },
      },
      {
        type: "agent.runner.failed",
        run_id: "run_failed",
        created_at: "2026-07-27T00:00:04Z",
        payload: { error: "Max turns (10) exceeded" },
      },
      {
        type: "run.failed",
        run_id: "run_failed",
        created_at: "2026-07-27T00:00:04Z",
        payload: { error: "agent_runner_failed", detail: "Max turns (10) exceeded" },
      },
    ];

    const exploration = mapRunEventsToExploration("探索复购率", events);

    expect(exploration.status).toBe("待确认");
    expect(exploration.summary).toBe("Max turns (10) exceeded");
    expect(exploration.messages.some((message) => message.title === "调用工具")).toBe(false);
    expect(exploration.messages.some((message) => message.body === "unknown_tool")).toBe(false);
    expect(exploration.messages.some((message) => message.title === "探索进展" && !message.body.trim())).toBe(false);
    expect(exploration.messages.some((message) => message.title === "工具调用摘要（1 次）")).toBe(true);
    expect(exploration.messages.some((message) => message.body.includes("沉淀知识 save_verified_knowledge"))).toBe(true);
    expect(exploration.messages.some((message) => message.body.includes("最多 10 个模型/工具回合"))).toBe(true);
    expect(exploration.messages.filter((message) => message.title === "探索 Run 已停止")).toHaveLength(0);
  });

  it("explains model connection failures in user-facing Chinese", () => {
    const events: ExplorationRunEvent[] = [
      { type: "run.created", run_id: "run_connection", created_at: "2026-07-27T00:00:00Z", payload: { question: "毛利率怎么算" } },
      { type: "agent.title.generated", run_id: "run_connection", created_at: "2026-07-27T00:00:00Z", payload: { title: "毛利率怎么算" } },
      {
        type: "agent.runner.failed",
        run_id: "run_connection",
        created_at: "2026-07-27T00:00:04Z",
        payload: { error: "Connection error." },
      },
      {
        type: "run.failed",
        run_id: "run_connection",
        created_at: "2026-07-27T00:00:04Z",
        payload: { error: "agent_runner_failed", detail: "Connection error." },
      },
    ];

    const exploration = mapRunEventsToExploration("毛利率怎么算", events);

    expect(exploration.messages.some((message) => message.body.includes("模型服务连接失败"))).toBe(true);
    expect(exploration.messages.some((message) => message.body === "原因：Connection error.。已保留当前发现，可继续追问或重新运行。")).toBe(false);
  });

  it("deduplicates identical progress and conclusion messages from the runner", () => {
    const events: ExplorationRunEvent[] = [
      { type: "run.created", run_id: "run_dupe", created_at: "2026-07-27T00:00:00Z", payload: { question: "自然周期复购率是什么意思" } },
      { type: "agent.title.generated", run_id: "run_dupe", created_at: "2026-07-27T00:00:00Z", payload: { title: "复购率解释" } },
      {
        type: "agent.message.created",
        run_id: "run_dupe",
        created_at: "2026-07-27T00:00:01Z",
        payload: { title: "探索进展", content: "自然周期复购率：周期内成交两次及以上会员数 / 周期内成交会员数。" },
      },
      {
        type: "agent.message.created",
        run_id: "run_dupe",
        created_at: "2026-07-27T00:00:02Z",
        payload: { title: "探索结论", content: "自然周期复购率：周期内成交两次及以上会员数 / 周期内成交会员数。" },
      },
      { type: "run.completed", run_id: "run_dupe", created_at: "2026-07-27T00:00:03Z", payload: { status: "completed" } },
    ];

    const exploration = mapRunEventsToExploration("自然周期复购率是什么意思", events);
    const matchedMessages = exploration.messages.filter((message) => message.role === "agent" && message.body.includes("自然周期复购率"));

    expect(matchedMessages).toHaveLength(1);
    expect(matchedMessages[0].title).toBe("探索结论");
  });

  it("normalizes legacy agent self naming in displayed messages", () => {
    const events: ExplorationRunEvent[] = [
      { type: "run.created", run_id: "run_identity", created_at: "2026-07-27T00:00:00Z", payload: { question: "hello" } },
      { type: "agent.title.generated", run_id: "run_identity", created_at: "2026-07-27T00:00:00Z", payload: { title: "hello" } },
      {
        type: "agent.message.created",
        run_id: "run_identity",
        created_at: "2026-07-27T00:00:01Z",
        payload: { title: "探索结论", content: "我是 Agentic GenBI 的数据探索 Agent。" },
      },
      { type: "run.completed", run_id: "run_identity", created_at: "2026-07-27T00:00:02Z", payload: { status: "completed" } },
    ];

    const exploration = mapRunEventsToExploration("hello", events);

    expect(exploration.messages.some((message) => message.body.includes("数据探索 Agent"))).toBe(false);
    expect(exploration.messages.some((message) => message.body.includes("知识探索 Agent"))).toBe(true);
  });
});

describe("knowledge exploration message visibility", () => {
  it("hides fixed exploration opener cards", () => {
    const messages: Exploration["messages"] = [
      { id: "u1", role: "user", body: "收入净额怎么算" },
      {
        id: "a1",
        role: "agent",
        title: "开始探索",
        body: "我会先搜索资源库里的已有报表、SQL、ETL 和字典，再按需要查看数据库元数据。",
      },
      { id: "a2", role: "agent", title: "探索进展", body: "已经查到 dm_fina_sales_profit_sum。" },
      { id: "u2", role: "user", body: "dm_fina_sales_profit_sum 不是有收入净额吗" },
      {
        id: "a3",
        role: "agent",
        title: "开始探索",
        body: "我会先搜索资源库里的已有报表、SQL、ETL 和字典，再按需要查看数据库元数据。",
      },
    ];

    expect(messages.filter(shouldShowExplorationMessage).map((message) => message.id)).toEqual(["u1", "a2", "u2"]);
  });
});

describe("knowledge exploration composer keys", () => {
  it("submits on plain Enter and keeps modified Enter for editing", () => {
    expect(getComposerKeyIntent({ key: "Enter" })).toBe("submit");
    expect(getComposerKeyIntent({ key: "Enter", shiftKey: true })).toBe("edit");
    expect(getComposerKeyIntent({ key: "Enter", ctrlKey: true })).toBe("edit");
    expect(getComposerKeyIntent({ key: "Enter", metaKey: true })).toBe("edit");
    expect(getComposerKeyIntent({ key: "Enter", nativeEvent: { isComposing: true } })).toBe("edit");
    expect(getComposerKeyIntent({ key: "a" })).toBe("edit");
  });
});

describe("knowledge exploration continuation", () => {
  it("continues an existing run even when it is still marked in progress", () => {
    const exploration: Exploration = {
      id: "run_a822b28a2c9a",
      title: "推广费用",
      agent: "知识探索 Agent",
      status: "进行中",
      updatedAt: "刚刚",
      resources: 0,
      summary: "等待用户补充",
      messages: [{ id: "m1", role: "user", body: "推广费用" }],
    };

    expect(shouldContinueExploration(exploration)).toBe(true);
  });

  it("does not persist a draft placeholder as a continuation target", () => {
    const exploration: Exploration = {
      id: "exploration-draft",
      title: "新的知识探索",
      agent: "知识探索 Agent",
      status: "进行中",
      updatedAt: "刚刚",
      resources: 0,
      summary: "",
      messages: [],
    };

    expect(shouldContinueExploration(exploration)).toBe(false);
  });
});

describe("knowledge exploration waiting state", () => {
  it("follows the active run id after a draft exploration becomes a real run", () => {
    expect(shouldShowExplorationWaiting(true, "exploration-draft", "run_1")).toBe(false);
    expect(shouldShowExplorationWaiting(true, "run_1", "run_1")).toBe(true);
    expect(shouldShowExplorationWaiting(false, "run_1", "run_1")).toBe(false);
  });
});

describe("knowledge exploration markdown math", () => {
  it("detects and parses bracketed latex fractions from model output", () => {
    const body = [
      "这不是前面解释的自然周期复购率。",
      "",
      "[ \\boxed{ \\text{复购率} }",
      "\\frac{\\text{复购用户数}} {\\text{新用户数}} } ]",
    ].join("\n");

    const segments = splitMarkdownMath(body);
    const formula = parseLatexFormula(segments.find((segment) => segment.type === "math")?.value ?? "");

    expect(segments.some((segment) => segment.type === "math")).toBe(true);
    expect(formula.label).toBe("复购率");
    expect(formula.numerator).toBe("复购用户数");
    expect(formula.denominator).toBe("新用户数");
  });
});

describe("exploration SSE", () => {
  it("parses server-sent exploration events", () => {
    const events = parseExplorationSse(
      [
        'event: run.created\ndata: {"type":"run.created","run_id":"run_1","created_at":"2026-07-27T00:00:00Z","payload":{"question":"q"}}',
        'event: run.completed\ndata: {"type":"run.completed","run_id":"run_1","created_at":"2026-07-27T00:00:01Z","payload":{"status":"completed"}}',
      ].join("\n\n"),
    );

    expect(events).toHaveLength(2);
    expect(events[0].type).toBe("run.created");
    expect(events[1].type).toBe("run.completed");
  });

  it("uses the stream endpoint and emits partial exploration updates", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const sse = [
      'event: run.created\ndata: {"type":"run.created","run_id":"run_1","created_at":"2026-07-27T00:00:00Z","payload":{"question":"q"}}',
      'event: agent.title.generated\ndata: {"type":"agent.title.generated","run_id":"run_1","created_at":"2026-07-27T00:00:00Z","payload":{"title":"首购复购"}}',
      'event: run.completed\ndata: {"type":"run.completed","run_id":"run_1","created_at":"2026-07-27T00:00:01Z","payload":{"status":"completed","next_action":"完成"}}',
    ].join("\n\n");
    const fetchMock = vi.fn().mockResolvedValue(new Response(sse, { status: 200 }));
    const updates = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const exploration = await createExplorationRun("首购复购", updates);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/explorations/conversations/stream",
      expect.objectContaining({ method: "POST" }),
    );
    expect(updates).toHaveBeenCalledTimes(3);
    expect(exploration.title).toBe("首购复购");
    expect(exploration.status).toBe("已完成");
  });
});

describe("persisted exploration runs", () => {
  const runTracePayload = {
    run_id: "run_1",
    conversation_id: "conv_1",
    title: "抖音订单占比探索",
    status: "completed",
    question: "抖音订单占比怎么算？",
    started_at: "2026-07-27T12:00:00Z",
    completed_at: "2026-07-27T12:00:02Z",
    duration_ms: 2345,
    event_count: 8,
    tool_call_count: 2,
    failed_tool_call_count: 0,
    agent_message_count: 3,
    token_usage: { input_tokens: 1000, output_tokens: 500, total_tokens: 1500 },
    cost: { input_usd: 0.0004, output_usd: 0.0008, total_usd: 0.0012 },
    error: null,
    metadata: { conversation_root: true },
  };

  it("loads recent persisted exploration runs as sidebar summaries", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ conversations: [runTracePayload] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const runs = await listExplorationRuns();

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/explorations/conversations?limit=30");
    expect(runs[0]).toMatchObject({
      id: "conv_1",
      title: "抖音订单占比探索",
      status: "已完成",
      resources: 2,
    });
    expect(runs[0].messages[1].title).toBe("已保存探索");
  });

  it("restores a persisted exploration run from saved events", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const events: ExplorationRunEvent[] = [
      { type: "run.created", run_id: "run_1", created_at: "2026-07-27T00:00:00Z", payload: { question: "抖音订单占比怎么算？" } },
      { type: "agent.title.generated", run_id: "run_1", created_at: "2026-07-27T00:00:00Z", payload: { title: "抖音订单占比探索" } },
      { type: "agent.message.created", run_id: "run_1", created_at: "2026-07-27T00:00:00Z", payload: { title: "探索结论", content: "需要确认用户 ID 口径。" } },
      { type: "run.completed", run_id: "run_1", created_at: "2026-07-27T00:00:00Z", payload: { status: "completed", next_action: "已完成" } },
    ];
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ conversation_id: "conv_1", latest_run_id: "run_1", run: { ...runTracePayload, conversation_id: "conv_1" }, events }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const run = await readExplorationRun("run_1");

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/explorations/conversations/run_1");
    expect(run?.updatedAt).not.toBe("刚刚");
    expect(run?.title).toBe("抖音订单占比探索");
    expect(run?.messages.some((message) => message.body.includes("需要确认用户 ID 口径"))).toBe(true);
  });
});

describe("deleteKnowledge", () => {
  it("calls the knowledge delete API when the backend is configured", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    const deleted = await deleteKnowledge("kn_1");

    expect(deleted).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/knowledge/kn_1", { method: "DELETE" });
  });

  it("does not pretend knowledge deletion succeeded when no backend is configured", async () => {
    const deleted = await deleteKnowledge("kn_local");

    expect(deleted).toBe(false);
  });
});

describe("listKnowledge", () => {
  it("keeps evidence references and source run metadata from the backend", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        records: [
          {
            id: "kn_1",
            title: "首购后 30 天复购率",
            question: "首购后 30 天复购率怎么算？",
            scope: "剃须刀品类",
            verification: "报表和 DM 宽表核验",
            evidence_refs: ["复购分析.cpt", "dm.rebuy"],
            run_id: "run_1",
            created_at: "2026-07-27T12:00:00Z",
            conclusion: "按会员 ID 去重。",
          },
        ],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const records = await listKnowledge();

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/knowledge?limit=50");
    expect(records[0]).toMatchObject({
      id: "kn_1",
      title: "首购后 30 天复购率",
      question: "首购后 30 天复购率怎么算？",
      verification: "报表和 DM 宽表核验",
      evidenceRefs: ["复购分析.cpt", "dm.rebuy"],
      runId: "run_1",
    });
  });
});

const knowledgeExploration: Exploration = {
  id: "run_knowledge",
  title: "首购后 30 天复购率",
  agent: "知识探索 Agent",
  status: "已完成",
  updatedAt: "刚刚",
  resources: 2,
  summary: "经营指标探索",
  messages: [
    { id: "user", role: "user", body: "首购后 30 天复购率怎么算？" },
    {
      id: "evidence",
      role: "agent",
      title: "资源库命中",
      body: "找到候选资源。",
      details: [{ label: "候选资源", items: ["复购分析.cpt", "dm.rebuy"] }],
    },
    {
      id: "knowledge",
      role: "agent",
      title: "可沉淀结论",
      body: "按会员 ID 去重，排除未支付订单。",
      details: [{ label: "沉淀范围", items: ["剃须刀品类", "消费者复购"] }],
      action: "沉淀为知识",
    },
  ],
};

describe("saveKnowledgeFromExploration", () => {
  it("builds a knowledge payload from an exploration conclusion", () => {
    const payload = buildKnowledgePayload(knowledgeExploration, knowledgeExploration.messages[2]);

    expect(payload.title).toBe("首购后 30 天复购率");
    expect(payload.question).toBe("首购后 30 天复购率怎么算？");
    expect(payload.conclusion).toBe("按会员 ID 去重，排除未支付订单。");
    expect(payload.scope).toBe("剃须刀品类、消费者复购");
    expect(payload.evidence_refs).toEqual(["复购分析.cpt", "dm.rebuy"]);
  });

  it("posts the knowledge payload when the backend is configured", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "kn_1",
        title: "首购后 30 天复购率",
        scope: "剃须刀品类、消费者复购",
        verification: "可沉淀结论",
        created_at: "2026-07-27T12:00:00Z",
        conclusion: "按会员 ID 去重，排除未支付订单。",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const saved = await saveKnowledgeFromExploration(knowledgeExploration, knowledgeExploration.messages[2]);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/knowledge",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).evidence_refs).toEqual(["复购分析.cpt", "dm.rebuy"]);
    expect(saved?.id).toBe("kn_1");
    expect(saved?.verified).toBe("2026-07-27");
    expect(saved?.evidenceRefs).toEqual(["复购分析.cpt", "dm.rebuy"]);
    expect(saved?.runId).toBe("run_knowledge");
  });

  it("does not create local demo knowledge when no backend is configured", async () => {
    const saved = await saveKnowledgeFromExploration(knowledgeExploration, knowledgeExploration.messages[2]);

    expect(saved).toBeNull();
  });
});

describe("getRuntimeStatus", () => {
  it("returns a backend disconnected status when no backend URL is configured", async () => {
    const status = await getRuntimeStatus();

    expect(status.connected).toBe(false);
    expect(status.ready).toBe(false);
    expect(status.checks[0].message).toContain("后端未连接");
  });

  it("loads runtime readiness from the backend", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        env_file: "E:/repo/.env",
        env_loaded: true,
        ready: false,
        checks: [
          { name: "mysql", ok: false, message: "MySQL 只读连接信息不完整。", detail: "missing=GENBI_DB_PASSWORD" },
        ],
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const status = await getRuntimeStatus();

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/runtime/status");
    expect(status.connected).toBe(true);
    expect(status.envLoaded).toBe(true);
    expect(status.checks[0].detail).toContain("GENBI_DB_PASSWORD");
  });
});

describe("readResourceExcerpt", () => {
  it("loads a bounded resource excerpt from the backend", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        resource_id: "res_1",
        relative_path: "LR/SALES/复购分析.cpt",
        section: "match",
        start_line: 10,
        end_line: 12,
        truncated: true,
        encoding: "utf-8",
        text: "select * from dm.rebuy",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const excerpt = await readResourceExcerpt("res_1", "复购分析.cpt");
    const url = new URL(fetchMock.mock.calls[0][0] as string);

    expect(url.pathname).toBe("/api/resources/res_1/excerpt");
    expect(url.searchParams.get("section")).toBe("match");
    expect(url.searchParams.get("max_lines")).toBe("80");
    expect(excerpt?.resourceId).toBe("res_1");
    expect(excerpt?.startLine).toBe(10);
    expect(excerpt?.truncated).toBe(true);
  });
});

describe("readRunTrace", () => {
  const runTracePayload = {
    run_id: "run_1",
    title: "首购后 30 天复购率",
    status: "completed",
    question: "首购后 30 天复购率怎么算？",
    started_at: "2026-07-27T12:00:00Z",
    completed_at: "2026-07-27T12:00:02Z",
    duration_ms: 2345,
    event_count: 8,
    tool_call_count: 2,
    failed_tool_call_count: 0,
    agent_message_count: 3,
    token_usage: { input_tokens: 1000, output_tokens: 500, total_tokens: 1500 },
    cost: { input_usd: 0.0004, output_usd: 0.0008, total_usd: 0.0012 },
    error: null,
  };

  it("loads a run trace summary from the backend", async () => {
    process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://localhost:8000";
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => runTracePayload,
    });
    vi.stubGlobal("fetch", fetchMock);

    const trace = await readRunTrace("run_1");

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/explorations/run-traces/run_1");
    expect(trace?.status).toBe("已完成");
    expect(trace?.metrics).toContainEqual({ label: "耗时", value: "2.35 s" });
    expect(trace?.metrics).toContainEqual({ label: "Token", value: "1,500" });
    expect(trace?.metrics).toContainEqual({ label: "成本", value: "$0.001200" });
  });

  it("maps failed traces into readable status and error fields", () => {
    const trace = mapRunTraceSummary({
      ...runTracePayload,
      status: "failed",
      duration_ms: null,
      cost: { total_usd: null },
      error: "OPENAI_API_KEY is required",
    });

    expect(trace.status).toBe("失败");
    expect(trace.error).toContain("OPENAI_API_KEY");
    expect(trace.metrics).toContainEqual({ label: "耗时", value: "未知" });
    expect(trace.metrics).toContainEqual({ label: "成本", value: "未估算" });
  });
});

describe("filterResources", () => {
  it("filters resources by type and search text", () => {
    const resources = [
      { id: "r1", type: "报表" as const, name: "销售总览.cpt", location: "LR/SALES", description: "销售报表" },
      { id: "r2", type: "ETL" as const, name: "dm_sales.hpl", location: "DM", description: "销售宽表" },
      { id: "r3", type: "SQL" as const, name: "inventory.sql", location: "SQL", description: "库存查询" },
    ];

    expect(filterResources(resources, "销售", "全部").map((item) => item.id)).toEqual(["r1", "r2"]);
    expect(filterResources(resources, "销售", "ETL").map((item) => item.id)).toEqual(["r2"]);
    expect(filterResources(resources, "销售", "SQL")).toEqual([]);
  });
});

describe("findResourceByEvidenceRef", () => {
  const resources = [
    { id: "r1", type: "报表" as const, name: "剃须刀复购分析.cpt", location: "LR/SALES", description: "复购报表" },
    { id: "r2", type: "数据表" as const, name: "dm.dm_consr_shaver_rebuy_analysis_v2", location: "Doris / dm", description: "复购宽表" },
  ];

  it("matches evidence references against resource names and locations", () => {
    expect(findResourceByEvidenceRef(resources, "复购分析.cpt")?.id).toBe("r1");
    expect(findResourceByEvidenceRef(resources, "dm.dm_consr_shaver_rebuy_analysis_v2")?.id).toBe("r2");
    expect(findResourceByEvidenceRef(resources, "LR/SALES")?.id).toBe("r1");
  });

  it("returns null when the evidence reference is not in the current resource list", () => {
    expect(findResourceByEvidenceRef(resources, "missing_resource.sql")).toBeNull();
  });
});

describe("buildResourceExplorationPrompt", () => {
  it("turns a resource into an exploration question", () => {
    const prompt = buildResourceExplorationPrompt({
      id: "res_1",
      type: "报表",
      name: "销售总览.cpt",
      location: "LR/SALES",
      description: "销售报表",
    });

    expect(prompt).toContain("销售总览.cpt");
    expect(prompt).toContain("数据集、表引用和口径");
  });
});

describe("resource profile helpers", () => {
  it("formats file sizes for readable resource profiles", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.00 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.00 MB");
    expect(formatBytes(-1)).toBe("未知");
  });

  it("maps resource detail metadata into profile items", () => {
    const items = buildResourceProfileItems({
      status: "summarized",
      truncated_summary: true,
      size_bytes: 1536,
      modified_at: "2026-07-27T11:22:33+08:00",
      warnings: ["too_large"],
    });

    expect(items).toContainEqual({ label: "读取状态", value: "summarized" });
    expect(items).toContainEqual({ label: "文件大小", value: "1.50 KB" });
    expect(items).toContainEqual({ label: "文件更新时间", value: "2026-07-27 11:22:33" });
    expect(items).toContainEqual({ label: "摘要范围", value: "已按限制截断" });
    expect(items).toContainEqual({ label: "读取告警", value: "1 条" });
  });
});

describe("buildResourceSignalGroups", () => {
  it("maps resource summary signals into readable groups", () => {
    const groups = buildResourceSignalGroups({
      table_refs: ["dm.sales"],
      read_table_refs: ["dm.sales"],
      write_table_refs: ["ads.sales_summary"],
      field_candidates: ["order_id"],
      finereport: {
        dataset_candidates: ["ds_sales"],
        parameter_candidates: ["start_date"],
        lineage_table_refs: ["ads.sales_report"],
        field_candidates: ["gmv"],
        formula_candidates: ["sum(gmv)"],
      },
      hop: {
        action_or_transform_names: ["写入销售宽表"],
        lineage_table_refs: ["dwd.sales_order"],
        read_table_refs: ["dwd.sales_order"],
        field_candidates: ["paid_time"],
      },
      dictionary: {
        field_candidates: ["member_id"],
      },
      named_nodes: [{ tag: "TableData", attribute: "name", value: "销售数据集" }],
    });

    expect(groups.map((group) => group.label)).toContain("表引用");
    expect(groups.find((group) => group.label === "表引用")?.items).toEqual(["dm.sales", "ads.sales_report", "dwd.sales_order"]);
    expect(groups.find((group) => group.label === "读表")?.items).toEqual(["dm.sales", "dwd.sales_order"]);
    expect(groups.find((group) => group.label === "写表")?.items).toEqual(["ads.sales_summary"]);
    expect(groups.find((group) => group.label === "数据集候选")?.items).toEqual(["ds_sales"]);
    expect(groups.find((group) => group.label === "参数候选")?.items).toEqual(["start_date"]);
    expect(groups.find((group) => group.label === "Hop 节点")?.items).toEqual(["写入销售宽表"]);
    expect(groups.find((group) => group.label === "输出字段")?.items).toEqual(["order_id", "paid_time"]);
    expect(groups.find((group) => group.label === "字段候选")?.items).toEqual(["gmv", "member_id"]);
    expect(groups.find((group) => group.label === "表达式候选")?.items).toEqual(["sum(gmv)"]);
    expect(groups.find((group) => group.label === "命名节点")?.items[0]).toContain("销售数据集");
  });
});
