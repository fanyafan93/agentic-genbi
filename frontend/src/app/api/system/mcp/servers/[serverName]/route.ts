import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import {
  deleteSystemMcpServer,
  updateSystemMcpServer,
} from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import type { ManagedMcpInput } from "@/modules/system/system-api";

type RouteContext = { params: Promise<{ serverName: string }> };

export async function PATCH(request: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const body = (await request.json()) as Partial<ManagedMcpInput>;
  const { serverName } = await context.params;
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const server = await updateSystemMcpServer(
      serverName,
      body,
      session.user.id,
    );
    return NextResponse.json({ server });
  } catch (error) {
    return systemRouteError(error);
  }
}

export async function DELETE(_: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { serverName } = await context.params;
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    await deleteSystemMcpServer(serverName, session.user.id);
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return systemRouteError(error);
  }
}
