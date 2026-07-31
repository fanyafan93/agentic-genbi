import type { AgentClient, AgentEvent, AgentInput, AnalysisMode } from "./types";
import { channelScript } from "./scripts/channel";

function delay(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

async function* streamText(text: string, perChar = 22): AsyncGenerator<AgentEvent> {
  const nodeId = `agent-${Date.now()}`;
  yield { type: "agent", nodeId, content: "", mode: "delta" };
  for (const char of text) {
    await delay(perChar);
    yield { type: "tokens", nodeId, text: char };
  }
}

async function* streamAnalysis(text: string, labels: string[], perChar = 22): AsyncGenerator<AgentEvent> {
  const nodeId = `agent-${Date.now()}`;
  yield { type: "agent", nodeId, content: "", mode: "delta" };
  for (const label of labels) {
    yield { type: "step", label, state: "running", nodeId };
    await delay(420);
    yield { type: "step", label, state: "done", nodeId };
  }
  for (const char of text) {
    await delay(perChar);
    yield { type: "tokens", nodeId, text: char };
  }
}

function newId(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

type RuntimeState = {
  runId: string;
  askCount: number;
  lastUser: string;
  analysisMode: AnalysisMode;
  askQueue: { question: string; options: { id: string; label: string }[] }[];
};

export class MockAgentClient implements AgentClient {
  private state: RuntimeState = { runId: "demo", askCount: 0, lastUser: "", analysisMode: "quick", askQueue: [] };

  async *send(input: AgentInput): AsyncIterable<AgentEvent> {
    if (input.kind === "reset") {
      this.state = { runId: newId("run"), askCount: 0, lastUser: "", analysisMode: "quick", askQueue: [] };
      yield { type: "conversation-init", runId: this.state.runId };
      return;
    }

    if (input.kind === "start") {
      this.state = { runId: newId("run"), askCount: 0, lastUser: input.question ?? channelScript.startQuestion, analysisMode: input.analysisMode ?? "quick", askQueue: [] };
      yield { type: "conversation-init", runId: this.state.runId };
      yield { type: "user", nodeId: newId("user"), content: this.state.lastUser };

      if (this.state.analysisMode === "deep") {
        yield* streamAnalysis("我会按深度分析推进。这个问题需要先补齐口径，再生成 SQL、图表、报告和可复用资产。", ["理解业务问题类型", "检索业务语义库", "语义查证", "读取报表语义 / 字段 / 血缘 / SQL 示例", "列出待确认口径"]);
        yield { type: "ask", nodeId: newId("ask"), question: channelScript.nodes.firstAsk.question, options: channelScript.nodes.firstAsk.options };
        this.state.askQueue.push(channelScript.nodes.firstAsk);
      } else {
        yield* streamAnalysis("我先按快速分析给出可用初稿：已基于业务语义库里的语义模型和已确认业务知识生成 SQL、图表、报告摘要，并把未确认口径标成假设。", ["理解业务问题", "快速检索业务语义库", "语义查证", "生成候选 SQL", "生成图表和初稿报告", "标注假设与风险"]);
        yield { type: "artifact", path: "reports/quick_report.html", kind: "html" };
        yield { type: "artifact", path: "queries/quick_candidate.sql", kind: "sql" };
        yield { type: "artifact", path: "charts/channel_share.chart.json", kind: "json" };
        yield { type: "artifact", path: "notes/assumptions.md", kind: "markdown" };
        yield { type: "artifact", path: "definitions/channel_sales_metric.md", kind: "markdown" };
        yield { type: "artifact", path: "rules/order_scope_rule.md", kind: "markdown" };
        yield { type: "artifact", path: "paths/channel_analysis_path.md", kind: "markdown" };
        yield { type: "artifact", path: "dashboards/channel_overview.dashboard.json", kind: "json" };
      }
      yield { type: "done" };
      return;
    }

    if (input.kind === "message") {
      this.state.lastUser = input.content;
      this.state.analysisMode = input.analysisMode ?? this.state.analysisMode;
      yield { type: "user", nodeId: newId("user"), content: input.content };
      if (/skill\.md|skill|技能|复用/.test(input.content.toLowerCase())) {
        yield* streamAnalysis("我会把这次成功分析整理成 Skill.md 草稿：先明确适用场景，再列出必须确认的口径、推荐步骤、可引用资产和复用权限。", ["整理适用场景", "提取需要确认的业务口径", "引用 SQL / 图表 / 报告资产", "生成可复用分析方法", "标注复用权限"]);
        yield { type: "artifact", path: "skills/analysis_skill.md", kind: "markdown" };
        yield { type: "done" };
        return;
      }
      yield* streamAnalysis(this.state.analysisMode === "deep"
        ? "我会在当前分析任务里继续改资产：先保留已有 SQL 和图表版本，再补充语义查证证据，最后更新报告与 Skill 草稿；如果用户确认新口径，我会把它沉淀为业务知识。"
        : "我先直接改当前资产草稿，并把仍未确认的业务假设继续保留在说明里；确认后的规则可沉淀为业务知识。",
        this.state.analysisMode === "deep"
          ? ["读取当前资产版本", "检索业务语义库", "语义查证", "修改 SQL / 图表 / 报告", "更新资产版本记录"]
          : ["读取当前资产", "快速语义查证", "快速修改图表和结论", "更新资产草稿"]);
      yield { type: "artifact", path: "reports/updated_report.html", kind: "html" };
      yield { type: "artifact", path: "queries/revised_query.sql", kind: "sql" };
      yield { type: "artifact", path: "paths/channel_analysis_path.md", kind: "markdown" };
      if (/python|预测|异常|聚类|相关/.test(input.content.toLowerCase())) {
        yield { type: "artifact", path: "scripts/analysis_notebook.py", kind: "python" };
      }
      yield { type: "done" };
      return;
    }

    if (input.kind === "reply") {
      const current = this.state.askQueue.shift();
      yield { type: "user", nodeId: newId("user"), content: current?.options.find((o) => o.id === input.optionId)?.label ?? input.optionId };

      if (!current) {
        yield* streamText("继续探索吧，有什么想细看的内容可以告诉我。", 22);
        yield { type: "done" };
        return;
      }

      yield* streamText("好的，按你的选择继续展开。", 22);

      if (current.question === channelScript.nodes.firstAsk.question) {
        yield* streamAnalysis("关键发现：线上直营占比 42.0%，社交电商同比增速 44.7%（基数小）。", ["检索业务语义库", "语义查证", "读取数据表", "校验口径", "生成 SQL", "渲染图表"]);
        yield { type: "ask", nodeId: newId("ask"), question: channelScript.nodes.followAsk.question, options: channelScript.nodes.followAsk.options };
        this.state.askQueue.push(channelScript.nodes.followAsk);
      } else if (current.question === channelScript.nodes.followAsk.question) {
        const replyMap: Record<string, string> = {
          继续: "继续路径：已下钻到区域，并尝试拆分新老用户，新客表现明显优于老客。",
          报告: "已生成最新一版报告，标题为《渠道销售占比分析·2026-07》。",
          审批: "已为你起草一份预算调拨审批，可直接走流程。",
        };
        yield* streamText(replyMap[input.optionId] ?? "已收到你的选择。", 22);
      }

      yield { type: "done" };
      return;
    }

    yield { type: "done" };
  }
}
