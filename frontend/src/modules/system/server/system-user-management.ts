export type SystemUserRole = "admin" | "user";
export type SystemUserStatus = "active" | "disabled";

export type ManagedSystemUser = {
  id: string;
  name: string | null;
  email: string | null;
  image: string | null;
  role: SystemUserRole;
  status: SystemUserStatus;
  createdAt: Date;
  updatedAt: Date;
};

export type SystemUserUpdate = {
  role?: SystemUserRole;
  status?: SystemUserStatus;
};

export interface SystemUserRepository {
  list(): Promise<ManagedSystemUser[]>;
  get(userId: string): Promise<ManagedSystemUser | null>;
  update(userId: string, update: SystemUserUpdate): Promise<ManagedSystemUser>;
  countActiveAdministrators(): Promise<number>;
}

export type SystemAccess = "administrator" | "bootstrap_required" | "forbidden";

export function resolveSystemAccess(
  actor: ManagedSystemUser,
  activeAdministratorCount: number,
): SystemAccess {
  if (actor.status !== "active") return "forbidden";
  if (actor.role === "admin") return "administrator";
  return activeAdministratorCount === 0 ? "bootstrap_required" : "forbidden";
}

export class SystemUserManagementError extends Error {
  constructor(
    public readonly code:
      | "administrator_already_exists"
      | "administrator_required"
      | "last_administrator_required"
      | "user_not_found",
  ) {
    super(code);
    this.name = "SystemUserManagementError";
  }
}

export class SystemUserManagementService {
  constructor(private readonly repository: SystemUserRepository) {}

  async bootstrapAdministrator(actorId: string): Promise<ManagedSystemUser> {
    if ((await this.repository.countActiveAdministrators()) > 0) {
      throw new SystemUserManagementError("administrator_already_exists");
    }
    await this.requireUser(actorId);
    return this.repository.update(actorId, { role: "admin", status: "active" });
  }

  async listUsers(actorId: string): Promise<ManagedSystemUser[]> {
    await this.requireAdministrator(actorId);
    return this.repository.list();
  }

  async updateUser(
    actorId: string,
    targetUserId: string,
    update: SystemUserUpdate,
  ): Promise<ManagedSystemUser> {
    await this.requireAdministrator(actorId);
    const target = await this.requireUser(targetUserId);
    const removesActiveAdministrator =
      target.role === "admin" &&
      target.status === "active" &&
      (update.role === "user" || update.status === "disabled");
    if (
      removesActiveAdministrator &&
      (await this.repository.countActiveAdministrators()) <= 1
    ) {
      throw new SystemUserManagementError("last_administrator_required");
    }
    return this.repository.update(targetUserId, update);
  }

  private async requireAdministrator(userId: string): Promise<ManagedSystemUser> {
    const user = await this.requireUser(userId);
    if (user.role !== "admin" || user.status !== "active") {
      throw new SystemUserManagementError("administrator_required");
    }
    return user;
  }

  private async requireUser(userId: string): Promise<ManagedSystemUser> {
    const user = await this.repository.get(userId);
    if (!user) throw new SystemUserManagementError("user_not_found");
    return user;
  }
}

export class InMemorySystemUserRepository implements SystemUserRepository {
  private readonly users: ManagedSystemUser[];

  constructor(users: ManagedSystemUser[]) {
    this.users = users.map((user) => ({ ...user }));
  }

  async list(): Promise<ManagedSystemUser[]> {
    return this.users.map((user) => ({ ...user }));
  }

  async get(userId: string): Promise<ManagedSystemUser | null> {
    const user = this.users.find((entry) => entry.id === userId);
    return user ? { ...user } : null;
  }

  async update(userId: string, update: SystemUserUpdate): Promise<ManagedSystemUser> {
    const index = this.users.findIndex((entry) => entry.id === userId);
    if (index < 0) throw new SystemUserManagementError("user_not_found");
    const next = {
      ...this.users[index],
      ...update,
      updatedAt: new Date(),
    };
    this.users[index] = next;
    return { ...next };
  }

  async countActiveAdministrators(): Promise<number> {
    return this.users.filter(
      (user) => user.role === "admin" && user.status === "active",
    ).length;
  }
}
