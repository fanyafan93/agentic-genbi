import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { PrismaSystemUserRepository } from "@/modules/system/server/prisma-system-user-repository";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import { SystemUserManagementService } from "@/modules/system/server/system-user-management";

export async function POST() {
  const session = await auth();
  if (!session?.user?.id || session.user.status === "disabled") {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    const user = await prisma.$transaction(async (transaction) => {
      await transaction.$executeRaw`SELECT pg_advisory_xact_lock(hashtext('genbi_system_admin_bootstrap'))`;
      const repository = new PrismaSystemUserRepository(transaction);
      const claimed = await new SystemUserManagementService(
        repository,
      ).bootstrapAdministrator(session.user.id);
      await transaction.systemAuditLog.create({
        data: {
          actorId: session.user.id,
          action: "administrator.bootstrap",
          targetType: "user",
          targetId: claimed.id,
          after: { role: claimed.role, status: claimed.status },
        },
      });
      return claimed;
    });
    return NextResponse.json({ user });
  } catch (error) {
    return systemRouteError(error);
  }
}
