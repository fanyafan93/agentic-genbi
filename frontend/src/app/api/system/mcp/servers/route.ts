import { NextResponse } from "next/server";

import { auth } from "@/auth";
import { prisma } from "@/lib/prisma";
import { requireSystemAdministrator } from "@/modules/system/server/require-system-administrator";
import { listSystemMcpServers } from "@/modules/system/server/system-backend-client";
import { systemRouteError } from "@/modules/system/server/system-route-response";

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
