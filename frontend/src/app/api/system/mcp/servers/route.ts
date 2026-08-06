import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import {
  createSystemMcpServer,
  listSystemMcpServers,
} from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";
import type { ManagedMcpInput } from "@/modules/system/system-api";

export async function GET() {
  const session = await auth();
  if (!session?.user?.id) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  try {
    await requireSystemAdministrator(session.user.id, prisma);
    return NextResponse.json({ servers: await listSystemMcpServers() });
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
    const input = (await request.json()) as ManagedMcpInput;
    const server = await createSystemMcpServer(input, session.user.id);
    return NextResponse.json({ server }, { status: 201 });
  } catch (error) {
    return systemRouteError(error);
  }
}
