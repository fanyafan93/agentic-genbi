import { describe, expect, test } from "vitest";

import {
  InMemorySystemUserRepository,
  resolveSystemAccess,
  SystemUserManagementService,
  SystemUserManagementError,
  type ManagedSystemUser,
} from "@/modules/system/server/system-user-management";

function user(overrides: Partial<ManagedSystemUser> = {}): ManagedSystemUser {
  return {
    id: "user-1",
    name: "Jason",
    email: null,
    image: null,
    role: "user",
    status: "active",
    createdAt: new Date("2026-08-01T00:00:00.000Z"),
    updatedAt: new Date("2026-08-01T00:00:00.000Z"),
    ...overrides,
  };
}

describe("system user management", () => {
  test("exposes bootstrap only when the installation has no active administrator", () => {
    expect(resolveSystemAccess(user(), 0)).toBe("bootstrap_required");
    expect(resolveSystemAccess(user({ role: "admin" }), 1)).toBe("administrator");
    expect(resolveSystemAccess(user(), 1)).toBe("forbidden");
    expect(resolveSystemAccess(user({ status: "disabled" }), 0)).toBe("forbidden");
  });

  test("lets the signed-in user claim administrator only while no administrator exists", async () => {
    const repository = new InMemorySystemUserRepository([
      user(),
      user({ id: "user-2", name: "Second user" }),
    ]);
    const service = new SystemUserManagementService(repository);

    const claimed = await service.bootstrapAdministrator("user-1");

    expect(claimed.role).toBe("admin");
    await expect(service.bootstrapAdministrator("user-2")).rejects.toMatchObject({
      code: "administrator_already_exists",
    });
  });

  test("rejects user management by a non-administrator", async () => {
    const repository = new InMemorySystemUserRepository([
      user(),
      user({ id: "admin-1", role: "admin" }),
    ]);
    const service = new SystemUserManagementService(repository);

    await expect(service.listUsers("user-1")).rejects.toBeInstanceOf(SystemUserManagementError);
    await expect(
      service.updateUser("user-1", "admin-1", { status: "disabled" }),
    ).rejects.toMatchObject({ code: "administrator_required" });
  });

  test("does not allow the last active administrator to be disabled or demoted", async () => {
    const repository = new InMemorySystemUserRepository([
      user({ id: "admin-1", role: "admin" }),
      user({ id: "user-2" }),
    ]);
    const service = new SystemUserManagementService(repository);

    await expect(
      service.updateUser("admin-1", "admin-1", { status: "disabled" }),
    ).rejects.toMatchObject({ code: "last_administrator_required" });
    await expect(
      service.updateUser("admin-1", "admin-1", { role: "user" }),
    ).rejects.toMatchObject({ code: "last_administrator_required" });
  });

  test("allows an administrator to update another user after a second active administrator exists", async () => {
    const repository = new InMemorySystemUserRepository([
      user({ id: "admin-1", role: "admin" }),
      user({ id: "admin-2", role: "admin" }),
      user({ id: "user-3" }),
    ]);
    const service = new SystemUserManagementService(repository);

    const updated = await service.updateUser("admin-1", "user-3", {
      role: "admin",
      status: "active",
    });

    expect(updated).toMatchObject({ id: "user-3", role: "admin", status: "active" });
    expect((await service.listUsers("admin-1")).map((entry) => entry.id)).toEqual([
      "admin-1",
      "admin-2",
      "user-3",
    ]);
  });
});
