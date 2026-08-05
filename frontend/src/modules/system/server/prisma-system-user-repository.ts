import type { Prisma, PrismaClient, User } from "@prisma/client";

import {
  SystemUserManagementError,
  type ManagedSystemUser,
  type SystemUserRepository,
  type SystemUserRole,
  type SystemUserStatus,
  type SystemUserUpdate,
} from "./system-user-management";

type DatabaseClient = PrismaClient | Prisma.TransactionClient;

function asRole(value: string): SystemUserRole {
  return value === "admin" ? "admin" : "user";
}

function asStatus(value: string): SystemUserStatus {
  return value === "disabled" ? "disabled" : "active";
}

export function managedSystemUser(row: User): ManagedSystemUser {
  return {
    id: row.id,
    name: row.name,
    email: row.email,
    image: row.image,
    role: asRole(row.role),
    status: asStatus(row.status),
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
  };
}

export class PrismaSystemUserRepository implements SystemUserRepository {
  constructor(private readonly database: DatabaseClient) {}

  async list(): Promise<ManagedSystemUser[]> {
    const rows = await this.database.user.findMany({
      orderBy: [{ createdAt: "asc" }, { id: "asc" }],
    });
    return rows.map(managedSystemUser);
  }

  async get(userId: string): Promise<ManagedSystemUser | null> {
    const row = await this.database.user.findUnique({ where: { id: userId } });
    return row ? managedSystemUser(row) : null;
  }

  async update(userId: string, update: SystemUserUpdate): Promise<ManagedSystemUser> {
    try {
      return managedSystemUser(
        await this.database.user.update({
          where: { id: userId },
          data: update,
        }),
      );
    } catch (error) {
      if (
        typeof error === "object" &&
        error !== null &&
        "code" in error &&
        error.code === "P2025"
      ) {
        throw new SystemUserManagementError("user_not_found");
      }
      throw error;
    }
  }

  async countActiveAdministrators(): Promise<number> {
    return this.database.user.count({
      where: { role: "admin", status: "active" },
    });
  }
}
