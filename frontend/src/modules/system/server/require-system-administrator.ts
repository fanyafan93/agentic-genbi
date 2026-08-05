import type { Prisma, PrismaClient } from "@prisma/client";

import { PrismaSystemUserRepository } from "./prisma-system-user-repository";
import {
  SystemUserManagementError,
  type ManagedSystemUser,
} from "./system-user-management";

type DatabaseClient = PrismaClient | Prisma.TransactionClient;

export async function requireSystemAdministrator(
  userId: string,
  database: DatabaseClient,
): Promise<ManagedSystemUser> {
  const actor = await new PrismaSystemUserRepository(database).get(userId);
  if (!actor || actor.role !== "admin" || actor.status !== "active") {
    throw new SystemUserManagementError("administrator_required");
  }
  return actor;
}
