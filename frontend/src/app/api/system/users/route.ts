import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { PrismaSystemUserRepository } from "@/modules/system/server/prisma-system-user-repository";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import { SystemUserManagementService } from "@/modules/system/server/system-user-management";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id || session.user.status === "disabled") {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    const users = await new SystemUserManagementService(
      new PrismaSystemUserRepository(prisma),
    ).listUsers(session.user.id);
    return NextResponse.json({ users });
  } catch (error) {
    return systemRouteError(error);
  }
}
