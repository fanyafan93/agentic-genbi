import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import { testSystemMcpServer } from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";

type RouteContext = { params: Promise<{ serverName: string }> };

export async function POST(_: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { serverName } = await context.params;
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const result = await testSystemMcpServer(serverName, session.user.id);
    return NextResponse.json(result);
  } catch (error) {
    return systemRouteError(error);
  }
}
