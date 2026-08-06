// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { SystemAdminPage } from "@/modules/system/components/SystemAdminPage";

const updateSession = vi.fn();

vi.mock("next-auth/react", () => ({
  useSession: () => ({
    data: { user: { id: "user-1", role: "user", status: "active" } },
    update: updateSession,
  }),
}));

describe("system administration page", () => {
  beforeEach(() => {
    updateSession.mockReset();
    vi.restoreAllMocks();
  });

  test("offers one-time administrator initialization when no administrator exists", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access: "bootstrap_required" }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ user: { id: "user-1", role: "admin" } }), {
          status: 200,
        }),
      );

    render(<SystemAdminPage />);

    expect(await screen.findByText("初始化系统管理员")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "设为当前账号" }));

    await waitFor(() => expect(updateSession).toHaveBeenCalled());
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/system/bootstrap",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("shows the unified administration domains without a second navigation rail", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access: "administrator" }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ users: [] }), { status: 200 }),
      );

    const { container } = render(<SystemAdminPage />);

    expect(await screen.findByRole("heading", { name: "系统控制台" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "系统管理导航" })).toBeNull();
    expect(screen.getByRole("button", { name: /用户与权限/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /模型连接/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /MCP 服务/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /上下文管理/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /系统提示词/ })).toBeNull();
    expect(screen.getByRole("button", { name: /运行策略/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /模型与运行策略/ })).toBeNull();
    expect(container.textContent?.toLowerCase()).not.toContain("codex");
  });

  test("opens model connections from the system overview", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access: "administrator" }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ connections: [] }), { status: 200 }),
      );

    render(<SystemAdminPage />);

    fireEvent.click(await screen.findByRole("button", { name: /模型连接/ }));

    expect(
      await screen.findByRole("heading", { name: "模型连接" }),
    ).toBeTruthy();
  });
});
