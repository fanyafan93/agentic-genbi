import { beforeEach, describe, expect, test, vi } from "vitest";

import { SystemUserManagementError } from "@/modules/system/server/system-user-management";

const mocks = vi.hoisted(() => ({
  auth: vi.fn(),
  requireAdministrator: vi.fn(),
  findSettings: vi.fn(),
  upsertSetting: vi.fn(),
  findPrompt: vi.fn(),
  getRuntime: vi.fn(),
  listSkills: vi.fn(),
  listServers: vi.fn(),
}));

vi.mock("@/auth", () => ({ auth: mocks.auth }));
vi.mock("@/lib/prisma", () => ({
  prisma: {
    systemSetting: {
      findMany: mocks.findSettings,
      upsert: mocks.upsertSetting,
    },
    systemPromptVersion: { findFirst: mocks.findPrompt },
  },
}));
vi.mock("@/modules/system/server/require-system-administrator", () => ({
  requireSystemAdministrator: mocks.requireAdministrator,
}));
vi.mock("@/modules/system/server/system-backend-client", async () => {
  const actual = await vi.importActual<
    typeof import("@/modules/system/server/system-backend-client")
  >("@/modules/system/server/system-backend-client");
  return {
    ...actual,
    getSystemRuntimeStatus: mocks.getRuntime,
    listSystemSkills: mocks.listSkills,
    listSystemMcpServers: mocks.listServers,
  };
});

import { GET, PUT } from "@/app/api/system/context/route";

describe("system context route", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.findSettings.mockResolvedValue([]);
    mocks.findPrompt.mockResolvedValue({
      content: "当前系统提示词",
      publishedAt: new Date("2026-08-06T10:00:00.000Z"),
    });
    mocks.getRuntime.mockResolvedValue({
      provider: "minimax",
      enabled: true,
      model: "MiniMax-M3",
      approvalMode: "auto_review",
      sandbox: "read_only",
      defaultToolsEnabled: false,
    });
    mocks.listSkills.mockResolvedValue([]);
    mocks.listServers.mockResolvedValue([]);
    mocks.upsertSetting.mockResolvedValue({});
  });

  test("returns 401 when the user is not signed in", async () => {
    mocks.auth.mockResolvedValue(null);

    const response = await GET();

    expect(response.status).toBe(401);
    expect(mocks.getRuntime).not.toHaveBeenCalled();
  });

  test("returns 403 for a signed-in non-administrator", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "user-1" } });
    mocks.requireAdministrator.mockRejectedValue(
      new SystemUserManagementError("administrator_required"),
    );

    const response = await GET();

    expect(response.status).toBe(403);
    expect(mocks.getRuntime).not.toHaveBeenCalled();
  });

  test("returns the current aggregate context for an administrator", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "admin-1" } });
    mocks.requireAdministrator.mockResolvedValue(undefined);

    const response = await GET();
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.context.baseInstructions).toEqual({
      content: "",
      source: "codex_native",
      updatedAt: null,
    });
    expect(payload.context.systemPrompt.content).toBe("当前系统提示词");
  });

  test("directly saves one instruction field", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "admin-1" } });
    mocks.requireAdministrator.mockResolvedValue(undefined);

    const response = await PUT(new Request("http://localhost/api/system/context", {
      method: "PUT",
      body: JSON.stringify({ baseInstructions: "新的基础指令" }),
    }));

    expect(response.status).toBe(200);
    expect(mocks.upsertSetting).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { key: "context.base_instructions" },
        create: expect.objectContaining({
          value: { content: "新的基础指令" },
          updatedById: "admin-1",
        }),
      }),
    );
  });
});
