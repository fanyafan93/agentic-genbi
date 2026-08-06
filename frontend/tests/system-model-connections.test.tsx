// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { SystemModelConnectionsPanel } from "@/modules/system/components/SystemModelConnectionsPanel";

const connections = [
  {
    id: "model-1",
    name: "minimax",
    displayName: "MiniMax 主连接",
    providerType: "minimax",
    model: "MiniMax-M3",
    baseUrl: "https://api.minimaxi.com/v1",
    enabled: true,
    isDefault: true,
    apiKeyConfigured: true,
    status: "ready",
    message: "连接可用",
    lastTestedAt: "2026-08-06T12:00:00.000Z",
    createdAt: "2026-08-06T10:00:00.000Z",
    updatedAt: "2026-08-06T12:00:00.000Z",
  },
  {
    id: "model-2",
    name: "openai-compatible",
    displayName: "OpenAI 兼容",
    providerType: "openai_compatible",
    model: "gpt-4.1-mini",
    baseUrl: "https://models.example.com/v1",
    enabled: true,
    isDefault: false,
    apiKeyConfigured: true,
    status: "untested",
    message: "连接尚未检查",
    lastTestedAt: null,
    createdAt: "2026-08-06T10:00:00.000Z",
    updatedAt: "2026-08-06T10:00:00.000Z",
  },
];

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), { status }),
  );
}

describe("SystemModelConnectionsPanel", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  test("shows the default connection in the existing system master-detail style", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ connections }), { status: 200 }),
    );

    const { container } = render(<SystemModelConnectionsPanel />);

    expect((await screen.findAllByText("MiniMax 主连接")).length).toBeGreaterThan(0);
    expect(screen.getByText("MiniMax-M3")).toBeTruthy();
    expect(screen.getByText("https://api.minimaxi.com/v1")).toBeTruthy();
    expect(screen.getByText("当前默认")).toBeTruthy();
    expect(screen.getByRole("button", { name: "运行检查" })).toBeTruthy();
    expect(container.textContent?.toLowerCase()).not.toContain("codex");
  });

  test("opens create and edit drawers with the supported connection fields", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ connections }), { status: 200 }),
    );

    render(<SystemModelConnectionsPanel />);
    await screen.findAllByText("MiniMax 主连接");

    fireEvent.click(screen.getByRole("button", { name: "添加连接" }));

    expect(screen.getByRole("heading", { name: "添加模型连接" })).toBeTruthy();
    expect(screen.getByRole("button", { name: /OpenAI$/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: "MiniMax" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "OpenAI-compatible" })).toBeTruthy();
    expect(screen.getByLabelText("连接名称")).toBeTruthy();
    expect(screen.getByLabelText("模型名称")).toBeTruthy();
    expect(screen.getByLabelText("API Base URL")).toBeTruthy();
    expect(screen.getByLabelText("API Key")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));

    expect(screen.getByRole("heading", { name: "编辑模型连接" })).toBeTruthy();
    expect((screen.getByLabelText("连接名称") as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByLabelText("API Key").getAttribute("placeholder")).toBe(
      "留空保留原值",
    );
  });

  test("sets an enabled connection as default and checks its availability", async () => {
    let rows = connections.map((connection) => ({ ...connection }));
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/openai-compatible/default")) {
        rows = rows.map((connection) => ({
          ...connection,
          isDefault: connection.name === "openai-compatible",
        }));
        return jsonResponse({
          connection: rows.find((connection) => connection.isDefault),
        });
      }
      if (url.endsWith("/openai-compatible/test")) {
        rows = rows.map((connection) =>
          connection.name === "openai-compatible"
            ? { ...connection, status: "ready", message: "连接成功" }
            : connection,
        );
        return jsonResponse({
          ok: true,
          status: "ready",
          message: "连接成功",
          latencyMs: 12,
        });
      }
      if (url === "/api/system/model-connections" && (!init?.method || init.method === "GET")) {
        return jsonResponse({ connections: rows });
      }
      return jsonResponse({});
    });

    render(<SystemModelConnectionsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /OpenAI 兼容/ }));

    fireEvent.click(screen.getByRole("button", { name: "设为默认" }));
    await waitFor(() => expect(screen.getByText("当前默认")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "运行检查" }));
    expect(await screen.findByText(/连接成功/)).toBeTruthy();
  });

  test("reveals the API key directly and hides it after thirty seconds", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/minimax/secret")) {
        return jsonResponse({ apiKey: "plain-model-secret" });
      }
      return jsonResponse({ connections });
    });

    render(<SystemModelConnectionsPanel />);
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });

    fireEvent.click(screen.getByRole("button", { name: "查看密钥" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("plain-model-secret")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(screen.queryByText("plain-model-secret")).toBeNull();
    expect(screen.getByText("••••••••")).toBeTruthy();
  });

  test("offers a direct first action when no connection exists", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ connections: [] }), { status: 200 }),
    );

    render(<SystemModelConnectionsPanel />);

    expect(await screen.findByText("还没有模型连接")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "添加第一个连接" }),
    ).toBeTruthy();
  });
});
