import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { PrismaSystemUserRepository } from "@/modules/system/server/prisma-system-user-repository";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import {
  SystemUserManagementService,
  type SystemUserRole,
  type SystemUserStatus,
} from "@/modules/system/server/system-user-management";

type RouteContext = {
  params: Promise<{ userId: string }>;
};

function role(value: unknown): SystemUserRole | undefined {
  return value === "admin" || value === "user" ? value : undefined;
}

function status(value: unknown): SystemUserStatus | undefined {
  return value === "active" || value === "disabled" ? value : undefined;
}

export async function PATCH(request: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id || session.user.status === "disabled") {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const body = (await request.json()) as Record<string, unknown>;
  const update = { role: role(body.role), status: status(body.status) };
  if (!update.role && !update.status) {
    return NextResponse.json({ error: "invalid_user_update" }, { status: 422 });
  }
  const { userId } = await context.params;
  try {
    const user = await prisma.$transaction(async (transaction) => {
      await transaction.$executeRaw`SELECT pg_advisory_xact_lock(hashtext('genbi_system_user_management'))`;
      const service = new SystemUserManagementService(
        new PrismaSystemUserRepository(transaction),
      );
      const before = await transaction.user.findUnique({ where: { id: userId } });
      const updated = await service.updateUser(session.user.id, userId, update);
      await transaction.systemAuditLog.create({
        data: {
          actorId: session.user.id,
          action: "user.update",
          targetType: "user",
          targetId: userId,
          before: before ? { role: before.role, status: before.status } : undefined,
          after: { role: updated.role, status: updated.status },
        },
      });
      return updated;
    });
    return NextResponse.json({ user });
  } catch (error) {
    return systemRouteError(error);
  }
}
