// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { SystemRuntimePanel } from "@/modules/system/components/SystemRuntimePanel";

describe("SystemRuntimePanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("saves only execution policy fields and never writes model selection", async () => {
    const runtime = {
      provider: "minimax",
      model: "MiniMax-M3",
      connectionName: "minimax",
      connectionSource: "managed",
      enabled: true,
      approvalMode: "auto_review",
      sandbox: "read_only",
      defaultToolsEnabled: true,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ runtime }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ runtime }), { status: 200 }),
      );

    render(<SystemRuntimePanel />);
    await screen.findByText("运行服务正常");

    expect(screen.queryByText("默认模型")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "保存并应用" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const request = fetchMock.mock.calls[1]?.[1];
    expect(JSON.parse(String(request?.body))).toEqual({
      approvalMode: "auto_review",
      sandbox: "read_only",
      defaultToolsEnabled: true,
    });
  });
});
