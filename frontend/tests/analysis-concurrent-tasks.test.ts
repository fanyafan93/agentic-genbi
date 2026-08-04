/**
 * Multi-task isolation contract tests.
 *
 * The product bug we're locking down: opening one task previously threw a
 * single, shared ``AbortController`` out of the client. A new request for
 * task B could overwrite task A's controller, and the shared "in-flight"
 * flag never knew which task to cancel. Switching tasks therefore
 * interrupted SSE streams that had nothing to do with the task being
 * switched away from.
 *
 * Two layers of guarantee must hold:
 *  1. ``BackendAnalysisAgentClient`` passes a distinct ``AbortSignal`` per
 *     ``send`` call and never aborts a sibling's signal.
 *  2. ``useFlow`` owns a per-task controller map and forwards the right
 *     signal to the client, so cancelling task A leaves task B's stream
 *     intact.
 *
 * These tests deliberately bypass the unit-level ``mockSend`` hammer and
 * instead stub ``fetch`` so we exercise the real client + the real
 * streaming loop.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { BackendAnalysisAgentClient } from "../src/modules/analysis/agentClients/backendClient";
import type { AgentEvent } from "../src/modules/analysis/agentClients/types";
import { useFlow } from "../src/modules/analysis/hooks/use-flow";
import type { FlowNode } from "../src/modules/analysis/hooks/use-turn-execution";

/* eslint-disable @typescript-eslint/no-explicit-any */

const EMPTY_FLOW: FlowNode[] = [];

type RecordedFetch = {
  url: string;
  body: { taskId: string; threadId: string; question: string };
  signal: AbortSignal;
  /** Resolves with the SSE chunk stream the client should read. */
  releaseStream: () => void;
  /** Awaited by the client; resolves when the stream is "complete". */
  streamClosed: Promise<void>;
  /** Emits events when the release is satisfied. */
  stream: ReadableStream<Uint8Array>;
  /** Used by ``pushEvent`` to write raw bytes. The fetch factory fills this
   *  before the test gets hold of the entry. */
  controller: ReadableStreamDefaultController<Uint8Array> | null;
};

