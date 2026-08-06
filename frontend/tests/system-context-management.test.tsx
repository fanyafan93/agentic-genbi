// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { SystemContextPanel } from "@/modules/system/components/SystemContextPanel";

const contextPayload = {
  baseInstructions: {
    content: "",
    source: "codex_native",
    updatedAt: null,
  },
  systemPrompt: {
    content: "围绕用户提出的业务问题推进分析。",
    updatedAt: "2026-08-06T10:00:00.000Z",
  },
  runtime: {
    provider: "minimax",
    enabled: true,
    model: "MiniMax-M3",
    approvalMode: "auto_review",
    sandbox: "read_only",
    defaultToolsEnabled: false,
  },
  skills: [
    {
      name: "openai-docs",
      description: "读取 OpenAI 官方文档",
      scope: "system",
    },
  ],
  mcpServers: [
    {
      name: "GenBI_report",
      displayName: "GenBI Report",
      category: "system",
      transport: "stdio",
      command: "python",
      args: [],
      url: "",
      bearerTokenEnvVar: "",
      oauthClientId: "",
      oauthResource: "",
      environment: [],
      enabled: true,
      mutable: false,
      deletable: false,
      status: "trusted",
      permission: "report.write",
      trusted: true,
      approval: "trusted",
      tools: [
        {
          name: "create_report",
          description: "Create Report",
          permission: "report.write",
          trusted: true,
        },
      ],
      envKeys: [],
      message: "",
    },
  ],
};

describe("SystemContextPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("shows the ordered context sources without prompt version controls", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ context: contextPayload }), { status: 200 }),
    );

    render(<SystemContextPanel />);

    expect(await screen.findByRole("heading", { name: "上下文管理" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /上下文总览/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /内置基础指令/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /系统提示词/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /权限与环境/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Skills/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /MCP 工具/ })).toBeTruthy();
    expect(screen.queryByText("版本记录")).toBeNull();
    expect(screen.queryByRole("button", { name: /发布|回滚|草稿/ })).toBeNull();
  });

  test("saves a complete custom base instruction directly", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ context: contextPayload }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          context: {
            ...contextPayload,
            baseInstructions: {
              content: "你是 GenBI 企业数据分析助手。",
              source: "managed",
              updatedAt: "2026-08-06T11:00:00.000Z",
            },
          },
        }), { status: 200 }),
      );

    render(<SystemContextPanel />);
    await screen.findByRole("heading", { name: "上下文管理" });
    fireEvent.click(screen.getByRole("button", { name: /内置基础指令/ }));
    fireEvent.change(screen.getByLabelText("基础指令内容"), {
      target: { value: "你是 GenBI 企业数据分析助手。" },
    });
    fireEvent.click(screen.getByRole("button", { name: "保存基础指令" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/system/context",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          baseInstructions: "你是 GenBI 企业数据分析助手。",
        }),
      }),
    );
  });

  test("shows runtime skills and MCP tools as read-only context", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ context: contextPayload }), { status: 200 }),
    );

    render(<SystemContextPanel />);
    await screen.findByRole("heading", { name: "上下文管理" });

    fireEvent.click(screen.getByRole("button", { name: /权限与环境/ }));
    expect(screen.getByText("MiniMax-M3")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /保存.*策略/ })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Skills/ }));
    expect(screen.getByText("openai-docs")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /MCP 工具/ }));
    expect(screen.getByText("GenBI Report")).toBeTruthy();
    expect(screen.getByText("create_report")).toBeTruthy();
    expect(screen.queryByText("MYSQL_PASSWORD")).toBeNull();
  });
});
