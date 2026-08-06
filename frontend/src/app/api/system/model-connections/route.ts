import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import {
  createSystemModelConnection,
  listSystemModelConnections,
} from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import type { ManagedModelConnectionInput } from "@/modules/system/system-api";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    return NextResponse.json({
      connections: await listSystemModelConnections(),
    });
  } catch (error) {
    return systemRouteError(error);
  }
}

export async function POST(request: Request) {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    const input = (await request.json()) as ManagedModelConnectionInput;
    const connection = await createSystemModelConnection(input, session.user.id);
    return NextResponse.json({ connection }, { status: 201 });
  } catch (error) {
    return systemRouteError(error);
  }
}