function sseEventBlock(event: Record<string, unknown>): string {
  return `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

function startMockFetch(record: (entry: RecordedFetch) => void) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const body = JSON.parse(init?.body as string) as Record<string, unknown>;
    const signal = (init?.signal ?? new AbortController().signal) as AbortSignal;

    let release: () => void = () => {};
    const streamClosed = new Promise<void>((resolve) => { release = resolve; });

    // Used by the streamed chunks. The test feeds bytes through ``push``
    // and finally calls ``close``.
    const ctrlHolder = { current: null as ReadableStreamDefaultController<Uint8Array> | null };
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        ctrlHolder.current = controller;
      },
    });

    const entry: RecordedFetch = {
      url,
      body: {
        taskId: String((body.metadata as { frontend_task_id?: unknown } | undefined)?.frontend_task_id ?? ""),
        // The client routes turns via the URL, not the body, so pull
        // ``threadId`` from the path to make the recorded entry self-
        // contained for assertions.
        threadId: (() => {
          const match = url.match(/\/api\/analysis\/threads\/([^/]+)\/turns\/stream/);
          return match ? decodeURIComponent(match[1]) : "";
        })(),
        question: String(body.question ?? ""),
      },
      signal,
      controller: null,
      releaseStream: () => {
        try {
          ctrlHolder.current?.close();
        } catch {
          // The stream may already be closed; suppress.
        }
        release();
      },
      streamClosed,
      stream,
    };
    record(entry);

    (entry as { controller: ReadableStreamDefaultController<Uint8Array> | null }).controller = ctrlHolder.current;
    entry.controller = ctrlHolder.current;

    // When the caller aborts the fetch, mirror that on the response
    // stream so the SSE reader loop unblocks deterministically. Without
    // this the reader parks on a never-closing stream and the test
    // hangs.
    signal.addEventListener("abort", () => {
      try {
        ctrlHolder.current?.close();
      } catch {
        // ignore
      }
      release();
    });

    return new Response(stream, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  });
}

function pushEvent(entry: RecordedFetch, event: Record<string, unknown>) {
  const block = sseEventBlock(event);
  entry.controller?.enqueue(new TextEncoder().encode(block));
}

function closeStream(entry: RecordedFetch) {
  entry.releaseStream();
}

beforeEach(() => {
  vi.useRealTimers();
  // ``BackendAnalysisAgentClient`` is only constructable through the
  // factory when the backend runtime env is set; the test stubs ``fetch``
  // directly so we don't need a real backend base URL.
  process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME = "backend";
  process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
  (globalThis as { __GENBI_DEBUG_HOOK__?: (event: AgentEvent, currentNodes: FlowNode[]) => void }).__GENBI_DEBUG_HOOK__ = (event, currentNodes) => {
     console.log("[hook]", event.type, event.threadId, "nodes:", currentNodes.map((node) => node.id));
     if (event.type === "user") {
       const pendingIndex = currentNodes.findIndex((node) => node.id === "user-pending");
       const next = pendingIndex >= 0
         ? currentNodes.map((node, index) => (index === pendingIndex ? { id: event.nodeId, role: "user", content: event.content } : node))
         : [...currentNodes, { id: event.nodeId, role: "user", content: event.content }];
       console.log("[hook] about to setNodes next:", next.map((node) => node.id));
     }
   };
});

afterEach(() => {
  delete (globalThis as { __GENBI_DEBUG_HOOK__?: (event: AgentEvent, currentNodes: FlowNode[]) => void }).__GENBI_DEBUG_HOOK__;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("concurrent-task isolation (client layer)", () => {
  test("each send() gets its own AbortSignal; aborting one does not touch the other", async () => {
    const recorded: RecordedFetch[] = [];
    const fetchMock = startMockFetch((entry) => recorded.push(entry));
    vi.stubGlobal("fetch", fetchMock);

    const client = new BackendAnalysisAgentClient("http://backend.test");

    const aController = new AbortController();
    const bController = new AbortController();
    const aPromise = (async () => {
      const events: AgentEvent[] = [];
      for await (const event of client.send({
        kind: "message",
        taskId: "task_a",
        threadId: "thread_a",
        signal: aController.signal,
        content: "first task",
      })) {
        events.push(event);
      }
      return events;
    })();
    const bPromise = (async () => {
      const events: AgentEvent[] = [];
      for await (const event of client.send({
        kind: "message",
        taskId: "task_b",
        threadId: "thread_b",
        signal: bController.signal,
        content: "second task",
      })) {
        events.push(event);
      }
      return events;
    })();

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    expect(recorded).toHaveLength(2);
    const aFetch = recorded[0];
    const bFetch = recorded[1];
    expect(aFetch.signal).not.toBe(bFetch.signal);
    expect(aFetch.signal.aborted).toBe(false);
    expect(bFetch.signal.aborted).toBe(false);

    // Cancel task A only. Task B's fetch must remain untouched.
    aController.abort();
    await new Promise((resolve) => globalThis.setTimeout(resolve, 0));
    expect(aFetch.signal.aborted).toBe(true);
    expect(bFetch.signal.aborted).toBe(false);

    // Finish task B without ever aborting.
    pushEvent(bFetch, {
      type: "turn/started",
      turn_id: "turn_b",
      payload: {
        conversation_id: "thread_b",
        thread_id: "thread_b",
        turn_id: "turn_b",
        question: "second task",
      },
    });
    pushEvent(bFetch, {
      type: "item/agentMessage/delta",
      turn_id: "turn_b",
      payload: { turn_id: "turn_b", thread_id: "thread_b", codex_item_id: "msg_b", delta: "hello " },
    });
    pushEvent(bFetch, {
      type: "item/agentMessage/delta",
      turn_id: "turn_b",
      payload: { turn_id: "turn_b", thread_id: "thread_b", codex_item_id: "msg_b", delta: "world" },
    });
    pushEvent(bFetch, {
      type: "turn/completed",
      turn_id: "turn_b",
      payload: { turn_id: "turn_b", thread_id: "thread_b", status: "completed" },
    });
    closeStream(bFetch);

    const bEvents = await bPromise;
    await expect(aPromise).resolves.toEqual([]);

    // Task B's full token stream reached the caller.
    const tokens = bEvents.filter((event) => event.type === "tokens").map((event) => {
      if (event.type !== "tokens") throw new Error("expected tokens");
      return event.text;
    });
    expect(tokens.join("")).toBe("hello world");
    expect(bEvents.at(-1)).toMatchObject({ type: "done", threadId: "thread_b" });
  });
});

describe("concurrent-task isolation (useFlow end-to-end)", () => {
  test("cancelling task A leaves task B's fetch signal and stream intact", async () => {
    const recorded: RecordedFetch[] = [];
    const fetchMock = startMockFetch((entry) => recorded.push(entry));
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(() => useFlow(null, EMPTY_FLOW));

    // Start task A first. The mock fetch is wired but hasn't pushed any
    // bytes yet, so the SSE loop is parked waiting for the first chunk.
    act(() => {
      void result.current.start("first task", "task_a", "thread_a");
    });
    act(() => {
      void result.current.send("second task", "task_b", "thread_b");
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    const aFetch = recorded.find((entry) => entry.body.taskId === "task_a");
    const bFetch = recorded.find((entry) => entry.body.taskId === "task_b");
    if (!aFetch || !bFetch) throw new Error("expected both fetches to be recorded");

    // Sanity check: both fetches target the right URL and carry the
    // right per-task metadata.
    expect(aFetch.url).toBe("http://backend.test/api/analysis/threads/thread_a/turns/stream");
    expect(bFetch.url).toBe("http://backend.test/api/analysis/threads/thread_b/turns/stream");
    expect(aFetch.body).toMatchObject({ taskId: "task_a", threadId: "thread_a", question: "first task" });
    expect(bFetch.body).toMatchObject({ taskId: "task_b", threadId: "thread_b", question: "second task" });
    expect(aFetch.signal.aborted).toBe(false);
    expect(bFetch.signal.aborted).toBe(false);

    // Push the user echo for task A. The real backend emits
    // ``turn/started``; ``mapBackendEvents`` turns it into a ``user``
    // event so the optimistic ``user-pending`` placeholder is replaced.
    pushEvent(aFetch, {
      type: "turn/started",
      turn_id: "turn_a",
      payload: {
        conversation_id: "thread_a",
        thread_id: "thread_a",
        turn_id: "turn_a",
        question: "first task",
      },
    });
    // Yield to the microtask queue so the SSE reader loop runs and
    // the React state update commits before the test asserts.
    await act(async () => {
      await new Promise((resolve) => globalThis.setTimeout(resolve, 50));
    });
    console.log("[test] direct nodes after act:", result.current.nodes.map((node) => node.id));
    // Trigger a forced re-render so ``result.current`` is refreshed.
    rerender();
    console.log("[test] nodes after rerender:", result.current.nodes.map((node) => node.id));
    await waitFor(() => {
      const ids = result.current.nodes.map((node) => node.id);
      console.log("[test] nodes after user echo:", ids);
      const sawUserTurnA = ids.includes("user-turn_a");
      const userPendingCleared = !ids.includes("user-pending");
      expect(sawUserTurnA && userPendingCleared).toBe(true);
    }, { timeout: 5000, interval: 50 });

    // Cancel task A. The signal MUST transition to aborted; task B's
    // signal MUST remain live.
    act(() => {
      result.current.stop("task_a");
    });
    await waitFor(() => {
      expect(aFetch.signal.aborted).toBe(true);
    });
    expect(bFetch.signal.aborted).toBe(false);

    // Drain task A's stream so the client doesn't leak the reader.
    closeStream(aFetch);

    // Push task B's full stream and confirm every delta reaches the UI.
    pushEvent(bFetch, {
      type: "turn/started",
      turn_id: "turn_b",
      payload: {
        conversation_id: "thread_b",
        thread_id: "thread_b",
        turn_id: "turn_b",
        question: "second task",
      },
    });
    pushEvent(bFetch, {
      type: "item/agentMessage/delta",
      turn_id: "turn_b",
      payload: { turn_id: "turn_b", thread_id: "thread_b", codex_item_id: "msg_b", delta: "alpha " },
    });
    pushEvent(bFetch, {
      type: "item/agentMessage/delta",
      turn_id: "turn_b",
      payload: { turn_id: "turn_b", thread_id: "thread_b", codex_item_id: "msg_b", delta: "beta " },
    });
    pushEvent(bFetch, {
      type: "item/agentMessage/delta",
      turn_id: "turn_b",
      payload: { turn_id: "turn_b", thread_id: "thread_b", codex_item_id: "msg_b", delta: "gamma" },
    });
    pushEvent(bFetch, {
      type: "turn/completed",
      turn_id: "turn_b",
      payload: { turn_id: "turn_b", thread_id: "thread_b", status: "completed" },
    });
    closeStream(bFetch);

    await waitFor(() => {
      const tokens = result.current.nodes
        .filter((node) => node.role === "agent")
        .map((node) => (node.role === "agent" ? node.content : ""));
      expect(tokens.join("")).toBe("alpha beta gamma");
    });

    // Task B's signal stays aborted=false even after the UI settled.
    expect(bFetch.signal.aborted).toBe(false);

    // Sanity: only one of the two fetches was aborted.
    const abortedCount = recorded.filter((entry) => entry.signal.aborted).length;
    expect(abortedCount).toBe(1);
  });
});
