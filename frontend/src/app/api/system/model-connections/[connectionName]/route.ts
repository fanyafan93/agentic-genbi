import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import {
  deleteSystemModelConnection,
  updateSystemModelConnection,
} from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import type { ManagedModelConnectionInput } from "@/modules/system/system-api";

type RouteContext = { params: Promise<{ connectionName: string }> };

export async function PATCH(request: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { connectionName } = await context.params;
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const input = (await request.json()) as Partial<ManagedModelConnectionInput>;
    const connection = await updateSystemModelConnection(
      connectionName,
      input,
      session.user.id,
    );
    return NextResponse.json({ connection });
  } catch (error) {
    return systemRouteError(error);
  }
}

export async function DELETE(_: Request, context: RouteContext) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  const { connectionName } = await context.params;
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    await deleteSystemModelConnection(connectionName, session.user.id);
    return new NextResponse(null, { status: 204 });
  } catch (error) {
    return systemRouteError(error);
  }
}
