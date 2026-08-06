import { beforeEach, describe, expect, test, vi } from "vitest";

import { SystemUserManagementError } from "@/modules/system/server/system-user-management";

const mocks = vi.hoisted(() => ({
  auth: vi.fn(),
  requireAdministrator: vi.fn(),
  listConnections: vi.fn(),
  createConnection: vi.fn(),
  updateConnection: vi.fn(),
  deleteConnection: vi.fn(),
  revealSecret: vi.fn(),
  testConnection: vi.fn(),
  setDefault: vi.fn(),
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
  return {
    ...actual,
    listSystemModelConnections: mocks.listConnections,
    createSystemModelConnection: mocks.createConnection,
    updateSystemModelConnection: mocks.updateConnection,
    deleteSystemModelConnection: mocks.deleteConnection,
    revealSystemModelConnectionSecret: mocks.revealSecret,
    testSystemModelConnection: mocks.testConnection,
    setDefaultSystemModelConnection: mocks.setDefault,
  };
});

import {
  GET,
  POST,
} from "@/app/api/system/model-connections/route";
import {
  DELETE,
  PATCH,
} from "@/app/api/system/model-connections/[connectionName]/route";
import { GET as GET_SECRET } from "@/app/api/system/model-connections/[connectionName]/secret/route";
import { POST as POST_TEST } from "@/app/api/system/model-connections/[connectionName]/test/route";
import { POST as POST_DEFAULT } from "@/app/api/system/model-connections/[connectionName]/default/route";

const connection = {
  id: "model-1",
  name: "minimax",
  displayName: "MiniMax",
  providerType: "minimax",
  model: "MiniMax-M3",
  baseUrl: "https://api.minimaxi.com/v1",
  enabled: true,
  isDefault: true,
  apiKeyConfigured: true,
  status: "untested",
  message: "连接尚未检查",
  lastTestedAt: null,
  createdAt: "2026-08-06T10:00:00.000Z",
  updatedAt: "2026-08-06T10:00:00.000Z",
};

const routeContext = {
  params: Promise.resolve({ connectionName: "minimax" }),
};

describe("system model connection route authorization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("returns 401 when the user is not signed in", async () => {
    mocks.auth.mockResolvedValue(null);

    const response = await GET();

    expect(response.status).toBe(401);
    expect(mocks.listConnections).not.toHaveBeenCalled();
  });

  test("returns 403 for a signed-in non-administrator", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "user-1" } });
    mocks.requireAdministrator.mockRejectedValue(
      new SystemUserManagementError("administrator_required"),
    );

    const response = await GET();

    expect(response.status).toBe(403);
    expect(mocks.listConnections).not.toHaveBeenCalled();
  });

  test("allows an administrator to list model connections", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "admin-1" } });
    mocks.requireAdministrator.mockResolvedValue(undefined);
    mocks.listConnections.mockResolvedValue([connection]);

    const response = await GET();
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.connections).toEqual([connection]);
  });

  test("forwards an administrator create request with its actor id", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "admin-1" } });
    mocks.requireAdministrator.mockResolvedValue(undefined);
    mocks.createConnection.mockResolvedValue(connection);
    const input = {
      name: "minimax",
      displayName: "MiniMax",
      providerType: "minimax",
      model: "MiniMax-M3",
      baseUrl: "https://api.minimaxi.com/v1",
      apiKey: "plain-model-key",
      enabled: true,
    };

    const response = await POST(new Request(
      "http://localhost/api/system/model-connections",
      { method: "POST", body: JSON.stringify(input) },
    ));

    expect(response.status).toBe(201);
    expect(mocks.createConnection).toHaveBeenCalledWith(input, "admin-1");
  });

  test("protects the secret endpoint and disables response caching", async () => {
    mocks.auth.mockResolvedValueOnce(null);

    const unauthenticated = await GET_SECRET(
      new Request("http://localhost/api/system/model-connections/minimax/secret"),
      routeContext,
    );

    expect(unauthenticated.status).toBe(401);
    expect(mocks.revealSecret).not.toHaveBeenCalled();

    mocks.auth.mockResolvedValueOnce({ user: { id: "admin-1" } });
    mocks.requireAdministrator.mockResolvedValue(undefined);
    mocks.revealSecret.mockResolvedValue("plain-model-key");

    const response = await GET_SECRET(
      new Request("http://localhost/api/system/model-connections/minimax/secret"),
      routeContext,
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ apiKey: "plain-model-key" });
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  test("forwards update and delete mutations with the administrator actor", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "admin-1" } });
    mocks.requireAdministrator.mockResolvedValue(undefined);
    mocks.updateConnection.mockResolvedValue({
      ...connection,
      displayName: "MiniMax 更新",
    });
    mocks.deleteConnection.mockResolvedValue(undefined);

    const updated = await PATCH(
      new Request("http://localhost/api/system/model-connections/minimax", {
        method: "PATCH",
        body: JSON.stringify({ displayName: "MiniMax 更新" }),
      }),
      routeContext,
    );
    const deleted = await DELETE(
      new Request("http://localhost/api/system/model-connections/minimax", {
        method: "DELETE",
      }),
      routeContext,
    );

    expect(updated.status).toBe(200);
    expect(mocks.updateConnection).toHaveBeenCalledWith(
      "minimax",
      { displayName: "MiniMax 更新" },
      "admin-1",
    );
    expect(deleted.status).toBe(204);
    expect(mocks.deleteConnection).toHaveBeenCalledWith("minimax", "admin-1");
  });

  test("forwards connection checks and default changes", async () => {
    mocks.auth.mockResolvedValue({ user: { id: "admin-1" } });
    mocks.requireAdministrator.mockResolvedValue(undefined);
    mocks.testConnection.mockResolvedValue({
      ok: true,
      status: "ready",
      message: "连接成功",
      latencyMs: 12,
    });
    mocks.setDefault.mockResolvedValue(connection);

    const tested = await POST_TEST(
      new Request("http://localhost/api/system/model-connections/minimax/test", {
        method: "POST",
      }),
      routeContext,
    );
    const defaulted = await POST_DEFAULT(
      new Request("http://localhost/api/system/model-connections/minimax/default", {
        method: "POST",
      }),
      routeContext,
    );

    expect(tested.status).toBe(200);
    expect(mocks.testConnection).toHaveBeenCalledWith("minimax", "admin-1");
    expect(defaulted.status).toBe(200);
    expect(mocks.setDefault).toHaveBeenCalledWith("minimax", "admin-1");
  });
});
