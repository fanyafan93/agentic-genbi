import type { AgentClient, AgentEvent, AgentInput } from "./types";
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

async function* streamSteps(labels: string[]): AsyncGenerator<AgentEvent> {
  for (const label of labels) {
    yield { type: "step", label, state: "running" };
    await delay(420);
    yield { type: "step", label, state: "done" };
  }
}

function newId(prefix: string) {
  return `${prefix}-${Math.random().toString(36).slice(2, 9)}`;
}

type RuntimeState = {
  runId: string;
  askCount: number;
  lastUser: string;
  askQueue: { question: string; options: { id: string; label: string }[] }[];
};

export class MockAgentClient implements AgentClient {
  private state: RuntimeState = { runId: "demo", askCount: 0, lastUser: "", askQueue: [] };

  async *send(input: AgentInput): AsyncIterable<AgentEvent> {
    if (input.kind === "reset") {
      this.state = { runId: newId("run"), askCount: 0, lastUser: "", askQueue: [] };
      yield { type: "session-init", runId: this.state.runId };
      return;
    }

    if (input.kind === "start") {
      this.state = { runId: newId("run"), askCount: 0, lastUser: input.question ?? channelScript.startQuestion, askQueue: [] };
      yield { type: "session-init", runId: this.state.runId };
      yield { type: "user", nodeId: newId("user"), content: this.state.lastUser };

      yield* streamSteps(["识别业务口径", "查询可用数据表", "生成并校验 SQL", "整理图表与结论"]);
      yield* streamText("我先理解需求、查询口径，并生成可校验 SQL。", 22);
      yield { type: "ask", nodeId: newId("ask"), question: channelScript.nodes.firstAsk.question, options: channelScript.nodes.firstAsk.options };
      this.state.askQueue.push(channelScript.nodes.firstAsk);
      yield { type: "done" };
      return;
    }

    if (input.kind === "message") {
      this.state.lastUser = input.content;
      yield { type: "user", nodeId: newId("user"), content: input.content };
      yield* streamText("我接着展开分析。先核对一下数据范围，再继续给出建议。", 22);
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
        yield* streamSteps(["读取数据表", "校验口径", "生成 SQL", "渲染图表"]);
        yield* streamText("关键发现：线上直营占比 42.0%，社交电商同比增速 44.7%（基数小）。", 22);
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
