/**
 * @vitest-environment jsdom
 */
import { afterEach, describe, expect, test, vi } from "vitest";
import { BackendAnalysisAgentClient } from "../src/modules/analysis/agentClients/backendClient";
import type { AgentEvent } from "../src/modules/analysis/agentClients/types";

async function collect<T>(items: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of items) {
    out.push(item);
  }
  return out;
}

function sseEvent(event: { type: string; turn_id: string; created_at?: string; payload?: Record<string, unknown> }) {
  const payload = {
    created_at: event.created_at ?? "2026-07-30T00:00:00Z",
    payload: event.payload ?? {},
    ...event,
  };
  return `event: ${event.type}\ndata: ${JSON.stringify(payload)}\n\n`;
}

describe("analysis backend client — empty input contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("start with no question yields an error event, never a default report", async () => {
    // The previous client used a hardcoded ``"分析一下渠道销售占比"``
    // fallback for any empty ``start`` question. That fabricated a
    // channel-sales report whenever the UI forgot to pass the
    // question. The contract now is: empty input is a programming
    // error; the client surfaces it and never calls fetch.
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    const events: AgentEvent[] = await collect(
      client.send({
        kind: "start",
        taskId: "task_empty",
        threadId: "thread_empty",
        signal: new AbortController().signal,
      }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
    // The client yields exactly two events: the error explaining
    // the empty input, then ``done`` so the loop terminates.
    expect(events.map((event) => event.type)).toEqual(["error", "done"]);
    expect(events[0]).toMatchObject({
      type: "error",
      message: expect.stringContaining("问题不能为空"),
    });
  });

  test("start with an explicit empty string question never reaches fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    await collect(
      client.send({
        kind: "start",
        taskId: "task_empty",
        threadId: "thread_empty",
        question: "",
        signal: new AbortController().signal,
      }),
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("start with a real question hits fetch and forwards turn events", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        sseEvent({
          type: "turn/started",
          turn_id: "turn_real",
          payload: { conversation_id: "thread_real", question: "real question" },
        }) + sseEvent({
          type: "turn/completed",
          turn_id: "turn_real",
          payload: { status: "completed" },
        }),
        { status: 200, headers: { "Content-Type": "text/event-stream" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");
    const events = await collect(
      client.send({
        kind: "start",
        taskId: "task_real",
        threadId: "thread_real",
        question: "real question",
        signal: new AbortController().signal,
      }),
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(body.question).toBe("real question");
    // The user echo (``turn/started`` carrying the question) plus the
    // terminal ``done`` are the two events the renderer needs to
    // paint the turn and move on. We do not assert the exact count
    // because mapBackendEvents may add intermediate helper events;
    // the contract is "the question we sent reaches the server".
    expect(events.at(-1)?.type).toBe("done");
    expect(events[0]).toMatchObject({ type: "user", content: "real question" });
  });
});
