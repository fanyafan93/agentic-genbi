import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { SystemMcpPanel } from "@/modules/system/components/SystemMcpPanel";

const servers = [
  {
    name: "GenBI_report",
    displayName: "GenBI Report",
    category: "system",
    transport: "stdio",
    command: "python",
    args: ["-m", "backend.mcp_servers.genbi_report_server"],
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
        description: "Create report",
        permission: "report.write",
        trusted: true,
      },
    ],
    envKeys: [],
    message: "System-built-in Report configuration tool.",
  },
  {
    name: "BI_doris",
    displayName: "Doris 查询",
    category: "external",
    transport: "stdio",
    command: "npx",
    args: ["-y", "@benborla29/mcp-server-mysql"],
    url: "",
    bearerTokenEnvVar: "",
    oauthClientId: "",
    oauthResource: "",
    environment: [
      { key: "MYSQL_PASSWORD", value: "••••••••", secret: true, configured: true },
    ],
    enabled: true,
    mutable: true,
    deletable: true,
    status: "ready",
    permission: "database.readonly",
    trusted: false,
    approval: "required",
    tools: [
      {
        name: "mysql_query",
        description: "Readonly query",
        permission: "database.readonly",
        trusted: false,
      },
    ],
    envKeys: ["MYSQL_PASSWORD"],
    message: "External MCP is configured.",
  },
];

describe("SystemMcpPanel", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/BI_doris/secrets")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({ secrets: { MYSQL_PASSWORD: "plain-db-password" } }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify({ servers }), { status: 200 }),
      );
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  test("filters system and external MCP servers", async () => {
    render(<SystemMcpPanel />);

    expect((await screen.findAllByText("GenBI Report")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Doris 查询").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: /外部接入/ }));

    await waitFor(() => expect(screen.queryAllByText("GenBI Report")).toHaveLength(0));
    expect(screen.getAllByText("Doris 查询").length).toBeGreaterThan(0);
  });

  test("opens an external MCP create form with native transport choices", async () => {
    render(<SystemMcpPanel />);
    await screen.findAllByText("GenBI Report");

    fireEvent.click(screen.getByRole("button", { name: "添加 MCP" }));

    expect(screen.getByRole("heading", { name: "添加 MCP 服务" })).toBeTruthy();
    expect(screen.getByLabelText(/服务名称/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /stdio/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Streamable HTTP/ })).toBeTruthy();
  });

  test("reveals external secrets directly and hides them after 30 seconds", async () => {
    vi.useFakeTimers();
    render(<SystemMcpPanel />);
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });
    fireEvent.click(screen.getByText("Doris 查询"));

    fireEvent.click(screen.getByRole("button", { name: "查看密钥" }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("plain-db-password")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });
    expect(screen.queryByText("plain-db-password")).toBeNull();
    expect(screen.getByText("••••••••")).toBeTruthy();
  });
});
