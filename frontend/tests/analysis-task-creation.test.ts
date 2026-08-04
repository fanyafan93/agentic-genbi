/**
 * @vitest-environment jsdom
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { useTaskCreation } from "../src/modules/analysis/hooks/use-task-creation";

import type { BackendAnalysisThreadSummary } from "../src/modules/analysis/agentClients/backendClient";

type CreatedTask = BackendAnalysisThreadSummary;

const { createTaskMock } = vi.hoisted(() => ({
  // The hook calls ``createBackendAnalysisTask`` which the real
  // backend client wraps to return the unwrapped task object. The
  // mock here mirrors the *post-wrap* shape so the hook's contract
  // is what we exercise.
  createTaskMock: vi.fn<(...args: unknown[]) => Promise<BackendAnalysisThreadSummary>>(),
}));

vi.mock("../src/modules/analysis/agentClients/backendClient", async () => {
  const real = await vi.importActual<typeof import("../src/modules/analysis/agentClients/backendClient")>(
    "../src/modules/analysis/agentClients/backendClient",
  );
  return {
    ...real,
    createBackendAnalysisTask: createTaskMock,
  };
});

beforeEach(() => {
  createTaskMock.mockReset();
  process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME = "backend";
  process.env.NEXT_PUBLIC_GENBI_API_BASE_URL = "http://backend.test";
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.NEXT_PUBLIC_ANALYSIS_AGENT_RUNTIME;
  delete process.env.NEXT_PUBLIC_GENBI_API_BASE_URL;
});

describe("analysis task creation", () => {
  test("creating=true while POST is in flight; no client-side taskId is fabricated", async () => {
    let release: (() => void) | undefined;
    const inflight = new Promise<CreatedTask>((resolve) => {
      release = () => resolve({
        id: "analysis_thread_real",
        title: "新分析",
        status: "waiting_for_question",
        updatedAt: "2026-08-04T10:00:00Z",
      });
    });
    createTaskMock.mockReturnValueOnce(inflight);

    const { result } = renderHook(() => useTaskCreation());

    expect(result.current.creating).toBe(false);

    // Kick off the create but don't await it; we want to inspect
    // ``creating=true`` while the POST is still in flight.
    let settlePromise!: Promise<CreatedTask | null>;
    act(() => {
      settlePromise = result.current.createTask("新分析");
    });

    // While the POST is in flight, the hook reports ``creating=true``
    // and the caller has not yet received a taskId. The UI is
    // expected to display a "正在创建" placeholder during this window.
    await waitFor(() => {
      expect(result.current.creating).toBe(true);
    });

    // Resolving the POST gives us a single, backend-issued taskId.
    await act(async () => {
      release?.();
      const settledTask = await settlePromise!;
      expect(settledTask).not.toBeNull();
      expect(settledTask?.id).toBe("analysis_thread_real");
      expect(settledTask?.id.startsWith("draft_")).toBe(false);
    });

    await waitFor(() => {
      expect(result.current.creating).toBe(false);
    });
  });

  test("error path keeps the creating flag false and surfaces the message", async () => {
    createTaskMock.mockRejectedValueOnce(new Error("network down"));
    const { result } = renderHook(() => useTaskCreation());

    let createdTask: CreatedTask | null | undefined = undefined;
    await act(async () => {
      createdTask = await result.current.createTask("新分析");
    });

    expect(createdTask).toBeNull();
    expect(result.current.creating).toBe(false);
    expect(result.current.error).toBe("network down");
  });
});
