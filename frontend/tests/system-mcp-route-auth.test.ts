import { beforeEach, describe, expect, test, vi } from "vitest";

import { SystemUserManagementError } from "@/modules/system/server/system-user-management";

const mocks = vi.hoisted(() => ({
  auth: vi.fn(),
  requireAdministrator: vi.fn(),
  listServers: vi.fn(),
}));

vi.mock("@/auth", () => ({ auth: mocks.auth }));
vi.mock("@/lib/prisma", () => ({ prisma: {} }));
vi.mock("@/modules/system/server/require-system-administrator", () => ({
  requireSystemAdministrator: mocks.requireAdministrator,
}));
vi.mock("@/modules/system/server/system-backend-client", async () => {
  const actual = await vi.importActual<
    typeof import("@/modules/system/server/system-backend-client")
  >("@/modules/system/server/system-backend-client");
  return { ...actual, listSystemMcpServers: mocks.listServers };
});

import { GET } from "@/app/api/system/mcp/servers/route";

describe("system MCP route authorization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("returns 401 when the user is not signed in", async () => {
    mocks.auth.mockResolvedValue(null);

    const response = await GET();

    expect(response.status).toBe(401);
    expect(mocks.listServers).not.toHaveBeenCalled();
  });

  test("returns 403 for a signed-in non-administrator", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "user-1" } });
    mocks.requireAdministrator.mockRejectedValue(
      new SystemUserManagementError("administrator_required"),
    );

    const response = await GET();

    expect(response.status).toBe(403);
    expect(mocks.listServers).not.toHaveBeenCalled();
  });

  test("allows an administrator to list MCP servers", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "admin-1" } });
    mocks.requireAdministrator.mockResolvedValue(undefined);
    mocks.listServers.mockResolvedValue([]);

    const response = await GET();

    expect(response.status).toBe(200);
    expect(mocks.listServers).toHaveBeenCalledOnce();
  });
});
